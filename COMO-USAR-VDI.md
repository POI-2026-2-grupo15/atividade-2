# VM preparada para a Atividade 2

O arquivo `atividade-2-preparada.vdi` contém Ubuntu Server 22.04, SSH, o clone
do repositório na branch `main` com as três aplicações e um checkout separado
da branch `memory-bound`. As dependências Python das aplicações, do Locust e dos
scripts de análise e relatório já estão instaladas em
`/home/osboxes/atividade-2/.venv`.

## Nesta máquina

A VM criada para validar este guia é `poi_atividade2_validacao_guia`. Se estiver
desligada, inicie-a com:

```bash
VBoxManage startvm poi_atividade2_validacao_guia --type gui
```

As três APIs iniciam automaticamente. Estas são as **portas do hospedeiro da VM
`poi_atividade2_validacao_guia`**, confirmadas no VirtualBox:

| Aplicação | Endereço | Serviço no Ubuntu |
| --- | --- | --- |
| CPU-bound | <http://127.0.0.1:8000/docs> | `poi-cpu-bound` |
| IO-bound | <http://127.0.0.1:8001/docs> | `poi-io-bound` |
| Memory-bound | <http://127.0.0.1:8002/docs> | `poi-memory-bound` |

Para entrar por SSH:

```bash
ssh -p 2222 osboxes@127.0.0.1
```

A VM antiga `poi_atividade2_pronta` também está registrada e usa as mesmas
portas. As duas VMs apontam para o mesmo VDI; desligue uma antes de iniciar a
outra.

Os arquivos ficam em `/home/osboxes/atividade-2` (`main`). O checkout adicional
fica em `/home/osboxes/atividade-2-memory` (`memory-bound`). Há mais instruções em
`/home/osboxes/LEIA-ME-VM.txt` dentro da VM.

## Requisições para testar as APIs

Execute os comandos abaixo **no hospedeiro**, com a VM
`poi_atividade2_validacao_guia` ligada. Eles usam as portas 8000, 8001 e 8002
da tabela acima.

### CPU-bound

```bash
curl -fsS http://127.0.0.1:8000/health
printf 'abc' > /tmp/poi-teste-cpu.txt
curl -fsS -F file=@/tmp/poi-teste-cpu.txt http://127.0.0.1:8000/hash
curl -fsS -F file=@/tmp/poi-teste-cpu.txt \
  -F expected_hash=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad \
  http://127.0.0.1:8000/verify
```

`/health` deve retornar `{"status":"ok"}`. O `/hash` deve retornar 3 bytes e
o digest SHA-256 informado no comando seguinte; `/verify` deve retornar
`"matches":true`.

### IO-bound

```bash
curl -fsS http://127.0.0.1:8001/health
curl -fsS -H 'Content-Type: application/json' \
  -d '{"size_kb":4,"fsync":true}' http://127.0.0.1:8001/io
```

A resposta de `/io` deve conter `"size_kb":4`, `"fsync":true` e
`"verified":true`, confirmando a gravação e a leitura do conteúdo.

### Memory-bound

```bash
printf 'id,name,email,description\n1,Ana,ana@example.com,primeiro\n1,Bia,bia@example.com,substitui\n2,Caio,caio@example.com,novo\n' \
  > /tmp/poi-teste-memory.csv
curl -fsS -F files=@/tmp/poi-teste-memory.csv \
  http://127.0.0.1:8002/memory-test
```

A resposta deve informar `"records_received":3`, `"unique_records":2` e
`"replaced_occurrences":1`, pois o segundo registro com ID `1` substitui o
primeiro.

## Ao levar o VDI para outro computador

Um VDI contém o disco do Ubuntu, mas não as definições de hardware e rede do
VirtualBox. Crie uma VM Ubuntu (64-bit) com firmware BIOS, 4 vCPUs, 4096 MiB de
RAM, controlador SATA e adaptador NAT; anexe `atividade-2-preparada.vdi` como
disco existente. Configure os seguintes redirecionamentos TCP no adaptador NAT;
eles são os mesmos usados nos exemplos de requisição acima:

| Nome | IP do hospedeiro | Porta do hospedeiro | Porta da VM |
| --- | --- | ---: | ---: |
| ssh | 127.0.0.1 | 2222 | 22 |
| cpu | 127.0.0.1 | 8000 | 8000 |
| io | 127.0.0.1 | 8001 | 8001 |
| memory | 127.0.0.1 | 8002 | 8002 |

O usuário do VDI original é `osboxes`; a senha padrão aceita nesta imagem é
`osboxes.org`. O acesso por chave SSH já foi configurado para este computador;
em outro, use a senha ou instale sua própria chave.

Para medições de desempenho de uma aplicação, pare os serviços das outras
duas com `sudo systemctl stop poi-io-bound poi-memory-bound`, por exemplo.
Os experimentos que usam Docker exigem uma instalação separada do Docker;
as três APIs, seus testes, o Locust e os scripts Python estão prontos no VDI.
