#!/usr/bin/env bash
# Piloto local: simula os cenários de provisionamento com limites de CPU/RAM
# do Docker. API + monitor em um container; Locust em outro (fora da API).
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${IMAGE:-io-bound:experiment}"
RESULTS="${RESULTS:-$PROJECT_DIR/results}"
SCENARIOS="${SCENARIOS:-vcpu1-ram1g:1:1g vcpu2-ram1g:2:1g vcpu4-ram1g:4:1g vcpu2-ram2g:2:2g}"
export USERS_LIST="${USERS_LIST:-1 2 4 8 16 32 64}" DURATION="${DURATION:-30s}" PAUSE="${PAUSE:-5}"
export SIZE_KB="${SIZE_KB:-1024}" FSYNC="${FSYNC:-1}"

docker build -q -t "$IMAGE" "$PROJECT_DIR"
docker network create io-bound-net >/dev/null 2>&1 || true
mkdir -p "$RESULTS"
for scenario in $SCENARIOS; do
    IFS=: read -r name cpus memory <<< "$scenario"
    mkdir "$RESULTS/$name"
    docker rm -f io-api >/dev/null 2>&1 || true
    # exec: o monitor vira PID 1 e grava a última amostra ao receber o SIGTERM do docker stop.
    docker run -d --name io-api --network io-bound-net --cpus "$cpus" --memory "$memory" \
        -v "$RESULTS:/app/results" "$IMAGE" sh -c "
        python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log &
        exec python scripts/monitor.py --pid \$! --interval 1 --output results/$name/monitor.csv" >/dev/null
    sleep 3
    docker run --rm --network io-bound-net -v "$RESULTS:/app/results" \
        -e SCENARIO="$name" -e HOST=http://io-api:8000 -e OUTPUT_ROOT="results/$name" \
        -e USERS_LIST -e DURATION -e PAUSE -e SIZE_KB -e FSYNC "$IMAGE" bash scripts/run_demand_curve.sh
    docker stop io-api >/dev/null
    docker rm io-api >/dev/null
    echo "$name: cpus=$cpus memory=$memory" >> "$RESULTS/scenarios.txt"
done
