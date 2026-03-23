"""
Paper trading executor - simulates order execution with realistic fills.
Uses real market prices from Redis but does not place actual orders.
Tracks virtual portfolio for ML model validation.
"""
import json
import random
import uuid
from datetime import datetime
from typing import Optional, Dict

import redis.asyncio as aioredis
import structlog

from .base import ExchangeExecutor

logger = structlog.get_logger()


class PaperExecutor(ExchangeExecutor):
    """Paper trading executor for safe ML model validation."""

    name = "paper"

    def __init__(self, redis_client: aioredis.Redis, starting_capital: float = 10.0):
        self._redis = redis_client
        self._starting_capital = starting_capital
        self._balances: Dict[str, Dict] = {}
        self._orders: list = []
        # Virtual short positions: {symbol: {"amount": float, "entry_price": float, "margin_held": float}}
        self._virtual_shorts: Dict[str, Dict] = {}

    async def connect(self) -> None:
        # Load paper portfolio from Redis or initialize
        saved = await self._redis.get("paper_portfolio")
        if saved:
            data = json.loads(saved)
            self._balances = data.get("balances", {})
            self._virtual_shorts = data.get("virtual_shorts", {})
            logger.info("Paper executor loaded saved portfolio", balances=self._balances,
                        virtual_shorts=len(self._virtual_shorts))
        else:
            self._balances = {
                "USDT": {"free": self._starting_capital, "used": 0.0, "total": self._starting_capital}
            }
            await self._save_portfolio()
            logger.info("Paper executor initialized", capital=self._starting_capital)

    async def close(self) -> None:
        await self._save_portfolio()

    async def get_balance(self, currency: str = "USDT") -> Dict:
        if currency not in self._balances:
            return {"free": 0.0, "used": 0.0, "total": 0.0}
        return self._balances[currency].copy()

    async def create_market_buy(self, symbol: str, cost: float) -> Dict:
        price = await self.fetch_ticker_price(symbol)
        if price <= 0:
            raise ValueError(f"Cannot get price for {symbol}")

        # Simulate slippage (0.01% - 0.05%)
        slippage = random.uniform(0.0001, 0.0005)
        fill_price = price * (1 + slippage)

        # Simulate fee (0.05% taker fee on MEXC spot)
        fee_rate = 0.0005  # MEXC actual taker fee: 0.05%
        fee = cost * fee_rate
        effective_cost = cost - fee
        amount = effective_cost / fill_price

        # Check USDT balance
        usdt_bal = self._balances.get("USDT", {"free": 0})
        if usdt_bal["free"] < cost:
            raise ValueError(f"Insufficient USDT: {usdt_bal['free']:.4f} < {cost:.4f}")

        # Update balances
        base = symbol.split("/")[0]
        self._balances["USDT"]["free"] -= cost
        self._balances["USDT"]["total"] -= cost

        if base not in self._balances:
            self._balances[base] = {"free": 0.0, "used": 0.0, "total": 0.0}
        self._balances[base]["free"] += amount
        self._balances[base]["total"] += amount

        order = {
            "id": f"paper_{uuid.uuid4().hex[:12]}",
            "symbol": symbol,
            "side": "buy",
            "amount": amount,
            "price": fill_price,
            "cost": cost,
            "filled": amount,
            "status": "closed",
            "fee": fee,
        }
        self._orders.append(order)
        await self._save_portfolio()

        logger.info(
            "Paper BUY executed",
            symbol=symbol,
            amount=f"{amount:.8f}",
            price=f"{fill_price:.8f}",
            cost=f"{cost:.4f}",
            fee=f"{fee:.6f}",
        )
        return order

    async def create_market_sell(self, symbol: str, amount: float) -> Dict:
        price = await self.fetch_ticker_price(symbol)
        if price <= 0:
            raise ValueError(f"Cannot get price for {symbol}")

        # Simulate slippage (negative for sells)
        slippage = random.uniform(0.0001, 0.0005)
        fill_price = price * (1 - slippage)

        # Check coin balance
        base = symbol.split("/")[0]
        base_bal = self._balances.get(base, {"free": 0})
        if base_bal["free"] < amount * 0.99:  # 1% tolerance for rounding
            raise ValueError(f"Insufficient {base}: {base_bal['free']:.8f} < {amount:.8f}")

        # Calculate proceeds
        gross_proceeds = amount * fill_price
        fee_rate = 0.0005  # MEXC actual taker fee: 0.05%
        fee = gross_proceeds * fee_rate
        net_proceeds = gross_proceeds - fee

        # Update balances
        sell_amount = min(amount, self._balances[base]["free"])
        self._balances[base]["free"] -= sell_amount
        self._balances[base]["total"] -= sell_amount

        self._balances["USDT"]["free"] += net_proceeds
        self._balances["USDT"]["total"] += net_proceeds

        # Clean up zero balances
        if self._balances[base]["total"] < 1e-10:
            del self._balances[base]

        order = {
            "id": f"paper_{uuid.uuid4().hex[:12]}",
            "symbol": symbol,
            "side": "sell",
            "amount": sell_amount,
            "price": fill_price,
            "cost": gross_proceeds,
            "filled": sell_amount,
            "status": "closed",
            "fee": fee,
        }
        self._orders.append(order)
        await self._save_portfolio()

        logger.info(
            "Paper SELL executed",
            symbol=symbol,
            amount=f"{sell_amount:.8f}",
            price=f"{fill_price:.8f}",
            proceeds=f"{net_proceeds:.4f}",
            fee=f"{fee:.6f}",
        )
        return order

    async def create_virtual_short_entry(self, symbol: str, cost: float) -> Dict:
        """Open a virtual short position. Holds margin in USDT, tracks entry price.

        Virtual shorts simulate margin shorting on spot:
        - Reserve 'cost' USDT as margin collateral
        - Record the entry price and virtual amount
        - PnL = (entry_price - exit_price) * amount (realized on close)

        MEXC spot does NOT support native short selling. This is a paper-only
        simulation for strategy validation. For live short trading, MEXC Futures
        API (ccxt defaultType='swap') would be required.
        """
        price = await self.fetch_ticker_price(symbol)
        if price <= 0:
            raise ValueError(f"Cannot get price for {symbol}")

        # Simulate slippage
        slippage = random.uniform(0.0001, 0.0005)
        fill_price = price * (1 - slippage)  # Short sells at slightly lower price

        # Simulate fee
        fee_rate = 0.0005  # MEXC actual taker fee: 0.05%
        fee = cost * fee_rate
        effective_cost = cost - fee
        amount = effective_cost / fill_price

        # Check USDT balance for margin
        usdt_bal = self._balances.get("USDT", {"free": 0})
        if usdt_bal["free"] < cost:
            raise ValueError(f"Insufficient USDT for short margin: {usdt_bal['free']:.4f} < {cost:.4f}")

        # Reserve USDT as margin collateral
        self._balances["USDT"]["free"] -= cost
        self._balances["USDT"]["used"] += cost  # Margin is "used" not "free"

        # Track virtual short position
        self._virtual_shorts[symbol] = {
            "amount": amount,
            "entry_price": fill_price,
            "margin_held": cost,
        }

        order = {
            "id": f"paper_short_{uuid.uuid4().hex[:12]}",
            "symbol": symbol,
            "side": "short_entry",
            "amount": amount,
            "price": fill_price,
            "cost": cost,
            "filled": amount,
            "status": "closed",
            "fee": fee,
        }
        self._orders.append(order)
        await self._save_portfolio()

        logger.info(
            "Paper SHORT ENTRY executed",
            symbol=symbol,
            amount=f"{amount:.8f}",
            price=f"{fill_price:.8f}",
            margin=f"{cost:.4f}",
            fee=f"{fee:.6f}",
        )
        return order

    async def create_virtual_short_exit(self, symbol: str, amount: float) -> Dict:
        """Close a virtual short position. Returns margin + PnL to USDT balance.

        PnL = (entry_price - exit_price) * amount
        """
        price = await self.fetch_ticker_price(symbol)
        if price <= 0:
            raise ValueError(f"Cannot get price for {symbol}")

        if symbol not in self._virtual_shorts:
            raise ValueError(f"No virtual short position for {symbol}")

        short_pos = self._virtual_shorts[symbol]

        # Simulate slippage (adverse for short exit = price goes up slightly)
        slippage = random.uniform(0.0001, 0.0005)
        fill_price = price * (1 + slippage)

        # Simulate fee
        fee_rate = 0.0005  # MEXC actual taker fee: 0.05%
        close_cost = amount * fill_price
        fee = close_cost * fee_rate

        # Calculate PnL: shorts profit when price goes down
        pnl = (short_pos["entry_price"] - fill_price) * amount - fee

        # Return margin + PnL to available balance
        margin_returned = short_pos["margin_held"]
        self._balances["USDT"]["free"] += margin_returned + pnl
        self._balances["USDT"]["used"] -= margin_returned
        self._balances["USDT"]["total"] += pnl  # total changes by PnL only

        # Clean up virtual short
        del self._virtual_shorts[symbol]

        order = {
            "id": f"paper_short_exit_{uuid.uuid4().hex[:12]}",
            "symbol": symbol,
            "side": "short_exit",
            "amount": amount,
            "price": fill_price,
            "cost": close_cost,
            "filled": amount,
            "status": "closed",
            "fee": fee,
            "pnl": pnl,
        }
        self._orders.append(order)
        await self._save_portfolio()

        logger.info(
            "Paper SHORT EXIT executed",
            symbol=symbol,
            amount=f"{amount:.8f}",
            price=f"{fill_price:.8f}",
            pnl=f"{pnl:.4f}",
            fee=f"{fee:.6f}",
        )
        return order

    async def fetch_ticker_price(self, symbol: str) -> float:
        """Get real market price from Redis (latest_ticks from market-data service)."""
        tick_data = await self._redis.hget("latest_ticks", symbol)
        if tick_data:
            tick = json.loads(tick_data)
            return float(tick.get("price", 0))
        return 0.0

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> list:
        # Paper trading fills instantly - no open orders
        return []

    async def _save_portfolio(self) -> None:
        """Persist paper portfolio to Redis."""
        data = {
            "balances": self._balances,
            "virtual_shorts": self._virtual_shorts,
            "updated_at": datetime.utcnow().isoformat(),
            "total_orders": len(self._orders),
        }
        await self._redis.set("paper_portfolio", json.dumps(data))

    async def get_portfolio_summary(self) -> Dict:
        """Get full paper portfolio with current values."""
        total_value = self._balances.get("USDT", {}).get("total", 0)
        positions = {}

        for currency, bal in dict(self._balances).items():
            if currency == "USDT" or bal["total"] <= 0:
                continue
            symbol = f"{currency}/USDT"
            price = await self.fetch_ticker_price(symbol)
            value = bal["total"] * price
            total_value += value
            positions[symbol] = {
                "amount": bal["total"],
                "price": price,
                "value": value,
                "side": "long",
            }

        # Include virtual short positions and their unrealized PnL
        for symbol, short_pos in self._virtual_shorts.items():
            price = await self.fetch_ticker_price(symbol)
            unrealized_pnl = (short_pos["entry_price"] - price) * short_pos["amount"]
            # Virtual short value = margin held + unrealized PnL
            total_value += unrealized_pnl  # PnL adjusts total (margin is already in USDT used)
            positions[f"{symbol}_SHORT"] = {
                "amount": short_pos["amount"],
                "entry_price": short_pos["entry_price"],
                "price": price,
                "value": short_pos["margin_held"] + unrealized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "side": "short",
            }

        return {
            "total_value": total_value,
            "usdt_balance": self._balances.get("USDT", {}).get("total", 0),
            "positions": positions,
            "virtual_shorts": len(self._virtual_shorts),
            "total_orders": len(self._orders),
            "pnl": total_value - self._starting_capital,
            "pnl_pct": ((total_value / self._starting_capital) - 1) * 100 if self._starting_capital > 0 else 0,
        }
