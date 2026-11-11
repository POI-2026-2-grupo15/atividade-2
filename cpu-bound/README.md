# cpu-bound

API FastAPI para hashing SHA-256, verificação de arquivos e benchmark de CPU.

## Imagem no Docker Hub

A aplicação foi conteinerizada e a imagem foi publicada no
[Docker Hub — arthurgb469/cpu-bound](https://hub.docker.com/r/arthurgb469/cpu-bound/tags).
A versão publicada é `arthurgb469/cpu-bound:atividade-4` para Linux/amd64.

Para baixar a imagem e subir a aplicação:

```sh
docker pull arthurgb469/cpu-bound:atividade-4
docker run -d --name cpu-bound -p 8000:8000 arthurgb469/cpu-bound:atividade-4
```

Confira a disponibilidade da API e o estado do container:

```sh
curl --fail http://localhost:8000/health
docker inspect --format '{{.State.Health.Status}}' cpu-bound
docker logs cpu-bound
```

O healthcheck pode aparecer como `starting` nos primeiros segundos e depois
passa para `healthy`. A documentação interativa da API fica em
http://localhost:8000/docs.

Para parar e remover o container:

```sh
docker stop cpu-bound
docker rm cpu-bound
```

## Executar com Docker

Como alternativa à imagem publicada, na pasta `cpu-bound`, construa e execute
a imagem localmente. Remova o container anterior antes de reutilizar o nome:

```sh
docker build -t cpu-bound:latest .
docker run -d --name cpu-bound -p 8000:8000 cpu-bound:latest
curl --fail http://localhost:8000/health
```

A documentação interativa fica em http://localhost:8000/docs.
A imagem executa como usuário sem privilégios e verifica `/health` a cada
30 segundos. O processo padrão usa um worker para manter explícita a
concorrência dos experimentos de CPU. Para testar múltiplos workers:

```sh
docker run --rm -p 8000:8000 --cpus=2 cpu-bound:latest \
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Exemplo de benchmark:

```sh
curl --fail http://localhost:8000/benchmark \
  -H 'Content-Type: application/json' \
  -d '{"data_size_mb":1,"iterations":2}'
```

## Publicar no Docker Hub

Para construir e enviar novamente a imagem com a tag `atividade-4`, execute os
comandos abaixo na pasta `cpu-bound`, autenticado em uma conta com permissão de
escrita no repositório `arthurgb469/cpu-bound`:

```sh
docker login
docker build -t arthurgb469/cpu-bound:atividade-4 .
docker push arthurgb469/cpu-bound:atividade-4
```

Para publicar em outra conta, substitua `arthurgb469` pelo seu usuário ou
organização nos comandos. Senhas e tokens devem ser informados somente no
terminal, sem adicioná-los aos arquivos do projeto.

Depois da publicação, confirme o download pelo registro:

```sh
docker pull arthurgb469/cpu-bound:atividade-4
```

## Testes locais

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/test_api.py tests/test_hashing.py
```

As dependências da API ficam em `requirements-runtime.txt`, também incluído
em `requirements.txt`. Ferramentas de testes e de carga não entram na imagem.
