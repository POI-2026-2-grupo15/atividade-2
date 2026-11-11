# Atividade 4 — Execução com Docker Compose

Com Docker e Docker Compose instalados, execute os comandos abaixo na raiz
do repositório. O [compose.yaml](compose.yaml) utiliza imagens publicadas no
Docker Hub, sem construir imagens locais.

```bash
docker compose pull
docker compose up -d
docker compose ps
```

| Serviço | Imagem | Endereço local |
| --- | --- | --- |
| CPU-bound | `arthurgb469/cpu-bound:atividade-4` | http://localhost:8000 |
| IO-bound | `arthurgb469/io-bound:atividade-4` | http://localhost:8001 |
| Memory-bound (opcional) | `usuario-do-colega/memory-bound:atividade-4` (placeholder) | http://localhost:8002 |

As imagens e portas são fixas no `compose.yaml`. Para alterá-las, edite os
campos `image` e `ports` do serviço correspondente. No mapeamento de portas,
o lado esquerdo é a porta do hospedeiro e o direito é a porta do container.

### Verificar CPU-bound e IO-bound

```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
curl -H 'Content-Type: application/json' \
  -d '{"data_size_mb":1,"iterations":2}' http://localhost:8000/benchmark
curl -H 'Content-Type: application/json' \
  -d '{"size_kb":1024}' http://localhost:8001/io
```

O IO-bound usa `IO_DATA_DIR=/data` e grava os arquivos temporários em
`/data/io-bound-data`, no volume `atividade-4_io-bound-data`. Esse volume
evita que as operações do experimento passem pela camada gravável do
container; mantenha-o em disco, sem tmpfs. Cada requisição apaga seu arquivo
ao terminar, portanto a finalidade do volume é o acesso a disco, não a
persistência de resultados.

### Habilitar Memory-bound

O serviço `memory-bound` fica desativado por padrão pelo perfil `memory`.
Assim, o placeholder não impede o download e a inicialização dos outros
dois serviços. Quando a imagem estiver publicada, substitua
`docker.io/usuario-do-colega/memory-bound:atividade-4` no campo `image` e execute:

```bash
docker compose --profile memory up -d
```

A porta interna reservada é `8000`. Se a imagem usar outra porta, ajuste o
lado direito de `8002:8000`. A aplicação deve escutar em `0.0.0.0` dentro do
container; será usado o comando padrão da imagem.

### Logs e encerramento

```bash
docker compose --profile memory logs -f
docker compose --profile memory down
```

O perfil nos comandos acima inclui o serviço opcional, caso tenha sido
iniciado. O comando `down` remove os containers e a rede, preservando o
volume de dados.
