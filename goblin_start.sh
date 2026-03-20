#!/bin/bash
# ============================================================
# Goblin Start — Launch all services in correct dependency order
#
# Usage:
#   bash goblin_start.sh              # start all services
#   bash goblin_start.sh --no-dash    # skip dashboard
# ============================================================
set -euo pipefail

ROOT="/home/coder/Goblin"
LOGS="$ROOT/logs"
ENV_FILE="$ROOT/config/trading.env"
SKIP_DASHBOARD=false

if [[ "${1:-}" == "--no-dash" ]]; then
    SKIP_DASHBOARD=true
fi

# Load config
set -a
source "$ENV_FILE"
set +a
export REDIS_HOST="${REDIS_HOST:-localhost}"
export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
export FEATURE_STORE_URL=http://localhost:8007
export MARKET_DATA_URL=http://localhost:8001
export PREDICTION_URL=http://localhost:8002
export EXECUTOR_URL=http://localhost:8005
export POSITION_URL=http://localhost:8006
export SIGNAL_URL=http://localhost:8003
export RISK_URL=http://localhost:8004
export API_GATEWAY_URL=http://localhost:8080

mkdir -p "$LOGS"

echo ""
echo "  ========================================"
echo "  GOBLIN START"
echo "  ========================================"
echo "  Mode:    $TRADING_MODE"
echo "  Capital: \$${STARTING_CAPITAL}"
echo "  ========================================"
echo ""

# -----------------------------------------------------------
# Pre-flight checks
# -----------------------------------------------------------
echo "  [PRE-FLIGHT] Checking infrastructure..."

if ! redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" --no-auth-warning PING >/dev/null 2>&1; then
    echo "    [FAIL] Redis not running on $REDIS_HOST:$REDIS_PORT"
    echo "    Fix: sudo service redis-server start"
    exit 1
fi
echo "    Redis ............ OK"

export PGPASSWORD="$POSTGRES_PASSWORD"
if ! psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1" >/dev/null 2>&1; then
    echo "    [FAIL] PostgreSQL not running on $POSTGRES_HOST:$POSTGRES_PORT"
    echo "    Fix: sudo service postgresql start"
    exit 1
fi
unset PGPASSWORD
echo "    PostgreSQL ....... OK"

# Check if services are already running
if curl -sf -o /dev/null --max-time 1 http://localhost:8080/health 2>/dev/null; then
    echo ""
    echo "    [WARN] Services already running on port 8080."
    echo "    Run: bash $ROOT/goblin_reset.sh   (to stop + wipe)"
    echo "    Or:  bash $ROOT/stop_services.sh  (to stop only)"
    exit 1
fi

echo ""

# -----------------------------------------------------------
# Service launcher with health check
# -----------------------------------------------------------
start_service() {
    local name=$1
    local dir=$2
    local port=$3
    local wait=${4:-2}

    printf "  Starting %-22s port %s ..." "$name" "$port"
    cd "$dir"
    uvicorn main:app --host 0.0.0.0 --port "$port" > "$LOGS/$name.log" 2>&1 &
    echo $! > "$LOGS/$name.pid"
    cd - > /dev/null

    # Wait for health endpoint
    local attempts=0
    while [ $attempts -lt $((wait * 5)) ]; do
        if curl -s -o /dev/null --max-time 1 "http://localhost:$port/health" 2>/dev/null; then
            echo " UP"
            return 0
        fi
        sleep 0.2
        attempts=$((attempts + 1))
    done

    # Fallback: check if process is alive
    local pid=$(cat "$LOGS/$name.pid" 2>/dev/null)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo " started (health check pending)"
    else
        echo " FAILED"
        echo "    Check: tail -20 $LOGS/$name.log"
    fi
}

# -----------------------------------------------------------
# Start services in dependency order
# -----------------------------------------------------------
echo "  [PHASE 1] Data layer"
start_service "market-data"         "$ROOT/services/market-data"         8001 4
start_service "feature-store"       "$ROOT/services/feature-store"       8007 3

echo ""
echo "  [PHASE 2] Risk & execution"
start_service "risk"                "$ROOT/services/risk"                8004 2
start_service "portfolio-optimizer" "$ROOT/services/portfolio-optimizer"  8010 2
start_service "executor"            "$ROOT/services/executor"            8005 2
start_service "position"            "$ROOT/services/position"            8006 2

echo ""
echo "  [PHASE 3] Intelligence"
start_service "prediction"          "$ROOT/services/prediction"          8002 5
start_service "signal"              "$ROOT/services/signal"              8003 3
start_service "sentiment-analysis"  "$ROOT/services/sentiment-analysis"  8008 3
start_service "trend-analysis"      "$ROOT/services/trend-analysis"      8009 3

echo ""
echo "  [PHASE 4] Analytics & API"
start_service "backtesting"         "$ROOT/services/backtesting"         8011 2
start_service "api-gateway"         "$ROOT/services/api-gateway"         8080 3

# -----------------------------------------------------------
# Dashboard (Next.js)
# -----------------------------------------------------------
if [ "$SKIP_DASHBOARD" = false ]; then
    echo ""
    echo "  [PHASE 5] Dashboard"
    printf "  Starting %-22s port %s ..." "dashboard" "3000"
    # Ensure node is in PATH (code-server bundles it)
    if ! command -v node &>/dev/null; then
        NODE_BIN=$(find /tmp/code-server -name "node" -type f 2>/dev/null | head -1)
        if [ -n "$NODE_BIN" ]; then
            mkdir -p /home/coder/.local/bin
            ln -sf "$NODE_BIN" /home/coder/.local/bin/node
            export PATH="/home/coder/.local/bin:$PATH"
        fi
    fi
    cd "$ROOT/dashboard"
    ./node_modules/.bin/next start -p 3000 > "$LOGS/dashboard.log" 2>&1 &
    echo $! > "$LOGS/dashboard.pid"
    cd - > /dev/null

    local_attempts=0
    while [ $local_attempts -lt 15 ]; do
        if curl -s -o /dev/null --max-time 1 "http://localhost:3000" 2>/dev/null; then
            echo " UP"
            break
        fi
        sleep 0.5
        local_attempts=$((local_attempts + 1))
    done
    if [ $local_attempts -ge 15 ]; then
        echo " started (loading...)"
    fi
fi

# -----------------------------------------------------------
# Final health check
# -----------------------------------------------------------
echo ""
echo "  ========================================"
echo "  HEALTH CHECK"
echo "  ========================================"

SERVICES=(
    "market-data:8001"
    "prediction:8002"
    "signal:8003"
    "risk:8004"
    "executor:8005"
    "position:8006"
    "feature-store:8007"
    "sentiment:8008"
    "trend:8009"
    "optimizer:8010"
    "backtesting:8011"
    "api-gateway:8080"
)

ALL_OK=true
check_health() {
    local url=$1
    curl -sf -o /dev/null --max-time 3 "$url" 2>/dev/null && echo "OK" || echo "DOWN"
}

for svc in "${SERVICES[@]}"; do
    name="${svc%%:*}"
    port="${svc##*:}"
    result=$(check_health "http://localhost:$port/health")
    if [ "$result" = "OK" ]; then
        printf "    %-22s %s\n" "$name" "OK"
    else
        printf "    %-22s %s\n" "$name" "DOWN"
        ALL_OK=false
    fi
done

if [ "$SKIP_DASHBOARD" = false ]; then
    result=$(check_health "http://localhost:3000")
    if [ "$result" = "OK" ]; then
        printf "    %-22s %s\n" "dashboard" "OK"
    else
        printf "    %-22s %s\n" "dashboard" "DOWN (may still be loading)"
    fi
fi

echo ""
echo "  ========================================"
if $ALL_OK; then
    echo "  ALL SYSTEMS GO"
else
    echo "  SOME SERVICES FAILED — check logs in $LOGS/"
fi
echo "  ========================================"
echo ""
echo "  Dashboard:  http://localhost:3000"
echo "  API:        http://localhost:8080"
echo "  Logs:       $LOGS/"
echo ""
echo "  To stop:    bash $ROOT/stop_services.sh"
echo "  To reset:   bash $ROOT/goblin_reset.sh"
echo "  ========================================"
echo ""
