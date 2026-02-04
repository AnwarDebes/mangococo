"""
API Gateway - Central entry point for all services
"""
import json
import os
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import asyncio

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

SERVICES = {
    "market_data": "http://market-data:8001",
    "prediction": "http://prediction:8000",
    "signal": "http://signal:8000",
    "risk": "http://risk:8000",
    "executor": "http://executor:8005",  # Now in bridge network mode
    "position": "http://position:8000",
}

logger = structlog.get_logger()
redis_client: Optional[aioredis.Redis] = None
http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, http_client
    logger.info("Starting API Gateway...")
    redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    http_client = httpx.AsyncClient(timeout=30.0)
    yield
    if http_client:
        await http_client.aclose()
    if redis_client:
        await redis_client.close()


app = FastAPI(title="MangoCoco API Gateway", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/", response_class=HTMLResponse)
async def terminal():
    """Enhanced terminal interface with auto-scroll and wallet tracking"""
    return """<!DOCTYPE html>
<html><head><title>MangoCoco Terminal</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Fira Code',monospace;background:#0a0a0a;color:#0f0;overflow:hidden}
.container{display:grid;grid-template-columns:300px 1fr;grid-template-rows:60px 1fr;height:100vh;gap:2px;background:#222}
.header{grid-column:1/-1;background:linear-gradient(90deg,#1a1a2e,#16213e);padding:10px 20px;display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #0f0}
.logo{font-size:24px;font-weight:bold;color:#0f0;text-shadow:0 0 10px #0f0}
.time{color:#ff0;font-size:14px}
.sidebar{background:#111;padding:15px;overflow-y:auto}
.panel{background:#1a1a1a;border:1px solid #333;border-radius:8px;padding:12px;margin-bottom:12px}
.panel-title{color:#0ff;font-size:12px;text-transform:uppercase;margin-bottom:10px;border-bottom:1px solid #333;padding-bottom:5px}
.wallet-item{display:flex;justify-content:space-between;padding:4px 0;font-size:11px;border-bottom:1px solid #222}
.wallet-item:last-child{border:none}
.coin{color:#fff}.amt{color:#0f0}
.terminal{background:#0d0d0d;padding:15px;overflow-y:auto;scroll-behavior:smooth}
.log{padding:3px 0;font-size:12px;border-left:3px solid transparent;padding-left:8px;animation:fadeIn .3s}
@keyframes fadeIn{from{opacity:0;transform:translateX(-10px)}to{opacity:1;transform:translateX(0)}}
.log.status{border-color:#0ff;color:#0ff}.log.error{border-color:#f44;color:#f44}
.log.success{border-color:#0f0;color:#0f0}.log.price{border-color:#87ceeb;color:#87ceeb}
.log.trade{border-color:#f0f;color:#f0f}.log.signal{border-color:#ff0;color:#ff0}
.log.pnl-pos{border-color:#0f0;color:#0f0}.log.pnl-neg{border-color:#f44;color:#f44}
.ts{color:#666;margin-right:8px}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
.stat{background:#222;padding:8px;border-radius:4px;text-align:center}
.stat-val{font-size:16px;font-weight:bold;color:#0f0}.stat-lbl{font-size:10px;color:#888}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:#111}::-webkit-scrollbar-thumb{background:#333;border-radius:3px}
</style></head>
<body>
<div class="container">
<div class="header"><div class="logo">MANGOCOCO</div><div class="time" id="time"></div></div>
<div class="sidebar">
<div class="stats">
<div class="stat"><div class="stat-val" id="total">$0.00</div><div class="stat-lbl">TOTAL</div></div>
<div class="stat"><div class="stat-val" id="pnl">$0.00</div><div class="stat-lbl">P&L</div></div>
</div>
<div class="panel"><div class="panel-title">MEXC Wallet</div><div id="wallet">Loading...</div></div>
<div class="panel"><div class="panel-title">Bot Positions</div><div id="positions">Loading...</div></div>
</div>
<div class="terminal" id="terminal"></div>
</div>
<script>
const terminal=document.getElementById('terminal'),wallet=document.getElementById('wallet'),positions=document.getElementById('positions');
const updateTime=()=>document.getElementById('time').textContent=new Date().toLocaleString();
setInterval(updateTime,1000);updateTime();

const log=(msg,cls='')=>{const d=document.createElement('div');d.className='log '+cls;d.innerHTML='<span class="ts">'+new Date().toLocaleTimeString()+'</span>'+msg;terminal.appendChild(d);terminal.scrollTop=terminal.scrollHeight;if(terminal.children.length>200)terminal.removeChild(terminal.firstChild)};

const loadWallet=async()=>{try{const r=await fetch('/api/balance');if(r.ok){const d=await r.json();let h='';if(d.balances){Object.entries(d.balances).filter(([k,v])=>v.free>0||v.used>0).sort(([,a],[,b])=>(b.free||0)-(a.free||0)).forEach(([k,v])=>{const amt=v.free||0;const usd=amt*(k==='USDT'?1:0);h+=`<div class="wallet-item"><span class="coin">${k}</span><span class="amt">${amt.toFixed(k==='USDT'?2:8)}</span></div>`})}wallet.innerHTML=h||'<div style="color:#666">No assets</div>'}}catch(e){wallet.innerHTML='<div style="color:#f44">Error loading</div>'}};

const loadPositions=async()=>{try{const r=await fetch('/api/positions');if(r.ok){const d=await r.json();let h='';let totalPnl=0;Object.entries(d).forEach(([k,v])=>{const pnl=v.unrealized_pnl||0;totalPnl+=pnl;const cls=pnl>=0?'color:#0f0':'color:#f44';const entry=v.entry_price||0;const current=v.current_price||0;const amt=v.amount||0;const pnlPct=((current-entry)/entry*100)||0;const opened=new Date(v.opened_at||'').toLocaleString();h+=`<div class="wallet-item" style="display:block;margin:2px 0;padding:4px;border:1px solid #333;border-radius:3px"><div style="display:flex;justify-content:space-between"><span class="coin">${k}</span><span style="${cls}">$${pnl.toFixed(4)} (${pnlPct.toFixed(2)}%)</span></div><div style="font-size:10px;color:#888;margin-top:2px">Entry: $${entry.toFixed(6)} | Current: $${current.toFixed(6)} | Qty: ${amt.toFixed(6)}</div><div style="font-size:10px;color:#666">Opened: ${opened}</div></div>`});positions.innerHTML=h||'<div style="color:#666">No open positions</div>'}}catch(e){positions.innerHTML='<div style="color:#f44">Error</div>'}};

const loadPortfolio=async()=>{try{const r=await fetch('/api/portfolio');if(r.ok){const d=await r.json();const total=d.portfolio?.total_value||0;const pnl=d.summary?.total_unrealized_pnl||0;const pnlPct=total>0?(pnl/total*100):0;document.getElementById('total').textContent='$'+total.toFixed(2);const el=document.getElementById('pnl');el.textContent=(pnl>=0?'+':'')+pnl.toFixed(2)+' ('+(pnl>=0?'+':'')+pnlPct.toFixed(2)+'%)';el.style.color=pnl>=0?'#0f0':'#f44'}}catch(e){}};

const loadSignals=async()=>{try{const r=await fetch('/api/signals');if(r.ok){const s=await r.json();if(s.length>0)s.slice(-3).forEach(x=>log(`SIGNAL: ${x.symbol} ${x.action.toUpperCase()} @ $${x.price.toFixed(4)} (${(x.confidence*100).toFixed(1)}%)`,'signal'))}}catch(e){}};

const loadTrades=async()=>{try{const r=await fetch('/api/trades?limit=8');if(r.ok){const d=await r.json();if(d.trades){log('=== RECENT TRADES ===','status');d.trades.reverse().slice(0,5).forEach(t=>{const pnl=t.realized_pnl||0;const pnlPct=((t.exit_price-t.entry_price)/t.entry_price*100)||0;const pnlStr=pnl>=0?`+$${pnl.toFixed(4)}`:`$${pnl.toFixed(4)}`;const holdTime=t.hold_time_minutes||0;const holdStr=holdTime>60?`${(holdTime/60).toFixed(1)}h`:`${holdTime.toFixed(0)}m`;const entryStr=`Entry: $${t.entry_price.toFixed(6)}`;const exitStr=`Exit: $${t.exit_price.toFixed(6)}`;log(`${t.symbol} ${t.side.toUpperCase()} | ${entryStr} → ${exitStr} | P&L: ${pnlStr} (${pnlPct.toFixed(2)}%) | Qty: ${t.amount.toFixed(6)} | Held: ${holdStr}`,pnl>=0?'pnl-pos':'pnl-neg')});log('==================','status')}}catch(e){}};

const connectSSE=()=>{const es=new EventSource('/api/stream');es.onmessage=e=>{try{const d=JSON.parse(e.data);if(d.type==='price_update'&&(d.symbol.includes('BTC')||d.symbol.includes('ETH')||d.symbol.includes('SOL')))log(`${d.symbol}: $${d.price.toFixed(4)} (${d.change_pct>=0?'+':''}${d.change_pct.toFixed(2)}%)`,'price');else if(d.type==='trade_executed'){const amt=d.amount.toFixed(6);const price=d.price.toFixed(6);const value=(d.amount*d.price).toFixed(2);log(`🚀 TRADE EXECUTED: ${d.symbol} ${d.side.toUpperCase()} ${amt} @ $${price} = $${value}`,'trade');loadWallet();loadPortfolio();loadPositions();loadTrades()}else if(d.type==='signal_generated'){const conf=(d.confidence*100).toFixed(1);log(`AI SIGNAL: ${d.symbol} ${d.action.toUpperCase()} (${conf}% confidence)`,'signal')}else if(d.type==='portfolio_update'){loadPortfolio();loadPositions();loadWallet()}}catch(x){}};es.onerror=()=>{log('Connection lost, reconnecting...','error');setTimeout(connectSSE,5000)}};

log('MANGOCOCO REAL TRADING TERMINAL v1.0','status');
log('Loading wallet and positions...','status');
loadWallet();loadPortfolio();loadPositions();
setTimeout(()=>{log('Loading recent signals...','status');loadSignals();loadTrades();connectSSE()},2000);
setInterval(()=>{loadWallet();loadPortfolio();loadPositions()},15000);
</script></body></html>"""


@app.get("/status")
async def system_status():
    status = {}
    for name, url in SERVICES.items():
        try:
            response = await http_client.get(f"{url}/health", timeout=5.0)
            status[name] = {"healthy": response.status_code == 200, "response": response.json() if response.status_code == 200 else None}
        except Exception as e:
            status[name] = {"healthy": False, "error": str(e)}
    return {"timestamp": datetime.utcnow().isoformat(), "services": status}


@app.get("/api/tickers")
async def get_tickers():
    """Get all tickers directly from Redis for microsecond-level real-time data"""
    try:
        # Read ticker data directly from Redis (updated every 200ms by market-data service)
        latest_ticks = await redis_client.hgetall("latest_ticks")
        tickers = {}
        for symbol, tick_data_json in latest_ticks.items():
            try:
                tickers[symbol] = json.loads(tick_data_json)
            except json.JSONDecodeError:
                continue
        return tickers
    except Exception as e:
        logger.error("Failed to fetch tickers from Redis", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ticker/{symbol}")
async def get_ticker(symbol: str):
    """Get ticker for a specific symbol directly from Redis for microsecond-level real-time data"""
    try:
        symbol = symbol.replace("_", "/").upper()
        tick_data_json = await redis_client.hget("latest_ticks", symbol)
        if tick_data_json:
            return json.loads(tick_data_json)
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to fetch ticker from Redis", symbol=symbol, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/portfolio")
async def get_portfolio():
    try:
        risk_resp = await http_client.get(f"{SERVICES['risk']}/portfolio")
        pos_resp = await http_client.get(f"{SERVICES['position']}/positions")
        pnl_resp = await http_client.get(f"{SERVICES['position']}/pnl")

        portfolio_data = risk_resp.json()
        positions_data = pos_resp.json()
        pnl_data = pnl_resp.json()

        # Add more detailed portfolio info
        total_pnl = 0
        for symbol, position in positions_data.items():
            total_pnl += position.get('unrealized_pnl', 0)

        portfolio_data['total_unrealized_pnl'] = total_pnl
        portfolio_data['positions_count'] = len(positions_data)

        return {
            "portfolio": portfolio_data,
            "positions": positions_data,
            "pnl": pnl_data,
            "summary": {
                "total_positions": len(positions_data),
                "total_unrealized_pnl": total_pnl,
                "available_capital": portfolio_data.get('available_capital', 0),
                "total_value": portfolio_data.get('total_value', 0)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/positions")
async def get_positions():
    try:
        response = await http_client.get(f"{SERVICES['position']}/positions")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/balance")
async def get_balance():
    try:
        response = await http_client.get(f"{SERVICES['executor']}/balance")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/predictions")
async def get_predictions():
    try:
        response = await http_client.get(f"{SERVICES['prediction']}/predictions")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/trades")
async def get_trades(limit: int = 50):
    """Get recent trades history with P&L information"""
    try:
        # Get orders from position service (which should have trade history)
        response = await http_client.get(f"{SERVICES['position']}/trades")
        if response.status_code == 200:
            return response.json()

        # Fallback: get from executor if position service doesn't have trades endpoint
        response = await http_client.get(f"{SERVICES['executor']}/trades")
        return response.json()
    except Exception as e:
        # If no trades endpoint, return empty list
        return {"trades": [], "total": 0}


@app.post("/api/predict/{symbol}")
async def predict(symbol: str):
    try:
        response = await http_client.post(f"{SERVICES['prediction']}/predict/{symbol}")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/signals")
async def get_signals():
    try:
        response = await http_client.get(f"{SERVICES['signal']}/signals")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/manual-trade")
async def manual_trade(symbol: str, action: str, amount: float):
    try:
        response = await http_client.post(f"{SERVICES['signal']}/manual-signal", params={"symbol": symbol, "action": action, "amount": amount})
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/risk/limits")
async def get_risk_limits():
    try:
        response = await http_client.get(f"{SERVICES['risk']}/limits")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/emergency/stop")
async def emergency_stop():
    """Emergency stop all trading activities"""
    try:
        # Stop signal generation
        await http_client.post(f"{SERVICES['signal']}/emergency/stop")
        # Cancel any pending orders
        await http_client.post(f"{SERVICES['executor']}/emergency/cancel-all")
        return {"status": "success", "message": "All trading stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/emergency/close-all")
async def emergency_close_all():
    """Force sell all open positions"""
    try:
        positions_resp = await http_client.get(f"{SERVICES['position']}/positions")
        positions = positions_resp.json()

        closed_positions = []
        for symbol in positions.keys():
            try:
                # Create sell signal for each position
                await http_client.post(f"{SERVICES['signal']}/manual-signal",
                                     params={"symbol": symbol, "action": "sell", "amount": positions[symbol]["amount"]})
                closed_positions.append(symbol)
            except:
                pass

        return {"status": "success", "closed_positions": closed_positions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/emergency/reset")
async def emergency_reset():
    """Reset bot state and restart services"""
    try:
        # Reset portfolio state
        await http_client.post(f"{SERVICES['risk']}/update-capital", params={"amount": 4.73})
        # Clear any cached data
        await redis_client.flushdb()
        return {"status": "success", "message": "Bot state reset"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/manual/take-profit/{symbol}")
async def manual_take_profit(symbol: str):
    """Manually take profit on a position"""
    try:
        positions_resp = await http_client.get(f"{SERVICES['position']}/positions")
        positions = positions_resp.json()

        if symbol in positions:
            amount = positions[symbol]["amount"]
            await http_client.post(f"{SERVICES['signal']}/manual-signal",
                                 params={"symbol": symbol, "action": "sell", "amount": amount})
            return {"status": "success", "message": f"Take profit initiated for {symbol}"}
        else:
            raise HTTPException(status_code=404, detail=f"No position found for {symbol}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/manual/force-sell/{symbol}")
async def manual_force_sell(symbol: str):
    """Force sell a specific position"""
    try:
        positions_resp = await http_client.get(f"{SERVICES['position']}/positions")
        positions = positions_resp.json()

        if symbol in positions:
            amount = positions[symbol]["amount"]
            await http_client.post(f"{SERVICES['signal']}/manual-signal",
                                 params={"symbol": symbol, "action": "sell", "amount": amount})
            return {"status": "success", "message": f"Force sell initiated for {symbol}"}
        else:
            raise HTTPException(status_code=404, detail=f"No position found for {symbol}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stream")
async def stream_updates():
    """Server-Sent Events endpoint for real-time trading updates"""

    async def event_generator():
        """Generate SSE events for real-time updates"""
        while True:
            try:
                # Check for new price updates from Redis
                latest_ticks = await redis_client.hgetall("latest_ticks")
                for symbol, tick_data_json in latest_ticks.items():
                    try:
                        tick_data = json.loads(tick_data_json)
                        event_data = {
                            "type": "price_update",
                            "symbol": symbol,
                            "price": tick_data["price"],
                            "change_pct": tick_data.get("change_pct", 0),
                            "timestamp": tick_data["timestamp"]
                        }
                        yield f"data: {json.dumps(event_data)}\n\n"
                    except:
                        continue

                # Check for portfolio updates
                portfolio_state_str = await redis_client.get("portfolio_state")
                if portfolio_state_str:
                    try:
                        portfolio_state = json.loads(portfolio_state_str)
                        event_data = {
                            "type": "portfolio_update",
                            "total_value": portfolio_state.get("total_value", 0),
                            "daily_pnl": portfolio_state.get("daily_pnl", 0),
                            "timestamp": datetime.utcnow().isoformat()
                        }
                        yield f"data: {json.dumps(event_data)}\n\n"
                    except:
                        pass

            except Exception as e:
                logger.error("Error in event stream", error=str(e))

            await asyncio.sleep(1)  # Update every second

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )