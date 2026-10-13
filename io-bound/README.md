# io-bound

API acadêmica cujo gargalo é o **disco**, para os experimentos de demanda,
desempenho e provisionamento. Python 3.10+, FastAPI e Uvicorn; sem banco ou
serviços externos. Execute os comandos a partir da pasta `io-bound/`.

## Arquitetura e perfil computacional

```text
Hospedeiro: Locust → rede/VirtualBox → VM: Uvicorn (1 worker, thread pool)
                                            ├─ FastAPI → escreve/fsync/lê arquivo
                                            └─ monitor.py → CSV (CPU, RAM, iowait, disco)
```

- `app/main.py`: API inteira (`/health` e `/io`).
- `load_tests/locustfile.py`: carga constante por requisição.
- `scripts/run_load_test.sh`: um ponto de carga (N usuários).
- `scripts/run_demand_curve.sh`: curva de demanda de um cenário (vários N).
- `scripts/monitor.py`: coleta na VM; mesmo monitor da `cpu-bound` mais iowait e disco.
- `scripts/plot_results.py`: tabela consolidada e gráficos comparando cenários.

Cada `POST /io` faz:

1. grava `size_kb` KiB de um buffer aleatório fixo em um arquivo novo;
2. chama `fsync`, ou seja, espera o dado chegar fisicamente ao disco;
3. descarta o arquivo do page cache (`posix_fadvise DONTNEED`, só no Linux);
4. lê o arquivo de volta do disco, confere o conteúdo e o apaga.

A CPU quase não trabalha: o buffer é gerado uma vez na inicialização, e a
requisição passa a maior parte do tempo **esperando o disco**. A rota é
síncrona, então o FastAPI a executa no thread pool (40 threads por padrão).
Enquanto uma thread espera o disco, as outras continuam, e um único worker
atende várias requisições simultâneas. Esse é o contraste com a `cpu-bound`,
em que cada worker processa um benchmark por vez.

O sinal de saturação esperado é: **vazão estável, latência crescente, CPU
baixa e iowait alto**. O limite vem do disco (o VDI fica no disco do
hospedeiro), e não do número de vCPUs.

## Instalação e execução

No Ubuntu Server 22.04 (VM) ou no hospedeiro:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
git clone <url-do-repo> && cd <repo>/io-bound   # branch io-bound
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

Local: `python -m uvicorn app.main:app --port 8000 --no-access-log`

Na VM (escutando em todas as interfaces):

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log
```

Os arquivos temporários ficam em `/tmp/io-bound-data`. Para usar outro disco
ou diretório, defina `IO_DATA_DIR=/caminho`. Mantenha o mesmo diretório em
todos os cenários. Atenção: se `/tmp` for tmpfs (RAM), o teste deixa de medir
disco; confira com `df -h /tmp`. No Ubuntu Server 22.04, `/tmp` fica no disco.

### VirtualBox

Siga o roteiro da disciplina. Com a VM desligada, em **Rede → Avançado →
Redirecionamento de portas**, crie uma regra TCP: IP hospedeiro `127.0.0.1`,
porta hospedeiro `8000`, porta convidado `8000`. No hospedeiro:

```bash
curl http://127.0.0.1:8000/health
curl -H 'Content-Type: application/json' -d '{"size_kb":1024}' http://127.0.0.1:8000/io
```

## Endpoints

| Método e rota | Entrada | Resultado |
|---|---|---|
| `GET /health` | nenhuma | `{"status":"ok"}` |
| `POST /io` | JSON `{"size_kb": 1..16384, "fsync": true}` | `size_kb`, `fsync`, `write_ms`, `read_ms`, `total_ms`, `verified` |

Os parâmetros são estritos: strings, frações e campos extras retornam 422.
`fsync: false` deixa a escrita só no page cache, ou seja, mede a RAM e não o
disco. Use-o apenas para comparação. Com o limite de 40 threads × 16 MiB, o
pior caso ocupa cerca de 640 MiB temporários em disco.

## Protocolo dos experimentos

A carga é gerada **fora da VM** (no hospedeiro). Parâmetros fixos em todos os
cenários: `SIZE_KB=1024`, `FSYNC=1`, 1 worker, espera zero e 60 s por ponto.
Ajuste `SIZE_KB` num piloto, se necessário, e depois não mude mais.

Cenários sugeridos (mude um recurso de cada vez, com a VM desligada):

| Cenário | vCPUs | RAM |
|---|---|---|
| `vcpu1-ram1g` | 1 | 1 GiB |
| `vcpu2-ram1g` | 2 | 1 GiB |
| `vcpu4-ram1g` | 4 | 1 GiB |
| `vcpu2-ram2g` | 2 | 2 GiB |

Em cada cenário:

1. **Na VM**: inicie a API e o monitor.

   ```bash
   source .venv/bin/activate
   mkdir -p results
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 \
     --no-access-log > results/api.log 2>&1 &
   APP_PID=$!
   python scripts/monitor.py --pid "$APP_PID" --interval 1 --output results/monitor-vcpu1-ram1g.csv
   ```

2. **No hospedeiro**: rode a curva de demanda (1, 2, 4, 8, 16, 32 e 64 usuários,
   cerca de 8 minutos).

   ```bash
   source .venv/bin/activate
   SCENARIO=vcpu1-ram1g HOST=http://127.0.0.1:8000 bash scripts/run_demand_curve.sh
   ```

3. **Na VM**: pare o monitor com Ctrl+C e copie o CSV para o hospedeiro como
   `results/vcpu1-ram1g/monitor.csv` (por exemplo com
   `scp -P 2222 osboxes@127.0.0.1:...`, criando um redirecionamento 2222→22, ou
   por pasta compartilhada).

Depois de todos os cenários, gere os gráficos no hospedeiro:

```bash
python -m pip install -r requirements-analysis.txt
python scripts/plot_results.py      # results/plots/*.png e summary.csv
```

O script cruza os horários do Locust com os do monitor, considerando só o
trecho em que todos os usuários já estavam ativos. Por isso, os **relógios do
hospedeiro e da VM precisam estar sincronizados** (verifique `timedatectl` na
VM). A coluna `monitor_samples` mostra quantas amostras caíram em cada janela;
se ela vier zerada, os relógios estão desencontrados.

| Variável | Padrão | Significado |
|---|---|---|
| `SCENARIO` | obrigatória | nome do cenário e da pasta em `results/` |
| `USERS_LIST` | `1 2 4 8 16 32 64` | níveis de demanda |
| `DURATION` | `60s` | duração de cada ponto |
| `PAUSE` | `10` | pausa entre pontos, em segundos |
| `SIZE_KB` | `1024` | KiB gravados e lidos por requisição |
| `FSYNC` | `1` | `0` desliga o fsync |
| `HOST` | `http://127.0.0.1:8000` | URL da API |

## Interpretação

- **Vazão (req/s)** sobe com os usuários até o disco saturar e depois estabiliza.
- **Latência** (mediana e p95) cresce depois desse ponto: as requisições
  passam a esperar na fila do disco.
- **iowait alto com CPU baixa** confirma o gargalo de I/O. CPU alta indicaria
  outro gargalo (por exemplo, overhead de HTTP/JSON com 1 vCPU).
- Mais vCPUs devem ajudar pouco, só no overhead de rede/HTTP. Mais RAM não
  ajuda escrita com fsync, mas mudaria o resultado com `FSYNC=0`, porque o
  page cache passa a absorver as escritas.
- O disco virtual é um arquivo no disco do hospedeiro: a atividade do
  hospedeiro e o cache do VirtualBox afetam os números. Feche outros
  programas e repita cada cenário quando possível.
