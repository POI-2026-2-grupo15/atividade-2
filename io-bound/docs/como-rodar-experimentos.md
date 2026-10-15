# Como rodar experimentos com `experiment.sh`

O script `scripts/experiment.sh` roda uma **sessão** completa com um comando:

1. sobe a API em um container Docker com os limites de CPU e RAM de cada cenário;
2. gera carga com o Locust a partir de **outro container**, em cada nível de demanda;
3. coleta CPU, RAM, iowait e disco durante a carga;
4. monta a tabela e os gráficos da sessão.

## Pré-requisitos

- Docker Desktop instalado e **aberto**.
- Terminal na pasta `io-bound`:

  ```bash
  cd ~/Documents/poi/atividade-2/io-bound
  ```

Na primeira execução, o Docker constrói a imagem, o que demora alguns minutos e
precisa de internet. Depois disso, o script funciona offline. Não é preciso ter
Python instalado no computador: tudo roda dentro dos containers.

## Uso básico

```bash
bash scripts/experiment.sh          # valores padrão (~1,5 min)
bash scripts/experiment.sh -h       # mostra todas as opções
```

| Opção | Para que serve | Padrão |
|---|---|---|
| `-c`, `--cenarios` | cenários no formato `nome:cpus:ram`, separados por espaço | `vcpu1-ram1g:1:1g vcpu2-ram1g:2:1g` |
| `-u`, `--usuarios` | quantidades de usuários simultâneos (níveis de demanda) | `1 4 16` |
| `-d`, `--duracao` | tempo de carga em cada nível | `10s` |
| `-p`, `--pausa` | pausa entre níveis, em segundos | `2` |
| `-k`, `--tamanho` | KiB gravados e lidos por requisição (1 a 16384) | `1024` |
| `-f`, `--sem-fsync` | desliga o `fsync` (as escritas ficam na memória) | ligado |
| `-n`, `--nome` | nome da sessão (pasta em `results/`) | `sessao-<data-hora>` |

No cenário `vcpu2-ram1g:2:1g`, o `vcpu2-ram1g` é o nome que aparece nos gráficos,
`2` é o número de CPUs (aceita fração, como `0.5`) e `1g` é a RAM (`512m`, `1g`,
`2g`…).

### Quanto tempo leva

Aproximadamente: **cenários × níveis × (duração + pausa) + ~10 s por cenário**.

Por exemplo, 4 cenários × 7 níveis × (30 s + 5 s) ≈ 17 minutos.

## O que é gerado

```text
results/<nome>/
├── sessao.txt          parâmetros usados
├── execucao.log        log completo (consulte se algo falhar)
├── scenarios.txt       CPU/RAM de cada cenário
├── <cenário>/
│   ├── monitor.csv     CPU, RAM, iowait e disco, 1 amostra/s
│   └── u<N>/           resultados do Locust com N usuários
└── plots/
    ├── summary.csv     tabela consolidada
    ├── requests_per_s.png   vazão
    ├── median_ms.png        latência mediana
    ├── p95_ms.png           latência p95
    ├── app_cpu_percent.png  CPU do processo da API
    ├── cpu_percent.png      CPU do sistema
    ├── iowait_percent.png   tempo de CPU esperando o disco
    ├── disk_write_mib_s.png escrita em disco
    ├── ram_available_mib.png
    └── failure_percent.png
```

A tabela também aparece no terminal no final. No macOS, a pasta `plots/` abre
automaticamente.

## Casos de uso

### 1. Demonstração rápida em aula (~1 min)

Mostra o experimento funcionando de ponta a ponta, com gráficos.

```bash
bash scripts/experiment.sh -n aula
```

**O que esperar:** com 1 CPU, a vazão para de subir ou cai em 16 usuários, e a
CPU da API chega perto de 100%. Com 2 CPUs, a vazão continua subindo.

### 2. Efeito de mais CPU

Mantém a RAM fixa e varia só a CPU.

```bash
bash scripts/experiment.sh -n cpu \
  -c "cpu1:1:1g cpu2:2:1g cpu4:4:1g" -u "1 4 16 64" -d 20s
```

**O que esperar:** de 1 para 2 CPUs a vazão com alta demanda melhora bastante.
De 2 para 4 quase não muda, porque o limite passa a ser o disco: em
`app_cpu_percent.png`, a API com 4 CPUs usa bem menos que 400%.

### 3. Efeito de mais memória

Mantém a CPU fixa e varia só a RAM.

```bash
bash scripts/experiment.sh -n ram \
  -c "ram512m:2:512m ram1g:2:1g ram2g:2:2g" -u "1 8 32" -d 20s
```

**O que esperar:** praticamente nenhuma diferença. A aplicação usa menos de
100 MiB, e o `fsync` obriga cada escrita a ir ao disco.

### 4. Com e sem `fsync` (disco × memória)

Rode duas sessões com os mesmos cenários e compare.

```bash
bash scripts/experiment.sh -n com-fsync -c "c2:2:1g" -u "1 8 32" -d 20s
bash scripts/experiment.sh -n sem-fsync -c "c2:2:1g" -u "1 8 32" -d 20s -f
```

**O que esperar:** sem `fsync`, as escritas ficam primeiro no cache de memória
do sistema, e a vazão fica maior. Em um teste com 2 CPUs, foram ~1450–1490
req/s sem `fsync` contra ~1250 req/s com `fsync`. Em compensação, o
comportamento fica **instável**: de vez em quando o sistema operacional
precisa descarregar no disco tudo o que acumulou na memória, e nesse momento
as requisições travam. Nos testes, isso derrubou a vazão de um ponto para
~130–370 req/s, com iowait de 80–98%, em níveis de demanda diferentes a cada
execução. O `fsync` paga um custo fixo em cada requisição; sem ele, o custo
vem acumulado e imprevisível. Para enxergar o efeito, use `-d 15s` ou mais e
compare `requests_per_s.png` e `iowait_percent.png`.

### 5. Requisições maiores ou menores

O tamanho define quanto I/O cada requisição faz.

```bash
bash scripts/experiment.sh -n pequeno -c "c2:2:1g" -u "1 8 32" -k 64
bash scripts/experiment.sh -n grande  -c "c2:2:1g" -u "1 8 32" -k 8192
```

**O que esperar** (medido com 2 CPUs):

| Tamanho | Req/s no teto | p95 com 8 usuários | Escrita em disco | iowait |
|---|---:|---:|---:|---:|
| 64 KiB | ~2100 | 5 ms | ~150 MiB/s | ~10% |
| 8 MiB | ~200 | 150 ms | ~1550 MiB/s | ~20–30% |

Com requisições **pequenas**, há muitas requisições por segundo, mas o disco
fica quase ocioso: o limite passa a ser o custo de CPU de cada requisição
(HTTP, JSON). Ou seja, a aplicação deixa de ser IO-bound. Com requisições
**grandes**, há poucas requisições por segundo, o disco trabalha no limite e a
latência cresce já com poucos usuários. O tamanho da requisição decide qual
recurso vira o gargalo.

### 6. Curva completa para o relatório (~17 min)

Mesma configuração usada nos resultados do relatório.

```bash
bash scripts/experiment.sh -n relatorio \
  -c "vcpu1-ram1g:1:1g vcpu2-ram1g:2:1g vcpu4-ram1g:4:1g vcpu2-ram2g:2:2g" \
  -u "1 2 4 8 16 32 64" -d 30s -p 5
```

### 7. Encontrar o ponto de saturação

Use vários níveis próximos para ver exatamente onde a vazão para de crescer.

```bash
bash scripts/experiment.sh -n saturacao -c "c1:1:1g" -u "1 2 3 4 6 8 12 16" -d 15s
```

**O que esperar:** o ponto de saturação é onde `requests_per_s.png` para de
subir e `p95_ms.png` começa a crescer rapidamente.

## Dicas e problemas comuns

| Situação | O que fazer |
|---|---|
| `results/<nome> já existe` | use outro `-n`, ou apague a pasta antiga |
| `Cenário inválido` | confira o formato `nome:cpus:ram`, ex.: `c2:2:1g` |
| `Falhou; veja ...execucao.log` | abra o log; geralmente é o Docker fechado |
| `Cannot connect to the Docker daemon` | abra o Docker Desktop e espere iniciar |
| Números diferentes a cada execução | normal em execuções curtas; use `-d 20s` ou mais e feche outros programas |
| Pedir mais CPUs que o Docker tem | o Docker recusa; veja o limite em Docker Desktop → Settings → Resources |

- Abaixo de `-d 10s`, os resultados ficam muito instáveis.
- Para comparar sessões, mantenha fixos os parâmetros que não estão sendo
  estudados (duração, tamanho, usuários).
- Isto é um piloto em Docker: o disco é o SSD do computador, bem mais rápido
  que o disco virtual de uma VM VirtualBox. Os números absolutos não se
  transferem para a VM, mas as tendências sim.
