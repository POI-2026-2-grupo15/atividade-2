#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
USERS="${USERS:-10}"
SPAWN_RATE="${SPAWN_RATE:-10}"
DURATION="${DURATION:-60s}"
HOST="${HOST:-http://127.0.0.1:8000}"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_DIR/results/run-$(date -u +%Y%m%dT%H%M%S)-$$}"
export SIZE_KB="${SIZE_KB:-1024}"
export FSYNC="${FSYNC:-1}"
export WAIT_SECONDS="${WAIT_SECONDS:-0}"

mkdir -p -- "$(dirname -- "$OUTPUT_DIR")"
mkdir -- "$OUTPUT_DIR"
cat > "$OUTPUT_DIR/config.txt" <<CONF
timestamp_utc=$(date -u +%FT%TZ)
host=$HOST
users=$USERS
spawn_rate=$SPAWN_RATE
duration=$DURATION
size_kb=$SIZE_KB
fsync=$FSYNC
wait_seconds=$WAIT_SECONDS
CONF
python --version >> "$OUTPUT_DIR/config.txt"
python -m locust -f "$PROJECT_DIR/load_tests/locustfile.py" \
    --headless --host "$HOST" --users "$USERS" --spawn-rate "$SPAWN_RATE" \
    --run-time "$DURATION" --csv "$OUTPUT_DIR/locust" --csv-full-history \
    --only-summary 2>&1 | tee "$OUTPUT_DIR/locust.log"
