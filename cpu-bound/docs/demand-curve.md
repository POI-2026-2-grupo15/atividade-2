# Curva de demanda: usuários e ponto de saturação

Veja os [resultados medidos e gráficos](relatorio-final.md).

Objetivo: medir como CPU, vazão e latência mudam conforme a demanda aumenta,
e identificar em quais níveis cada configuração começa a ficar próxima da
saturação. Não se escolhe um resultado desejado nem se alteram valores medidos.

Matriz: quotas de **2, 4, 6 e 8 CPUs**, cada uma com **1, 2, 4, 8, 16 e 32
usuários**. RAM de **1 GiB**, **oito workers**, payload de **10 MiB × 100** e
espera zero em todos os pontos. São 24 medições sequenciais de 30 segundos,
com aquecimento inicial e espera de ociosidade entre níveis de usuários.

Critério operacional: **média de CPU ≥ 95% da quota** significa próximo da
saturação. O primeiro nível observado que satisfaz o critério é reportado como
limiar entre os pontos testados. Ele não é o número mínimo exato de usuários;
se níveis posteriores caírem abaixo de 95%, essa não monotonicidade é registrada.

O Locust usa um modelo fechado: usuários esperam a resposta antes de enviar
a próxima requisição. Portanto, usuários não equivalem a uma taxa fixa de
chegadas. Conexões persistentes e distribuição entre workers também podem
afetar quanto paralelismo um nível de usuários consegue explorar.

CPU é amostrada a cada segundo e resumida entre 5 e 28 segundos. Métricas HTTP
são acumuladas no Locust, incluindo início/rampa. Há uma execução por ponto:
não se calculam intervalos de confiança nem se prometem limiares reproduzíveis.
RAM/swap, falhas, CPU do gerador, alimentação e frequência do hospedeiro são
registrados para interpretar possíveis interferências.

O container mantém o pool de CPUs lógicas 2–15 do hospedeiro registrado;
o gerador fica na CPU 0, em outro núcleo físico. Quota 8 pode envolver SMT
em sete núcleos físicos. São condições Docker, não resultados de VirtualBox.

## Executar

```bash
source .venv/bin/activate
docker build -t cpu-bound:experiment .
OUTPUT_DIR=results/demand-curve bash scripts/run_demand_curve.sh
python -m pip install -r requirements-analysis.txt
python scripts/plot_demand_curve.py --input results/demand-curve
```

O diretório de coleta deve ser novo. O padrão dura cerca de 12 minutos de carga,
mais aquecimento, inicialização e esvaziamento de requisições remanescentes.
Adapte `SERVER_CPUS` e `GENERATOR_CPU` à topologia local. Use `DURATION` para
alongar todos os pontos igualmente em um estudo definitivo.

Por padrão, `REQUIRE_AC=1` impede iniciar/continuar quando o sensor informa
uso de bateria. Não altera o perfil de energia do sistema. Em máquinas sem
sensor de bateria, a condição deve ser controlada externamente. Cada amostra
registra a leitura de alimentação; `REQUIRE_AC=0` desativa apenas a interrupção.

O script de gráficos usa pandas e Matplotlib para produzir:

- CPU × usuários, com linha de referência em 95%.
- Vazão × usuários, evidenciando eventuais platôs.
- Latência média e p95 × usuários, em figuras separadas.
- Painel com as quatro curvas.
- Mapa de calor CPU × usuários, com destaque nos pontos ≥ 95%.

Figuras em PNG, SVG e PDF; `comparison.csv`, matriz de utilização e
`limiares_observados.json` preservam valores e interpretação dos pontos.
O eixo de usuários das curvas usa escala log₂ com todos os níveis rotulados;
o mapa de calor trata os níveis como categorias.
