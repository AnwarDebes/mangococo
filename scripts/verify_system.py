#!/usr/bin/env python3
"""Quick system verification script"""
import os
import json
import redis
import urllib.request
from datetime import datetime, timezone

def load_env():
    env_file = os.path.join(os.path.dirname(__file__), "..", "config", "trading.env")
    env_vars = {}
    try:
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().split("#")[0].strip().strip("'\"")
    except:
        pass
    return env_vars

env = load_env()
redis_host = "localhost"
redis_port = 6379
redis_password = env.get("REDIS_PASSWORD", "")

print("="*70)
print("SYSTEM VERIFICATION REPORT")
print("="*70)

# Check Redis
try:
    r = redis.Redis(host=redis_host, port=redis_port, password=redis_password or None, decode_responses=True)
    r.ping()
    ticks_count = r.hlen("latest_ticks")
    print(f"\n[OK] Redis: Connected")
    print(f"  Symbols in Redis: {ticks_count}")
    
    # Check data freshness
    if ticks_count > 0:
        sample = r.hget("latest_ticks", "BTC/USDT")
        if sample:
            tick = json.loads(sample)
            ts = datetime.fromisoformat(tick["timestamp"].replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            age = (now - ts.replace(tzinfo=timezone.utc)).total_seconds()
            print(f"  BTC/USDT data age: {age:.1f} seconds")
            print(f"  BTC/USDT price: ${tick['price']:,.2f}")
            if age < 60:
                print(f"  [OK] Data is fresh (<60s old)")
            else:
                print(f"  [WARN] Data is stale (>60s old)")
except Exception as e:
    print(f"\n[ERROR] Redis: Error - {e}")

# Check API Gateway
try:
    req = urllib.request.Request("http://127.0.0.1:8080/status")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
        services = data.get("services", {})
        
        print(f"\n[OK] API Gateway: Connected")
        print(f"\nService Health:")
        for name, info in services.items():
            status = "[OK] healthy" if info.get("healthy") else "[ERROR] unhealthy"
            print(f"  {name}: {status}")
            
            if name == "market_data":
                resp_data = info.get("response", {})
                symbols = resp_data.get("symbols", 0)
                print(f"    - {symbols} symbols in Redis")
                
            if name == "prediction":
                resp_data = info.get("response", {})
                tracked = resp_data.get("symbols_tracked", 0)
                print(f"    - {tracked} symbols tracked")
                
except Exception as e:
    print(f"\n[ERROR] API Gateway: Error - {e}")

# Check trading_pairs.txt
try:
    pairs_file = os.path.join(os.path.dirname(__file__), "..", "config", "trading_pairs.txt")
    with open(pairs_file, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
        print(f"\n[OK] trading_pairs.txt: {len(lines)} symbols")
        print(f"  Sample: {lines[0]}, {lines[1]}, {lines[2]}...")
except Exception as e:
    print(f"\n[ERROR] trading_pairs.txt: Error - {e}")

print("\n" + "="*70)
print("VERIFICATION COMPLETE")
print("="*70)
