#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_DIR/results/cpu-scaling-$(date -u +%Y%m%dT%H%M%S)-$$}"
SERVER_CPUS="${SERVER_CPUS:-2,3,4,5,6,7,8,9,10,11,12,13,14,15}"
GENERATOR_CPU="${GENERATOR_CPU:-0}"
DURATION="${DURATION:-60}"
USERS="${USERS:-32}"
IMAGE="${IMAGE:-cpu-bound:experiment}"
mkdir -p -- "$(dirname -- "$OUTPUT_DIR")"
mkdir -- "$OUTPUT_DIR"

for quota in 2 4 6 8; do
    python "$PROJECT_DIR/scripts/docker_experiment.py" \
        --image "$IMAGE" --cpu-limit "$quota" --server-cpus "$SERVER_CPUS" \
        --generator-cpu "$GENERATOR_CPU" --workers 8 --users "$USERS" \
        --duration "$DURATION" --output "$OUTPUT_DIR/cpu-$quota"
done
