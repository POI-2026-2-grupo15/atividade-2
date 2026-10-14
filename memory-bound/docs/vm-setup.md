# Preparação da VM VirtualBox

Este roteiro prepara o deploy; não executa a matriz de experimentos. O destino
da VM ainda precisa ser indicado. A VM não foi criada nem iniciada nesta etapa.

## Escolher o hospedeiro

No computador desta sessão foi detectado macOS ARM64, sem VirtualBox instalado.
O VDI fornecido está em Downloads, mas a arquitetura do SO dentro dele ainda
não foi confirmada. Um host ARM exige um convidado ARM no caminho oficialmente
suportado pelo VirtualBox; x86 sobre ARM não é suportado. Consulte as
[limitações oficiais](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/installation.html).

O roteiro da disciplina prevê uso do VirtualBox no LCC. Se o disco for x86,
utilize um hospedeiro Intel/AMD, por exemplo o computador do laboratório.

## Criar a VM no LCC

1. Copie `ubuntu_serve_2204_poi.vdi` de `/local/uasc/images` para um diretório
   próprio em `/tmp`, conforme o roteiro da disciplina. Não altere a imagem
   compartilhada. Mantenha a VM e a cópia do disco em `/tmp`.
2. No VirtualBox, crie uma VM Linux/Ubuntu e escolha usar o disco existente.
   Selecione a versão de arquitetura compatível com o VDI/hospedeiro.
3. Comece com 1 vCPU e 1.024 MiB de RAM, como preparação funcional. Os quatro
   cenários finais e workers ainda serão calibrados no piloto.
4. Na rede NAT, configure redirecionamento TCP: IP do hospedeiro `127.0.0.1`,
   porta do hospedeiro `8000`, porta do convidado `8000`. Deixe o IP do
   convidado vazio para a configuração NAT padrão. Se a porta local já estiver
   ocupada, escolha outra e ajuste a URL utilizada pelo cliente.
5. Inicie o sistema e entre com as credenciais do roteiro da disciplina.
   Dentro da VM, registre `uname -m` e `python3 --version`.

Não é necessário copiar os datasets para a VM: eles ficam junto ao Locust no
hospedeiro. O servidor recebe os CSVs por HTTP.

## Transferir o código atual

Há correções locais ainda não publicadas. Clonar somente o repositório remoto
pode deixar essas correções de fora. O usuário controla commits e publicação.

Para transferir uma cópia do trabalho local, no hospedeiro, a partir da raiz
do repositório:

```bash
tar -czf /tmp/memory-bound-deploy.tar.gz -C memory-bound \
  app scripts requirements.txt requirements-analysis.txt README.md docs
```

Transfira o arquivo por pasta compartilhada ou SSH. Para usar SSH, instale e
inicie `openssh-server` dentro da VM e configure uma regra NAT adicional:
`127.0.0.1:2222` no hospedeiro para porta `22` no convidado. Exemplo no Ubuntu:

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
```

Com o usuário `osboxes` informado no roteiro, execute no hospedeiro:

```bash
scp -P 2222 /tmp/memory-bound-deploy.tar.gz osboxes@127.0.0.1:/tmp/
```

Use a credencial do roteiro quando solicitada. Não inclua senhas nos scripts.

## Instalar a aplicação dentro da VM

No Ubuntu Server 22.04, em um diretório novo:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl
mkdir -p ~/memory-bound
tar -xzf /tmp/memory-bound-deploy.tar.gz -C ~/memory-bound
cd ~/memory-bound
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install psutil==7.0.0
python -m pip check
mkdir -p results
python -m pip freeze > results/dependencies.txt
uname -a > results/system.txt
lscpu > results/cpu.txt
free -b > results/memory.txt
```

Neste caminho, Locust não é instalado na VM. `psutil` é usado pelo monitor.

## Iniciar e conferir acesso

Na VM, com o ambiente ativado:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 \
  --no-access-log > results/api.log 2>&1 &
APP_PID=$!
curl --fail http://127.0.0.1:8000/openapi.json
```

No hospedeiro, o mesmo `curl` deve alcançar a API pelo redirecionamento. A API
atual não tem `/health`: use `/openapi.json` apenas para conferir acesso. Para
demonstrar processamento, envie CSVs reais ao endpoint `/memory-test`.

Por exemplo, na pasta `memory-bound/` do hospedeiro:

```bash
curl --fail -F 'files=@datasets/pequeno/cadastro-01.csv' \
  -F 'files=@datasets/pequeno/cadastro-02.csv' \
  http://127.0.0.1:8000/memory-test
```

Esse envio usa somente dois arquivos: não compare suas contagens com o
manifesto do conjunto inteiro, que corresponde a quatro arquivos.

## Preparação do monitor e evidências

No mesmo terminal da VM em que foi guardado `APP_PID`:

```bash
python scripts/monitor.py --pid "$APP_PID" --interval 1 \
  --output results/monitor-preparacao.csv
```

Pare a coleta com Ctrl+C após a demonstração. O servidor continua ativo;
quando não for mais necessário, `kill "$APP_PID"` encerra a instância iniciada.
Antes dos experimentos, sincronize os relógios hospedeiro/VM e registre vCPU,
RAM, workers, swap, versão do código e URL. O monitor produz CSV e metadados.

Guarde capturas de tela da configuração VirtualBox e da requisição/resposta,
conforme o roteiro da disciplina. Ao encerrar a sessão, desligue a VM e preserve
uma cópia do VDI e resultados fora de `/tmp`, pois os arquivos temporários podem
ser removidos pelo laboratório. O roteiro também pede cópia do disco no Drive.

Sucesso desta fase: VM iniciada, dependências instaladas, API acessível pelo
hospedeiro e consolidação demonstrada. As medições locais anteriores no Mac
não confirmam essas etapas. Piloto e matriz comparativa ficam para depois.
