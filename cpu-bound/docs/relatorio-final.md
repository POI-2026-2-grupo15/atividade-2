# Aplicação CPU-bound: implementação e curva de demanda

## Objetivo e implementação

Foi desenvolvido um serviço FastAPI em Python para calcular e verificar hashes
SHA-256 de arquivos. O endpoint `/benchmark` executa repetidamente o hash de
um conjunto determinístico de dados já preparado em memória. Essa carga
sintética permite observar o efeito da demanda e da quantidade de CPUs sobre
utilização, vazão e latência. O cálculo usa CPU real e não introduz esperas
artificiais. O código também inclui limites de entrada, testes automatizados,
geração de carga com Locust e coleta de CPU e memória com `psutil`.

A API oferece `/health` para verificar o serviço, `/hash` para calcular o
SHA-256 de um arquivo em blocos, `/verify` para comparar o resultado com um
digest informado e `/benchmark` para os experimentos. A comparação em
`/verify` usa `hmac.compare_digest`; a autenticidade do valor de referência
depende de sua origem. Os testes automatizados cobrem os quatro endpoints,
validação de parâmetros, determinismo e limites de upload e memória. A suíte
de **34 testes** passou também na imagem com Python 3.10; API, Locust e coleta
CSV foram verificados no ambiente de desenvolvimento.

## Método do experimento

O piloto foi executado em Docker, antes da etapa planejada no VirtualBox. Em
todos os casos, foram mantidos **1 GiB de RAM**, **8 workers**, **10 MiB × 100
iterações por requisição**, espera zero e o mesmo pool de CPUs do hospedeiro.
O Locust rodou fora do container. Variaram apenas a quota de CPU (2, 4, 6 ou
8) e a quantidade de usuários simultâneos. Cada ponto durou 30 segundos, com
a CPU resumida entre os segundos 5 e 28. Os dados selecionados foram coletados
com o hospedeiro ligado à tomada.

Adotou-se como critério operacional de saturação **utilização média ≥ 95% da
quota de CPU**. O Locust usa um modelo fechado: cada usuário espera a resposta
antes de fazer outra requisição. Assim, o número de usuários representa
concorrência, não uma taxa fixa de chegada.

## Resultados: utilização de CPU

| Usuários | 2 CPUs | 4 CPUs | 6 CPUs | 8 CPUs |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 46,8% | 23,4% | 15,6% | 11,7% |
| 2 | 92,5% | 46,6% | 31,0% | 23,3% |
| 4 | 99,9% | 72,0% | 62,4% | 47,0% |
| 8 | 99,8% | 99,7% | 80,4% | 72,2% |
| 16 | 100,0% | 100,1% | 100,0% | 99,9% |
| 32 | 99,9% | 100,0% | 100,0% | 98,0% |

![Utilização, vazão e latência conforme a demanda](../results/demand-curve-ac/graficos/painel_curva_demanda.png)

Com 4 usuários, saturou apenas a quota de 2 CPUs. Com 8 usuários, saturaram
as quotas de 2 e 4 CPUs. A grade inicial mostrou todas as quotas saturadas
em 16 usuários. Para distinguir as de 6 e 8 CPUs, foram medidos níveis
intermediários:

| Quota | Abaixo de 95% | Primeiro nível acima de 95% | Repetição do nível |
| ---: | ---: | ---: | ---: |
| 6 CPUs | 9 usuários: 81,3% | **10 usuários: 97,8%** | **99,9%** |
| 8 CPUs | 11 usuários: 73,6% | **12 usuários: 96,5%** | **96,8%** |

![Medições intermediárias de 6 e 8 CPUs](../results/demand-refinement/curva_intermediaria.png)

Os primeiros níveis de saturação observados foram, portanto, **4 usuários
para 2 CPUs, 8 para 4 CPUs, 10 para 6 CPUs e 12 para 8 CPUs**. Os pontos
intermediários de 10 usuários/6 CPUs e 12 usuários/8 CPUs ficaram acima do
critério nas duas execuções. O ponto de 11 usuários/8 CPUs apresentou queda de
utilização; a curva conserva essa variação observada.

## Vazão, latência e recursos

Na matriz de demanda, com 32 usuários, as vazões observadas foram **2,45;
5,25; 8,33; e 9,81 requisições/s** para 2, 4, 6 e 8 CPUs,
respectivamente. As latências médias correspondentes foram **7,37; 5,00;
3,01; e 2,89 segundos**. Essas métricas HTTP incluem a subida dos usuários,
enquanto a média de CPU usa a janela estável indicada no método.

Em cada um dos 24 pontos da matriz principal e dos 10 testes intermediários,
não houve falhas HTTP registradas, uso de swap ou eventos de falta de memória.
Na matriz principal, a RAM máxima amostrada ficou abaixo de 363 MiB e o
gerador de carga consumiu menos de 3% de um núcleo em média. Isso sustenta a
interpretação de que o gargalo observado foi o processamento de CPU, dentro
das condições deste piloto.

## Conclusão e limites

A curva obtida mostra a saturação progressiva desejada: à medida que a
concorrência cresce, configurações menores atingem primeiro o limite de CPU.
Depois da saturação, mais usuários aumentam a espera; a vazão não precisa
continuar crescendo. Aumentar a quota tende a oferecer mais capacidade para
a mesma carga, embora os valores medidos dependam também de escalonamento,
frequência e distribuição das conexões entre workers.

Os limiares são **primeiros níveis observados**, não mínimos universais.
Houve uma medição por ponto da grade principal e duas somente nos dois pontos
intermediários candidatos. O piloto não fornece intervalos de confiança. A
quota de 8 CPUs compartilha um pool de sete núcleos físicos com SMT; ela não
representa oito núcleos físicos exclusivos. Os resultados Docker também não
substituem medições no VirtualBox. Para a entrega experimental definitiva,
convém repetir cada cenário, alternar a ordem e usar janelas maiores.

## Arquivos para conferência

- [Painel em PDF](../results/demand-curve-ac/graficos/painel_curva_demanda.pdf)
  e [curva intermediária em PDF](../results/demand-refinement/curva_intermediaria.pdf).
- Matriz principal: `results/demand-curve-ac`; níveis adicionais:
  `results/demand-refinement` e `results/demand-refinement-boundary`.
- Os diretórios de resultados contêm os CSVs de CPU, memória e Locust, além
  dos parâmetros efetivos. A [metodologia de execução](demand-curve.md)
  descreve como reproduzir o experimento.

Os dados brutos e os gráficos em `results/` são locais e ignorados pelo Git;
inclua esses arquivos ao preparar uma cópia do relatório para entrega.
