# Metodologia dos experimentos

O objetivo foi observar como a demanda e a RAM disponível afetam o desempenho
e o consumo de recursos da aplicação memory-bound. Este arquivo resume o método;
os comandos de execução estão no [README](../README.md) e os resultados no
[relatório final](../output/pdf/relatorio-memory-bound.pdf).

## Cenários

| RAM do container | Usuários simultâneos | Repetições por demanda |
|---|---|---|
| 500 MiB | 1, 2, 4 e 8 | 3 |
| 1 GiB | 1, 2, 4 e 8 | 3 |
| 2 GiB | 1, 2, 4 e 8 | 3 |
| 4 GiB | 1, 2, 4 e 8 | 3 |

Foram **48 execuções**, todas com seis CPUs de quota, seis workers, swap
desabilitado e o mesmo dataset grande: quatro CSVs, totalizando 99,15 MiB.
A justificativa da escolha de CPU/workers está na metodologia do relatório.
Os parâmetros usados pelo executor estão em [protocol.json](../experiments/protocol.json).

## Procedimento

1. Criar um container novo com os recursos do cenário e aguardar a API iniciar.
2. Iniciar o Locust no hospedeiro. Cada usuário envia os CSVs e, ao receber a
   resposta, inicia outra requisição, sem espera artificial.
3. Após todos os usuários estarem ativos, aquecer por **10 segundos** e medir
   por **60 segundos**. CPU e memória são amostradas a cada **0,5 segundo**.
4. Salvar os dados, encerrar o container e aguardar **5 segundos** antes do próximo teste.

Cada repetição cobre todas as combinações de RAM e demanda. A ordem alterna
as configurações entre as coletas e fica registrada em `plan.json`.

## Métricas e comparação

| Métrica | Como foi medida |
|---|---|
| Vazão válida | Respostas corretas concluídas durante a medição, divididas por 60 segundos. |
| Latência média e p95 | Tempos dos sucessos iniciados e concluídos dentro da janela de medição. |
| CPU | Uso do container normalizado pela quota de seis CPUs. |
| Memória | Maior valor amostrado de memória do container durante a medição. |
| Falhas e OOM | Falhas nas respostas da janela e evidências de morte por falta de memória. Os contadores finais OOM abrangem todo o teste, incluindo aquecimento. |

Requisições pendentes ao fim da janela são registradas separadamente.
A análise apresenta média e desvio padrão entre as três repetições; o p95
apresentado é a média dos p95 de cada repetição. Coletas com lacunas de
monitoramento são identificadas e excluídas das médias de CPU e memória.

Os dados originais ficam em `results/docker-experiments-*`; as tabelas e os
gráficos derivados, em `output/analysis/`. Falhas por falta de memória fazem
parte dos resultados. CPU/workers constantes não garantem gargalo exclusivo de RAM.
