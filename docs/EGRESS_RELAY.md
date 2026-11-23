# Relay de saída: usar a internet do cliente

Alguns sistemas só aceitam acesso a partir do **IP do cliente**, que está na whitelist.
Para esses clientes, o container pode mandar **todo** o tráfego de saída por um relay
que usa a internet do cliente, em vez da internet do servidor onde o container roda.

O recurso é **opcional e fica desligado por padrão**. Sem `EGRESS_PROXY_URL`, nada muda.

```
                       servidor (datacenter)                                 rede do cliente
┌──────────────────────────────────────────────────────────┐        ┌────────────────────┐
│ container rpa-worker-selenium                            │        │                    │
│  Chrome / SeleniumBase UC ──┐ policy ProxySettings       │        │                    │
│  Firefox ───────────────────┤ policies.json              │ SOCKS5 │  seu relay server  │──► sistemas
│  Python / curl / pip ───────┼─► 127.0.0.1:3128 ──────────┼───────►│  (internet do      │    (IP do cliente
│  PJeOffice (Java) ──────────┘ JAVA_TOOL_OPTIONS          │ ou HTTP│   cliente)         │     na whitelist)
│  localhost, VNC, PJeOffice local, mTLS local ─► direto   │        │                    │
└──────────────────────────────────────────────────────────┘        └────────────────────┘
```

O entrypoint sobe um repassador em `127.0.0.1:3128` (`/app/egress_proxy.py`), que fala
com o seu relay usando usuário e senha. Todos os programas do container apontam para esse
repassador, então **os scripts não precisam mudar**.

---

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `EGRESS_PROXY_URL` | — (desligado) | `socks5://usuario:senha@relay:1080`, `http://usuario:senha@relay:3128` ou `https://...` |
| `EGRESS_PROXY_URL_FILE` | — | Arquivo com a URL (Docker secret). **Tem prioridade** e não aparece no `docker inspect` |
| `EGRESS_REQUIRED` | `1` | Se o relay não funcionar no boot, o container **para** (exit 1) sem executar nada. Com `0`, só avisa; o tráfego de saída falha até o relay voltar. Em nenhum caso sai direto |
| `EGRESS_EXPECTED_IP` | — | IP do cliente na whitelist. O boot e o `egress_check.py` falham se o IP de saída for outro |
| `EGRESS_CHECK_URL` | `https://api.ipify.org` | URL que devolve o IP de saída, consultada no boot. `off` = só testa a conexão com o relay |
| `EGRESS_BYPASS` | — | Destinos que saem **direto** pelo servidor, separados por vírgula: `.dominio.com.br`, `host`, `10.0.0.0/8` |
| `EGRESS_LOCAL_PORT` | `3128` | Porta local do repassador |
| `EGRESS_DEBUG` | `0` | `1` registra cada conexão em `/app/logs/egress_proxy.log` |

Usuário e senha com caracteres especiais vão codificados na URL: `@` → `%40`,
`:` → `%3A`, `/` → `%2F` (ex.: `socks5://rpa:S3nh%40@relay:1080`).

Localhost (`127.0.0.1`, `::1`) nunca passa pelo relay. Assim continuam funcionando o
PJeOffice, o servidor mTLS local do `a1_check.py`, o chromedriver e o geckodriver.

---

## O que é configurado no container

| Componente | Como passa a usar o relay |
|---|---|
| Chrome e SeleniumBase (inclusive UC) | policy gerenciada `ProxySettings` em `/etc/opt/chrome*/policies/managed/egress_proxy.json`. Ela vale mesmo que o script passe `--proxy-server` |
| Firefox | `/opt/firefox/distribution/policies.json` com `Proxy` travado (`Locked`) |
| Python (`requests`, `httpx`, `urllib`), `curl`, `pip` | `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY` (e versões minúsculas) |
| Java (PJeOffice e `keytool`) | `JAVA_TOOL_OPTIONS` com `http(s).proxyHost/Port` e `http.nonProxyHosts` |

### Proteções contra vazamento do IP do servidor

- **DNS:** o nome do destino vai para o relay sem ser resolvido no container (CONNECT/SOCKS5
  com nome de host). Assim, os sistemas veem consultas DNS da rede do cliente.
- **WebRTC:** o Chrome usa `WebRtcIPHandlingPolicy=disable_non_proxied_udp` e o Firefox usa
  `media.peerconnection.ice.proxy_only`. O WebRTC é a forma mais comum de um site descobrir o IP real.
- **QUIC/HTTP3** (UDP) desligado nos dois browsers.
- **DNS-over-HTTPS** do Firefox desligado.
- **Sem conexão direta de reserva:** se o relay cair, a saída falha em vez de usar o IP do servidor.

**Limite:** um script que desligue o proxy de propósito (por exemplo,
`requests.get(..., proxies={"https": None})` ou socket cru) sai direto. Para bloquear
isso no nível do kernel, seria preciso `NET_ADMIN` + firewall, que fica fora desta versão,
como combinado (sem VPN/túnel).

---

## O que o relay server precisa ter

Use esta lista para construir ou contratar o relay.

### Obrigatório

1. **Protocolo**, uma das opções:
   - **SOCKS5** (RFC 1928) com o comando **CONNECT** e endereços por **nome de domínio**
     (ATYP `0x03`). O relay resolve o DNS. A autenticação por usuário/senha (RFC 1929) é
     opcional, mas recomendada.
   - **Proxy HTTP** com:
     - `CONNECT host:porta` para HTTPS em **qualquer porta** que os sistemas usem
       (443, 8443…), e não só 443;
     - requisições em *absolute-form* (`GET http://host/caminho`) para sites `http://`;
     - autenticação `Proxy-Authorization: Basic`, respondendo **407** quando a senha estiver errada;
     - `https://` também é suportado (TLS entre o container e o relay).
2. **Repasse TCP puro, sem inspecionar TLS (sem MITM).** O relay não pode abrir o HTTPS:
   o certificado A1 (TLS com certificado de cliente) e a validação dos certificados dos
   sistemas dependem de o túnel ser ponta a ponta.
3. **Saída pela internet do cliente:** o IP de saída precisa ser o IP da whitelist
   (confira com `EGRESS_EXPECTED_IP`).
4. **Alcançável a partir do servidor:** IP/porta abertos para o IP do servidor, com
   usuário e senha. Não deixe o relay aberto para a internet sem autenticação.

### Capacidade e estabilidade

| Item | Recomendação |
|---|---|
| Conexões simultâneas | **≥ 100 por worker**: o Chrome abre muitas conexões por página. Ex.: 4 workers → 400 |
| Tempo ocioso de túnel | **≥ 10 min** (downloads longos, sessões e polling dos sistemas) |
| Banda | ~2–5 Mbit/s por worker ativo (páginas de tribunais, PDFs) |
| Latência | quanto menor melhor; cada página faz dezenas de requisições |
| IPv4 | obrigatório; IPv6 opcional |
| UDP | **não é necessário** (QUIC e WebRTC ficam desligados) |
| Reconexão | ao reiniciar, o relay deve voltar sozinho; o container não sai direto enquanto isso |
| Logs | registre destino, horário e bytes, sem registrar o conteúdo |

### Não é necessário

- Inspecionar ou decifrar HTTPS (não faça isso).
- Instalar CA no container.
- UDP, VPN ou túnel de rede.

---

## Rotina de teste

### 1. Teste o relay a partir do servidor (sem o container)

```bash
curl -sS -x 'socks5h://usuario:senha@relay.exemplo.com.br:1080' https://api.ipify.org; echo
```

Para um relay HTTP:

```bash
curl -sS -x 'http://usuario:senha@relay.exemplo.com.br:3128' https://api.ipify.org; echo
```

O resultado deve ser o **IP do cliente**. Se aparecer o IP do servidor, o relay não está
saindo pela rede do cliente.

### 2. Rode o verificador do container

Grave a URL do relay num arquivo, para a senha não ir para o histórico do shell nem para o `docker inspect`:

```bash
printf '%s' 'socks5://usuario:senha@relay.exemplo.com.br:1080' > relay-url.txt && chmod 600 relay-url.txt
```

```bash
docker run --rm --shm-size=2g -e USE_XVFB=1 \
  -e EGRESS_PROXY_URL_FILE=/run/secrets/relay -v "$PWD/relay-url.txt:/run/secrets/relay:ro" \
  -e EGRESS_EXPECTED_IP=200.200.200.200 \
  ghcr.io/nailtongomes/rpa-worker-selenium:latest \
  python /app/egress_check.py --url https://pje.tjrn.jus.br/pje/login.seam --compare-direct
```

Saída esperada:

```
🌐 Verificação da saída pelo relay

✅ relay: socks5://***@relay.exemplo.com.br:1080
✅ repassador local: 127.0.0.1:3128
✅ variáveis HTTP(S)_PROXY: http://127.0.0.1:3128
✅ Java (JAVA_TOOL_OPTIONS): proxy configurado para o PJeOffice
✅ policy do Chrome (chrome): ProxySettings + WebRTC/QUIC bloqueados
✅ policy do Chrome (chrome_for_testing): ProxySettings + WebRTC/QUIC bloqueados
✅ policy do Firefox: Proxy travado + WebRTC/HTTP3 bloqueados
✅ exceções (sem relay): localhost, 127.0.0.1, ::1
✅ Python (requests): 200.200.200.200
✅ Chrome (Selenium): 200.200.200.200
✅ Chrome (SeleniumBase UC): 200.200.200.200
✅ Firefox: 200.200.200.200
✅ Java (PJeOffice): 200.200.200.200
✅ acesso a https://pje.tjrn.jus.br/pje/login.seam: HTTP 200
✅ IP do servidor sem relay: 45.x.x.x (diferente do relay, como esperado)

✅ todo o tráfego testado sai pelo relay
```

O comando sai com exit 0 se tudo passar e 1 se algo falhar. `--json arquivo.json` grava o
resultado. `--url` pode ser repetido para cada sistema da whitelist.

### 3. Confira que o container para sem o relay

Com um relay inexistente, o container não pode executar nada:

```bash
docker run --rm -e EGRESS_PROXY_URL='socks5://u:p@127.0.0.1:9' \
  ghcr.io/nailtongomes/rpa-worker-selenium:latest echo NAO-DEVERIA-RODAR; echo "exit=$?"
```

Esperado: `❌ Egress relay failed: ...`, sem a linha `NAO-DEVERIA-RODAR`, e `exit=1`.

### 4. Antes do relay definitivo: relay de referência

`/app/egress_testkit.py` é um relay SOCKS5/HTTP mínimo, só com a biblioteca padrão do Python. Ele serve para:
- validar o container numa máquina da rede do cliente antes de o seu relay ficar pronto;
- comparar com o comportamento do seu relay quando algo falhar.

```bash
# na máquina do cliente (Python 3.11+); copie o arquivo do repositório: image/app/egress_testkit.py
python3 egress_testkit.py relay --protocol socks5 --listen 0.0.0.0:1080 --user rpa --password 'troque-esta-senha'
```

No servidor, aponte `EGRESS_PROXY_URL=socks5://rpa:troque-esta-senha@<ip-da-maquina>:1080` e
repita os passos 2 e 3. Use-o só para teste: ele não tem limites nem lista de destinos.

### 5. Em produção (vários workers)

No [`examples/server/docker-compose.yml`](../examples/server/docker-compose.yml), cada worker
pode ter o seu relay (`EGRESS_PROXY_URL_01`…`04`, `EGRESS_EXPECTED_IP_NN`) ou herdar um
`EGRESS_PROXY_URL` comum. O log de boot mostra o IP de saída de cada worker:

```bash
docker compose logs rpa-worker-02 | grep -i egress
```

---

## Testes automáticos (CI)

`scripts/test-image.sh` roda dois cenários a cada PR, release e build noturno, sem internet:

- **relay SOCKS5 com senha** (`tests/image/test_egress.py`), com um relay de teste que
  responde a qualquer host com um IP falso:
  - Python, curl, Java (JRE do PJeOffice), Chrome, SeleniumBase UC e Firefox (headless e com janela) saem pelo relay;
  - nomes `.invalid`, que não existem no DNS, funcionam: prova de que o DNS é resolvido no relay;
  - nenhum candidato WebRTC revela IP, e as policies aparecem em `chrome://policy`;
  - localhost segue direto, a senha do relay não aparece em variáveis nem em log;
  - o certificado A1 (mTLS local) continua funcionando com o relay ligado.
- **proxy HTTP e falhas:**
  - proxy HTTP com senha funciona;
  - relay fora do ar e senha errada param o container sem executar o comando;
  - `EGRESS_REQUIRED=0` só avisa;
  - esquema inválido é recusado.

---

## Problemas comuns

| Sintoma no log | Causa | O que fazer |
|---|---|---|
| `relay ... inacessível` | firewall, IP/porta errados, relay fora do ar | teste o passo 1 a partir do servidor |
| `usuário ou senha incorretos` | credenciais erradas ou não codificadas na URL | codifique `@`, `:` e `/` (veja acima) |
| `IP de saída ... diferente do esperado` | o relay está saindo por outra rede | confira a saída do relay; ajuste `EGRESS_EXPECTED_IP` |
| `conexão não permitida pelas regras do relay` | o relay bloqueia o destino ou a porta | libere o destino ou a porta no relay |
| site com erro de certificado só com o relay | o relay está inspecionando o TLS (MITM) | desligue a inspeção: o relay precisa ser repasse TCP puro |
| downloads longos caem | tempo ocioso do relay curto | aumente para ≥ 10 min |
| `api.ipify.org` bloqueado na rede do cliente | o serviço de IP não está liberado | `EGRESS_CHECK_URL=` uma URL sua que devolva o IP, ou `off` |
