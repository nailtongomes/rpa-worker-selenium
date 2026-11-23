# Receita: worker na VPS, saindo pela internet do PC do cliente

Para quando o PC do cliente não consegue rodar o container (pouca memória, sem WSL2), mas o sistema precisa
ver o IP residencial dele. O PC só **empresta a conexão** com o `internet on` do
[shutup-and-run](https://github.com/nailtongomes/shutup-and-run) (sem Docker). O worker roda na sua VPS e todo o
tráfego dele sai pelo PC: Python, Chrome, UC, Firefox, Java/PJeOffice e DNS.

```text
worker (VPS) ──EGRESS_PROXY_URL──▶ relay do shutup-and-run (VPS) ◀──conexão de saída── PC do cliente ──▶ tribunal / GOV.BR
```

O Chrome não aceita login de proxy na linha de comando, e o shutup-and-run resolve isso abrindo uma porta sem
login por PC. Esta imagem não precisa disso: o repassador local do `EGRESS_PROXY_URL` faz o login para todos
os programas. Uma URL com o login do PC basta.

Conferido assim: relay e agente do shutup-and-run 0.2.28 + esta imagem com `egress_check.py`. O log do relay
mostrou Python, Chrome, UC, Firefox e Java saindo pelo PC, inclusive na porta 80.

## Passo a passo

**Na VPS**, nesta pasta, crie o token do relay e suba só o relay:

```bash
echo "RELAY_TOKEN=$(head -c 24 /dev/urandom | base64 | tr -d '/+=')" > .env
```

```bash
docker compose up -d relay
```

**No PC do cliente** (Windows, PowerShell). Você escolhe o login do PC (`ID:SENHA`, senha de 16 a 128 letras,
dígitos, `-`, `_` ou `.`). A instalação liga o empréstimo da internet e espera conectar:

```powershell
$env:SHUTUP_AND_RUN_RELAY = "vps.exemplo.com:7000"; $env:SHUTUP_AND_RUN_RELAY_TOKEN = "O_TOKEN_DO_ENV"
```

```powershell
$env:SHUTUP_AND_RUN_INTERNET_LOGIN = "cliente-01:SENHA_LONGA"
```

```powershell
irm https://raw.githubusercontent.com/nailtongomes/shutup-and-run/main/scripts/install.ps1 | iex
```

Ou, com o shutup-and-run já instalado:
`shutup-and-run internet on --relay vps.exemplo.com:7000 --token O_TOKEN --login cliente-01:SENHA_LONGA --wait 60`.

**Na VPS**, grave a URL do proxy com o login do PC num arquivo, nunca numa variável:

```bash
mkdir -p segredos && printf '%s' 'http://cliente-01:SENHA_LONGA@relay:8080' > segredos/egress-url && chmod 600 segredos/egress-url
```

Confira antes de usar: o PC está conectado, o tráfego sai por ele e o site abre:

```bash
docker compose run --rm worker python /app/egress_check.py --url https://pje.tjrn.jus.br/
```

`✅` em todas as linhas e o mesmo IP de saída para Python, Chrome, UC, Firefox e Java: é o IP do PC.
Depois disso o worker roda como sempre (`SCRIPT_URL` no `.env` e `docker compose run --rm worker`, ou o
loop/standby dos [outros exemplos](../../examples/compose/)).

## Como se comporta

- **Fail-closed:** se o PC estiver desligado, pausado ou fora do horário (`--hours`), o worker para antes de
  qualquer tráfego, em vez de sair pela VPS (`EGRESS_REQUIRED=1`, o padrão). No modo loop, ele pula a iteração e
  tenta de novo, sem contar como falha. Veja [docs/EGRESS_RELAY.md](../../docs/EGRESS_RELAY.md).
- **O PC decide.** A pessoa no PC pausa ou desliga quando quiser (página `http://127.0.0.1:8788/`), e uma
  conexão já aberta nunca é cortada. O PC recusa destinos da rede local dele.
- **Um worker por PC:** o login (`ID`) escolhe o PC. Para vários clientes, um arquivo `egress-url` (e um worker)
  por cliente.
- **Proteja o proxy:** a porta 8080 do relay só pode ser alcançada pelos seus containers (neste compose, só
  pela rede interna). Na internet, qualquer um sairia pela casa do cliente.
