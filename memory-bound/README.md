# memory-bound

Para testar em containers, consulte o [protocolo Docker](docs/experiments.md).
O [piloto inicial](docs/docker-pilot.md) permanece como registro histórico.
Para escolher CPU e workers antes de variar RAM, consulte a
[calibração de CPU](docs/cpu-calibration.md).

Para preparar o ambiente exigido pela disciplina, consulte o
[roteiro de deploy no VirtualBox](docs/vm-setup.md).

Backend em Python 3.10 e FastAPI. Recebe vários CSVs e constrói uma lista de cadastro único em memória, mantendo o registro completo da última ocorrência de cada ID, ou seja, IDs duplicados são descartados e para identificar isso o sistema deve manter dados na memória.

## Execução local

Execute a partir de `memory-bound/`:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Dependências diretas seguem as versões utilizadas no projeto CPU-bound.
A documentação interativa da API fica em `http://127.0.0.1:8000/docs`.

## Contrato

- `POST /memory-test`: recebe arquivos multipart no campo repetido `files`.
  Processa os arquivos na ordem enviada e as linhas na ordem em que aparecem.

Cada arquivo deve ser CSV UTF-8, separado por vírgulas, com
cabeçalho exatamente nesta ordem:

```csv
id,name,email,description
001,Ana,ana@example.com,Primeiro cadastro
002,Bruno,bruno@example.com,Outro cadastro
```

Duplicidade significa igualdade do ID, mesmo que os outros campos sejam
diferentes. A última ocorrência substitui o registro anterior por inteiro, inclusive quando está no mesmo arquivo.

### Exemplo

Crie `a.csv` com o conteúdo acima e `b.csv` com:

```csv
id,name,email,description
001,Ana,ana@example.com,Cadastro atualizado
003,Carla,carla@example.com,Novo cadastro
```

Envie os arquivos na ordem desejada:

```bash
curl -sS -F 'files=@a.csv' -F 'files=@b.csv' http://127.0.0.1:8000/memory-test
```

Resposta esperada:

```json
{
  "files_processed": 2,
  "records_received": 4,
  "unique_records": 3,
  "replaced_occurrences": 1,
  "processing_time_ms": 0.8
}
```

`replaced_occurrences` conta todas as ocorrências posteriores à primeira de um
ID; é igual a `records_received - unique_records`.

## Datasets predefinidos

| Conjunto | Arquivos | MiB por arquivo (aprox.) | Registros recebidos | IDs únicos | Substituições |
|---|---:|---:|---:|---:|---:|
| `pequeno` | 4 | 0,72 | 9.600 | 8.800 | 800 |
| `medio` | 4 | 6,53 | 48.000 | 44.000 | 4.000 |
| `grande` | 4 | 24,79 | 96.000 | 88.000 | 8.000 |

O conjunto grande tem 99,15 MiB no total: cada CSV tem cerca de 25 MiB
Duplicatas têm o mesmo ID com uma versão
mais recente indicada na descrição. 

O `manifest.json` de cada conjunto define ordem dos arquivos, tamanhos, SHA-256,
parâmetros de geração e contagens esperadas. Não reordene os arquivos: a última
ocorrência vence. O Locust verifica as contagens; a resposta atual da API não
permite conferir o conteúdo completo dos registros finais.

### Reproduzir os arquivos

O gerador usa somente a biblioteca padrão, escreve linha por linha e não
sobrescreve diretórios existentes. Gere em outro diretório para preservar os
datasets entregues. Por exemplo, o seguinte reproduz o conjunto grande:

```bash
python scripts/generate_dataset.py --output /tmp/memory-bound-grande
```

Parâmetros padrão: `--unique-records 88000 --duplicates 8000
--description-bytes 1024 --files 4`. A ordem e os bytes gerados são determinísticos.
O limite de 25 MiB por CSV aplica-se ao gerador de artefatos.
Para conjuntos personalizados que excedam esse tamanho, aumente `--files`.

Os demais conjuntos foram gerados com:

```bash
python scripts/generate_dataset.py --output /tmp/memory-bound-example \
  --unique-records 6 --duplicates 2 --description-bytes 64 --files 2
python scripts/generate_dataset.py --output /tmp/memory-bound-pequeno \
  --unique-records 8800 --duplicates 800 --description-bytes 256 --files 4
python scripts/generate_dataset.py --output /tmp/memory-bound-medio \
  --unique-records 44000 --duplicates 4000 --description-bytes 512 --files 4
```

## Experimentos Docker

O [protocolo](docs/experiments.md) define quatro limites de RAM, quatro demandas
e três repetições: **48 execuções**, com seis CPUs e seis workers constantes.
Configuração única em [experiments/protocol.json](experiments/protocol.json).

A partir da raiz do repositório:

```bash
memory-bound/.venv/bin/python -m pip install -r memory-bound/requirements.txt \
  -r memory-bound/requirements-analysis.txt
memory-bound/.venv/bin/python memory-bound/scripts/docker_experiment.py --plan
docker build -t memory-bound:experiment memory-bound
```

Para executar a matriz, quando autorizada:

```bash
memory-bound/.venv/bin/python memory-bound/scripts/docker_experiment.py
```

Aplicação e monitor ficam no container; Locust e seu monitor ficam no Mac.
O executor cuida dos limites reais, ordem das coletas, aquecimento, janela,
repetições, falhas e limpeza. O antigo `docker_pilot.py` foi substituído por
`docker_experiment.py`. Pilotos anteriores permanecem em `results/` e nos
[registros históricos](docs/docker-pilot.md).

A comparação usa `load/measurement.json`, não os CSVs acumulados do Locust.
O protocolo explica sucessos, falhas, requisições pendentes e cobertura dos
monitores. Os resultados são ignorados pelo Git e precisam ser incluídos
explicitamente na entrega. Não há commit/push automático.

`run_load_test.sh` continua como adaptador do Locust e `run_demand_curve.sh`
como utilitário de carga contra uma API já iniciada; não provisionam Docker.
O [roteiro VirtualBox](docs/vm-setup.md) é referência separada para o LCC.

## Validação local

A partir de `memory-bound/`:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-analysis.txt
python -m unittest discover -s tests -v
```

Os testes cobrem consolidação de CSVs, API HTTP, Locust/monitor reais e validade
da matriz/janela experimental. A integração usa um lote mínimo e encerra os
processos ao final. Os artefatos ficam em `results/local-validation-*`.

Para verificar o fluxo Docker com coletas curtas, use o comando de validação
no [protocolo](docs/experiments.md). Essas verificações não são resultados da
matriz definitiva.
