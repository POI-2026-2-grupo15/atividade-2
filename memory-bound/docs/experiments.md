# Protocolo dos experimentos Docker

Configuração oficial: [experiments/protocol.json](../experiments/protocol.json).
O executor lê esse arquivo; overrides da CLI ficam registrados em cada coleta.

| Parâmetro | Valor |
|---|---|
| RAM | 500, 1024, 2048 e 4096 MiB |
| Demanda | 1, 2, 4 e 8 usuários Locust |
| Repetições | 3 por combinação: 48 execuções |
| CPU / workers | 6 / 6 em todas as configurações |
| Dataset | `datasets/grande`, mesmos arquivos, ordem e hashes |
| Swap | Desabilitado: `--memory-swap` igual a `--memory` |
| Aquecimento | 10 segundos após todos os usuários terem sido iniciados |
| Medição | Janela fixa de 60 segundos após o aquecimento |
| Monitoramento | A cada 0,5 segundo, container e árvore Locust no Mac |
| Intervalo | 5 segundos entre containers; fora da aplicação |
| Timeout HTTP | 30 segundos conforme cliente Requests/Locust |
| Espera entre requisições | Zero; cada usuário aguarda sua resposta |

RAM e CPU são limites do container; a CPU é uma quota compartilhada, sem
reserva de núcleos físicos. Locust fica no hospedeiro. Manter os recursos do
Docker Desktop, alimentação e demais cargas do Mac constantes e registrados.
Registrar qualquer interferência observada; não descartar resultados ruins.

## Ordem e execução

Cada uma das três rodadas cobre as 16 combinações. O executor rotaciona as
ordens de demanda e RAM; inverte a ordem de RAM na segunda rodada. Assim, RAM
é intercalada entre coletas, em vez de concluir todos os testes de uma RAM
antes das demais. A ordem é determinística e salva em `plan.json`.

Na raiz do repositório, conferir o plano sem executar carga:

```bash
memory-bound/.venv/bin/python memory-bound/scripts/docker_experiment.py --plan
```

Preparar e executar a matriz, quando autorizada:

```bash
docker build -t memory-bound:experiment memory-bound
memory-bound/.venv/bin/python memory-bound/scripts/docker_experiment.py
```

São 48 minutos de medição, 8 minutos de aquecimento e aproximadamente 4 minutos
de pausas, além de inicialização, rampa e validação de cada container.
A duração efetiva deve ser registrada; não confundir tempo total com janela útil.

Cada ponto usa um container novo, porta dinâmica em loopback e diretório
exclusivo. Uma requisição mínima valida o contrato; o dataset grande é usado
no aquecimento e na medição, inclusive nos cenários com falhas de memória.
O monitor inicia antes da carga. Ao fim da janela, Locust encerra os usuários,
o executor coleta evidências e remove somente o container criado naquele ponto.

## Definição das métricas

`load/measurement.json` é a fonte das métricas da janela. Os CSVs nativos do
Locust incluem rampa/aquecimento e servem para diagnóstico, não para comparação
direta da matriz. A janela começa depois de todos os usuários estarem ativos;
um watchdog separado identifica execuções interrompidas/incompletas. Dez
segundos de aquecimento não garantem estado estacionário: interpretar também
o histórico temporal e registrar mudanças de comportamento durante a janela.

- Vazão de sucesso: respostas válidas concluídas na janela / 60 segundos.
- Vazão total e falhas: todas as respostas concluídas na mesma janela.
- Uma resposta iniciada no aquecimento e concluída na medição contribui para
  vazão, mas é identificada como `carryover_completed` e excluída da latência.
- Latência média e p95 principais (`mean_ms`, `p95_ms`): somente respostas
  válidas iniciadas e concluídas dentro da janela. `all_*` inclui também falhas.
  O p95 usa a posição superior de 95% da lista ordenada (nearest rank).
- `in_flight_at_end`: requisições iniciadas na janela e ainda sem resposta ao
  fim dela. São censuradas pela janela, não tratadas como sucesso nem falha.
  Interpretar latência junto com esse número: omitir pendentes favoreceria
  artificialmente cenários com esperas longas. Sem sucessos, latência fica nula.
- CPU: diferença do contador cgroup entre amostras dentro da janela, dividida
  pelo intervalo real e pela quota de seis CPUs. As bordas sem amostra ficam
  explícitas; não inventar precisão para instantes não amostrados.
- Memória: máximo amostrado de `memory.current` na janela. Inclui processos e
  cache contabilizados no cgroup. RSS somado é auxiliar e pode contar páginas
  compartilhadas. O `memory.peak` bruto pode incluir aquecimento.
- Campos `system_*` e RAM/swap do psutil descrevem a VM interna do Docker
  Desktop; não são o consumo/limite de memória do container.
- CPU da árvore Locust usa escala de 100% por núcleo. Registrar sua coleta
  para detectar possível interferência do gerador.
- OOM: estado do container e `memory.events` final abrangem todo o ponto,
  inclusive aquecimento. `sampled_oom_kill_delta` cobre apenas o intervalo
  entre as amostras disponíveis na janela; não confundir com o total do ponto.
- `resource_window_covered`, lacunas de borda e maior lacuna entre amostras
  indicam cobertura. Sem monitor, valores ficam nulos, nunca zero fabricado.

Três repetições permitem apresentar média, desvio padrão e pontos individuais
por combinação. Não combinar todas as requisições como se fossem repetições
independentes. Não afirmar significância estatística com três medidas.

## Falhas, preservação e reprodução

OOM e respostas HTTP inválidas são resultados experimentais. O executor
continua os demais pontos, registrando `completed_with_oom` ou
`resource_failure_before_window` quando aplicável. Um ponto sem janela não
possui latência/vazão comparável: registrar a ausência, sem inventar números.
Erros de infraestrutura sem evidência OOM interrompem a matriz e ficam em
`error.json`. Janelas incompletas ficam identificadas e produzem status não zero.

Cada execução salva configuração, manifesto, ID da imagem, ambiente Docker,
versão/estado Git, snapshot dos fontes, dependências do gerador, resposta de
validação, dependências do servidor quando acessível, janela, requisições
individuais, CSVs dos monitores, logs,
`docker inspect` e resumo. Resultados ficam em `results/docker-matrix-<UTC>/`,
ignorados pelo Git; incluir os selecionados deliberadamente na entrega.
Preservar também datasets e imagem identificada nos metadados.

Aumentar RAM pode não elevar a vazão: CPU por worker, GIL, upload e arquivos
temporários continuam participando. O protocolo controla recursos, não garante
que a aplicação tenha exclusivamente gargalo de memória.

## Validação do executor

Uma verificação curta, separada dos resultados finais:

```bash
memory-bound/.venv/bin/python memory-bound/scripts/docker_experiment.py \
  --label validation --rams 500 4096 --users 1 --repetitions 1 \
  --warmup 2 --duration 3 --pause 0 --dataset memory-bound/datasets/pequeno
```

Os limites de 500 MiB e 4 GiB foram conferidos dessa forma. A matriz completa
permanece pendente. Os testes automatizados também verificam isolamento da
janela, aquecimento, censura de pendentes, ausência de métricas e plano de 48
execuções. Pilotos anteriores foram preservados como histórico, com metodologia
própria, e não devem ser misturados à matriz final.

Validação concluída em 14/10/2026:

- 16 testes automatizados aprovados.
- Dois containers com dataset pequeno (500 e 4096 MiB): janela completa,
  zero falhas, limites reais preservados, monitores com cobertura e limpeza.
- Container de 64 MiB: OOM antes da janela registrado, seguido de execução
  normal em 4096 MiB. Demonstra continuação após falta de recursos.
- Dataset grande com 500 MiB e oito usuários: falta de memória durante a carga
  registrada como `completed_with_oom`; janela completa, falhas/pendentes
  preservados, vazão de sucesso zero e latências de sucesso nulas.
- As verificações usaram janelas de três segundos e não pertencem à matriz.

Artefatos da versão final:

- [Validação dos dois limites](../results/docker-validation-final-20261014T161024054645Z/summary.json).
- [OOM antes da janela e continuação](../results/docker-validation-oom-20261014T160520910287Z/summary.json).
- [OOM durante a carga real](../results/docker-validation-load-oom-20261014T161128426722Z/summary.json).
- [Integração local](../results/local-validation-txkwx85t/).
