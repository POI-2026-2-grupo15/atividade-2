# memory-bound

Backend experimental em Python 3.10+ e FastAPI. Recebe vários CSVs e constrói
um cadastro único em memória, mantendo o registro completo da última ocorrência
de cada ID. 

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

Resposta ilustrativa (o tempo varia):

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

CSV inválido retorna 422 com `detail.file`, `detail.line` e `detail.reason`.
A linha é a linha física informada pelo parser, podendo ser o fim de um
registro com múltiplas linhas; para falhas de decodificação, é aproximada
devido à leitura antecipada. Não é retornado resultado parcial. Ausência do
campo `files` recebe o erro de validação 422 do FastAPI. Erros do parser
multipart usam o tratamento padrão do framework.

## Trabalho realizado e uso de memória

Cada requisição cria seu próprio dicionário `ID -> registro completo`.
Os arquivos são lidos incrementalmente; não mantemos todas as listas de origem.
O cadastro consolidado permanece em memória até o fim do lote porque arquivos
posteriores podem substituir registros anteriores. Ao terminar ou falhar,
limpamos o cadastro e fechamos os streams dos uploads.

A resposta contém apenas estatísticas: o cadastro completo é construído
internamente, mas não é exportado ou persistido. Esse é um recorte experimental;
se a única necessidade fosse contar IDs, um conjunto de IDs consumiria menos
memória. A eliminação das referências não garante redução imediata do RSS,
pois o alocador pode reter páginas para reutilização.

O consumo depende principalmente da quantidade de IDs únicos, do tamanho dos
campos e do overhead dos objetos Python. Mais linhas repetidas não implicam
crescimento equivalente do cadastro. Requisições simultâneas têm cadastros
independentes, aumentando o conjunto de dados mantido pela aplicação.

A rota de consolidação é síncrona e roda no thread pool do FastAPI. Isso mantém
o loop de eventos disponível, mas não garante paralelismo de CPU entre threads
em CPython. O número de workers Uvicorn é configurável; mantenha-o constante
ao comparar provisionamento. Quantidade de clientes não equivale necessariamente
a quantidade de consolidações simultaneamente em processamento.

Não adicionamos limites próprios de tamanho ou concorrência. Continuam valendo
restrições do framework, parser e sistema operacional, incluindo limite de
campo do módulo `csv` e quantidade de arquivos do parser multipart. A aplicação
não redefine esses padrões. Falta de memória pode interromper o processo.

`UploadFile` pode armazenar arquivos recebidos temporariamente em disco.
Receber uploads, interpretar CSV, criar objetos e manipular o dicionário também
consomem rede, I/O e CPU. Portanto, o gargalo de memória é uma hipótese a medir,
não uma propriedade já comprovada por esta implementação.

`processing_time_ms` inclui leitura dos streams, parsing e consolidação.
Exclui recepção/parsing multipart anterior à chamada da rota, limpeza final e
serialização/transmissão da resposta. O tempo HTTP medido pelo cliente inclui
essas outras etapas e eventuais filas.

## Estado desta entrega

Parte 1: implementação da API e documentação local.
Exemplos de resposta são ilustrativos. Geração de lotes, Locust, monitoramento,
gráficos e protocolo VirtualBox ficam para as próximas partes.
