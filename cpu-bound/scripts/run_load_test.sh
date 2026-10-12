#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
USERS="${USERS:-10}"
SPAWN_RATE="${SPAWN_RATE:-2}"
DURATION="${DURATION:-60s}"
HOST="${HOST:-http://127.0.0.1:8000}"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_DIR/results/run-$(date -u +%Y%m%dT%H%M%S)-$$}"
export DATA_SIZE_MB="${DATA_SIZE_MB:-10}"
export ITERATIONS="${ITERATIONS:-100}"
export WAIT_SECONDS="${WAIT_SECONDS:-0}"

mkdir -p -- "$(dirname -- "$OUTPUT_DIR")"
mkdir -- "$OUTPUT_DIR"
cat > "$OUTPUT_DIR/config.txt" <<EOF
timestamp_utc=$(date -u +%FT%TZ)
host=$HOST
users=$USERS
spawn_rate=$SPAWN_RATE
duration=$DURATION
data_size_mb=$DATA_SIZE_MB
iterations=$ITERATIONS
wait_seconds=$WAIT_SECONDS
EOF
python --version >> "$OUTPUT_DIR/config.txt"
python -m pip freeze > "$OUTPUT_DIR/dependencies.txt"
python -m locust -f "$PROJECT_DIR/load_tests/locustfile.py" \
    --headless --host "$HOST" --users "$USERS" --spawn-rate "$SPAWN_RATE" \
    --run-time "$DURATION" --csv "$OUTPUT_DIR/locust" --csv-full-history \
    --exit-code-on-error 1 --only-summary 2>&1 | tee "$OUTPUT_DIR/locust.log"
