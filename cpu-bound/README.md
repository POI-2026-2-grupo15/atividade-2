# cpu-bound

API acadêmica para cálculo e verificação de SHA-256 e experimentos de
desempenho e provisionamento no VirtualBox. Python 3.10+, FastAPI e Uvicorn;
sem banco ou serviços externos. O projeto está na pasta `cpu-bound/` deste
repositório. Execute os comandos abaixo a partir dela.

## Arquitetura e perfil computacional

```text
Hospedeiro: Locust → rede/VirtualBox → VM: Uvicorn (N workers)
                                            ├─ FastAPI → hashing → hashlib
                                            └─ monitor.py → CSV local
```

- `app/main.py`: contratos HTTP e comparação segura.
- `app/schemas.py`: validação e limites de recursos.
- `app/hashing.py`: cálculo em chunks e benchmark determinístico.
- `app/limits.py`: limite do corpo recebido e admissão por worker.
- `load_tests/locustfile.py`: carga constante por requisição.
- `scripts/`: execução headless e monitoramento.
- `tests/`: testes pequenos; `results/`: dados brutos e figuras dos experimentos.

O benchmark prepara uma sequência de bytes `0..255` repetida até preencher o
buffer. Cada iteração calcula SHA-256 do **mesmo buffer**. Um acumulador SHA-256
recebe os 32 bytes de cada digest, e seu digest final é retornado. Assim, todas
as iterações executam hashing real, sem cache, espera artificial ou reconstrução
do buffer. O resultado depende do tamanho e do número de iterações.

O cálculo não acessa disco ou rede e usa memória limitada. A resposta tem tamanho
pequeno. O perfil pretendido é CPU-bound, mas caches, largura de banda da memória,
instruções SHA do processador e bibliotecas OpenSSL também afetam o resultado.
Confirme o perfil pelas medições; não presuma saturação apenas pelo nome.
Hashing repetido é uma **carga sintética**, não uma exigência normal de integridade.

## Instalação e execução

No Ubuntu Server 22.04 (na VM) ou Linux hospedeiro:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
cd /caminho/para/cpu-bound
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
python -m pytest -q
```

As dependências diretas estão fixadas e são compatíveis com Python 3.10.
O pip seleciona dependências transitivas compatíveis com o interpretador.
Para reproduzir um experimento, mantenha também as versões transitivas:
`python -m pip freeze > results/dependencies.txt` e registre `python --version`,
`uname -a`, `lscpu` e `openssl version`. Os scripts headless salvam seu próprio
inventário. Use o mesmo inventário em repetições na mesma plataforma.

Execução local:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Na VM, escute em todas as interfaces:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --no-access-log
```

### VirtualBox

Com NAT, configure em **Rede → Avançado → Redirecionamento de portas** uma regra
TCP: IP hospedeiro `127.0.0.1`, porta hospedeiro `8000`, porta convidado `8000`.
O hospedeiro acessa `http://127.0.0.1:8000`. Escolha outra porta no hospedeiro
se 8000 estiver ocupada. Com rede bridge/host-only, use o IP da VM na URL.
Se o UFW estiver ativo, permita a porta para a rede do laboratório.
Desligue a VM antes de alterar vCPUs ou RAM e registre a configuração.

## Endpoints

Todos os campos `*_mb` representam **MiB = 1.048.576 bytes**. Durações em
milissegundos são medidas por `time.perf_counter`, sem arredondamento fixo.

| Método e rota | Entrada | Resultado |
|---|---|---|
| `GET /health` | nenhuma | `{"status":"ok"}` |
| `POST /hash` | multipart, campo `file` | `filename`, `size_bytes`, `algorithm`, `digest`, `execution_time_ms` |
| `POST /verify` | multipart, `file` e `expected_hash` | nome, tamanho, algoritmo, `expected_hash`, `calculated_hash`, `matches`, tempo |
| `POST /benchmark` | JSON com `data_size_mb` e `iterations` | parâmetros, algoritmo, total processado, tempos e digest agregado |

`/hash` lê o arquivo em chunks de 64 KiB. FastAPI/Starlette pode armazenar uploads
temporariamente em disco; esses endpoints não são a carga principal do estudo.
O tempo retornado inclui a leitura do arquivo já recebido e o hashing, excluindo
transferência e parsing multipart. Arquivos vazios são válidos.

`/verify` exige exatamente 64 caracteres hexadecimais, aceita maiúsculas e
normaliza para minúsculas. Usa `hmac.compare_digest`. Correspondência estabelece
**integridade em relação à referência fornecida**; autenticidade depende de
essa referência ser confiável. O digest do benchmark é agregado e não é o hash
simples de um arquivo.

### Limites e erros

| Recurso | Limite |
|---|---|
| Arquivo enviado | 16 MiB |
| Corpo HTTP de `/hash` e `/verify`, incluindo multipart | 17 MiB |
| Corpo HTTP das outras rotas | 4 KiB |
| `data_size_mb` | inteiro de 1 a 32 |
| `iterations` | inteiro de 1 a 1.000 |
| Produto tamanho × iterações | até 8.192 MiB |
| Requisições simultâneas admitidas | 8 por worker |

O limite do corpo é contado durante a recepção, mesmo sem `Content-Length`.
O parser fecha arquivos temporários quando o limite interrompe multipart.
Os parâmetros JSON são estritos: strings numéricas, booleanos, frações e campos
extras são rejeitados. Não existe parâmetro HTTP para aumentar os limites.
Erros de validação retornam 422, corpo/arquivo excessivo 413, multipart
malformado 400 e excesso de requisições admitidas 503.

Esses são limites por requisição/processo, não uma garantia de RAM total para
qualquer número de workers/clientes. Cada processo tem interpretador e buffer
próprios. Em 1 GiB, comece com um worker e acompanhe memória disponível e swap;
depois valide a configuração fixa escolhida para a comparação. A admissão de
oito requisições inclui uploads em andamento. Conexões podem aguardar fora dela
no servidor/SO. A aplicação destina-se à rede controlada do laboratório.

### Exemplos curl

```bash
curl -sS http://127.0.0.1:8000/health
printf 'abc' > /tmp/exemplo-hash.txt
curl -sS -F 'file=@/tmp/exemplo-hash.txt' http://127.0.0.1:8000/hash
curl -sS -F 'file=@/tmp/exemplo-hash.txt' \
  -F 'expected_hash=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad' \
  http://127.0.0.1:8000/verify
curl -sS -H 'Content-Type: application/json' \
  -d '{"data_size_mb":10,"iterations":100}' http://127.0.0.1:8000/benchmark
```

O benchmark retorna `algorithm`, `data_size_mb`, `iterations`,
`total_processed_mb`, `preparation_time_ms`, `execution_time_ms` e `digest`.
O total principal é exatamente tamanho × iterações; o acumulador processa
adicionalmente 32 bytes por iteração. `preparation_time_ms` mede alocação e
preenchimento. `execution_time_ms` mede o loop e a finalização do digest agregado.
Nenhum dos dois inclui espera em fila, transporte ou serialização HTTP.

## Workers, GIL e comparações

O endpoint assíncrono `/benchmark` chama deliberadamente o cálculo síncrono sem
`await` nem thread pool. Portanto, há **um benchmark ativo por worker**, e o loop
de eventos desse worker fica ocupado até o cálculo terminar. Isso também atrasa
`/health` e outras requisições atribuídas a ele. Essa decisão simplifica a unidade
de concorrência experimental. As rotas de arquivo usam o thread pool do FastAPI.

Em CPython, `hashlib` libera o GIL ao receber blocos maiores que 2.047 bytes nas
operações suportadas por OpenSSL. Isso permite paralelismo entre threads em
certos usos, mas não faz o loop de eventos ceder automaticamente. Aqui o
paralelismo dos benchmarks é obtido por processos Uvicorn independentes.
Referência: [documentação hashlib do Python 3.10](https://docs.python.org/3.10/library/hashlib.html).

**Mantenha o número de workers fixo ao comparar provisionamento**, preferindo
um número capaz de aproveitar o maior número de vCPUs testado. Por exemplo,
quatro workers para cenários de 1, 2 e 4 vCPUs, se a memória permitir. Em uma
vCPU eles disputam CPU, aumentam trocas de contexto, RAM e possivelmente latência.
Mais workers não implica mais desempenho. Estudar workers é outro experimento:
varie apenas workers, mantendo vCPUs, RAM e carga constantes.

## Experimento VirtualBox e gráficos

O [relatório técnico consolidado](docs/relatorio-cpu-bound.md) reúne a
análise dos cenários de 1, 2, 4, 6 e 8 vCPUs, os dados brutos de
`results/vbox-*`, os seis gráficos, o roteiro de reprodução da VM e as
capturas de tela. Ele é o documento único de entrega da aplicação CPU-bound.

No hospedeiro, instale as dependências de análise e gere novamente as figuras:

```bash
.venv/bin/python -m pip install -r requirements-analysis.txt
.venv/bin/python scripts/plot_virtualbox_results.py \
  --input results --output results/virtualbox-graficos
```

O comando preserva os dados brutos e grava PNG, SVG, PDF e CSVs em
`results/virtualbox-graficos/`. A pasta `results/` pode ser adicionada ao Git
e deve acompanhar o relatório na entrega. Remover a regra do `.gitignore` não
adiciona nem envia os arquivos automaticamente.

## Testes de carga — no hospedeiro

Instale as mesmas dependências e ative o ambiente virtual no **hospedeiro**, fora
da VM. Não execute o gerador junto do servidor nos experimentos comparativos.

```bash
source .venv/bin/activate
DATA_SIZE_MB=10 ITERATIONS=100 WAIT_SECONDS=0 \
USERS=10 SPAWN_RATE=2 DURATION=120s \
HOST=http://127.0.0.1:8000 OUTPUT_DIR=results/vcpu1-ram1g-rep1 \
bash scripts/run_load_test.sh
```

| Variável | Padrão | Significado |
|---|---|---|
| `DATA_SIZE_MB` | 10 | MiB por iteração |
| `ITERATIONS` | 100 | hashes por requisição |
| `WAIT_SECONDS` | 0 | espera fixa após cada resposta, em segundos |
| `USERS` | 10 | usuários virtuais |
| `SPAWN_RATE` | 2 | novos usuários por segundo |
| `DURATION` | 60s | duração incluindo rampa |
| `HOST` | `http://127.0.0.1:8000` | URL da API |
| `OUTPUT_DIR` | `results/run-<UTC>-<PID>` | novo diretório de saída |

O diretório de saída não pode existir, para preservar resultados anteriores.
São gerados `config.txt`, `dependencies.txt`, `locust_stats.csv`,
`locust_stats_history.csv`, `locust_failures.csv`, `locust_exceptions.csv` e
`locust.log` com o resumo final. Os CSVs são atualizados periodicamente; em uma
execução curta, o último snapshot pode preceder o total do resumo de encerramento.
Falhas HTTP, timeout (120 s) ou resposta inconsistente contam como falhas e
produzem status de saída não zero. O `WAIT_SECONDS` pertence ao gerador;
não simula trabalho dentro da API.

O Locust é um modelo fechado: cada usuário espera a resposta antes de iniciar
a próxima requisição. Usuários fixos não significam taxa de chegada fixa.
Em saturação, a vazão pode estabilizar enquanto a latência cresce. Use os mesmos
parâmetros de payload em todos os cenários; varie usuários para estudar demanda.
Não use uploads como carga principal. Referência:
[opções e CSV do Locust](https://docs.locust.io/en/stable/configuration.html).

## Monitoramento — dentro da VM

Inicie a API em segundo plano para capturar o PID mestre e monitore sua árvore:

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 \
  --no-access-log > results/api.log 2>&1 &
APP_PID=$!
python scripts/monitor.py --pid "$APP_PID" --interval 1 \
  --duration 150 --output results/monitor-vcpu1-rep1.csv
# Ao terminar todos os testes:
kill "$APP_PID"
```

Inicie o monitor antes da carga e deixe-o ativo após ela. Sem `--duration`,
coleta até Ctrl+C/SIGTERM e grava uma última amostra. O arquivo deve ser novo.
Sem `--pid`, coleta apenas o sistema e deixa colunas da aplicação vazias.

O CSV registra UTC, tempo decorrido e intervalo real da amostra, CPU total
do sistema (0–100%), CPU por núcleo (lista JSON), RAM usada/disponível em bytes,
número de processos, soma de RSS e CPU dos processos acessíveis da árvore.
O primeiro intervalo de CPU é preparado antes da primeira linha.

`app_cpu_percent` usa 100% por núcleo ocupado e pode superar 100% ao somar
processos. Para comparar com CPU do sistema, divida pelo número de CPUs lógicas.
RSS somado pode contar páginas compartilhadas mais de uma vez; não equivale
à memória física exclusiva da aplicação. `ram_used_bytes` segue a definição
do psutil; memória disponível é mais útil para avaliar pressão por RAM.

Processos novos têm CPU mensurável a partir da amostra seguinte; a coluna
`app_cpu_sampled_process_count` informa a cobertura. Processos encerrados ou
sem permissão podem ser omitidos, e processos muito curtos podem não ser vistos.
Se a árvore acabar, a contagem vira zero e uso da aplicação fica vazio.
CPU do sistema inclui monitor, SO e outros programas. A coleta e a escrita do
CSV têm custo próprio: mantenha intervalo e local de gravação constantes.

## Protocolo e interpretação dos experimentos

1. Registre vCPUs, RAM, workers, SO, Python/OpenSSL/dependências, configuração
   do VirtualBox, CPU do hospedeiro, energia e payload. Sincronize relógios
   hospedeiro/VM para correlacionar os CSVs.
2. Faça aquecimento separado com a mesma carga; escolha uma janela estável.
   Use duração maior que a rampa (`USERS / SPAWN_RATE`). Inicie o monitor antes.
3. Para demanda, mantenha recursos/workers/payload e varie usuários. Para
   provisionamento, mantenha usuários/payload/workers e altere um recurso por vez.
4. Repita cada cenário pelo menos três vezes, alternando a ordem para reduzir
   efeitos de temperatura e atividade do hospedeiro. Separe rampa, trecho estável
   e encerramento; não misture esses períodos sem declarar.
5. Compare requisições/s, erros, mediana, p95/p99 e CPU/RAM na mesma janela.
   Os percentis de Locust são aproximados; janelas curtas têm poucas observações.
   `total_processed_mb / (execution_time_ms / 1000)` dá MiB/s de uma execução;
   não substitui a vazão HTTP total sob concorrência.
6. CPU alta com vazão estabilizada e latência crescente sugere saturação de CPU.
   Confira todos os núcleos e erros antes de concluir. Pressão de memória/swap,
   rede, filas, limite de admissão e gerador saturado podem mudar essa interpretação.

O tempo HTTP do Locust inclui transporte e espera; o tempo interno do benchmark
mede apenas cálculo. A VM compete com o hospedeiro, inclusive com o próprio
Locust, embora sejam processos em ambientes distintos. Feche cargas estranhas,
monitore o gerador e não atribua automaticamente todo ganho a vCPUs. SHA-256
pode ser muito rápido em hardware com aceleração: ajuste a carga em um piloto,
dentro dos limites, e então mantenha-a fixa. Mais RAM pode não melhorar uma
carga que já cabe na memória. Limites de CPU são de trabalho, não de tempo;
uma requisição já em cálculo continua mesmo se o cliente desistir.

## Validação do projeto

```bash
python -m pytest -q
python -m pip check
bash -n scripts/run_load_test.sh
```

A suíte cobre referências conhecidas, integridade positiva/negativa, hashes
inválidos, determinismo, validação estrita, limites individuais/combinados e
uploads, incluindo requisição sem tamanho declarado. Os testes de benchmark
usam 1 MiB e poucas iterações. A validação de integração usa API real, carga
Locust pequena e monitor CSV; ela não substitui os experimentos na VM.

Validação realizada no ambiente de desenvolvimento com Python 3.12.3: API com
dois workers, endpoints HTTP reais, benchmark de 1 MiB × 2, Locust headless e
monitoramento CSV. A VM Ubuntu 22.04 usada no cenário de 1 vCPU passou nos
34 testes da aplicação; a suíte atual de 49 testes inclui também a análise
dos resultados VirtualBox.
Há um aviso de depreciação do alias `BlockingPortal` entre Starlette e AnyIO
durante os testes, sem falha funcional.
