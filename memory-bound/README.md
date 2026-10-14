# memory-bound

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

## Carga Locust no hospedeiro

No computador que gera a carga, instale as dependências adicionais:

```bash
source .venv/bin/activate
python -m pip install -r requirements-experiment.txt
```

O `load_tests/locustfile.py` envia os arquivos ao `/memory-test`. Cada usuário
aguarda sua resposta antes de repetir a operação, sem espera entre
requisições. Usuários simultâneos não equivalem a uma taxa fixa de chegada.

Antes da carga, conferimos hashes e tamanhos do manifesto. Não altere os CSVs
durante uma execução. Cada requisição abre streams independentes e os fecha
ao terminar. O multipart usa `requests-toolbelt` para enviar os dados em fluxo,
evitando montar o lote inteiro em RAM por usuário. Consulte a
[documentação do encoder](https://toolbelt.readthedocs.io/en/latest/uploading-data.html).
Isso não elimina o custo de leitura, rede e processamento do gerador.

### Um nível de demanda

Com a API já executando, este comando prepara e inicia uma coleta:

```bash
DATASET_DIR=datasets/grande USERS=4 SPAWN_RATE=2 DURATION=60s \
SCENARIO=vcpu2-ram1g REPETITION=1 SERVER_WORKERS=4 VM_VCPUS=2 VM_RAM_MIB=1024 \
HOST=http://127.0.0.1:8000 OUTPUT_DIR=results/vcpu2-ram1g/rep-1/u4 \
bash scripts/run_load_test.sh
```

Os valores são exemplos de configuração, não resultados medidos ou valores já
calibrados. O diretório de saída deve ser novo. São gerados `config.json`,
`dataset-manifest.json`, `dependencies.txt`, `locust.log` e CSVs de estatísticas,
histórico, falhas e exceções. Erros HTTP, timeout ou contagens inconsistentes
são falhas; o script retorna status não zero se o Locust registrar erros.

| Variável | Padrão | Significado |
|---|---|---|
| `DATASET_DIR` | `datasets/example` do projeto | conjunto escolhido |
| `USERS` | 1 | usuários virtuais |
| `SPAWN_RATE` | 1 | usuários iniciados por segundo |
| `DURATION` | `60s` | duração, incluindo rampa |
| `REQUEST_TIMEOUT` | 120 | timeout do cliente em segundos |
| `HOST` | `http://127.0.0.1:8000` | endereço acessível da API |
| `OUTPUT_DIR` | diretório novo com data/PID | resultados |
| `SCENARIO`, `REPETITION` | não informados | identificação da execução |
| `SERVER_WORKERS`, `VM_VCPUS`, `VM_RAM_MIB` | não informados | recursos declarados |

As variáveis de recursos registram valores declarados: não modificam a VM nem
o número de workers do servidor. Se omitidas, ficam explicitamente não informadas.
Use caminhos absolutos de dataset/saída se executar fora da pasta do projeto.
Mantenha o mesmo lote, timeout, workers e configuração de carga ao comparar RAM.
Timeout do cliente não garante cancelamento do trabalho já iniciado no servidor.

### Sequência de demandas de um cenário

```bash
DATASET_DIR=datasets/grande SCENARIO=vcpu2-ram1g REPETITION=1 \
SERVER_WORKERS=4 VM_VCPUS=2 VM_RAM_MIB=1024 \
USERS_LIST='1 2 4 8 16' DURATION=60s \
bash scripts/run_demand_curve.sh
```

Cria `results/<cenário>/rep-<repetição>/u<N>`. O diretório da repetição deve ser
novo. `USERS_LIST` é a lista de demandas; as demais opções do comando de um
ponto continuam valendo. Há pausa padrão de 10 segundos entre pontos, ajustável
por `PAUSE_SECONDS`; ela ocorre no gerador, fora da aplicação. Pontos que falham
ficam registrados e a curva continua; o status final indica se houve alguma falha.

## Monitoramento na VM

O monitor precisa de `psutil`; instale `psutil==7.0.0` no ambiente da aplicação.
Inicie o servidor e acompanhe o PID mestre e seus descendentes:

```bash
mkdir -p results
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 \
  --no-access-log > results/api.log 2>&1 &
APP_PID=$!
python scripts/monitor.py --pid "$APP_PID" --interval 1 \
  --output results/monitor-vcpu2-ram1g-rep1.csv
```

Inicie antes da carga e pare com Ctrl+C depois dela. `--duration` limita a coleta
em segundos; sem `--pid`, coleta apenas o sistema. Saídas existentes não são
sobrescritas. O monitor também grava `<arquivo>.metadata.json`, com recursos
detectados, plataforma, PID e comando do servidor, quando acessível.

O CSV inclui UTC, intervalo, CPU total/por núcleo, RAM usada/disponível,
contagem de processos, soma de RSS, CPU da árvore e swap ocupado/total. Em
Linux inclui taxas de entrada/saída de swap; em outras plataformas essas taxas
ficam vazias. Contadores de swap são do sistema inteiro, não apenas da API.

Os resultados são locais e ignorados durante as execuções; prepare também os
resultados relevantes para a entrega exigida pela disciplina. Os datasets não
são ignorados. Esta parte não executa deploy, coleta comparativa ou publicação.
