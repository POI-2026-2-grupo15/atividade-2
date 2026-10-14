#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export DATASET_DIR="${DATASET_DIR:-$PROJECT_DIR/datasets/example}"
export REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-120}"
USERS="${USERS:-1}"
SPAWN_RATE="${SPAWN_RATE:-1}"
DURATION="${DURATION:-60s}"
HOST="${HOST:-http://127.0.0.1:8000}"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_DIR/results/run-$(date -u +%Y%m%dT%H%M%S)-$$}"
export OUTPUT_DIR


python "$PROJECT_DIR/scripts/prepare_run.py" \
    --dataset "$DATASET_DIR" --output "$OUTPUT_DIR" \
    --host "$HOST" --users "$USERS" --spawn-rate "$SPAWN_RATE" --duration "$DURATION"
python -m pip freeze > "$OUTPUT_DIR/dependencies.txt"
python -m locust -f "$PROJECT_DIR/load_tests/locustfile.py" \
    --headless --host "$HOST" --users "$USERS" --spawn-rate "$SPAWN_RATE" \
    --run-time "$DURATION" --csv "$OUTPUT_DIR/locust" --csv-full-history \
    --exit-code-on-error 1 --only-summary 2>&1 | tee "$OUTPUT_DIR/locust.log"
