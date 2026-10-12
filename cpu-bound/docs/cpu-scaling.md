# Comparação de provisionamento: 2, 4, 6 e 8 CPUs

| Caso | CPU | RAM | Workers | Usuários | Payload | Espera |
|---|---:|---:|---:|---:|---|---:|
| A | 2 | 1 GiB | 8 | 32 | 10 MiB × 100 | 0 s |
| B | 4 | 1 GiB | 8 | 32 | 10 MiB × 100 | 0 s |
| C | 6 | 1 GiB | 8 | 32 | 10 MiB × 100 | 0 s |
| D | 8 | 1 GiB | 8 | 32 | 10 MiB × 100 | 0 s |

Somente CPU varia. Oito workers fixos permitem utilizar o maior cenário. Nos
menores, os processos disputam tempo de CPU e geram trocas de contexto; isso
faz parte do efeito observado. A aplicação não requer mudança de código.

O [relatório final](relatorio-final.md) apresenta a curva de demanda medida
para os quatro casos e as limitações de interpretação.

## Piloto Docker

O hospedeiro tem Ryzen 7 7735HS, oito núcleos físicos e 16 CPUs lógicas.
CPUs 0 e 1 pertencem ao núcleo 0; CPU 0 é usada pelo Locust. O servidor pode
usar o pool fixo 2–15, correspondendo a sete núcleos físicos com SMT. Variam
apenas as quotas Docker `--cpus=2`, `4`, `6`, `8`. Cada caso cria um container
novo com 1 GiB, swap desabilitado e oito workers.

A quota 8 não representa oito núcleos físicos exclusivos: nesse pool, parte
do paralelismo depende de SMT. Essa restrição e o compartilhamento do hospedeiro
podem reduzir o ganho marginal do último cenário. CPU, temperatura, memória
compartilhada e escalonamento também influenciam a curva de desempenho.

```bash
source .venv/bin/activate
docker build -t cpu-bound:experiment .
bash scripts/run_cpu_scaling.sh
```

O padrão executa 60 segundos por caso, além de inicialização e 32 requisições
de aquecimento distribuídas por conexões independentes. O Locust usa 32 usuários,
taxa de criação de 32 usuários/s, carga fixa e espera zero. O pool de CPUs,
workers, demanda e RAM ficam constantes. Os containers são encerrados/removidos
entre os casos; resultados são preservados em diretório novo.

`DURATION`, `USERS`, `SERVER_CPUS`, `GENERATOR_CPU`, `IMAGE` e `OUTPUT_DIR` podem
ser definidos por ambiente, mantendo seus valores fixos em toda a comparação.
Adapte o pool à topologia real da máquina, sem incluir o núcleo do gerador.

Avalie requisições/s, latência média/p95, falhas e uso de memória. A CPU bruta
tem escala de 100% por CPU; seus tetos são 200%, 400%, 600% e 800%. O campo
`allocated_cpu_utilization_percent` divide o uso bruto pela quota para permitir
comparar saturação em escala 0–100%. O uso do Locust é medido separadamente.

O resumo identifica as janelas: CPU exclui primeiros cinco/últimos dois segundos;
HTTP usa snapshot acumulado do Locust, incluindo rampa. O piloto tem uma
execução por cenário e serve para verificar viabilidade, sem significância
estatística. Mantenha os CSVs brutos para recortes posteriores.

## VirtualBox

Repita os quatro casos configurando efetivamente 2, 4, 6 e 8 vCPUs, com
1.024 MiB de RAM e oito workers em todos. Não transplante os IDs de afinidade
Docker para dentro da VM. Gere carga no hospedeiro e monitore a VM.
Use aquecimento, janela estável e pelo menos três repetições, alternando a ordem
dos cenários. O limite de 1 GiB deve ser acompanhado: se houver swap ou falta de
memória, o cenário deixou de isolar o efeito de CPU e precisa ser replanejado
mantendo a mesma RAM em todos os casos.
