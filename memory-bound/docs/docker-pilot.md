# Piloto Docker inicial (histórico)

Registro da calibração inicial. O executor antigo foi substituído por
[Docker Experiment](../scripts/docker_experiment.py); o procedimento vigente
está no [protocolo](experiments.md). Não usar os comandos antigos nem misturar
estes dados de 20 segundos, incluindo rampa, à matriz com janela separada.

Locust rodou no Mac; API e monitor no container. Foram mantidos dois workers,
duas CPUs, dataset grande e swap desabilitado.

## Resultado observado e parâmetros seguintes

Executado em 14/10/2026. Docker Desktop: Linux ARM64, 10 CPUs lógicas e cerca
de 7,75 GiB disponíveis à VM interna. Imagem Python 3.10 construída nativamente
para ARM64. Seis testes existentes de consolidação passaram dentro da imagem;
validação HTTP de entradas inválidas e contagens do dataset passou nos cinco
containers que suportaram uma requisição completa.

| RAM MiB | Usuários | Requisições | Falhas | Req/s total | Média ms | CPU (% de 2 CPUs) | Memória máxima amostrada MiB | Mortes OOM |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1024 | 1 | 17 | 0 | 0,91 | 1102 | 46,67 | 343,86 | 0 |
| 1024 | 2 | 26 | 0 | 1,37 | 1443 | 80,93 | 572,79 | 0 |
| 1024 | 4 | 23 | 0 | 1,22 | 3053 | 88,10 | 849,68 | 0 |
| 1024 | 8 | 16 | 5 | 1,19 | 6126 | 80,59 | 1024,00 | 1 |
| 512 | 4 | 20 | 11 | 1,10 | 3645 | 59,38 | 512,00 | 3 |
| 256 | - | - | - | - | - | - | - | 1 na validação |

Req/s, média e contagens Locust incluem requisições que falharam. Mortes OOM
são contadores cumulativos do cgroup, incluindo a validação anterior à carga.
Em 256 MiB não houve carga Locust: a primeira requisição grande perdeu a conexão.
Uma repetição isolada confirmou `oom_kill=1`, com logs e estado preservados.

Artefatos medidos:

- [Cinco pontos de carga](../results/docker-pilot-20261014T152424Z/summary.csv).
- [Configuração e identidade da imagem](../results/docker-pilot-20261014T152424Z/environment.json).
- [Confirmação da falha com 256 MiB](../results/docker-pilot-20261014T152804Z/ram256-u4/failure.json).

A primeira execução parou na validação de 256 MiB por uma desconexão. O script
foi ajustado para preservar evidência desse caso esperado, e somente esse ponto
foi repetido; os cinco pontos anteriores não foram repetidos nem descartados.

Conclusão do piloto: há pressão real de memória e mortes OOM sob concorrência;
também há forte custo de CPU. Entre 2 e 4 usuários com 1 GiB, CPU se aproxima
do limite, a vazão não cresce e a latência aumenta. Não atribuir toda degradação
à RAM nem afirmar que o gargalo é exclusivamente memory-bound.

Decisões iniciais (CPU e RAM foram posteriormente revistas na
[calibração](cpu-calibration.md); preservar esta seção como histórico):

- Manter dataset grande, 2 CPUs e 2 workers, com Locust no Mac e sem swap.
- Manter níveis de demanda 1, 2, 4 e 8 usuários; descartar 256 MiB como cenário
  principal, pois não suporta sequer uma requisição desse lote.
- Propor 512, 768, 1024 e 2048 MiB para a matriz final; 768 e 2048 ainda não
  foram medidos. Não executar a matriz nesta entrega.
- Ampliar a duração para pelo menos 60 segundos, separar aquecimento/janela
  estável, repetir cada ponto três vezes e monitorar também o gerador no Mac.
- Registrar throughput de sucesso separadamente de erros e contabilizar OOM,
  inclusive quando Uvicorn recria workers e o container permanece ativo.
