#!/usr/bin/env bash
# Sessão completa de experimento (cenários no Docker + gráficos) com parâmetros personalizados.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${IMAGE:-io-bound:experiment}"
SCENARIOS="vcpu1-ram1g:1:1g vcpu2-ram1g:2:1g"
USERS_LIST="1 4 16"
DURATION="10s"
PAUSE="2"
SIZE_KB="1024"
FSYNC="1"
NAME="sessao-$(date +%Y%m%d-%H%M%S)"

usage() {
    cat <<USAGE
Uso: bash scripts/experiment.sh [opções]

  -c, --cenarios "nome:cpus:ram ..."   padrão: "$SCENARIOS"
  -u, --usuarios "1 4 16 ..."          níveis de demanda; padrão: "$USERS_LIST"
  -d, --duracao 10s                    tempo de cada nível; padrão: $DURATION
  -p, --pausa 2                        segundos entre níveis; padrão: $PAUSE
  -k, --tamanho 1024                   KiB por requisição (1–16384); padrão: $SIZE_KB
  -f, --sem-fsync                      desliga o fsync (passa a medir cache, não disco)
  -n, --nome sessao                    pasta em results/; padrão: sessao-<data-hora>
  -h, --help                           mostra esta ajuda

Exemplo:
  bash scripts/experiment.sh -c "vcpu1:1:1g vcpu4:4:1g" -u "1 8 32" -d 20s -n aula
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--cenarios) SCENARIOS="$2"; shift 2 ;;
        -u|--usuarios) USERS_LIST="$2"; shift 2 ;;
        -d|--duracao) DURATION="$2"; shift 2 ;;
        -p|--pausa) PAUSE="$2"; shift 2 ;;
        -k|--tamanho) SIZE_KB="$2"; shift 2 ;;
        -f|--sem-fsync) FSYNC="0"; shift ;;
        -n|--nome) NAME="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Opção desconhecida: $1" >&2; usage >&2; exit 1 ;;
    esac
done

for scenario in $SCENARIOS; do
    [[ "$scenario" =~ ^[A-Za-z0-9_-]+:[0-9.]+:[0-9]+[kmg]$ ]] || {
        echo "Cenário inválido: '$scenario' (formato nome:cpus:ram, ex.: vcpu2-ram1g:2:1g)" >&2; exit 1; }
done
OUT="$PROJECT_DIR/results/$NAME"
if [[ -e "$OUT" ]]; then
    echo "results/$NAME já existe; escolha outro --nome" >&2
    exit 1
fi
mkdir -p "$OUT"
cat > "$OUT/sessao.txt" <<CONF
inicio_utc=$(date -u +%FT%TZ)
cenarios=$SCENARIOS
usuarios=$USERS_LIST
duracao=$DURATION
pausa=$PAUSE
size_kb=$SIZE_KB
fsync=$FSYNC
CONF

echo "Sessão results/$NAME: cenários [$SCENARIOS], usuários [$USERS_LIST], $DURATION por nível"
SCENARIOS="$SCENARIOS" USERS_LIST="$USERS_LIST" DURATION="$DURATION" PAUSE="$PAUSE" \
    SIZE_KB="$SIZE_KB" FSYNC="$FSYNC" RESULTS="$OUT" IMAGE="$IMAGE" \
    bash "$PROJECT_DIR/scripts/run_docker_scenarios.sh" > "$OUT/execucao.log" 2>&1 \
    || { echo "Falhou; veja results/$NAME/execucao.log" >&2; exit 1; }

docker run --rm -v "$OUT:/app/sessao" "$IMAGE" \
    python scripts/plot_results.py --results sessao --output sessao/plots
echo
echo "Gráficos e tabela em results/$NAME/plots"
if [[ "$(uname)" == "Darwin" ]]; then
    open "$OUT/plots"
fi
