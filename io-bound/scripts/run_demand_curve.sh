#!/usr/bin/env bash
# Roda uma curva de demanda (vários números de usuários) contra a VM já
# configurada em um cenário. Execute no hospedeiro, uma vez por cenário.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SCENARIO="${SCENARIO:?Informe SCENARIO, ex.: SCENARIO=vcpu1-ram1g}"
USERS_LIST="${USERS_LIST:-1 2 4 8 16 32 64}"
PAUSE="${PAUSE:-10}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$PROJECT_DIR/results/$SCENARIO}"

for users in $USERS_LIST; do
    echo "== $SCENARIO: $users usuários =="
    USERS="$users" SPAWN_RATE="$users" OUTPUT_DIR="$OUTPUT_ROOT/u$users" \
        bash "$PROJECT_DIR/scripts/run_load_test.sh"
    sleep "$PAUSE"
done
