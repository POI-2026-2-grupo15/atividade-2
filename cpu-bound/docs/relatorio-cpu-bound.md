# Relatório técnico Aplicação CPU-bound

**Estudo:** serviço de hashing SHA-256 e avaliação de provisionamento de CPU em máquinas virtuais VirtualBox.
**Data dos registros experimentais:** 13 e 14 de outubro de 2026.
Este documento reúne o relatório acadêmico e o procedimento de reprodução. Abrange somente a aplicação CPU-bound.

## 1. Introdução

A atividade investiga como o provisionamento de recursos de uma máquina virtual afeta o desempenho de uma aplicação submetida a carga. A análise conjunta de utilização de recursos, vazão e tempo de resposta permite distinguir uma melhoria de capacidade de uma mera mudança no número de processadores atribuídos. Para estudar esse efeito, foi desenvolvido um serviço HTTP que executa hashing SHA-256 repetido, uma carga simulada com trabalho computacional parametrizável e pouca entrada/saída durante o cálculo.

O objetivo geral é caracterizar o comportamento desse serviço sob carga e comparar cenários de provisionamento de CPU no VirtualBox. Para isso, busca-se implementar e validar uma carga reproduzível, registrar o ambiente e o procedimento de medição, comparar utilização de CPU e memória, vazão, latência e falhas HTTP, e avaliar os limites das inferências possíveis a partir dos dados coletados.

Os resultados são apresentados na Seção 5.

## 2. Desenvolvimento da aplicação

O serviço utiliza Python, FastAPI, Pydantic, Uvicorn e a implementação de SHA-256 de `hashlib`. O núcleo de hashing está em [`app/hashing.py`](../app/hashing.py); [`app/main.py`](../app/main.py) expõe os endpoints; [`app/schemas.py`](../app/schemas.py) valida os dados; [`app/limits.py`](../app/limits.py) controla o tamanho dos corpos HTTP e a concorrência admitida por worker. O gerador de carga ([`load_tests/locustfile.py`](../load_tests/locustfile.py)) e o monitor ([`scripts/monitor.py`](../scripts/monitor.py)) são processos separados da API.

```text
Hospedeiro: Locust (usuários virtuais) ── TCP 127.0.0.1:8000 / NAT ──► VM Ubuntu
                                                                    Uvicorn (8 workers)
                                                                         │
                                                            FastAPI → SHA-256 em memória
                                                                         │
                                                    monitor.py + vmstat (CPU, RAM, swap)
Hospedeiro: SSH 127.0.0.1:2222 ─────────────── NAT TCP ───────────────► VM:22
```

**Figura 1 — Arquitetura experimental.** As setas indicam o caminho das requisições e do acesso administrativo; os comandos de carga rodam no hospedeiro, enquanto API e coleta de recursos rodam na VM. As portas são TCP.

| Endpoint | Método e entrada | Função e saída principal |
| --- | --- | --- |
| `/health` | `GET`, sem corpo | Informa disponibilidade com `{"status":"ok"}`. |
| `/hash` | `POST`, arquivo multipart | Calcula SHA-256 do arquivo em blocos e retorna nome, tamanho, digest e tempo de execução. |
| `/verify` | `POST`, arquivo e digest hexadecimal esperado | Calcula SHA-256 e retorna o digest calculado, o esperado e o resultado da comparação. |
| `/benchmark` | `POST`, JSON com `data_size_mb` e `iterations` | Executa hashing repetido de um buffer determinístico e informa digest agregado, volume processado e tempos de preparação/execução. |

**Tabela 1 — Endpoints HTTP da aplicação.** Fonte: [`app/main.py`](../app/main.py) e modelos em [`app/schemas.py`](../app/schemas.py).

No `/benchmark`, o buffer é construído em memória pela repetição da sequência de bytes de 0 a 255 até o tamanho solicitado. Em cada iteração é calculado um novo SHA-256 do **mesmo buffer inteiro**; os digests binários são incorporados a um hash agregador que produz o resultado final. O serviço informa separadamente o tempo de preparar o buffer e o tempo do laço de hashing. Os parâmetros controlam o trabalho: `data_size_mb × iterations` expressa o volume lógico processado, não a quantidade de RAM simultaneamente alocada. No perfil experimental, 10 MiB × 100 iterações correspondem a 1.000 MiB processados logicamente por requisição. O buffer não é lido de disco durante o laço, e não há escrita de arquivo por requisição. Trata-se de uma **carga sintética**, não de uma aplicação de produção com arquivos reais ou uma simulação integral de I/O.

Os endpoints de arquivo leem blocos de 64 KiB e limitam o upload a 16 MiB. O digest esperado em `/verify` deve ter 64 caracteres hexadecimais e a comparação emprega `hmac.compare_digest`; isso compara os valores. Para `/benchmark`, o esquema exige inteiros estritos, 1–32 MiB, 1–1.000 iterações e produto de no máximo 8.192 MiB. O middleware limita o corpo a 17 MiB nos endpoints multipart, a 4 KiB nos demais e a oito requisições admitidas simultaneamente **por worker**; tamanhos excessivos são rejeitados com HTTP 413 e excesso de concorrência pode gerar HTTP 503. Restrições de esquema produzem erro de validação. Esses limites reduzem o risco de consumo descontrolado de recursos, mas a presença de oito workers não torna ilimitada a capacidade da VM.

O endpoint `/benchmark` executa o cálculo síncrono diretamente no worker que recebeu a requisição; enquanto o cálculo ocorre, esse worker não atende outra requisição. Os oito processos Uvicorn permitem cálculos simultâneos em processos separados. O tempo interno retornado pela API mede o cálculo, enquanto a latência HTTP do Locust também inclui espera e transporte. Os testes automatizados da aplicação e da análise podem ser executados com `.venv/bin/python -m pytest -q` após instalar `requirements.txt` e `requirements-analysis.txt`.

![Respostas de health e benchmark formatadas com jq no hospedeiro](../evidencias/manual-02-api.png)

**Figura 2 — API em funcionamento.** A resposta de `/health` contém `status: ok`; `/benchmark` apresenta o algoritmo, os parâmetros 10 MiB e 100 iterações, o total lógico de 1.000 MiB, o tempo de execução e o digest. O tempo da chamada isolada exibida não é a latência HTTP sob a carga concorrente do Locust.

## 3. Ambiente experimental

Os artefatos documentam cinco configurações VirtualBox: 1, 2, 4, 6 e 8 vCPUs. Em todas, a memória atribuída foi de 1.024 MiB e a API foi iniciada com oito workers Uvicorn. O hospedeiro utilizou um AMD Ryzen 5 5500 com seis núcleos físicos e 12 threads. A configuração de 8 vCPUs compartilha os recursos desse hospedeiro com o sistema operacional e o gerador de carga; portanto, os resultados não representam oito núcleos físicos exclusivos.

| Componente | Configuração comprovada | Evidência |
| --- | --- | --- |
| Sistema hospedeiro | Ubuntu 24.04.4 LTS, kernel 7.0.0-31-generic durante a matriz. | [`host-inventory.txt`](../results/demand-vbox-8cpu-20261014T104931Z-504345/host-inventory.txt) e [`host-os-release.txt`](../results/demand-vbox-analysis/host-os-release.txt). |
| Processador físico e RAM do hospedeiro | AMD Ryzen 5 5500, 6 núcleos/12 threads, 15.857 MiB de RAM. | [`host-inventory.txt`](../results/demand-vbox-8cpu-20261014T104931Z-504345/host-inventory.txt), coletado no hospedeiro. |
| VirtualBox no hospedeiro | VirtualBox 7.2.20r175154. | [`host-inventory.txt`](../results/demand-vbox-8cpu-20261014T104931Z-504345/host-inventory.txt). |
| Sistema convidado | Ubuntu Server 22.04.5 LTS; kernel 5.15.0-198-generic nos inventários de 2–8 vCPUs. | [`inventory.txt` de 2 vCPUs](../results/vbox-2cpu-20261013T140512Z/inventory.txt) e inventários dos demais cenários. |
| vCPUs e RAM da VM | 1, 2, 4, 6 ou 8 vCPUs; 1.024 MiB atribuídos. | Captura de configuração de 1 vCPU, `nproc` na VM e inventários/arquivos de resultados. |
| Python na VM | 3.10.12 em 1–8 vCPUs. | `guest-inventory.txt` em cada bateria definitiva. |
| API | FastAPI 0.115.14, Uvicorn 0.34.3, Pydantic 2.11.7; oito workers. | [`requirements.txt`](../requirements.txt), inventários e registros de deploy. |
| Gerador externo | Locust 2.37.14 em Python 3.12.3, no hospedeiro, fixado à CPU lógica 0. | `config.txt` e `dependencies.txt` das repetições; roteiro de execução. |

**Tabela 2 — Infraestrutura registrada.** Os registros do convidado e do gerador estão separados para não atribuir à máquina física características observadas dentro da VM.

A criação da VM utilizou o VDI fornecido para a atividade, selecionado na interface do VirtualBox. As capturas registram 1 vCPU e 1.024 MiB para a VM de demonstração, além das regras NAT TCP `127.0.0.1:2222 → VM:22` (SSH) e `127.0.0.1:8000 → VM:8000` (API). As configurações de 2, 4, 6 e 8 vCPUs não possuem capturas individuais de tela no relatório; suas contagens constam nos inventários textuais e nos estados preservados por snapshots.

![1 vCPU e 1024 MiB definidos na criação da VM](../evidencias/configuracao-hardware.png)

**Figura 3 — Configuração da VM de 1 vCPU.** A interface mostra 1 processador e 1.024 MiB; trata-se da etapa de criação, complementada pela conferência dentro do sistema convidado na Figura 6.

![Seleção do VDI na criação da VM](../evidencias/escolhendo-vdi.png)

**Figura 4 — Disco da VM.** A captura mostra a seleção do VDI disponibilizado para a atividade; ela não comprova, isoladamente, que a VM já iniciou ou que os testes rodaram.

![Regras NAT para SSH e API](../evidencias/portas.png)

**Figura 5 — Encaminhamento de portas NAT.** As regras permitem acessar SSH pela porta 2222 e a API pela 8000 no loopback do hospedeiro; não expõem esses serviços para outras interfaces por essa configuração.

![Terminal da VM com usuário, hostname, nproc e free](../evidencias/manual-01-configuracao.png)

**Figura 6 — Conferência dentro da VM de 1 vCPU.** O prompt `osboxes@osboxes`, `nproc=1` e `free -m` registram a instância efetivamente iniciada. A captura foi feita após a bateria e mostra 26 MiB de swap ocupado naquele instante; a análise de swap **durante** os testes usa os arquivos `vmstat`, não essa imagem.

O código foi clonado por HTTPS na branch `cpu-bound`, para `/home/osboxes/atividade-2-git/cpu-bound`. O serviço foi iniciado em `0.0.0.0:8000`, com oito workers e sem access log. A reprodução dos gráficos e o estado final da VM constam no Apêndice A.
## 4. Metodologia experimental

A matriz definitiva cruzou cinco provisionamentos (1, 2, 4, 6 e 8 vCPUs) com cinco demandas (1, 2, 4, 8 e 16 usuários simultâneos). Cada combinação teve três repetições de 120 s, totalizando 75 execuções. Cada usuário do Locust enviou `POST /benchmark` com 10 MiB × 100 iterações de SHA-256, aguardou a resposta e repetiu sem espera adicional. A API permaneceu com oito workers Uvicorn e a VM com 1.024 MiB de RAM. Trata-se de carga fechada: quando a latência cresce, o próprio usuário virtual reduz a frequência de novas chamadas.

| Variável | Valor e controle |
| --- | --- |
| Provisionamento | 1, 2, 4, 6 e 8 vCPUs; 1.024 MiB de RAM em todos os cenários. |
| Demanda | 1, 2, 4, 8 e 16 usuários; três repetições por ponto. |
| Trabalho | `POST /benchmark`, 10 MiB × 100 iterações; oito workers. |
| Duração | 120 s por repetição, conforme configuração e log do Locust. |
| Medição | Locust e registro individual de respostas no hospedeiro; `monitor.py` e `vmstat` na VM, iniciados antes da carga. |
| Janelas de comparação | A partir do primeiro registro com todos os usuários ativos: 30 s de aquecimento; descartam-se também os 5 s finais do histórico. Restam 79–80 s efetivos em cada execução. |

**Tabela 3 — Parâmetros da matriz definitiva.** Fontes: manifestos e `config.txt` das cinco [baterias](../results/), conferidos pela [auditoria](../results/demand-vbox-analysis/auditoria.csv).

O [analisador](../scripts/demand_curve_analysis.py) usa a mesma janela por execução para CPU, RAM e respostas. A vazão é o número de respostas **bem-sucedidas concluídas** na janela dividido por sua duração; o total de requisições é o número de respostas concluídas nessa janela. A latência média e o p95 consideram somente respostas bem-sucedidas que começaram e terminaram dentro dela. Logo, o ponto p95 apresentado é a **mediana dos p95 das três repetições**, e não um p95 global nem a média de percentis. A CPU é `system_cpu_percent` do monitor, percentual agregado de toda a VM normalizado à capacidade provisionada (escala 0–100), e não a soma dos workers. A RAM representa a média de bytes usados na VM, convertida para MiB. O `vmstat` registra swap alocada e tráfego de entrada/saída durante a coleta inteira; sem timestamps por amostra nesse arquivo, esses valores são diagnósticos e não médias alinhadas à janela HTTP.

A [auditoria por execução](../results/demand-vbox-analysis/auditoria.csv) verificou manifesto, inventário de vCPUs/RAM, configuração, duração observada, contagens finais do Locust contra `requests.csv`, timestamps, arquivos obrigatórios, cobertura de monitoramento (mínimo de 95% dos segundos da janela), falhas, timeouts e swap. Arquivos ausentes ou vazios, parâmetros divergentes, duração insuficiente, contagens incoerentes ou monitor incompleto invalidariam uma execução; nenhum limiar de vazão, latência ou CPU foi usado para selecionar resultados. Todos os 75 ensaios da matriz passaram. Houve 40.722 respostas concluídas e zero falhas/timeouts nos testes completos de 120 s; na janela comparável, 26.967 respostas e zero falhas. A execução incompleta de 32 usuários em 1 vCPU foi preservada, marcada como **fora da matriz** e excluída. As campanhas anteriores de 32 usuários por 60 s também permanecem arquivadas, sem entrar nas tabelas ou gráficos abaixo.

As séries temporais usam apenas as linhas `Aggregated` do histórico real do Locust. Calcula-se as requisições por segundo(RPS) de cada intervalo observado de 5 s pela **diferença dos contadores cumulativos** nas duas extremidades; não há interpolação de limites ausentes. As três séries de uma mesma combinação são alinhadas por tempo decorrido e resumidas por mediana e amplitude mínimo–máximo. A linha vertical tracejada marca aproximadamente o fim do aquecimento inicial nos gráficos temporais; os limites exatos da janela analítica de cada repetição estão em [`repeticoes.csv`](../results/demand-vbox-analysis/repeticoes.csv).

## 5. Resultados e discussão

As tabelas [por repetição](../results/demand-vbox-analysis/repeticoes.csv) e [por combinação](../results/demand-vbox-analysis/resumo.csv) reproduzem todos os valores das figuras. Cada ponto dos gráficos de demanda é a mediana de três repetições. As figuras mostram somente as linhas centrais; os mínimos e máximos permanecem nas tabelas derivadas. Todas as métricas quantitativas desta seção se referem à matriz de 120 s, salvo indicação contrária.

### 5.1. Efeito da demanda sobre a vazão

![Vazão mediana e amplitude por demanda e provisionamento](figuras/cpu-bound/vazao-vs-demanda.png)

**Figura 7 — Vazão em função da demanda.** Eixo horizontal: usuários simultâneos; vertical: respostas bem-sucedidas por segundo na janela comparável. Cores identificam o mesmo provisionamento em todos os gráficos de demanda. Fonte: [`resumo.csv`](../results/demand-vbox-analysis/resumo.csv).

Com apenas um usuário, os cinco cenários ficaram entre 1,81 e 1,86 req/s. Esse perfil oferece, no máximo, uma solicitação em andamento por usuário e não ocupa todos os workers; portanto, mais vCPUs não elevaram materialmente a vazão nesse ponto. Em 1 vCPU, a mediana permaneceu entre 1,81 e 1,82 req/s de 1 a 16 usuários, enquanto o p95 aumentou fortemente. Em 8 vCPUs, a vazão passou de 1,86 req/s com 1 usuário a 12,49 req/s com 16. O patamar de 8 vCPUs ainda cresceu de 11,01 para 12,49 req/s entre 8 e 16 usuários.



| Usuários | 1 vCPU | 2 vCPUs | 4 vCPUs | 6 vCPUs | 8 vCPUs |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1,81 | 1,86 | 1,86 | 1,85 | 1,86 |
| 2 | 1,81 | 3,65 | 3,68 | 3,67 | 3,72 |
| 4 | 1,82 | 1,85 | 5,56 | 7,38 | 7,39 |
| 8 | 1,82 | 1,86 | 5,54 | 9,24 | 11,01 |
| 16 | 1,82 | 3,66 | 7,40 | 11,06 | 12,49 |

**Tabela 4 — Vazão mediana (req/s) nas janelas comparáveis.** Fonte: [`resumo.csv`](../results/demand-vbox-analysis/resumo.csv). Os valores são arredondados a duas casas.

Podemos verificar que apesar do aumento de vazão com o aumento de vCPUs para trabalhar, o acrescimo da vazão não é linear.

O cenário de 2 vCPUs não foi monotônico: 3,65 req/s com 2 usuários, cerca de 1,85 com 4 e 8, e 3,66 com 16. Em 4 usuários, as três repetições variaram de 1,85 a 3,66 req/s; em 16 usuários, de 1,86 a 3,67 req/s. A queda não foi descartada como anomalia: os arquivos passaram nos critérios de validade e a variação entre repetições está registrada em `resumo.csv`. CPU, latência e série temporal ajudam a descrevê-la, mas a instrumentação não permite determinar sua causa. Uma hipótese é a distribuição desigual de conexões persistentes entre os processos Uvicorn; o Locust usa `HttpUser`, e cada usuário pode reutilizar sua conexão. Essa hipótese não foi testada por telemetria de conexões por worker.

### 5.2. Efeito da demanda sobre a latência

![Latência p95 mediana das repetições por demanda](figuras/cpu-bound/latencia-p95-vs-demanda.png)

**Figura 8 — Latência p95 em função da demanda.** Cada ponto é a mediana dos p95 calculados separadamente nas três repetições; seus extremos estão em `resumo.csv`. A escala vertical é linear e está em milissegundos. Fonte: [`resumo.csv`](../results/demand-vbox-analysis/resumo.csv).

Em 1 vCPU, o p95 mediano cresceu de 559 ms com 1 usuário a 14.346 ms com 16, enquanto a vazão permaneceu quase constante. Essa combinação é compatível com espera crescente por capacidade de processamento. Em 8 vCPUs, o p95 permaneceu próximo de 540–546 ms até 4 usuários, chegou a 1.095 ms com 8 e a 2.812 ms com 16. A configuração de 6 vCPUs registrou 548 ms com 4 usuários, 1.619 ms com 8 e 2.723 ms com 16. O cenário de 2 vCPUs mostrou 2.169 ms com 4 usuários e 4.313 ms com 8, coerentes com a menor vazão desses pontos, mas sua variação entre repetições impede inferir um mecanismo único.

![Latência média por demanda e provisionamento](figuras/cpu-bound/latencia-media-vs-demanda.png)

**Figura 9 — Latência média em função da demanda.** A média é calculada dentro de cada repetição, e a figura apresenta a mediana entre repetições. A amplitude mínimo–máximo está em `resumo.csv`. Fonte: [`resumo.csv`](../results/demand-vbox-analysis/resumo.csv).

A latência média confirma a tendência, sem substituir a medida de cauda: com 16 usuários, as medianas foram 8.390 ms em 1 vCPU, 4.329 ms em 2, 2.157 ms em 4, 1.440 ms em 6 e 1.274 ms em 8. O p95 de 8 vCPUs com 16 usuários (2.812 ms) ficou ligeiramente acima do de 6 vCPUs (2.723 ms); três repetições e amplitudes sobrepostas não sustentam concluir que a configuração maior piorou a cauda de forma sistemática.

### 5.3. Comportamento temporal das requisições por segundo

![RPS temporal de 1 vCPU](figuras/cpu-bound/rps-temporal-1vcpu.png)

**Figura 10 — RPS temporal em 1 vCPU.** Cinco painéis representam os níveis de demanda, com a mesma escala vertical; linha = mediana de três repetições. A linha vertical tracejada indica aproximadamente o fim do aquecimento; mínimos e máximos estão no CSV. Fonte: [`rps-temporal-resumo.csv`](../results/demand-vbox-analysis/rps-temporal-resumo.csv).

![RPS temporal de 2 vCPUs](figuras/cpu-bound/rps-temporal-2vcpu.png)

**Figura 11 — RPS temporal em 2 vCPUs.** Mesma convenção da Figura 10. As diferenças entre repetições podem ser conferidas no CSV temporal.

![RPS temporal de 4 vCPUs](figuras/cpu-bound/rps-temporal-4vcpu.png)

**Figura 12 — RPS temporal em 4 vCPUs.** Mesma convenção, com intervalos observados de 5 s.

![RPS temporal de 6 vCPUs](figuras/cpu-bound/rps-temporal-6vcpu.png)

**Figura 13 — RPS temporal em 6 vCPUs.** Mesma convenção, alinhada ao primeiro registro de cada execução.

![RPS temporal de 8 vCPUs](figuras/cpu-bound/rps-temporal-8vcpu.png)

**Figura 14 — RPS temporal em 8 vCPUs.** Mesma convenção. A série termina no último intervalo completo presente no histórico; não há pontos fabricados até 120 s.

As curvas de 1 vCPU permanecem próximas de 1,8 req/s apesar do aumento de usuários, ao passo que 6 e 8 vCPUs sustentam níveis progressivamente maiores. Em 2 vCPUs, os mínimos e máximos registrados para 4 e 16 usuários diferem durante boa parte do ensaio, em vez de apenas em um instante isolado; essa dispersão permanece documentada no CSV temporal. O gráfico permite observar oscilações de 5 s, mas não prova sua origem. O aquecimento de 30 s foi aplicado de forma idêntica à análise principal; as séries completas o exibem para contextualizar o comportamento, sem misturá-lo às medianas das Figuras 7–9.

### 5.4. Utilização de CPU e possíveis pontos de saturação

![Utilização média de CPU da VM por demanda](figuras/cpu-bound/cpu-vs-demanda.png)

**Figura 15 — CPU total da VM em função da demanda.** Percentual agregado normalizado à capacidade de cada provisionamento, mediana das médias temporais por repetição; a linha de 95% é referência operacional de alta utilização. Fonte: [`resumo.csv`](../results/demand-vbox-analysis/resumo.csv).

Em 1 vCPU, a utilização já foi 99,8% com um usuário e ficou aproximadamente em 100% nos demais níveis. A vazão quase constante e o p95 crescente fornecem evidência conjunta de forte restrição de CPU em toda a faixa testada; o primeiro nível já está próximo do limite, de modo que não é possível localizar o limiar abaixo de um usuário. Em 4 e 6 vCPUs, o primeiro nível testado acima de 95% foi 16 usuários, com medianas próximas de 100%; entretanto, a vazão ainda cresceu entre 8 e 16 usuários. Há pressão de CPU e degradação da latência, mas não confirmação de um platô de vazão. Em 8 vCPUs, a CPU mediana chegou a 87,6% com 16 usuários: a matriz não demonstrou saturação por CPU nesse cenário, embora a latência tenha aumentado.

Em 2 vCPUs, a mediana de CPU foi 99,8% com 2 e 16 usuários, mas 51,1% com 4 e 43,2% com 8. O padrão acompanha a vazão não monotônica e varia também entre repetições; por isso, não permite identificar um ponto de saturação único. A linha de 95% não é prova isolada de saturação. O número de workers fixo, a carga fechada e a ausência de telemetria de filas e escalonamento do hospedeiro impedem uma explicação causal das oscilações.

### 5.5. Total de requisições atendidas

![Requisições concluídas por demanda](figuras/cpu-bound/requisicoes-totais-vs-demanda.png)

**Figura 16 — Requisições concluídas na janela comparável.** Cada ponto é a mediana das contagens de três repetições, em janelas de 79–80 s; não representa solicitações iniciadas. Fonte: [`resumo.csv`](../results/demand-vbox-analysis/resumo.csv).

A contagem complementa a vazão, pois usa as mesmas respostas concluídas e a mesma janela. Com 16 usuários, as medianas foram 144, 290, 585, 874 e 999 requisições, respectivamente para 1, 2, 4, 6 e 8 vCPUs. O total nas 75 janelas foi 26.967, sem falhas. As pequenas diferenças de duração entre 79 e 80 s justificam usar req/s para comparações de capacidade mais precisas; a figura de totais confirma a ordem de grandeza do atendimento efetivo.

### 5.6. Impacto do provisionamento

![Consumo médio de RAM da VM por demanda](figuras/cpu-bound/ram-vs-demanda.png)

**Figura 17 — RAM usada na VM em função da demanda.** Mediana da média temporal de cada repetição, em MiB; inclui sistema operacional, aplicação e caches. Fonte: [`resumo.csv`](../results/demand-vbox-analysis/resumo.csv).

A RAM mediana variou de aproximadamente 470 a 548 MiB entre os pontos, abaixo dos 1.024 MiB atribuídos. Isso não aponta esgotamento de memória física nos cenários de 2–8 vCPUs. O `vmstat` registrou, na VM separada de 1 vCPU, cerca de 194–206 MiB de swap alocada nas coletas, com até 9,3 MiB de entrada acumulada e nenhuma saída; em 2 vCPUs a swap alocada chegou a 524 KiB, e em 4–8 vCPUs foi zero. Como esse arquivo não tem timestamps por linha, tais números não podem ser atribuídos exclusivamente à janela de respostas.

![Speedup e eficiência relativa por demanda](figuras/cpu-bound/speedup-eficiencia-vs-demanda.png)

**Figura 18 — Ganho de vazão e eficiência relativa.** Speedup = mediana da vazão de `n` vCPUs / mediana de 1 vCPU no mesmo nível; eficiência = speedup/`n`. São quocientes descritivos, sujeitos à diferença de VM do cenário-base. Fonte: [`resumo.csv`](../results/demand-vbox-analysis/resumo.csv).

Com 16 usuários, a vazão passou de 1,82 req/s em 1 vCPU a 12,49 req/s em 8 vCPUs, ganho observado de **6,85×** para oito vezes o provisionamento e eficiência relativa de **85,6%**. Com um usuário, a vazão ficou quase igual e o ganho de provisionar mais CPUs foi pequeno. Portanto, o benefício dependeu da concorrência disponível; os ganhos não foram universalmente proporcionais aos recursos. A razão 6 vCPUs/1 vCPU em 16 usuários ficou ligeiramente acima de 6 (6,07×), diferença pequena e sujeita às condições distintas da VM de 1 vCPU, à dispersão e ao arredondamento; não é evidência suficiente de escalabilidade superlinear.

| vCPUs | Vazão com 16 usuários (req/s) | p95 mediano (ms) | CPU mediana (%) | Requisições medianas na janela | Speedup relativo a 1 vCPU |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1,82 | 14.346 | 100,0 | 144 | 1,00× |
| 2 | 3,66 | 6.025 | 100,0 | 290 | 2,01× |
| 4 | 7,40 | 2.751 | 100,0 | 585 | 4,06× |
| 6 | 11,06 | 2.723 | 99,9 | 874 | 6,07× |
| 8 | 12,49 | 2.812 | 87,6 | 999 | 6,85× |

**Tabela 5 — Comparação sob a maior demanda testada.** Todos os valores centrais são medianas de três repetições, exceto o speedup derivado delas. Fonte: [`resumo.csv`](../results/demand-vbox-analysis/resumo.csv).

### 5.7. Limitações e ameaças à validade

Os ensaios foram sequenciais e não randomizados. Não se mediram temperatura, frequência efetiva, competição por núcleos físicos, filas da API ou utilização detalhada do gerador durante cada execução.

Oito workers foram mantidos em todos os cenários para controlar a configuração do servidor, mas podem impor custos diferentes em 1 e 8 vCPUs. O teste usa SHA-256 de dados determinísticos residentes em memória e não representa uma mistura de operações reais. Três repetições mostram variação observada, sem justificar intervalos de confiança estreitos ou inferências causais. A carga fechada do Locust não mede uma taxa de chegada externa independente. O histórico temporal periódico termina antes dos 120 s completos; o arquivo individual de respostas e o log final sustentam as contagens da execução inteira, enquanto os gráficos usam apenas intervalos completos observados. Falhas HTTP e timeouts foram zero, mas isso não prova ausência de espera ou reserva de capacidade.

## 6. Conclusão

A demanda elevou a pressão de CPU de forma dependente do provisionamento. Em 1 vCPU, a CPU já chegou a 99,8% com um usuário; a vazão permaneceu perto de 1,8 req/s até 16 usuários, enquanto o p95 subiu de 559 para 14.346 ms. Essa combinação é o sinal mais forte de restrição de processamento na matriz. Em 4 e 6 vCPUs, 16 usuários levaram a CPU a aproximadamente 100% e elevaram a latência, mas a vazão ainda cresceu em relação a 8 usuários, de modo que um patamar de capacidade não foi demonstrado. Em 8 vCPUs, a CPU mediana máxima foi 87,6%; não se observou saturação de CPU até 16 usuários, embora a latência p95 tenha aumentado de cerca de 546 ms com 4 usuários para 2.812 ms com 16.

O aumento de vCPUs melhorou a capacidade sob demanda suficiente: com 16 usuários, a vazão mediana cresceu de 1,82 para 12,49 req/s entre 1 e 8 vCPUs, e a latência média caiu de 8.390 para 1.274 ms. O ganho de 6,85× para oito vezes o provisionamento ficou abaixo da proporcionalidade ideal. Com um usuário, mais vCPUs praticamente não alteraram a vazão. O cenário de 2 vCPUs apresentou queda e dispersão não monotônicas em demandas intermediárias; as execuções são válidas e foram mantidas, mas a causa não foi identificada. Os 75 ensaios registraram 40.722 respostas concluídas, nenhuma falha e nenhum timeout no teste completo; 26.967 dessas respostas pertencem às janelas comuns de análise.

As conclusões são descritivas deste ambiente virtualizado e deste benchmark. O uso de outra VM para 1 vCPU, a ordem fixa de execução, a pequena quantidade de repetições e a ausência de medição de filas e do hospedeiro durante a carga limitam a precisão de limiares de saturação e a atribuição causal dos ganhos. Os dados brutos, a [auditoria](../results/demand-vbox-analysis/auditoria.csv), as tabelas derivadas e o [script de reprodução](../scripts/build_demand_report.py) permitem revisar todos os números.

## Apêndice A — Execução manual histórica e evidências visuais

### A.1. Criar a VM, habilitar SSH e verificar recursos

No VirtualBox, crie uma VM Ubuntu Server 22.04 usando o VDI da atividade, 1 vCPU, 1.024 MiB de RAM e adaptador NAT. Configure no redirecionamento de portas as regras TCP `127.0.0.1:2222 → 22` e `127.0.0.1:8000 → 8000`, como nas Figuras 3–5.

Caso o serviço SSH não esteja instalado, execute **no console da VM**:

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
sudo systemctl status ssh
```

No **hospedeiro**, confira a configuração e entre na VM:

```bash
ssh -p 2222 osboxes@127.0.0.1
```

Ao usar outra VM com o mesmo redirecionamento de porta `2222`, a chave SSH apresentada ao hospedeiro muda. Confirme que a VM desejada está ligada e, se aparecer o aviso de chave antiga, remova apenas a entrada desse destino com `ssh-keygen -R '[127.0.0.1]:2222'` antes de conectar novamente. Esse aviso é esperado ao alternar entre VMs distintas; não identifica, por si só, uma falha do Ubuntu.

### A.2. Clonar a branch correta dentro da VM e validar a instalação

O repositório foi clonado **dentro da VM** por HTTPS; não é necessária chave SSH do GitHub para essa etapa:

```bash
git clone --branch cpu-bound --single-branch \
  https://github.com/POI-2026-2-grupo15/atividade-2.git atividade-2-git
cd atividade-2-git
git branch --show-current
git rev-parse --short HEAD
cd cpu-bound
sudo apt update
sudo apt install -y python3.10-venv
python3 -m venv --clear .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r requirements-analysis.txt
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
```

O pacote `python3.10-venv` é necessário na imagem Ubuntu 22.04 usada na validação. A opção `--clear` recria uma `.venv` que tenha ficado incompleta após a falha de `ensurepip`; use-a apenas nessa pasta de trabalho, sem afetar os CSVs de resultados. A suíte completa também contém testes de análise que importam `pandas` e `matplotlib`, por isso instala-se `requirements-analysis.txt` antes de executar `pytest`.

### A.3. Iniciar a API e conferir as respostas

Em **um terminal da VM**, inicie o Uvicorn com o mesmo número de workers em todos os cenários. Use uma pasta de saída nova; se a porta 8000 já estiver ocupada, verifique a instância existente antes de tentar iniciar outra:

```bash
cd ~/atividade-2-git/cpu-bound
mkdir results/NOVA-EXECUCAO-1CPU
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 \
  --port 8000 --workers 8 --no-access-log \
  > results/NOVA-EXECUCAO-1CPU/api.log 2>&1 &
APP_PID=$!
printf '%s\n' "$APP_PID" > results/NOVA-EXECUCAO-1CPU/api.pid
for tentativa in $(seq 1 20); do
  test -s results/NOVA-EXECUCAO-1CPU/api.log && break
  sleep 1
done
tail -n 12 results/NOVA-EXECUCAO-1CPU/api.log
ps -p "$APP_PID" -o pid,stat,args
grep -c 'Started server process' results/NOVA-EXECUCAO-1CPU/api.log
ps --ppid "$APP_PID" -o pid,stat,args
```

O Uvicorn é iniciado em segundo plano; a espera evita consultar `api.log` antes de o processo criar o arquivo. Se `tail` ainda falhar, confira o estado do PID e a existência da pasta antes de iniciar outra instância. Em um log novo, `grep -c` deve retornar **8** linhas de inicialização de workers; a lista de filhos do mestre permite conferir se eles continuam ativos (ela também pode incluir um processo auxiliar do Python). O PID salvo identifica o processo mestre usado pelo monitor. Na execução documentada, `api.log` e `api.pid` ficaram em `results/vbox-1cpu-20261013T2036Z/`. Em **outro terminal no hospedeiro**, com `jq` instalado, consulte a API pela porta redirecionada:

```bash
curl --silent --show-error http://127.0.0.1:8000/health | jq .
curl --silent --show-error -H 'Content-Type: application/json' \
  -d '{"data_size_mb":10,"iterations":100}' \
  http://127.0.0.1:8000/benchmark | jq .
```

A Figura 2 mostra as saídas reais: `status: ok` confirma o acesso HTTP; `algorithm: sha256`, `data_size_mb`, `iterations`, `total_processed_mb` e `digest` identificam o trabalho executado. `preparation_time_ms` e `execution_time_ms` são tempos internos da API. A latência observada pelo Locust inclui também transporte e espera sob concorrência. Para os prints, priorize a resposta formatada, não comandos de instalação sem saída relevante.

### A.4. Executando carga de maneira manual

O **hospedeiro** gera a carga; a **VM** hospeda a API, `monitor.py` e `vmstat`. Antes da primeira repetição de um cenário, o aquecimento documentado foi:

```bash
seq 32 | xargs -P 8 -I{} curl --silent --show-error --max-time 120 \
  -o /dev/null -w '%{http_code}\n' \
  -H 'Content-Type: application/json' \
  -d '{"data_size_mb":10,"iterations":100}' \
  http://127.0.0.1:8000/benchmark | sort | uniq -c
```

Foram obtidas 32 respostas HTTP 200 na VM de 1 vCPU. Para **cada repetição**, inicie primeiro o monitor **na VM**; o exemplo usa `rep1`:

```bash
cd ~/atividade-2-git/cpu-bound
APP_PID=$(cat results/NOVA-EXECUCAO-1CPU/api.pid)
.venv/bin/python scripts/monitor.py --pid "$APP_PID" --interval 1 \
  --output results/NOVA-EXECUCAO-1CPU/rep1-monitor.csv &
MONITOR_PID=$!
vmstat -n 1 600 > results/NOVA-EXECUCAO-1CPU/rep1-vmstat.txt &
VMSTAT_PID=$!
```

No **hospedeiro**, use o projeto no mesmo commit e um ambiente Python que contenha Locust. Se ainda não houver clone local, prepare uma pasta nova:

```bash
git clone --branch cpu-bound --single-branch \
  https://github.com/POI-2026-2-grupo15/atividade-2.git atividade-2-local
cd atividade-2-local/cpu-bound
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Depois, ainda **no hospedeiro**, execute a carga de 60 s:

```bash
source .venv/bin/activate
USERS=32 SPAWN_RATE=32 DURATION=60s DATA_SIZE_MB=10 ITERATIONS=100 \
  WAIT_SECONDS=0 HOST=http://127.0.0.1:8000 \
  OUTPUT_DIR=results/NOVA-EXECUCAO-1CPU/rep1 \
  taskset -c 0 bash scripts/run_load_test.sh
```

Somente **depois** de o Locust terminar, pare a coleta **na VM**:

```bash
kill -TERM "$MONITOR_PID" "$VMSTAT_PID"
```

Repita o ciclo monitor → Locust → encerramento do monitor para `rep2` e `rep3`, trocando os nomes dos arquivos e diretórios. Não reaproveite `OUTPUT_DIR`. O script grava `config.txt`, `dependencies.txt`, `locust.log` e CSVs detalhados em cada pasta `repN`; os arquivos `repN-monitor.csv` e `repN-vmstat.txt` ficam na pasta do cenário. O monitor deve cobrir toda a janela do Locust — quatro execuções históricas não satisfizeram esse critério e foram excluídas do resumo daquela campanha, preservado separadamente.

Durante uma rodada **extra de demonstração**, com os mesmos parâmetros e fora das três repetições históricas resumidas na Tabela A1, foram capturadas as Figuras A1–A3. Ela está em [`results/print-live-1cpu`](../results/print-live-1cpu/) e serve apenas de evidência visual. Para reproduzir essa demonstração, abra `top -o %CPU` **na VM** e rode **no hospedeiro** em uma pasta nova:

```bash
mkdir results/NOVA-CAPTURA-1CPU
DATA_SIZE_MB=10 ITERATIONS=100 WAIT_SECONDS=0 \
taskset -c 0 .venv/bin/python -m locust \
  -f load_tests/locustfile.py --headless \
  --host http://127.0.0.1:8000 \
  --users 32 --spawn-rate 32 --run-time 60s \
  --csv results/NOVA-CAPTURA-1CPU/locust \
  --csv-full-history \
  2>&1 | tee results/NOVA-CAPTURA-1CPU/locust.log
```

![Processos Python no top da VM durante a rodada visual extra](../evidencias/manual-03-top-carga.png)

**Figura A1 — `top` na VM durante a carga visual extra.** `PID` identifica os processos; `USER=osboxes` e `COMMAND=python` permitem reconhecê-los; `RES` e `%MEM` indicam memória residente; `%CPU` é a utilização instantânea de cada processo e `TIME+` o tempo de CPU acumulado. Os três processos próximos de 31,1% e outro de 5,0% somam aproximadamente 98% de **uma** vCPU naquele instante. As médias da campanha histórica vêm dos CSVs, não desse print.

![Tabela do Locust durante a rodada visual extra](../evidencias/manual-04-locust-carga.png)

**Figura A2 — Locust durante a rodada visual extra.** `POST /benchmark` é o endpoint sob carga; `# reqs` passou de 98 a 102 nas linhas capturadas e `# fails` permaneceu em zero. `Avg`, `Min`, `Max` e `Med` são tempos HTTP em ms; `req/s` é a taxa estimada. Os 32 usuários virtuais vêm do comando, enquanto `iterations=100` significa cem hashes por **requisição**, não cem requisições.

![Percentis Locust da rodada visual extra](../evidencias/manual-05-locust-p95.png)

**Figura A3 — Percentis aproximados da rodada visual extra.** Com 106 requisições no momento da captura, o Locust mostrou mediana de cerca de 21.000 ms, p95 de 24.000 ms e p99 de 25.000 ms. Esses números arredondados **não** entram na matriz definitiva de 75 execuções.

### A.5. Conferir e transferir os dados sem misturar execuções

A Figura A4 registra a pasta real `results/vbox-1cpu-20261013T2036Z` **dentro da VM**. A listagem mostra as três pastas Locust e os arquivos `repN-monitor.csv`/`repN-vmstat.txt`; `rep1` contém configuração, dependências, log final e CSVs. Assim, os resultados podem ser auditados sem depender dos prints de terminal. O monitor de 1 vCPU cobriu 59, 60 e 60 amostras das janelas reais de `rep1`, `rep2` e `rep3` dessa campanha.

| Repetição de 1 vCPU | Requisições | Falhas | Vazão (req/s) | Latência média (ms) | p95 (ms) | CPU média (%) | Pico de RAM (MiB) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 108 | 0 | 1,82 | 13.869 | 33.000 | 99,1 | 646,6 |
| 2 | 108 | 0 | 1,81 | 14.945 | 23.000 | 98,6 | 648,0 |
| 3 | 105 | 0 | 1,76 | 14.162 | 35.000 | 100,0 | 647,9 |

**Tabela A1 — Bateria manual histórica registrada na VM de 1 vCPU.** As três repetições somaram 321 requisições sem falha. Esses valores pertencem à campanha de 32 usuários por 60 s e não entram nas tabelas ou gráficos da Seção 5; CPU e RAM derivam das janelas efetivas daquela carga. Fonte: [`repeticoes.csv`](../results/virtualbox-graficos/repeticoes.csv).

Para mostrar a organização dos arquivos em um terminal da **VM**, como na captura abaixo:

```bash
cd ~/atividade-2-git/cpu-bound
ls -lh results/vbox-1cpu-20261013T2036Z
ls -lh results/vbox-1cpu-20261013T2036Z/rep1
```

![Listagem dos resultados brutos da VM de 1 vCPU](../evidencias/manual-06-resultados-vm.png)

**Figura A4 — Presença dos dados brutos na VM.** O prompt `osboxes@osboxes` identifica o convidado. A captura demonstra arquivos, não a execução de uma transferência naquele momento.

Na execução documentada, a API, os arquivos do monitor e o `vmstat` foram gerados na VM; os diretórios Locust `rep1`–`rep3` foram gerados no hospedeiro. Para reunir tudo **na VM**, copie os diretórios Locust do hospedeiro por SSH (escolha uma pasta de cenário existente, sem sobrepor outra medição):

```bash
scp -O -P 2222 -r results/NOVA-EXECUCAO-1CPU/rep1 \
  results/NOVA-EXECUCAO-1CPU/rep2 \
  results/NOVA-EXECUCAO-1CPU/rep3 \
  osboxes@127.0.0.1:/home/osboxes/atividade-2-git/cpu-bound/results/NOVA-EXECUCAO-1CPU/
```

Para trazer **a cópia completa já existente** da VM ao hospedeiro, o procedimento seria executado **no hospedeiro**, dentro da pasta `cpu-bound`:

```bash
mkdir results/importacao-vm-1cpu
scp -O -P 2222 -r \
  osboxes@127.0.0.1:/home/osboxes/atividade-2-git/cpu-bound/results/vbox-1cpu-20261013T2036Z \
  results/importacao-vm-1cpu/
ls -lh results/importacao-vm-1cpu/vbox-1cpu-20261013T2036Z
```

`-r` copia recursivamente e `-O` força o protocolo SCP caso o SFTP não esteja disponível. Use uma pasta de destino **nova** em uma repetição futura. A instrução explica a procedência das cópias; nenhuma transferência adicional foi realizada para este relatório.

## Apêndice B — Execução automatizada da matriz definitiva

A matriz analisada neste relatório foi conduzida pelo orquestrador [`run_demand_curve.py`](../scripts/run_demand_curve.py), com Locust no hospedeiro e `monitor.py`/`vmstat` na VM. A Figura B1 mostra o fluxo; a Figura B3 mostra onde os dados ficam. **Esses dois esquemas são explicativos, não capturas de tela da execução.** O Apêndice A conserva as capturas autênticas da execução manual histórica.

![Fluxo da execução automatizada e da análise](figuras/cpu-bound/apendice-fluxo-execucao.png)

**Figura B1 — Fluxo da bateria automatizada.** Os cinco cenários foram executados sequencialmente, cada um com 15 execuções (cinco demandas × três repetições); a análise posterior lê os CSVs preservados. Fonte: scripts e diretórios citados neste apêndice.

### B.1. Preparar e executar um cenário

No **hospedeiro**, prepare o ambiente para executar o Locust e o orquestrador. Os pacotes de análise também permitem rodar a suíte completa de testes:

```bash
cd /caminho/para/atividade-2/cpu-bound
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r requirements-analysis.txt
.venv/bin/python -m pip check
```

Com a VM do cenário e a API ligadas, confira no **hospedeiro** o acesso SSH e o endpoint de saúde. O orquestrador confere estado, vCPUs, RAM, acesso ao projeto na VM e processo Uvicorn configurado com oito workers antes de criar os resultados. As capturas das Figuras 2–6 ilustram a preparação e conferência de serviços na VM de 1 vCPU.

```bash
ssh -p 2222 osboxes@127.0.0.1
curl -fsS http://127.0.0.1:8000/health
```

Para conferir uma VM recém-criada de 1 vCPU, execute primeiro o **smoke test** na pasta `cpu-bound` do hospedeiro:

```bash
export CPU_BOUND_VM_NAME="Nome_Que_Voce_Criou_A_VM"
export CPU_BOUND_REMOTE_PROJECT="/home/osboxes/atividade-2-git/cpu-bound"
.venv/bin/python scripts/run_demand_curve.py --vcpus 1 --smoke
```

![Terminal do hospedeiro ao concluir o smoke test automatizado](../evidencias/bateria_teste_smoke.png)

**Figura B2 — Smoke test automatizado.** A captura registra um usuário, oito segundos, 4.103 respostas e zero falhas na VM de validação. Esse teste usa 1 MiB × 1 iteração e não integra a matriz definitiva.

Substitua `Nome_Que_Voce_Criou_A_VM` pelo nome exato exibido no VirtualBox e ajuste `CPU_BOUND_REMOTE_PROJECT` se o clone do repositório estiver em outro caminho **dentro da VM**. Defina essas variáveis no terminal do **hospedeiro**, onde o script é executado. Sem elas, `--vcpus 1` seleciona a VM experimental `cpu_Bound`; as opções `--vm-name` e `--remote-project` têm prioridade sobre o ambiente.

Para executar uma **nova bateria completa** no mesmo cenário, retire `--smoke`:

```bash
.venv/bin/python scripts/run_demand_curve.py --vcpus 1
```

Esse comando produz 15 execuções de 120 s (cinco demandas × três repetições). Não o execute apenas para conferir o apêndice, pois as 75 execuções definitivas já estão preservadas. Para reproduzir outro provisionamento, desligue a VM, ajuste as vCPUs e confirme o estado correto antes de executar o comando com o novo valor de `--vcpus`.

Os parâmetros padrão do script são cinco demandas (1, 2, 4, 8 e 16 usuários), três repetições de 120 s para cada demanda, payload de 10 MiB × 100 iterações, rampa de 32 usuários/s e gerador fixado à CPU lógica 0 do hospedeiro. A API permanece com oito workers e 1.024 MiB de RAM.

A opção `--smoke` produz uma medição curta em pasta separada, fora da matriz. O script confirma os pré-requisitos, cria um diretório inédito, executa as repetições **em série** e copia os arquivos de monitoramento da VM. Ele recusa sobrescrever resultados anteriores.

### B.2. Localizar e conferir os dados

| vCPUs | Diretório da bateria definitiva | Execuções válidas |
| ---: | --- | ---: |
| 1 | [`demand-vbox-1cpu-20261014T081757Z-421203`](../results/demand-vbox-1cpu-20261014T081757Z-421203/) | 15 |
| 2 | [`demand-vbox-2cpu-20261014T085949Z-444834`](../results/demand-vbox-2cpu-20261014T085949Z-444834/) | 15 |
| 4 | [`demand-vbox-4cpu-20261014T094305Z-463098`](../results/demand-vbox-4cpu-20261014T094305Z-463098/) | 15 |
| 6 | [`demand-vbox-6cpu-20261014T101658Z-490172`](../results/demand-vbox-6cpu-20261014T101658Z-490172/) | 15 |
| 8 | [`demand-vbox-8cpu-20261014T104931Z-504345`](../results/demand-vbox-8cpu-20261014T104931Z-504345/) | 15 |

**Tabela B1 — Fontes da matriz de 75 execuções.** O smoke test e os ensaios manuais de 32 usuários estão em pastas distintas e não integram essa análise.

![Organização dos arquivos de uma bateria automatizada](figuras/cpu-bound/apendice-organizacao-dados.png)

**Figura B3 — Organização dos dados brutos.** Cada bateria reúne cinco pastas de demanda `uN`, cada uma com três pastas `repN`. `requests.csv` registra respostas individuais, `locust_stats_history.csv` contém os contadores periódicos, e `monitor.csv` e `vmstat.txt` contêm medições da VM. O `manifest.json` e os arquivos `config.txt` documentam parâmetros e procedência.

Os arquivos originais permanecem em `results/`. Para conferir uma execução sem iniciar carga nova, no hospedeiro execute:

```bash
ls -lh results/demand-vbox-8cpu-20261014T104931Z-504345
ls -lh results/demand-vbox-8cpu-20261014T104931Z-504345/u16/rep3
```

### B.3. Auditar e regenerar os gráficos

O script lê os CSVs preservados e recusa sobrescrever a saída existente. Para produzir uma cópia independente da análise, use nomes de destino novos:

```bash
.venv/bin/python scripts/build_demand_report.py \
  --case results/demand-vbox-1cpu-20261014T081757Z-421203 \
  --case results/demand-vbox-2cpu-20261014T085949Z-444834 \
  --case results/demand-vbox-4cpu-20261014T094305Z-463098 \
  --case results/demand-vbox-6cpu-20261014T101658Z-490172 \
  --case results/demand-vbox-8cpu-20261014T104931Z-504345 \
  --output results/demand-vbox-analysis-verificacao \
  --figures docs/figuras/cpu-bound-verificacao
```

A [auditoria](../results/demand-vbox-analysis/auditoria.csv) registra a validade dos ensaios. [`repeticoes.csv`](../results/demand-vbox-analysis/repeticoes.csv) guarda as métricas por execução; [`resumo.csv`](../results/demand-vbox-analysis/resumo.csv) resume as 25 combinações. As taxas temporais derivadas estão em [`rps-temporal-repeticoes.csv`](../results/demand-vbox-analysis/rps-temporal-repeticoes.csv) e [`rps-temporal-resumo.csv`](../results/demand-vbox-analysis/rps-temporal-resumo.csv). Os gráficos da Seção 5 são reproduzíveis a partir desses arquivos e dos CSVs brutos das baterias da Tabela B1.
