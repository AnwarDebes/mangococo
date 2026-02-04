#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real-Time Redis Update Monitor - Verifies Redis is being updated continuously
This script monitors Redis to ensure prices are being updated in real-time
"""
import os
import sys
import json
import time
import redis
from datetime import datetime, timezone

# Ensure unbuffered output
os.environ['PYTHONUNBUFFERED'] = '1'

def load_env():
    env_file = os.path.join(os.path.dirname(__file__), "..", "config", "trading.env")
    env_vars = {}
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().split("#")[0].strip().strip("'\"")
    return env_vars

def main():
    env = load_env()
    redis_host = env.get("REDIS_HOST", "localhost")
    if redis_host == "redis":
        redis_host = "localhost"
    redis_port = int(env.get("REDIS_PORT", "6379"))
    redis_password = env.get("REDIS_PASSWORD", "")
    
    print("="*70, flush=True)
    print("  REDIS REAL-TIME UPDATE VERIFICATION", flush=True)
    print("="*70, flush=True)
    print(f"Connecting to Redis at {redis_host}:{redis_port}...", flush=True)
    
    try:
        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password or None,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        r.ping()
        print("[OK] Redis connected successfully\n", flush=True)
    except Exception as e:
        print(f"[ERROR] Cannot connect to Redis: {e}", flush=True)
        return 1
    
    # Get initial state
    print("Checking latest_ticks hash...", flush=True)
    ticks = r.hgetall("latest_ticks")
    total_symbols = len(ticks)
    print(f"[OK] Found {total_symbols} symbols in latest_ticks\n", flush=True)
    
    if total_symbols == 0:
        print("[ERROR] No symbols found in Redis! Market-data service may not be running.", flush=True)
        return 1
    
    # Sample 10 random symbols to monitor
    sample_symbols = list(ticks.keys())[:10]
    print(f"Monitoring updates for {len(sample_symbols)} sample symbols:", flush=True)
    for sym in sample_symbols:
        print(f"  - {sym}", flush=True)
    print("", flush=True)
    
    # Track timestamps for each symbol
    symbol_timestamps = {}
    for symbol in sample_symbols:
        try:
            tick_json = ticks[symbol]
            tick_data = json.loads(tick_json)
            ts_str = tick_data.get("timestamp", "")
            if ts_str:
                tick_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                symbol_timestamps[symbol] = tick_time
        except:
            symbol_timestamps[symbol] = None
    
    print("="*70, flush=True)
    print("  MONITORING REAL-TIME UPDATES (Press Ctrl+C to stop)", flush=True)
    print("="*70, flush=True)
    print("Checking every 2 seconds for updates...\n", flush=True)
    
    update_count = 0
    check_count = 0
    
    try:
        while True:
            check_count += 1
            now = datetime.now(timezone.utc)
            updates_found = []
            stale_symbols = []
            
            # Check each sample symbol
            for symbol in sample_symbols:
                try:
                    tick_json = r.hget("latest_ticks", symbol)
                    if tick_json:
                        tick_data = json.loads(tick_json)
                        ts_str = tick_data.get("timestamp", "")
                        price = tick_data.get("price", 0)
                        
                        if ts_str:
                            tick_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                            age_seconds = (now - tick_time.replace(tzinfo=timezone.utc)).total_seconds()
                            
                            # Check if this symbol was updated since last check
                            if symbol in symbol_timestamps:
                                old_time = symbol_timestamps[symbol]
                                if old_time and tick_time > old_time:
                                    updates_found.append(symbol)
                                    update_count += 1
                            
                            symbol_timestamps[symbol] = tick_time
                            
                            # Flag stale data (> 10 seconds old)
                            if age_seconds > 10:
                                stale_symbols.append((symbol, age_seconds))
                except Exception as e:
                    pass
            
            # Display status
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            if updates_found:
                print(f"[{timestamp}] [UPDATE] {len(updates_found)} symbols updated: {', '.join(updates_found[:5])}", flush=True)
                if len(updates_found) > 5:
                    print(f"         ... and {len(updates_found) - 5} more", flush=True)
            
            if stale_symbols:
                print(f"[{timestamp}] [STALE] {len(stale_symbols)} symbols have stale data (>10s):", flush=True)
                for sym, age in stale_symbols[:3]:
                    print(f"         {sym}: {age:.1f}s old", flush=True)
            
            if not updates_found and not stale_symbols:
                # Show summary every 10 checks
                if check_count % 10 == 0:
                    print(f"[{timestamp}] [OK] Redis is updating. Total updates detected: {update_count}", flush=True)
            
            # Overall health check
            all_ticks = r.hgetall("latest_ticks")
            current_count = len(all_ticks)
            if current_count != total_symbols:
                print(f"[{timestamp}] [INFO] Symbol count changed: {total_symbols} -> {current_count}", flush=True)
                total_symbols = current_count
            
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\n\n" + "="*70, flush=True)
        print("  SUMMARY", flush=True)
        print("="*70, flush=True)
        print(f"Total checks performed: {check_count}", flush=True)
        print(f"Total updates detected: {update_count}", flush=True)
        if update_count > 0:
            print(f"[OK] Redis IS being updated in real-time!", flush=True)
        else:
            print(f"[WARNING] No updates detected during monitoring period.", flush=True)
            print(f"         This may indicate market-data service is not publishing to Redis.", flush=True)
        return 0
    except Exception as e:
        print(f"\n[ERROR] Monitor error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
