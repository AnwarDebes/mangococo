#!/usr/bin/env python3
"""
MangoCoco System Health Check - Verifies full system and MEXC API (IP not blocked).
Run: python scripts/system_health_check.py
"""
import os
import sys
import json

def load_env():
    env_file = os.path.join(os.path.dirname(__file__), "..", "config", "trading.env")
    env_vars = {}
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip().split("#")[0].strip().strip("'\"")
    return env_vars

def main():
    env = load_env()
    api_key = env.get("MEXC_API_KEY", "")
    api_secret = env.get("MEXC_SECRET_KEY", "")
    redis_host = env.get("REDIS_HOST", "localhost")
    if redis_host == "redis":
        redis_host = "localhost"  # When running script on host, Docker exposes 6379 on localhost
    redis_port = int(env.get("REDIS_PORT", "6379"))
    redis_password = env.get("REDIS_PASSWORD", "")

    results = {"mexc_api": None, "redis": None, "api_gateway": None, "services": None}
    all_ok = True

    print("=" * 60)
    print("  MANGOCOCO SYSTEM HEALTH CHECK")
    print("=" * 60)

    # ---- 1. MEXC API (IP not blocked, credentials valid) ----
    print("\n[1] MEXC API (IP & credentials)...")
    if not api_key or not api_secret or api_key == "your_mexc_api_key_here":
        print("    SKIP: No API keys in config/trading.env")
        results["mexc_api"] = "skipped"
    else:
        try:
            import ccxt
            exchange = ccxt.mexc({
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "timeout": 15000,
            })
            balance = exchange.fetch_balance()
            usdt = balance.get("USDT", {}) or {}
            free = usdt.get("free", 0) or 0
            total = usdt.get("total", 0) or 0
            print(f"    OK   - API reachable, IP not blocked. USDT free: {free:.4f} total: {total:.4f}")
            results["mexc_api"] = "ok"
        except ccxt.AuthenticationError as e:
            print(f"    FAIL - Auth error (invalid key or IP not whitelisted): {e}")
            results["mexc_api"] = "auth_error"
            all_ok = False
        except ccxt.ExchangeError as e:
            err_str = str(e).lower()
            if "ip" in err_str and ("white" in err_str or "700006" in str(e)):
                print(f"    FAIL - MEXC IP not whitelisted: {e}")
                print(f"    FIX  - Add this IP to MEXC API whitelist: https://www.mexc.com/user/openapi")
                results["mexc_api"] = "ip_not_whitelisted"
            elif "403" in err_str or "forbidden" in err_str or "block" in err_str:
                print(f"    FAIL - API blocked/403 (IP may be blocked or not whitelisted): {e}")
                results["mexc_api"] = "blocked"
            else:
                print(f"    FAIL - Exchange error: {e}")
                results["mexc_api"] = "exchange_error"
            all_ok = False
        except Exception as e:
            print(f"    FAIL - {type(e).__name__}: {e}")
            results["mexc_api"] = "error"
            all_ok = False

    # ---- 2. Redis ----
    print("\n[2] Redis...")
    try:
        import redis
        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password or None,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        r.ping()
        print(f"    OK   - Connected to {redis_host}:{redis_port}")
        results["redis"] = "ok"
    except redis.ConnectionError as e:
        print(f"    FAIL - Cannot connect (is Redis/Docker running?): {e}")
        results["redis"] = "connection_error"
        all_ok = False
    except Exception as e:
        print(f"    FAIL - {type(e).__name__}: {e}")
        results["redis"] = "error"
        all_ok = False

    # ---- 3. API Gateway (Docker stack) ----
    print("\n[3] API Gateway (http://localhost:8080)...")
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8080/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            print(f"    OK   - Gateway healthy: {data.get('status', 'ok')}")
            results["api_gateway"] = "ok"
    except urllib.error.HTTPError as e:
        print(f"    FAIL - HTTP {e.code}: {e.reason}")
        results["api_gateway"] = "http_error"
        all_ok = False
    except OSError as e:
        print(f"    WARN - Gateway not reachable (is Docker stack up?): {e}")
        results["api_gateway"] = "not_running"
    except Exception as e:
        print(f"    FAIL - {type(e).__name__}: {e}")
        results["api_gateway"] = "error"
        all_ok = False

    # ---- 4. All services via /status ----
    if results["api_gateway"] == "ok":
        print("\n[4] Backend services (via gateway /status)...")
        try:
            req = urllib.request.Request("http://127.0.0.1:8080/status", method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                services = data.get("services", {})
                results["services"] = {}
                for name, info in services.items():
                    healthy = info.get("healthy", False)
                    results["services"][name] = "ok" if healthy else "fail"
                    status = "OK" if healthy else "FAIL"
                    err = info.get("error", "")
                    print(f"    {status}   - {name}" + (f" - {err}" if err else ""))
                    if not healthy:
                        all_ok = False
        except Exception as e:
            print(f"    FAIL - {type(e).__name__}: {e}")
            results["services"] = "error"
            all_ok = False
    else:
        print("\n[4] Backend services - skipped (gateway not running)")

    # ---- Summary ----
    print("\n" + "=" * 60)
    if all_ok:
        print("  RESULT: All checks passed. System is working.")
    else:
        print("  RESULT: Some checks failed. See above for details.")
        if results.get("mexc_api") in ("auth_error", "blocked", "ip_not_whitelisted"):
            print("  TIP: Add your current IP at MEXC -> API Management -> Edit key -> IP whitelist.")
        if results.get("redis") != "ok":
            print("  TIP: Start stack with: docker compose up -d")
    print("=" * 60)
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
