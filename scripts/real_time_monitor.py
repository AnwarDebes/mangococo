#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real-Time Trading Monitor - Live Position Tracking
Shows current positions, PnL, recent signals, trades, and price movements
"""

import ccxt
import redis
import json
import time
import os
import sys
from datetime import datetime
from colorama import init, Fore, Back, Style
from tabulate import tabulate
from collections import deque

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Initialize colorama for colored output
init(autoreset=True)

# Load environment variables from .env file if it exists
def load_env_file():
    """Load environment variables from config/.env file"""
    env_file = os.path.join(os.path.dirname(__file__), '..', 'config', '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    value = value.strip().split('#')[0].strip().strip('"\'')
                    os.environ[key.strip()] = value

# Load .env file if it exists
load_env_file()

# Initialize connections - all credentials from environment variables
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
MEXC_API_KEY = os.getenv('MEXC_API_KEY', '')
MEXC_SECRET_KEY = os.getenv('MEXC_SECRET_KEY', '')

# Trading strategy parameters from environment variables (used only for "near" alert thresholds)
# Note: Actual stop_loss_price and take_profit_price come from positions in Redis
# These may be dynamic/ATR-based, so we use the stored prices directly
PROFIT_TARGET_PCT = float(os.getenv('PROFIT_TARGET_PCT', 0.002))  # Default 0.2% profit target
MAX_TRADE_LOSS_PCT = float(os.getenv('MAX_TRADE_LOSS_PCT', 0.005))  # Default 0.5% stop loss
NEAR_ALERT_THRESHOLD_PCT = 0.05  # Alert when within 0.05% of target/stop (absolute distance)

# If REDIS_HOST is 'redis' (Docker hostname), check if it resolves, otherwise use localhost for local execution
if REDIS_HOST == 'redis':
    import socket
    try:
        # Try to resolve the hostname
        socket.gethostbyname('redis')
        # If successful, keep using 'redis'
    except socket.gaierror:
        # If 'redis' hostname doesn't resolve, use 'localhost' for local execution
        REDIS_HOST = 'localhost'

# Global tracking
recent_signals = deque(maxlen=10)
recent_trades = deque(maxlen=10)
holdings_tracker = {}  # Track entry prices for holdings

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_SECRET_KEY,
    'enableRateLimit': True
})

def get_positions():
    """Get all positions from Redis with error handling"""
    try:
        positions_data = redis_client.hgetall("positions")
        positions = {}

        for symbol, data in positions_data.items():
            try:
                pos = json.loads(data)
                if pos.get('status') == 'open':
                    positions[symbol] = pos
            except json.JSONDecodeError:
                continue

        return positions
    except Exception as e:
        print(f"{Fore.RED}Error getting positions from Redis: {e}")
        return {}

def get_live_prices(symbols):
    """Get live prices for all symbols"""
    prices = {}
    for symbol in symbols:
        try:
            ticker = exchange.fetch_ticker(symbol)
            prices[symbol] = ticker['last']
        except Exception as e:
            prices[symbol] = None
    return prices

def get_account_balance():
    """Get account balance from executor service with live MEXC prices"""
    global holdings_tracker

    try:
        import requests
        resp = requests.get("http://localhost:8005/balance", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            balances = data.get('balances', {})
            usdt = balances.get('USDT', {}).get('total', 0)

            # Calculate total value
            total_value = usdt
            holdings = []

            for coin, info in balances.items():
                amount = info.get('total', 0)
                if amount > 0.0001 and coin != 'USDT':
                    try:
                        ticker = exchange.fetch_ticker(f"{coin}/USDT")
                        current_price = ticker['last']
                        value = amount * current_price
                        total_value += value

                        # Track entry price (first time we see this coin)
                        if coin not in holdings_tracker:
                            holdings_tracker[coin] = {
                                'entry_price': current_price,
                                'entry_value': value,
                                'amount': amount
                            }

                        # Calculate profit/loss
                        entry_price = holdings_tracker[coin]['entry_price']
                        entry_value = holdings_tracker[coin]['entry_value']
                        price_change_pct = ((current_price - entry_price) / entry_price) * 100
                        value_change = value - entry_value

                        holdings.append({
                            'coin': coin,
                            'amount': amount,
                            'entry_price': entry_price,
                            'current_price': current_price,
                            'entry_value': entry_value,
                            'current_value': value,
                            'price_change_pct': price_change_pct,
                            'value_change': value_change
                        })
                    except Exception as e:
                        pass

            return total_value, usdt, holdings
    except:
        pass
    return None, None, []

def get_recent_signals():
    """Get recent signals from Redis"""
    try:
        # Try to get from a list if signals are stored there
        signals = redis_client.lrange("recent_signals", 0, 9)
        return [json.loads(s) for s in signals]
    except:
        return list(recent_signals)

def get_recent_trades():
    """Get recent trades from Redis"""
    try:
        trades = redis_client.lrange("recent_trades", 0, 9)
        return [json.loads(t) for t in trades]
    except:
        return list(recent_trades)

def calculate_pnl(entry_price, current_price, side='long'):
    """Calculate percentage profit/loss"""
    if side == 'long':
        return ((current_price - entry_price) / entry_price) * 100
    else:
        return ((entry_price - current_price) / entry_price) * 100

def get_color_for_pnl(pnl):
    """Get color based on PnL"""
    if pnl >= 0:
        return Fore.GREEN
    else:
        return Fore.RED

def get_color_for_distance(distance):
    """Get color based on distance to target"""
    if distance is None:
        return Fore.WHITE
    if distance <= 0.1:  # Very close (within 0.1%)
        return Fore.YELLOW + Style.BRIGHT
    elif distance <= 0.2:  # Close (within 0.2%)
        return Fore.BLUE + Style.BRIGHT
    else:
        return Fore.WHITE

def print_header(total_value=None):
    """Print the header"""
    print("\n" + "="*120)
    print(f"{Fore.CYAN}{Style.BRIGHT}🤑 MANGO COCO - REAL TIME TRADING MONITOR 🤑{Style.RESET_ALL}")
    print("="*120)
    print(f"{Fore.WHITE}Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", end="")
    if total_value:
        print(f" | Portfolio: {Fore.GREEN}${total_value:.2f} USDT{Fore.WHITE}", end="")
    print()

    # Check Redis connection
    try:
        redis_status = "🟢 Redis" if redis_client.ping() else "🔴 Redis"
    except:
        redis_status = "🔴 Redis (disconnected)"

    # Check MEXC API
    try:
        exchange.fetch_ticker("BTC/USDT")
        mexc_status = "🟢 MEXC API"
    except:
        mexc_status = "🔴 MEXC API (error)"

    print(f"{Fore.WHITE}Status: {redis_status} | {mexc_status}")
    print(f"{Fore.WHITE}Strategy: Dynamic stop-loss/take-profit targets (may be ATR-based)")
    print("-"*120)

def print_positions_table(positions, prices):
    """Print positions in a nice table"""
    if not positions:
        print("📭 No open positions")
        return
    
    print(f"\n{Fore.CYAN}{Style.BRIGHT}📈 OPEN POSITIONS (Dynamic Targets):")
    print(f"{Fore.WHITE}Stop-loss and take-profit prices are set per position (may be dynamic/ATR-based)")
    print(f"{Fore.WHITE}Alerts trigger when price crosses these actual target levels\n")

    table_data = []
    alerts = []

    for symbol, pos in positions.items():
        current_price = prices.get(symbol)
        if current_price is None:
            continue

        entry_price = pos['entry_price']
        take_profit = pos.get('take_profit_price')
        stop_loss = pos.get('stop_loss_price')
        amount = pos['amount']
        side = pos.get('side', 'long')  # Default to long if not specified

        # Calculate PnL based on position side
        pnl_pct = calculate_pnl(entry_price, current_price, side)
        
        # Calculate distance to targets (percentage from entry price)
        # Uses actual stop_loss_price and take_profit_price from position (may be dynamic/ATR-based)
        if take_profit:
            if side == 'long':
                dist_to_tp = ((take_profit - current_price) / entry_price) * 100
            else:  # short
                dist_to_tp = ((current_price - take_profit) / entry_price) * 100
        else:
            dist_to_tp = None
        
        if stop_loss:
            if side == 'long':
                dist_to_sl = ((current_price - stop_loss) / entry_price) * 100
            else:  # short
                dist_to_sl = ((stop_loss - current_price) / entry_price) * 100
        else:
            dist_to_sl = None

        # Determine action needed based on strategy thresholds
        action = ""
        action_color = Fore.WHITE
        
        # Check if take profit or stop loss is triggered
        if take_profit and stop_loss:
            if side == 'long':
                tp_triggered = current_price >= take_profit
                sl_triggered = current_price <= stop_loss
            else:  # short
                tp_triggered = current_price <= take_profit
                sl_triggered = current_price >= stop_loss
            
            if tp_triggered:
                action = "🚨 TAKE-PROFIT TRIGGERED!"
                action_color = Back.GREEN + Fore.BLACK + Style.BRIGHT
                tp_pct = ((take_profit - entry_price) / entry_price * 100) if side == 'long' else ((entry_price - take_profit) / entry_price * 100)
                alerts.append(f"SELL {symbol} - Take-profit reached! ({side.upper()}) Target: {tp_pct:.3f}%")
            elif sl_triggered:
                action = "🚨 STOP-LOSS TRIGGERED!"
                action_color = Back.RED + Fore.WHITE + Style.BRIGHT
                sl_pct = ((entry_price - stop_loss) / entry_price * 100) if side == 'long' else ((stop_loss - entry_price) / entry_price * 100)
                alerts.append(f"SELL {symbol} - Stop-loss reached! ({side.upper()}) Stop: {sl_pct:.3f}%")
            elif dist_to_tp is not None and dist_to_tp > 0 and dist_to_tp <= NEAR_ALERT_THRESHOLD_PCT:
                # Within 0.05% of take profit target
                action = "⚠️  NEAR TAKE-PROFIT"
                action_color = Fore.YELLOW + Style.BRIGHT
            elif dist_to_sl is not None and dist_to_sl > 0 and dist_to_sl <= NEAR_ALERT_THRESHOLD_PCT:
                # Within 0.05% of stop loss
                action = "⚠️  NEAR STOP-LOSS"
                action_color = Fore.MAGENTA + Style.BRIGHT

        # Format take profit and stop loss display
        tp_display = f"{take_profit:.6f}" if take_profit else "N/A"
        sl_display = f"{stop_loss:.6f}" if stop_loss else "N/A"
        dist_to_tp_display = f"{dist_to_tp:.3f}%" if dist_to_tp is not None else "N/A"
        dist_to_sl_display = f"{dist_to_sl:.3f}%" if dist_to_sl is not None else "N/A"
        
        table_data.append([
            symbol,
            f"{side.upper()}",
            f"{entry_price:.6f}",
            f"{current_price:.6f}",
            f"{get_color_for_pnl(pnl_pct)}{pnl_pct:+.2f}%",
            tp_display,
            f"{get_color_for_distance(dist_to_tp) if dist_to_tp is not None else Fore.WHITE}{dist_to_tp_display}",
            sl_display,
            f"{get_color_for_distance(dist_to_sl) if dist_to_sl is not None else Fore.WHITE}{dist_to_sl_display}",
            f"{amount:.4f}",
            f"{action_color}{action}"
        ])

    headers = [
        "Symbol", "Side", "Entry Price", "Current", "PnL",
        "Take-Profit", "To TP", "Stop-Loss", "To SL", "Amount", "Action"
    ]

    print(tabulate(table_data, headers=headers, tablefmt="grid"))

    # Show alerts
    if alerts:
        print(f"\n{Back.RED}{Fore.WHITE}{Style.BRIGHT} 🚨 POSITION ALERTS - ACTION REQUIRED: {Style.RESET_ALL}")
        for alert in alerts:
            if "TRIGGERED" in alert or "reached" in alert.lower():
                print(f"  {Fore.RED + Style.BRIGHT}{alert}")
            else:
                print(f"  {Fore.YELLOW + Style.BRIGHT}{alert}")

def print_portfolio_summary(positions, prices):
    """Print portfolio summary"""
    if not positions:
        return

    total_value = 0
    total_cost = 0
    positions_with_targets = 0

    for symbol, pos in positions.items():
        current_price = prices.get(symbol)
        if current_price is None:
            continue

        amount = pos['amount']
        entry_price = pos['entry_price']
        take_profit = pos.get('take_profit_price')
        stop_loss = pos.get('stop_loss_price')

        total_value += current_price * amount
        total_cost += entry_price * amount
        
        if take_profit and stop_loss:
            positions_with_targets += 1

    if total_cost > 0:
        total_pnl = ((total_value - total_cost) / total_cost) * 100
        print(f"\n{Fore.YELLOW}{Style.BRIGHT}💰 PORTFOLIO SUMMARY:")
        print(f"{Fore.WHITE}  Open Positions Value: ${total_value:.4f} USDT")
        print(f"{Fore.WHITE}  Total Cost: ${total_cost:.4f} USDT")
        print(f"{Fore.WHITE}  Unrealized PnL: {get_color_for_pnl(total_pnl)}{total_pnl:+.2f}%")
        if positions_with_targets > 0:
            print(f"{Fore.WHITE}  Positions with Targets: {positions_with_targets}/{len(positions)}")

def print_recent_signals(signals):
    """Print recent trading signals"""
    print(f"\n{Fore.CYAN}{Style.BRIGHT}🔔 RECENT SIGNALS (Last 5):")
    if not signals:
        print(f"{Fore.WHITE}  No recent signals")
        return

    for sig in signals[:5]:
        timestamp = sig.get('timestamp', datetime.now().isoformat())
        time_str = timestamp[11:19] if len(timestamp) > 19 else timestamp
        symbol = sig.get('symbol', 'UNKNOWN')
        direction = sig.get('direction', 'hold')
        confidence = sig.get('confidence', 0) * 100

        if direction == 'buy':
            color = Fore.GREEN
            emoji = "🟢"
        elif direction == 'sell':
            color = Fore.RED
            emoji = "🔴"
        else:
            continue

        print(f"  {emoji} {time_str} | {symbol:15s} | {color}{direction.upper():4s}{Fore.WHITE} | Confidence: {confidence:.0f}%")

def print_recent_trades(trades):
    """Print recent executed trades"""
    print(f"\n{Fore.GREEN}{Style.BRIGHT}💰 RECENT TRADES (Last 5):")
    if not trades:
        print(f"{Fore.WHITE}  No trades executed yet")
        return

    for trade in trades[:5]:
        timestamp = trade.get('timestamp', datetime.now().isoformat())
        time_str = timestamp[11:19] if len(timestamp) > 19 else timestamp
        symbol = trade.get('symbol', 'UNKNOWN')
        side = trade.get('side', 'unknown')
        amount = trade.get('amount', 0)
        price = trade.get('price', 0)

        if side == 'buy':
            color = Fore.GREEN
            emoji = "✅"
        else:
            color = Fore.RED
            emoji = "🔻"

        print(f"  {emoji} {time_str} | {symbol:15s} | {color}{side.upper():4s}{Fore.WHITE} | {amount:.4f} @ ${price:.6f}")

def print_balance_info(total_value, usdt, holdings):
    """Print account balance information"""
    if total_value is None:
        return

    print(f"\n{Fore.YELLOW}{Style.BRIGHT}💵 ACCOUNT BALANCE:")
    print(f"  USDT: ${usdt:.2f}")
    print(f"  {Fore.CYAN}{Style.BRIGHT}Total Portfolio Value: ${total_value:.2f} USDT")

def print_holdings_monitor(holdings):
    """Print live holdings monitor with profit/loss tracking"""
    if not holdings:
        return

    print(f"\n{Fore.CYAN}{Style.BRIGHT}💼 WALLET HOLDINGS (Live Price Tracking):")
    print(f"{Fore.WHITE}Tracking your coin holdings - Shows real-time P/L since monitor started")
    print(f"{Fore.WHITE}Entry prices are locked when monitor starts for accurate P/L calculation\n")

    table_data = []
    total_holdings_value = 0
    total_holdings_pnl = 0

    for holding in holdings:
        coin = holding['coin']
        amount = holding['amount']
        entry_price = holding['entry_price']
        current_price = holding['current_price']
        price_change_pct = holding['price_change_pct']
        current_value = holding['current_value']
        value_change = holding['value_change']
        
        total_holdings_value += current_value
        total_holdings_pnl += value_change

        # Determine status and color based on P/L
        if price_change_pct >= 0.5:  # Significant profit (0.5%+)
            status = f"{Fore.GREEN}📈 Strong Profit"
            change_color = Fore.GREEN + Style.BRIGHT
        elif price_change_pct >= 0.2:  # Moderate profit (0.2-0.5%)
            status = f"{Fore.GREEN}📈 Profit"
            change_color = Fore.GREEN
        elif price_change_pct > 0:  # Small profit (0-0.2%)
            status = f"{Fore.CYAN}📊 Slight Profit"
            change_color = Fore.CYAN
        elif price_change_pct >= -0.2:  # Small loss (0 to -0.2%)
            status = f"{Fore.YELLOW}📊 Slight Loss"
            change_color = Fore.YELLOW
        elif price_change_pct >= -0.5:  # Moderate loss (-0.2% to -0.5%)
            status = f"{Fore.RED}📉 Loss"
            change_color = Fore.RED
        else:  # Significant loss (-0.5%+)
            status = f"{Fore.RED}📉 Strong Loss"
            change_color = Fore.RED + Style.BRIGHT

        # Calculate P/L percentage for display
        pnl_pct_display = f"{price_change_pct:+.3f}%"
        
        table_data.append([
            coin,
            f"{amount:.4f}",
            f"${entry_price:.6f}",
            f"${current_price:.6f}",
            f"{change_color}{pnl_pct_display}{Style.RESET_ALL}",
            f"${current_value:.2f}",
            f"{change_color}${value_change:+.2f}{Style.RESET_ALL}",
            status
        ])

    headers = [
        "Coin", "Amount", "Entry Price", "Current Price", "P/L %",
        "Value", "P/L $", "Status"
    ]

    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    
    # Show summary
    if total_holdings_pnl != 0:
        summary_color = Fore.GREEN if total_holdings_pnl > 0 else Fore.RED
        print(f"\n{Fore.WHITE}Holdings Summary: Total Value: ${total_holdings_value:.2f} | Total P/L: {summary_color}${total_holdings_pnl:+.2f}{Fore.WHITE}")

def main():
    """Main monitoring loop"""
    print(f"{Fore.CYAN}{Style.BRIGHT}Starting enhanced real-time trading monitor...")
    print(f"{Fore.WHITE}📊 Positions: Monitors open positions with dynamic stop-loss/take-profit targets")
    print(f"{Fore.WHITE}💼 Holdings: Tracks wallet holdings with real-time P/L (entry prices locked at start)")
    print(f"{Fore.WHITE}💰 Real-time: Live prices, P/L, and alerts from MEXC")
    print(f"{Fore.YELLOW}Press Ctrl+C to exit\n")

    try:
        while True:
            # Get all data
            total_value, usdt, holdings = get_account_balance()
            positions = get_positions()
            symbols = list(positions.keys())
            prices = get_live_prices(symbols) if symbols else {}
            signals = get_recent_signals()
            trades = get_recent_trades()

            # Display everything
            print_header(total_value)
            print_balance_info(total_value, usdt, holdings)
            print_holdings_monitor(holdings)
            print_positions_table(positions, prices)
            print_portfolio_summary(positions, prices)
            print_recent_signals(signals)
            print_recent_trades(trades)

            print(f"\n{Fore.CYAN}🔄 Refreshing in 5 seconds... (Ctrl+C to exit)")
            print("\n" + "="*120 + "\n")  # Separator line between updates
            time.sleep(5)

    except KeyboardInterrupt:
        print(f"\n\n{Fore.YELLOW}👋 Monitor stopped by user")
    except Exception as e:
        print(f"\n{Fore.RED}❌ Error: {e}")
        print(f"{Fore.YELLOW}Check Redis connection and MEXC API keys")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()