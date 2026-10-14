# Calibração de CPU e workers para os cenários de RAM

Objetivo: reduzir a interferência de CPU antes de comparar 500, 1024, 2048 e
4096 MiB. Não presumir que CPU extra elimina todos os gargalos da aplicação.

## Método

- Dataset grande, idêntico em todas as requisições (~99,15 MiB).
- 4096 MiB por container e swap desabilitado, para reduzir pressão de memória.
- Oito usuários simultâneos, a maior demanda proposta para a matriz.
- Comparação de 4 CPUs/4 workers com 6 CPUs/6 workers.
- Três repetições por configuração, 30 segundos de Locust por repetição.
- Container novo por repetição; validação HTTP com lote completo antes da carga.
- Locust no Mac; monitor cgroup/Uvicorn no container, a cada 0,5 segundo.
- Monitor adicional no Mac para a árvore bash/Locust; CPU em escala de 100%
  por núcleo, incluindo os pequenos processos auxiliares dessa árvore.

Esta coleta usou o executor antigo, depois substituído por
[docker_experiment.py](../scripts/docker_experiment.py). Para as próximas
medições, seguir o [protocolo vigente](experiments.md).

As duas configurações são executadas sequencialmente, sem cargas simultâneas.
As métricas HTTP incluem rampa; CPU e memória são resumidas entre o início e
fim do processo de carga. Esta calibração não substitui as coletas mais longas
com janela estável da matriz final. A ordem agrupada das configurações pode
sofrer influência de temperatura e atividade externa.

CPU e workers variam juntos: os resultados avaliam o par de configuração,
sem separar o ganho causado por quota daquele causado por mais processos.
Os resultados do piloto anterior (2 CPUs/2 workers, RAM diferente) não são
uma comparação controlada com estes dados.

## Resultados e decisão

Concluído em 14/10/2026: seis execuções de carga, todas sem falhas HTTP e sem
mortes OOM. Os dez testes existentes passaram após as mudanças do executor.

| CPU / workers | Req/s média ± desvio padrão | Latência média s | CPU média (% do limite) | Máximo amostrado MiB | CPU média gerador (% de um núcleo) |
|---|---:|---:|---:|---:|---:|
| 4 / 4 | 1,62 ± 0,14 | 4,64 | 75,44 | 1951,85 | 32,50 |
| 6 / 6 | 1,36 ± 0,12 | 5,47 | 52,63 | 2013,25 | 30,89 |

O desvio padrão é entre as três execuções; a latência da tabela é a média das
médias de cada execução. Não representa um intervalo de confiança.

- [Dados de 4 CPUs/4 workers](../results/docker-pilot-cpu4-w4-20261014T154248Z/summary.csv).
- [Dados de 6 CPUs/6 workers](../results/docker-pilot-cpu6-w6-20261014T154458Z/summary.csv).
- [Comparação consolidada](../results/cpu-calibration-20261014T154248Z/comparison.csv).

Não houve ganho de vazão ao aumentar CPU/workers. A vazão também caiu ao longo
das repetições de cada configuração: como a ordem não foi intercalada, não se
pode concluir que seis CPUs causam pior desempenho. Não houve saturação média
do limite global de CPU; isso não exclui um worker individual ocupado, GIL,
overhead de upload, disco temporário ou outros limites do caminho da requisição.
O gerador não saturou um núcleo em média, mas isso não exclui espera por I/O.

Decisão operacional: fixar 6 CPUs e 6 workers nos cenários de RAM, para maior
margem em relação à quota global de CPU, mantendo esse mesmo custo de processos
em todas as configurações. O objetivo é reduzir interferência da quota; não
afirmar que a RAM será o único gargalo ou que seis workers são uma otimização.
Essa calibração histórica usou 4096 MiB, oito usuários, 30 segundos e três
repetições. O executor atual tem uma janela separada e o protocolo da matriz.

RAM definida pelo usuário: 500, 1024, 2048 e 4096 MiB. Com demandas 1, 2, 4 e
8 usuários e três repetições, a matriz terá 48 execuções; ainda não executada.
Para essa matriz, usar coletas mais longas, janela estável e intercalar a ordem
das configurações entre rodadas. Preservar falhas e OOM como resultados.

Na primeira tentativa desta calibração a referência da imagem não pôde ser
resolvida, antes de iniciar qualquer carga. A imagem foi reconstruída e as seis
execuções acima foram concluídas. Imagens, código da API e datasets não foram
alterados entre as duas configurações; seus IDs estão nos metadados.
