# Atividade 2 — Aplicações CPU-bound, IO-bound e Memory-bound

Este repositório reúne três aplicações HTTP usadas para estudar como a demanda e o provisionamento de recursos afetam o desempenho. Os experimentos usam **FastAPI** para as aplicações, **Locust** para gerar carga e coleta de métricas para analisar vazão, latência e utilização de recursos.

## Grupo

**POI 2026.2 — Grupo 15**

- Arthur Gabriel Santos Albuquerque (`Arthurabriel`) - 122110395
- Hildon Regis Navarro Neto (`Hildon27`) - 122110322
- Victor Vili Xavier Luna (`victor-vili-luna`) - 122110387

## Aplicações e relatórios

| Aplicação | Carga principal | Relatório |
| --- | --- | --- |
| [CPU-bound](cpu-bound/) | Hashing SHA-256 repetido, com foco no uso de CPU. | [Relatório CPU-bound](cpu-bound/docs/relatorio-cpu-bound.md) |
| [IO-bound](io-bound/) | Escrita, sincronização e leitura de arquivos, com foco no acesso a disco. | [Relatório IO-bound](io-bound/docs/relatorio-final.md) |
| [Memory-bound](memory-bound/) | Identificação e eliminação de cadastros duplicados em CSVs, com registros mantidos em memória. | [Relatório Memory-bound](memory-bound/output/pdf/relatorio-memory-bound.md) |

O relatório de **CPU-bound** apresenta medições em uma VM VirtualBox com 1, 2, 4, 6 e 8 vCPUs, variando a quantidade de usuários simultâneos. O relatório de **IO-bound** documenta um piloto local em Docker com diferentes limites de CPU e memória. O estudo de **Memory-bound** usa arquivos CSV e cenários Docker com diferentes limites de RAM e quantidades de usuários. Como os ambientes e as cargas são distintos, seus valores absolutos de desempenho não devem ser comparados diretamente.

Os relatórios descrevem os métodos, resultados, gráficos e limites de cada experimento. Para executar as aplicações e reproduzir os testes, consulte o [Apêndice B do relatório CPU-bound](cpu-bound/docs/relatorio-cpu-bound.md#apêndice-b--execução-automatizada-da-matriz-definitiva) e o [README de IO-bound](io-bound/README.md).

O relatório de **Memory-bound** apresenta 48 experimentos locais em Docker, variando a RAM entre 500 MiB e 4 GiB e a demanda entre um e oito usuários simultâneos. A versão em [PDF](memory-bound/output/pdf/relatorio-memory-bound.pdf) está na mesma pasta da versão Markdown. Para reproduzir os testes, consulte o [README de Memory-bound](memory-bound/README.md).
