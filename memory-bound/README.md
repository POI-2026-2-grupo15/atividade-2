# Memory-bound

Backend em Python e FastAPI que recebe arquivos CSV em `POST /memory-test`
e cadastra por ID. A última ocorrência de cada ID substitui a
anterior. Os registros únicos permanecem em memória até o fim da requisição.

Os CSVs usam o cabeçalho `id,name,email,description` e são enviados no campo
multipart `files`. A resposta informa quantidades recebidas, únicas e
substituídas, além do tempo de processamento.

## Preparação

Requisitos: Python 3.10 e Docker em execução para os experimentos.
A partir da raiz do repositório:

```bash
cd memory-bound
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Os comandos seguintes partem de `memory-bound/`, com o ambiente ativado.

## 1. Aplicação

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Acesse `http://127.0.0.1:8000/docs` para testar o envio dos arquivos.

## 2. Experimentos

```bash
python -m pip install -r requirements-analysis.txt
docker build -t memory-bound:experiment .
python scripts/docker_experiment.py --plan
python scripts/docker_experiment.py
```

O executor cria e encerra os containers automaticamente. São **48 testes**:
500 MiB, 1 GiB, 2 GiB e 4 GiB de RAM × 1, 2, 4 e 8 usuários × três repetições.
CPU e workers ficam fixos em seis, com swap desabilitado. Cada teste tem
10 segundos de aquecimento e 60 segundos de medição, usando `datasets/grande`.

Os dados ficam em uma nova pasta `results/docker-experiments-*` a cada execução.
Configuração: [protocol.json](experiments/protocol.json).
Metodologia: [experiments.md](docs/experiments.md).

## 3. Relatório

Para analisar os testes já realizados e gerar gráficos, PDF e Markdown:

```bash
python -m pip install -r requirements-report.txt
python scripts/analyze_results.py --input results/docker-experiments-<identificador>
python scripts/build_report.py
```

Para analisar outra execução, substitua o caminho passado em `--input`.
Gerar o relatório usa os dados salvos e não executa novos testes.

- Tabelas e gráficos: `output/analysis/`.
- PDF: [relatorio-memory-bound.pdf](output/pdf/relatorio-memory-bound.pdf).
- Markdown gerado: `docs/relatorio-memory-bound.md`.
