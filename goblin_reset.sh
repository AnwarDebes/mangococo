#!/bin/bash
# ============================================================
# Goblin Reset — Stop all services, wipe data, prepare fresh start
#
# Usage:
#   bash goblin_reset.sh          # interactive confirmation
#   bash goblin_reset.sh --yes    # skip confirmation
# ============================================================
set -euo pipefail

ROOT="/home/coder/Goblin"
LOGS="$ROOT/logs"
ENV_FILE="$ROOT/config/trading.env"

# Load config
set -a
source "$ENV_FILE"
set +a
export REDIS_HOST="${REDIS_HOST:-localhost}"
export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"

echo ""
echo "  ========================================"
echo "  GOBLIN RESET"
echo "  ========================================"
echo "  This will:"
echo "    1. Stop all running services"
echo "    2. Flush Redis (all trading state)"
echo "    3. Truncate PostgreSQL tables"
echo "    4. Clear logs and caches"
echo "    5. Re-seed with \$${STARTING_CAPITAL} capital"
echo "  ========================================"
echo ""

if [[ "${1:-}" != "--yes" && "${1:-}" != "-y" ]]; then
    read -p "  Type 'yes' to wipe everything and start fresh: " confirm
    if [[ "$confirm" != "yes" ]]; then
        echo "  Aborted."
        exit 0
    fi
fi

# -----------------------------------------------------------
# 1. STOP ALL SERVICES
# -----------------------------------------------------------
echo ""
echo "  [1/5] Stopping services..."

# Stop dashboard if running
DASHBOARD_PID=$(cat "$LOGS/dashboard.pid" 2>/dev/null || true)
if [ -n "$DASHBOARD_PID" ] && kill -0 "$DASHBOARD_PID" 2>/dev/null; then
    kill "$DASHBOARD_PID" 2>/dev/null || true
    echo "    Stopped dashboard (PID $DASHBOARD_PID)"
fi

# Stop all services via PID files
for pidfile in "$LOGS"/*.pid; do
    [ -f "$pidfile" ] || continue
    name=$(basename "$pidfile" .pid)
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        echo "    Stopped $name (PID $pid)"
    fi
    rm -f "$pidfile"
done

# Kill any stragglers (pkill is more reliable than lsof)
pkill -f "uvicorn main:app" 2>/dev/null && echo "    Killed remaining uvicorn processes." || true
pkill -f "next start" 2>/dev/null && echo "    Killed remaining next processes." || true
pkill -f "next-server" 2>/dev/null || true

sleep 2
echo "    All services stopped."

# -----------------------------------------------------------
# 2. FLUSH REDIS
# -----------------------------------------------------------
echo ""
echo "  [2/5] Flushing Redis..."

if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" --no-auth-warning PING >/dev/null 2>&1; then
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" --no-auth-warning FLUSHALL >/dev/null 2>&1
    echo "    Flushed all Redis data."

    # Re-seed portfolio state
    PORTFOLIO_JSON="{\"total_capital\":${STARTING_CAPITAL},\"available_capital\":${STARTING_CAPITAL},\"positions_value\":0,\"open_positions\":0,\"starting_capital\":${STARTING_CAPITAL},\"daily_pnl\":0}"
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" --no-auth-warning \
        SET portfolio_state "$PORTFOLIO_JSON" >/dev/null 2>&1
    echo "    Seeded portfolio_state with \$${STARTING_CAPITAL}."
else
    echo "    [WARN] Redis unreachable — skipping. Make sure Redis is running."
fi

# -----------------------------------------------------------
# 3. TRUNCATE POSTGRESQL
# -----------------------------------------------------------
echo ""
echo "  [3/5] Cleaning PostgreSQL..."

export PGPASSWORD="$POSTGRES_PASSWORD"
if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1" >/dev/null 2>&1; then
    psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
        DO \$\$
        DECLARE t TEXT;
        BEGIN
            FOR t IN SELECT tablename FROM pg_tables
                     WHERE schemaname = 'public'
                       AND tablename IN ('trade_history','portfolio_snapshots','signals','orders','ml_predictions')
            LOOP
                EXECUTE 'TRUNCATE TABLE ' || quote_ident(t) || ' CASCADE';
            END LOOP;
        END\$\$;

        INSERT INTO portfolio_snapshots (time, total_value, cash_balance, positions_value, daily_pnl)
        VALUES (NOW(), $STARTING_CAPITAL, $STARTING_CAPITAL, 0, 0);
SQL
    echo "    Truncated trade_history, portfolio_snapshots, signals, orders, ml_predictions."
    echo "    Seeded initial portfolio snapshot."
else
    echo "    [WARN] PostgreSQL unreachable — skipping."
fi
unset PGPASSWORD

# -----------------------------------------------------------
# 4. CLEAR LOGS AND CACHES
# -----------------------------------------------------------
echo ""
echo "  [4/5] Clearing logs and caches..."

# Truncate log files (keep the files, clear contents)
for logfile in "$LOGS"/*.log; do
    [ -f "$logfile" ] && > "$logfile"
done
echo "    Cleared all log files."

# Remove PID files
rm -f "$LOGS"/*.pid
echo "    Removed PID files."

# Remove Python caches (skip permission errors)
CLEANED=0
while IFS= read -r -d '' dir; do
    rm -rf "$dir" 2>/dev/null || true
    CLEANED=$((CLEANED + 1))
done < <(find "$ROOT/services" "$ROOT/scripts" -type d -name "__pycache__" -print0 2>/dev/null)
echo "    Removed $CLEANED __pycache__ directories."

# Remove tmp model files (keep trained models)
find "$ROOT/shared/models" -name "*.tmp" -delete 2>/dev/null || true

# -----------------------------------------------------------
# 5. VERIFY CLEAN STATE
# -----------------------------------------------------------
echo ""
echo "  [5/5] Verifying clean state..."

REDIS_KEYS=0
if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" --no-auth-warning PING >/dev/null 2>&1; then
    REDIS_KEYS=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" --no-auth-warning DBSIZE 2>/dev/null | grep -oP '\d+' || echo "0")
fi
echo "    Redis keys: $REDIS_KEYS (should be 1 — portfolio_state)"

RUNNING=0
for p in 8001 8002 8003 8004 8005 8006 8007 8008 8009 8010 8011 8080; do
    curl -sf -o /dev/null --max-time 1 "http://localhost:$p/health" 2>/dev/null && RUNNING=$((RUNNING + 1))
done
echo "    Services still responding: $RUNNING (should be 0)"

echo ""
echo "  ========================================"
echo "  RESET COMPLETE"
echo "  ========================================"
echo "  Starting capital: \$${STARTING_CAPITAL}"
echo ""
echo "  To start the system:"
echo "    bash $ROOT/goblin_start.sh"
echo "  ========================================"
echo ""
