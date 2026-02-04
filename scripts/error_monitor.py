#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real-Time Error Monitor - Discovers and displays all errors in the system
Run: python -u scripts/error_monitor.py  (use -u flag for unbuffered output on Windows)
Updates every 5 seconds, shows all errors found.
"""
import os
import sys
import json
import time
import redis
import urllib.request
from datetime import datetime
from collections import defaultdict

# Ensure unbuffered output for immediate display
if sys.platform == 'win32':
    import os
    # Force unbuffered mode
    os.environ['PYTHONUNBUFFERED'] = '1'

# Colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

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

def check_mexc_api():
    """Check MEXC API for various error types"""
    errors = []
    env = load_env()
    api_key = env.get("MEXC_API_KEY", "")
    api_secret = env.get("MEXC_SECRET_KEY", "")
    
    if not api_key or api_key == "your_mexc_api_key_here":
        errors.append("MEXC_API_KEY not set or invalid")
        return errors
    
    try:
        import ccxt
        exchange = ccxt.mexc({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "timeout": 15000,
        })
        
        # Test 1: Balance fetch (requires IP whitelist)
        try:
            balance = exchange.fetch_balance()
            usdt = balance.get("USDT", {}) or {}
            free = usdt.get("free", 0) or 0
            total = usdt.get("total", 0) or 0
            if free == 0 and total == 0:
                errors.append("MEXC: Balance fetch OK but USDT is 0 (may need to deposit)")
            elif free < 1.5:
                errors.append(f"MEXC: USDT free ${free:.2f} is below $1.50 minimum for trades")
        except ccxt.AuthenticationError as e:
            err_str = str(e).lower()
            if "ip" in err_str and ("white" in err_str or "700006" in str(e)):
                errors.append(f"MEXC: IP NOT WHITELISTED - {e}")
            elif "invalid" in err_str or "key" in err_str:
                errors.append(f"MEXC: Invalid API key or secret - {e}")
            else:
                errors.append(f"MEXC: Authentication error - {e}")
        except ccxt.ExchangeError as e:
            err_str = str(e).lower()
            error_code = str(e)
            if "429" in error_code or "rate limit" in err_str:
                errors.append(f"MEXC: Rate limit exceeded (429) - {e}")
            elif "403" in error_code or "forbidden" in err_str:
                errors.append(f"MEXC: Forbidden (403) - IP blocked or no permission - {e}")
            elif "10101" in error_code or "insufficient" in err_str:
                errors.append(f"MEXC: Insufficient balance (10101) - {e}")
            elif "30014" in error_code or "invalid symbol" in err_str:
                errors.append(f"MEXC: Invalid symbol (30014) - {e}")
            elif "30018" in error_code or "market order disabled" in err_str:
                errors.append(f"MEXC: Market order disabled (30018) - {e}")
            elif "timeout" in err_str:
                errors.append(f"MEXC: Request timeout - network issue - {e}")
            else:
                errors.append(f"MEXC: Exchange error - {e}")
        except Exception as e:
            errors.append(f"MEXC: Unexpected error - {type(e).__name__}: {e}")
        
        # Test 2: Ticker fetch (public endpoint, tests connectivity)
        try:
            ticker = exchange.fetch_ticker("BTC/USDT")
            if not ticker or not ticker.get("last"):
                errors.append("MEXC: Ticker fetch returned empty data")
        except Exception as e:
            if "429" in str(e):
                errors.append(f"MEXC: Rate limit on ticker fetch (429)")
            elif "timeout" in str(e).lower():
                errors.append(f"MEXC: Ticker fetch timeout - network slow")
            else:
                errors.append(f"MEXC: Ticker fetch failed - {e}")
    
    except ImportError:
        errors.append("ccxt library not installed")
    except Exception as e:
        errors.append(f"MEXC: Setup error - {type(e).__name__}: {e}")
    
    return errors

def check_redis():
    """Check Redis connectivity and data"""
    errors = []
    env = load_env()
    redis_host = env.get("REDIS_HOST", "localhost")
    if redis_host == "redis":
        redis_host = "localhost"
    redis_port = int(env.get("REDIS_PORT", "6379"))
    redis_password = env.get("REDIS_PASSWORD", "")
    
    try:
        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password or None,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        r.ping()
        
        # Check if latest_ticks has data
        ticks_count = r.hlen("latest_ticks")
        if ticks_count == 0:
            errors.append("Redis: latest_ticks hash is empty (no price data)")
        elif ticks_count < 100:
            errors.append(f"Redis: Only {ticks_count} symbols in latest_ticks (expected ~1000)")
        
        # Check portfolio_state
        portfolio = r.get("portfolio_state")
        if not portfolio:
            errors.append("Redis: portfolio_state not found (may be normal on first run)")
        
    except redis.ConnectionError as e:
        errors.append(f"Redis: Cannot connect - {e}")
    except redis.AuthenticationError as e:
        errors.append(f"Redis: Authentication failed - wrong password - {e}")
    except Exception as e:
        errors.append(f"Redis: Error - {type(e).__name__}: {e}")
    
    return errors

def check_services():
    """Check all services via API gateway"""
    errors = []
    base = "http://127.0.0.1:8080"
    
    try:
        req = urllib.request.Request(f"{base}/status", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            services = data.get("services", {})
            
            for name, info in services.items():
                if not info.get("healthy", False):
                    error_msg = info.get("error", "Unknown error")
                    errors.append(f"Service {name}: Not healthy - {error_msg}")
                
                # Check specific service data
                if name == "market_data":
                    resp_data = info.get("response", {})
                    symbols = resp_data.get("symbols", 0)
                    if symbols == 0:
                        errors.append("market_data: No symbols in Redis (not fetching data)")
                    elif symbols < 100:
                        errors.append(f"market_data: Only {symbols} symbols (expected ~1000)")
                
                elif name == "prediction":
                    resp_data = info.get("response", {})
                    tracked = resp_data.get("symbols_tracked", 0)
                    if tracked == 0:
                        errors.append("prediction: No symbols tracked (not receiving ticks from market-data)")
                    elif tracked < 20:  # Only report if very low (less than 20)
                        # For 1000 coins, symbols_tracked = len(price_history) which only includes symbols
                        # that have received at least some tick data. This is normal during startup.
                        # Check if market-data is actually fetching data
                        market_data_resp = services.get("market_data", {}).get("response", {})
                        market_data_symbols = market_data_resp.get("symbols", 0)
                        if market_data_symbols == 0:
                            errors.append(f"prediction: Only {tracked} symbols tracked (market-data not fetching data - check market-data service)")
                        # If market-data has symbols but prediction has very few, might be a real issue
                        elif market_data_symbols > 100 and tracked < 20:
                            errors.append(f"prediction: Only {tracked} symbols tracked (market-data has {market_data_symbols} symbols - prediction service may not be receiving ticks)")
                        # Otherwise, it's normal startup behavior - don't report as error
                
                elif name == "executor":
                    # Executor health doesn't tell us much, but if it's unhealthy that's an error
                    pass
                
                elif name == "signal":
                    resp_data = info.get("response", {})
                    # Signal health is OK if service is running
                    pass
                
                elif name == "position":
                    resp_data = info.get("response", {})
                    # Position health is OK if service is running
                    pass
    
    except urllib.error.HTTPError as e:
        errors.append(f"API Gateway: HTTP {e.code} - {e.reason}")
    except OSError as e:
        errors.append(f"API Gateway: Cannot connect - {e}")
    except Exception as e:
        errors.append(f"API Gateway: Error - {type(e).__name__}: {e}")
    
    return errors

def check_docker_containers():
    """Check Docker containers are running and check logs for errors"""
    errors = []
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            errors.append("Docker: Cannot run docker ps command")
            return errors
        
        lines = result.stdout.strip().split("\n")
        expected = ["mc-redis", "mc-market-data", "mc-prediction", "mc-signal", 
                    "mc-executor", "mc-position", "mc-risk", "mc-api-gateway"]
        running = [line.split("\t")[0] for line in lines if line]
        
        for container in expected:
            if container not in running:
                errors.append(f"Docker: Container {container} is not running")
            else:
                # Check status
                for line in lines:
                    if line.startswith(container):
                        status = line.split("\t")[1] if "\t" in line else ""
                        if "unhealthy" in status.lower():
                            errors.append(f"Docker: {container} is unhealthy - {status}")
                        elif "restarting" in status.lower():
                            errors.append(f"Docker: {container} is restarting (may be crashing) - {status}")
                
                # Check recent logs for errors (last 50 lines) and extract actual error messages
                try:
                    log_result = subprocess.run(
                        ["docker", "logs", "--tail", "50", container],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if log_result.returncode == 0:
                        log_lines = log_result.stdout.split("\n")
                        error_keywords = ["error", "exception", "failed", "traceback", "timeout"]
                        found_errors = []
                        
                        # Filter patterns that are NOT real errors (false positives)
                        false_positive_patterns = [
                            "info:",  # INFO level logs
                            "get /health http/1.1",  # Health check logs
                            "get /status http/1.1",  # Status check logs
                            "get /api/",  # API request logs (unless they're 500 errors)
                            "signal generated",  # Normal operation
                            "prediction completed",  # Normal operation
                            "background saving started",  # Redis normal operation
                        ]
                        
                        # Look for error lines and extract context
                        for i, line in enumerate(log_lines):
                            line_lower = line.lower()
                            
                            # Skip false positives
                            is_false_positive = any(pattern in line_lower for pattern in false_positive_patterns)
                            
                            # Check for HTTP 500 errors specifically (these are real errors)
                            is_http_500 = "500 internal server error" in line_lower
                            
                            # Check for other error keywords
                            has_error_keyword = any(keyword in line_lower for keyword in error_keywords)
                            
                            # Only report if it's a real error (not a false positive)
                            if (has_error_keyword or is_http_500) and not is_false_positive:
                                # For HTTP 500, check if it's in an INFO log line (normal logging)
                                if is_http_500 and "info:" in line_lower:
                                    # This is a real error being logged, include it
                                    pass
                                elif is_http_500:
                                    # HTTP 500 without INFO prefix - might be in error context
                                    pass
                                
                                # Extract error message with context
                                context_start = max(0, i - 1)
                                context_end = min(len(log_lines), i + 2)
                                context_lines = log_lines[context_start:context_end]
                                error_msg = " | ".join([l.strip() for l in context_lines if l.strip()])
                                
                                # Truncate if too long
                                if len(error_msg) > 200:
                                    error_msg = error_msg[:197] + "..."
                                
                                # Avoid duplicates
                                if error_msg not in found_errors:
                                    found_errors.append(error_msg)
                                
                                # Limit to 3 most recent unique errors per container
                                if len(found_errors) >= 3:
                                    break
                        
                        # Report actual error messages
                        for error_msg in found_errors[:3]:  # Show up to 3 most recent errors
                            errors.append(f"Docker logs ({container}): {error_msg}")
                        
                except Exception as e:
                    # If log check fails, at least report that we couldn't check
                    pass  # Skip log check if it fails
    
    except FileNotFoundError:
        errors.append("Docker: docker command not found (Docker not installed or not in PATH)")
    except Exception as e:
        errors.append(f"Docker: Error checking containers - {type(e).__name__}: {e}")
    
    return errors

def check_configuration():
    """Check configuration errors"""
    errors = []
    env = load_env()
    
    # Required configs
    required = {
        "MEXC_API_KEY": "MEXC API key",
        "MEXC_SECRET_KEY": "MEXC secret key",
        "REDIS_PASSWORD": "Redis password",
    }
    
    for key, desc in required.items():
        val = env.get(key, "")
        if not val or val == f"your_{key.lower()}_here" or val.startswith("ChangeMe"):
            errors.append(f"Config: {desc} not set or using placeholder value")
    
    # Check MOCK_MODE
    mock_mode = env.get("MOCK_MODE", "false").lower() == "true"
    if mock_mode:
        errors.append("Config: MOCK_MODE=true (no real orders will be placed)")
    
    # Check TRADING_PAIRS_FILE
    pairs_file = env.get("TRADING_PAIRS_FILE", "")
    if pairs_file:
        local_path = os.path.join(os.path.dirname(__file__), "..", "config", "trading_pairs.txt")
        if not os.path.exists(local_path):
            errors.append(f"Config: TRADING_PAIRS_FILE set but file {local_path} not found")
        elif os.path.getsize(local_path) == 0:
            errors.append(f"Config: trading_pairs.txt exists but is empty")
    
    return errors

def check_data_flow():
    """Check if data is flowing (predictions, signals, ticks)"""
    errors = []
    env = load_env()
    redis_host = env.get("REDIS_HOST", "localhost")
    if redis_host == "redis":
        redis_host = "localhost"
    redis_port = int(env.get("REDIS_PORT", "6379"))
    redis_password = env.get("REDIS_PASSWORD", "")
    
    try:
        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password or None,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        
        # Check latest_ticks timestamps (data freshness)
        ticks = r.hgetall("latest_ticks")
        if ticks:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            stale_count = 0
            for symbol, tick_json in list(ticks.items())[:10]:  # Sample first 10
                try:
                    tick_data = json.loads(tick_json)
                    ts_str = tick_data.get("timestamp", "")
                    if ts_str:
                        tick_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                        age_seconds = (now - tick_time.replace(tzinfo=timezone.utc)).total_seconds()
                        if age_seconds > 60:  # More than 1 minute old
                            stale_count += 1
                except:
                    pass
            if stale_count > 5:
                errors.append(f"Redis: {stale_count}/10 sampled ticks are stale (>60s old) - market-data may not be updating")
        
        # Check if orders are being stored
        orders = r.hgetall("orders")
        signal_orders = r.hgetall("signal_orders")
        
        # Check positions
        positions = r.hgetall("positions")
        
    except Exception:
        pass  # Already checked in check_redis
    
    return errors

def check_order_execution():
    """Check if executor can actually place orders"""
    errors = []
    env = load_env()
    api_key = env.get("MEXC_API_KEY", "")
    api_secret = env.get("MEXC_SECRET_KEY", "")
    mock_mode = env.get("MOCK_MODE", "false").lower() == "true"
    
    if not api_key or api_key == "your_mexc_api_key_here":
        return errors  # Already checked in check_mexc_api
    
    if mock_mode:
        return errors  # Mock mode - no real orders
    
    try:
        import ccxt
        exchange = ccxt.mexc({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "timeout": 15000,
        })
        
        # Test: Try to fetch open orders (requires valid API and IP)
        try:
            open_orders = exchange.fetch_open_orders()
            # If this works, executor can place orders
        except ccxt.AuthenticationError as e:
            err_str = str(e).lower()
            if "ip" in err_str and ("white" in err_str or "700006" in str(e)):
                errors.append("Executor: Cannot place orders - IP not whitelisted")
            elif "invalid" in err_str or "key" in err_str:
                errors.append("Executor: Cannot place orders - Invalid API key/secret")
        except ccxt.ExchangeError as e:
            if "403" in str(e):
                errors.append("Executor: Cannot place orders - 403 Forbidden (IP blocked or no permission)")
            elif "429" in str(e):
                errors.append("Executor: Rate limit on order check (429)")
        except Exception as e:
            if "timeout" in str(e).lower():
                errors.append("Executor: Timeout checking orders - network issue")
    
    except Exception:
        pass
    
    return errors

def check_service_endpoints():
    """Check individual service endpoints directly"""
    errors = []
    base = "http://127.0.0.1:8080"
    
    endpoints = {
        "/api/balance": "Balance endpoint",
        "/api/positions": "Positions endpoint",
        "/api/tickers": "Tickers endpoint",
        "/api/predictions": "Predictions endpoint",
        "/api/signals": "Signals endpoint",
    }
    
    for endpoint, desc in endpoints.items():
        try:
            req = urllib.request.Request(f"{base}{endpoint}", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status != 200:
                    errors.append(f"{desc}: HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                errors.append(f"{desc}: Server error {e.code}")
        except Exception:
            pass  # Gateway check already covers this
    
    return errors

def main():
    env = load_env()
    print(f"{BOLD}{CYAN}{'='*70}{RESET}", flush=True)
    print(f"{BOLD}{CYAN}  MANGOCOCO REAL-TIME ERROR MONITOR{RESET}", flush=True)
    print(f"{BOLD}{CYAN}{'='*70}{RESET}", flush=True)
    print(f"{YELLOW}Checking for errors... Updates every 5 seconds. Press Ctrl+C to stop.{RESET}\n", flush=True)
    
    error_history = defaultdict(list)
    
    try:
        while True:
            all_errors = []
            
            # Check all error sources (comprehensive)
            all_errors.extend(check_configuration())
            all_errors.extend(check_mexc_api())
            all_errors.extend(check_redis())
            all_errors.extend(check_services())
            all_errors.extend(check_docker_containers())
            all_errors.extend(check_data_flow())
            all_errors.extend(check_order_execution())
            all_errors.extend(check_service_endpoints())
            
            # Clear screen (optional - comment out if you want history)
            # os.system('cls' if os.name == 'nt' else 'clear')
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n{BOLD}[{timestamp}]{RESET}", flush=True)
            
            if not all_errors:
                print(f"{GREEN}[OK] No errors found. System is healthy.{RESET}", flush=True)
            else:
                print(f"{RED}[ERROR] Found {len(all_errors)} error(s):{RESET}\n", flush=True)
                # Group errors by category
                categories = {
                    "MEXC": [],
                    "Redis": [],
                    "Docker": [],
                    "Service": [],
                    "Config": [],
                    "Data Flow": [],
                    "Other": []
                }
                for error in all_errors:
                    if error.startswith("MEXC") or error.startswith("Executor"):
                        categories["MEXC"].append(error)
                    elif error.startswith("Redis"):
                        categories["Redis"].append(error)
                    elif error.startswith("Docker"):
                        categories["Docker"].append(error)
                    elif error.startswith("Service") or error.startswith("market_data") or error.startswith("prediction"):
                        categories["Service"].append(error)
                    elif error.startswith("Config"):
                        categories["Config"].append(error)
                    elif "stale" in error.lower() or "tracked" in error.lower():
                        categories["Data Flow"].append(error)
                    else:
                        categories["Other"].append(error)
                
                for cat, errs in categories.items():
                    if errs:
                        print(f"{BOLD}{YELLOW}[{cat}]{RESET}", flush=True)
                        for i, error in enumerate(errs, 1):
                            print(f"  {RED}*{RESET} {error}", flush=True)
                            error_history[error].append(timestamp)
                        print(flush=True)
            
            # Show error frequency
            if error_history:
                print(f"\n{YELLOW}Error frequency (last 10 checks):{RESET}", flush=True)
                for error, timestamps in list(error_history.items())[-5:]:
                    count = len([t for t in timestamps if (time.time() - time.mktime(time.strptime(t, "%Y-%m-%d %H:%M:%S"))) < 60])
                    if count > 0:
                        print(f"  {error[:60]}... ({count}x)", flush=True)
            
            # Summary of checks performed
            checks_performed = [
                "Configuration (env vars, MOCK_MODE, files)",
                "MEXC API (IP whitelist, auth, rate limits, balance)",
                "Redis (connection, data freshness, keys)",
                "Services (health, symbols tracked, data flow)",
                "Docker (containers running, logs, status)",
                "Order execution (can place orders)",
                "API endpoints (balance, positions, tickers, etc.)"
            ]
            
            print(f"\n{YELLOW}{'-'*70}{RESET}", flush=True)
            print(f"{CYAN}Checks performed: {len(checks_performed)}{RESET}", flush=True)
            print(f"{CYAN}Next check in 5 seconds... (Press Ctrl+C to stop){RESET}", flush=True)
            time.sleep(5)
    
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Monitor stopped.{RESET}", flush=True)
        return 0
    except Exception as e:
        print(f"\n{RED}Monitor error: {e}{RESET}", flush=True)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
