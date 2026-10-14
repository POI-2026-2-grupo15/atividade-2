#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export SCENARIO="${SCENARIO:?Informe SCENARIO, ex.: docker-cpu6-ram1g}"
export REPETITION="${REPETITION:-1}"
USERS_LIST="${USERS_LIST:-1 2 4 8}"
PAUSE_SECONDS="${PAUSE_SECONDS:-10}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$PROJECT_DIR/results/$SCENARIO/rep-$REPETITION}"
mkdir -p -- "$(dirname -- "$OUTPUT_ROOT")"
mkdir -- "$OUTPUT_ROOT"
failed=0
for users in $USERS_LIST; do
    if ! USERS="$users" OUTPUT_DIR="$OUTPUT_ROOT/u$users" \
        bash "$PROJECT_DIR/scripts/run_load_test.sh"; then
        failed=1
        echo "Falha no nível $users; consulte os logs antes de interpretar o ponto." >&2
    fi
    sleep "$PAUSE_SECONDS"
done
exit "$failed"
