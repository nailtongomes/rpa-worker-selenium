# rpa-worker-selenium

Imagem Docker de produção para automação web (RPA) em sistemas judiciais brasileiros:
**Chrome + Firefox + Selenium/SeleniumBase**, execução *headful* com Xvfb + OpenBox,
**PJeOffice Pro** e suporte a certificados digitais (A1/NSS).

```bash
docker pull ghcr.io/nailtongomes/rpa-worker-selenium:latest
```

A imagem é construída a partir de [`Dockerfile.trixie`](Dockerfile.trixie) (Debian 13 "Trixie")
e publicada no GHCR pelo GitHub Actions a cada mudança na `main`. Para servidores **ARM64**
(Oracle Ampere, Hetzner CAX, AWS Graviton), use `:latest-arm64`: mesma imagem e mesmo contrato,
testada no mesmo portão num runner ARM ([receita do servidor ARM](recipes/servidor-arm/README.md)).

> **Começando?** As [receitas plug and play](recipes/README.md) têm arquivos prontos para copiar:
> testar o seu certificado A1 no PC com o [shutup-and-run](https://github.com/nailtongomes/shutup-and-run),
> rotinas no PC sem orquestrador, tarefas cadastradas na nuvem (ou por uma IA) e executadas no PC,
> desenvolvimento vendo o browser, worker na VPS saindo pela internet do cliente e servidor ARM barato.

---

## O que vem na imagem

| Componente | Versão / origem | Observação |
|---|---|---|
| Debian | 13 (Trixie) | locale `pt_BR.UTF-8`, `TZ=America/Sao_Paulo` |
| Python | 3.13 (venv em `/opt/venv`) | pacotes em [`requirements.txt`](requirements.txt) |
| Google Chrome for Testing + ChromeDriver | `ARG CHROME_VERSION` | mesma versão, baixados juntos |
| Firefox ESR (pt-BR) + GeckoDriver | `ARG FIREFOX_VERSION` / `ARG GECKODRIVER_VERSION` | profile `selenium.default-release` com NSS pronto |
| SeleniumBase | **sempre a mais recente do PyPI** no momento do release | camada própria, renovada a cada release |
| PJeOffice Pro (com o Java 8 dele, que também é o `java`/`keytool` do PATH) | 2.5.16 | `BUILD_PJEOFFICE=1` no release |
| ImageMagick + Ghostscript | Debian | `ENABLE_PDF_TOOLS=1` no release |
| x11vnc + noVNC | Debian / GitHub | `ENABLE_VNC=1`, `ENABLE_NOVNC=1` no release |
| FFmpeg (gravação de tela) | — | **não incluso** na imagem publicada (`ENABLE_FFMPEG=0`) |

As versões exatas da imagem atual estão registradas em
[`docs/baseline/`](docs/baseline/) (gerado por `scripts/image-snapshot.sh`).

**Imagem enxuta.** A imagem tinha 3,8 GB, e cerca de 700 MB disso eram cópias repetidas de arquivos
entre camadas. Ficaram de fora também: o Java 21 do sistema (o PJeOffice usa o Java 8 que vem com ele),
o ffmpeg do PJeOffice (só para cortar vídeo; no lugar há um stub que sai com erro), o `pcsc-tools`
(diagnóstico de token A3), as traduções do Chrome e do sistema que não são pt/en, manuais/documentação
dos pacotes e as suítes de teste do pandas/numpy. O Dockerfile anterior está em
[`legacy/Dockerfile.trixie`](legacy/Dockerfile.trixie), só como referência (o release não o usa; para
voltar à imagem antiga basta o rollback por tag, veja abaixo).

---

## Uso rápido

### Executar um script uma vez

```bash
docker run --rm --shm-size=2g \
  -e SCRIPT_URL="https://exemplo.com/meu-script.py" \
  -e USE_XVFB=1 -e USE_OPENBOX=1 \
  ghcr.io/nailtongomes/rpa-worker-selenium:latest
```

### Worker em loop (produção)

```bash
docker run -d --name rpa-worker-01 --shm-size=2g --restart=always \
  -e SCRIPT_URL="https://exemplo.com/meu-script.py" \
  -e WORKER_LOOP=1 -e WORKER_TIMEOUT=3600 -e WORKER_RESTART_DELAY=120 \
  -e USE_XVFB=1 -e USE_OPENBOX=1 -e USE_PJEOFFICE=1 \
  ghcr.io/nailtongomes/rpa-worker-selenium:latest
```

Versão com Docker Compose: [`examples/compose/docker-compose.worker.yml`](examples/compose/docker-compose.worker.yml)
(detalhes em [`docs/WORKER.md`](docs/WORKER.md)).

### Vários workers no mesmo servidor (ex.: 4)

```bash
cd examples/server
cp ../../.env.example .env && nano .env   # SCRIPT_URL e segredos
docker compose up -d                      # 4 workers: rpa-worker-01..04
# ou, só com Docker:
./workers.sh start 4
```

Guia completo (dimensionamento, atualização, rollback, override por worker):
[`examples/server/README.md`](examples/server/README.md).

### Ver o navegador ao vivo (noVNC)

```bash
docker run --rm --shm-size=2g -p 6080:6080 \
  -e SCRIPT_URL="https://exemplo.com/meu-script.py" \
  -e USE_XVFB=1 -e USE_OPENBOX=1 -e USE_VNC=1 -e USE_NOVNC=1 \
  ghcr.io/nailtongomes/rpa-worker-selenium:latest
# abrir http://localhost:6080/vnc.html
```

Sem senha, o VNC fica aberto para quem alcançar a porta: use só em rede confiável. Para pedir
senha, monte um arquivo e aponte `VNC_PASSWORD_FILE` para ele (ou use `VNC_PASSWORD`, que fica
visível no `docker inspect`). O noVNC pede a mesma senha na tela. Só os 8 primeiros caracteres
contam, por limitação do protocolo VNC. `VNC_VIEW_ONLY=1` deixa só assistir, sem clicar nem digitar,
para acompanhar uma execução sem atrapalhar.

```bash
  -e USE_VNC=1 -e USE_NOVNC=1 -e VNC_VIEW_ONLY=1 \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc -v "$PWD/vnc-senha.txt:/run/secrets/vnc:ro" \
```

### Modo standby (recebe tarefas por HTTP)

Veja [`examples/compose/docker-compose.standby.yml`](examples/compose/docker-compose.standby.yml)
e a seção "Standby" de [`docs/WORKER.md`](docs/WORKER.md).

### Certificado digital A1

A imagem traz `/app/a1cert.py` para os scripts configurarem o A1 em Python:

```python
import a1cert

cert = a1cert.load_from_env()                       # A1_PFX_URL + A1_PFX_PASSWORD(_FILE)
a1cert.install_chrome(cert, ["https://pje.tjrn.jus.br"])  # NSS + AutoSelectCertificateForUrls
a1cert.install_firefox(cert)                        # NSS do profile + seleção automática
a1cert.sign_p7s(cert, "peticao.pdf")                # -> peticao.pdf.p7s (attached, CAdES-BES)
a1cert.uninstall(cert)                              # limpeza ao final
```

Para conferir um certificado no servidor antes de usar em produção:

```bash
docker run --rm --shm-size=2g -e USE_XVFB=1 -e USE_OPENBOX=1 \
  -e A1_PFX_URL="https://exemplo.com/certificado.pfx" \
  -e A1_PFX_PASSWORD_FILE=/run/secrets/a1 -v "$PWD/a1-senha.txt:/run/secrets/a1:ro" \
  ghcr.io/nailtongomes/rpa-worker-selenium:latest python /app/a1_check.py
```

Ele abre o `.pfx`, mostra titular/CPF/validade, assina um PDF (`.p7s` e PAdES), confere se o
Java/PJeOffice abre o arquivo e se Chrome, SeleniumBase UC e Firefox apresentam o certificado
a um servidor HTTPS local. Senha com acento ou "ç" é recusada pelo Java/PJeOffice; o
verificador avisa, e `a1cert.export_pfx()` regrava o arquivo com outra senha.
A cadeia de um A1 ICP-Brasil é validada até as raízes oficiais do ITI, que vêm na imagem em
`/opt/icp-brasil` (`a1cert.verify_chain(cert)`). Isso não muda a confiança TLS dos browsers.
Guia completo: [`docs/A1_CERTIFICATE_GUIDE.md`](docs/A1_CERTIFICATE_GUIDE.md); exemplo:
[`examples/scripts/example_a1_certificate.py`](examples/scripts/example_a1_certificate.py).

### Saída pela internet do cliente (relay, opcional)

Para clientes cujos sistemas só aceitam o IP do cliente (whitelist), todo o tráfego do
container (Chrome, SeleniumBase, Firefox, Python, PJeOffice) pode sair por um relay:

```bash
docker run -d --shm-size=2g \
  -e EGRESS_PROXY_URL='socks5://usuario:senha@relay.exemplo.com.br:1080' \
  -e EGRESS_EXPECTED_IP=200.200.200.200 \
  -e SCRIPT_URL=... -e USE_XVFB=1 -e USE_OPENBOX=1 \
  ghcr.io/nailtongomes/rpa-worker-selenium:latest
```

Fica desligado por padrão. Com o relay configurado e fora do ar, o container para em vez
de sair pelo IP do servidor. Com `WORKER_LOOP=1`, o relay é conferido antes de cada
iteração: se ele cair, a iteração é pulada e o worker volta sozinho quando o relay voltar. Requisitos do relay e a rotina de teste
(`python /app/egress_check.py`) estão em [`docs/EGRESS_RELAY.md`](docs/EGRESS_RELAY.md).

### Preflight: o worker está pronto?

```bash
docker exec worker-01 python /app/preflight.py --json /data/preflight.json
```

Um comando, um JSON. Confere se Chrome, SeleniumBase UC e Firefox abrem. Se houver
`A1_PFX_URL`, roda o `a1_check.py`; se houver `EGRESS_PROXY_URL`, roda o
`egress_check.py`. `--url https://sistema...` confere se o worker alcança os sistemas.
Termina com exit 0 se nada falhou. Um browser que só abre na segunda tentativa (máquina com
pouca CPU) vira aviso, não falha.

Antes dos browsers, o preflight confere o ambiente do container e só avisa, sem reprovar:
`/dev/shm` abaixo de 1 GB (o Chrome trava com "page crash"; use `--shm-size=1g`), disco livre
abaixo de 2 GB, limite de memória abaixo do recomendado (2 GB com `USE_PJEOFFICE=1`, 1 GB sem),
menos de 1 CPU e relógio com mais de 30 s de diferença. O relógio é comparado com o horário de um
servidor HTTPS (`--clock-url`, `PREFLIGHT_CLOCK_URL`, `off` desliga), pela saída configurada:
com relay, passa pelo relay. O JSON traz também a imagem (`"imagem"`: revisão, tag, arquitetura,
browsers).

Para o worker conferir isso sozinho ao subir, use `PREFLIGHT_ON_START=1` (desligado por padrão). O
preflight roda depois dos serviços (Xvfb, PJeOffice...) e antes da primeira tarefa. Se falhar, o
container para com exit 1 e a mensagem diz o que falhou, em vez de quebrar no meio do primeiro
processo. O relatório fica em `/app/logs/preflight.json`. `PREFLIGHT_ARGS` passa opções, por exemplo
`PREFLIGHT_ARGS="--browsers chrome --url https://pje.tjxx.jus.br"` para conferir só o Chrome e o
sistema que o worker usa.

### Qual imagem está rodando?

A primeira linha do log diz a tag, a arquitetura, a data do build e os browsers:

```text
🏷️  Imagem sha-4eda8ad (arm64) · build 20261124-153000 · Chrome 158.0.8127.36 · Firefox 153.7.0esr
```

`python /app/image_info.py --json` mostra o mesmo em JSON (gravado no build em `/app/image_info.json`).
Um build local, sem `IMAGE_REVISION`, aparece como `dev`.

### Quanto o script consumiu (para dimensionar)

Ao fim de cada execução (`SCRIPT_URL`, cada iteração do loop e cada tarefa do standby), o log mostra
a média, o p95 e o pico de CPU e de memória do container, e sugere quanto reservar:

```text
📊 Recursos de tarefa.py (exit 0, 2m31s; cgroup v2 (container inteiro), 151 amostras)
   CPU: média 0,62 núcleo · p95 0,90 núcleo · pico 1,00 núcleo (limite 1,00 núcleo)
   memória: início 410 MB · média 812 MB · pico 1,13 GB (limite 2,00 GB, 56%)
   picos: memória aos 1m48s · CPU aos 12s
   por processo (CPU média · memória média / pico; memória PSS, aproximada):
     Chrome                   0,41 núcleo (66%) · 520 MB / 780 MB
     PJeOffice (Java)         0,12 núcleo (20%) · 190 MB / 210 MB
     script (Python)          0,04 núcleo (6%) · 60 MB / 75 MB
     Xvfb/OpenBox/VNC         0,02 núcleo (3%) · 32 MB / 32 MB
     chromedriver/geckodriver 0,01 núcleo (1%) · 14 MB / 15 MB
     outros                   0,01 núcleo (2%) · 25 MB / 29 MB
   💡 reserva sugerida: memória 1,41 GB (pico + 25%) · CPU 1,00 núcleo (p95)
RESOURCE_SUMMARY {"rotulo": "tarefa.py", "cpu": {...}, "memoria": {...}, "processos": {...}, "sugestao": {...}}
```

- É o container inteiro (script, browsers, Xvfb, PJeOffice), medido pelo cgroup como no `docker stats`.
  É isso que conta para a reserva. O "início" mostra quanto já estava em uso antes do script.
- "Por processo" diz quem consumiu, lido do `/proc` do container: CPU média de cada grupo (e a fatia
  dela na CPU do container) e memória média/pico. A memória por processo é a PSS (páginas
  compartilhadas divididas entre os processos), uma aproximação: a soma não bate exatamente com o total.
  "Picos" diz em que momento da execução foram os picos do container. `RESOURCE_PROCESSES=0` desliga a divisão.
- Avisa quando a CPU bateu no limite (`--cpus`) por 10% do tempo ou mais, porque aí a necessidade real
  é maior que a medida, e quando o kernel matou processos por falta de memória (OOM).
- A linha `RESOURCE_SUMMARY` é JSON para o orquestrador. A mesma linha vai para `/app/logs/resources.jsonl`.
  Para juntar várias execuções (média, pico médio e pico máximo por script, com a reserva sugerida
  para o pior caso):

```bash
docker exec worker-01 python /app/resource_usage.py report
```

Para medir um comando avulso: `python /app/resource_usage.py run -- python meu_script.py`.
`RESOURCE_SUMMARY=0` desliga. O exit code do script não muda.

### Tokens nas URLs

`SCRIPT_URL`/`HELPER_URLS` podem levar token (GitHub raw, S3/GCS pré-assinada, SAS do Azure,
`https://usuario:token@...`). O log mostra só o caminho: usuário/senha e o valor de todo
parâmetro da query viram `***`.

### Conferir o script baixado (`SCRIPT_SHA256`)

Com `SCRIPT_SHA256=<saída do sha256sum>`, o worker só executa o `SCRIPT_URL` se o arquivo baixado
tiver exatamente esse hash. Se não tiver, o arquivo é apagado, o download não é repetido e o container
sai com erro. Protege contra um script trocado no caminho ou na origem, já que o worker roda com o A1
carregado. Gere o hash com `sha256sum meu-script.py`. Os `HELPER_URLS` não são conferidos.

### Container reiniciado (`docker restart`, política de restart)

O `/tmp` do container sobrevive ao restart, e com ele as travas da execução anterior. Antes de subir
qualquer serviço, o entrypoint remove o que ficou para trás:

- o lock do Xvfb (`/tmp/.X99-lock`), que impedia o Xvfb de subir com "Server is already active for display 99";
- as travas de perfil do Chrome (`SingletonLock`/`Socket`/`Cookie` em `/tmp`, `/app` e `/root`) e do Firefox
  (`lock`);
- os perfis temporários dos browsers.

Uma trava só é removida se o processo dono não estiver rodando: um Xvfb vivo no display é reaproveitado.
Se o Xvfb não subir, o log mostra o erro dele na hora, sem esperar 10 s.

Para workers que ficam no ar por muito tempo, `LOG_MAX_MB=50` (desligado por padrão) roda os arquivos de
`/app/logs` acima desse tamanho, na partida e entre as iterações do loop: o conteúdo vai para `<arquivo>.1` e o
arquivo recomeça vazio.

### Sem `SCRIPT_URL`

O container executa o comando passado (padrão: `python --version`). Com `WORKER_LOOP=1`
e sem `SCRIPT_URL`, roda o smoke test embutido (`/app/smoke_test.py`) em loop.
O smoke test abre `TARGET_URL` (padrão: página deste projeto no GitHub) com SeleniumBase UC
e **falha** se o browser falhar; `SMOKE_ALLOW_REQUESTS_FALLBACK=1` restaura o comportamento
antigo (aceitar o fallback via `requests`).

---

## Variáveis de ambiente

### Execução

| Variável | Padrão | Descrição |
|---|---|---|
| `SCRIPT_URL` | — | Script Python baixado para `/tmp/` e executado |
| `SCRIPT_SHA256` | — | Hash esperado do `SCRIPT_URL`; diferente, o script não roda (exit 1, sem nova tentativa) |
| `HELPER_URLS` | — | Scripts auxiliares (separados por vírgula), salvos em `/app/src` |
| `WORKER_MODE` | `pull` | `pull` (baixa e executa) ou `standby` (servidor HTTP em `/app/task_server.py`) |
| `WORKER_LOOP` | `0` | `1` = executa em loop infinito |
| `WORKER_TIMEOUT` | `3600` | Timeout por iteração/tarefa (s) |
| `WORKER_KILL_AFTER` | `30` | Loop: segundos entre o SIGTERM do timeout e o SIGKILL, para o script que não para sozinho |
| `WORKER_RESTART_DELAY` | `120` | Pausa entre iterações (s) |
| `WORKER_CLEANUP` | `1` | Loop: depois de cada iteração fecha Chrome/Firefox/drivers que o script deixou abertos e apaga os perfis temporários deles; `0` mantém |
| `PREFLIGHT_ON_START` / `PREFLIGHT_ARGS` | `0` / — | `1` roda o `preflight.py` ao subir e para o container (exit 1) se falhar; `PREFLIGHT_ARGS` passa opções a ele |
| `RESOURCE_SUMMARY` | `1` | Resumo de CPU/memória (média, p95, pico) ao fim de cada execução; `0` desliga |
| `RESOURCE_SAMPLE_SECS` / `RESOURCE_LOG` | `1` / `/app/logs/resources.jsonl` | Intervalo das amostras (s) / onde gravar os resumos (`""` não grava) |
| `RESOURCE_PROCESSES` | `1` | Divisão do resumo por processo (Chrome, PJeOffice, Xvfb, script...); `0` desliga |
| `TASK_SERVER_PORT` | `8080` | Porta do modo standby |
| `TASK_AUTH_TOKEN` | — | Token Bearer do modo standby |
| `A1_PFX_URL` / `A1_PFX_PATH` | — | Certificado A1 (`.pfx`) por URL ou arquivo montado; usado por `a1cert.load_from_env()` |
| `A1_PFX_PASSWORD` / `A1_PFX_PASSWORD_FILE` | — | Senha do A1 (o arquivo, via Docker secret, tem prioridade e não aparece no `docker inspect`) |
| `EGRESS_PROXY_URL` / `EGRESS_PROXY_URL_FILE` | — (desligado) | Relay de saída: todo o tráfego sai pela internet do cliente ([guia](docs/EGRESS_RELAY.md)) |
| `EGRESS_REQUIRED` / `EGRESS_EXPECTED_IP` / `EGRESS_BYPASS` | `1` / — / — | Parar se o relay falhar / IP esperado na saída / destinos que saem direto |
| `CHROME_PROFILE_URL` | — | `.zip` de profile do Chrome; baixado no boot para `/usr/local/share/<nome>.zip`, caminho exportado em `CHROME_PROFILE_ZIP_PATH` |

### Display e serviços

| Variável | Padrão | Descrição |
|---|---|---|
| `USE_XVFB` | `0` | Display virtual (`DISPLAY=:99`) |
| `USE_OPENBOX` | `0` | Window manager (requer Xvfb) — necessário para diálogos de certificado |
| `USE_PJEOFFICE` | `0` | Inicia o PJeOffice Pro no boot |
| `USE_VNC` / `VNC_PORT` | `0` / `5900` | Servidor VNC (requer Xvfb); sem senha, a menos que `VNC_PASSWORD_FILE`/`VNC_PASSWORD` esteja definido |
| `VNC_PASSWORD_FILE` / `VNC_PASSWORD` | — | Senha do VNC/noVNC (o arquivo é preferível; só os 8 primeiros caracteres contam) |
| `VNC_VIEW_ONLY` | `0` | `1` = VNC/noVNC só para assistir (sem mouse/teclado) |
| `USE_NOVNC` / `NOVNC_PORT` | `0` / `6080` | VNC pelo navegador (requer VNC) |
| `SCREEN_WIDTH` × `SCREEN_HEIGHT` | `1600` × `900` | Resolução do Xvfb |
| `USE_SCREEN_RECORDING` | `0` | Grava a tela com FFmpeg (exige imagem com `ENABLE_FFMPEG=1`) |
| `PJEOFFICE_EXECUTABLE` | `/opt/pjeoffice/pjeoffice-pro.sh` | Executável do PJeOffice |
| `PJEOFFICE_JAVA_XMX` | — (o launcher usa `2048m`) | Teto de memória (heap) do Java do PJeOffice, ex.: `512m`; o preflight avisa quando o teto deixa menos de 1 GB para o Chrome |
| `LOG_MAX_MB` | `0` (desligado) | Arquivos de `/app/logs` maiores que isso (MB) são rodados (`.1`) |
| `PJEOFFICE_CONFIG_DIR` | `/app/.pjeoffice-pro` | Configuração do PJeOffice |
| `FIREFOX_PROFILE_DIR` | `/root/.mozilla/firefox/selenium.default-release` | Profile do Firefox com NSS |

---

## Release, tags e rollback

Um push na `main` que muda `Dockerfile.trixie`, `requirements.txt` ou `image/` dispara o
release: **build → `scripts/test-image.sh` na mesma imagem → push**. Se algum teste falhar,
nada é publicado e a `:latest` atual continua valendo. Um build noturno sem cache avisa
antes quando Debian/PyPI quebrarem algo.

Cada release publica três tags por arquitetura (amd64 e arm64, cada uma testada no seu runner nativo;
uma falha no arm64 não segura o amd64):

| Tag (amd64) | Tag (arm64) | Uso |
|---|---|---|
| `latest` | `latest-arm64` | produção |
| `sha-<7 chars>` | `sha-<7 chars>-arm64` | imagem de um commit específico |
| `YYYYMMDD-HHMMSS` | `YYYYMMDD-HHMMSS-arm64` | imagem de um momento específico (rollback) |

Cada release também cria um [GitHub Release](https://github.com/nailtongomes/rpa-worker-selenium/releases)
com o digest publicado, os PRs incluídos, o que mudou dentro da imagem (versões de
browsers/drivers/pip) e os **comandos de rollback** para a versão anterior.

Rollback: troque `:latest` pela tag anterior no seu compose/Kestra
(`docker pull ghcr.io/nailtongomes/rpa-worker-selenium:<tag>`), ou aponte a `:latest` de volta
para todos com `docker buildx imagetools create -t ...:latest ...:sha-<anterior>`. O GHCR guarda
só as 5 versões mais recentes de cada arquitetura.

---

## Estrutura do repositório

```
Dockerfile.trixie        # a imagem de produção
requirements.txt         # pacotes Python da imagem
image/
  app/                   # tudo que vai para /app dentro da imagem
    entrypoint.sh        #   orquestra Xvfb/OpenBox/PJeOffice/VNC e executa SCRIPT_URL
    preflight.py         #   "o worker está pronto?" (browsers + A1 + relay num JSON)
    pjeoffice_check.py   #   o PJeOffice assina? (botão "Testar" da página local dele)
    resource_usage.py    #   CPU/memória de cada execução (média, p95, pico) e relatório
    image_info.py        #   qual imagem é esta (revisão, arquitetura, browsers)
    a1cert.py ...        #   certificado A1 (a1_check.py) e relay de saída (egress_*.py)
    script_downloader.py #   download de SCRIPT_URL e HELPER_URLS
    task_server.py       #   modo standby (HTTP)
    smoke_test.py ...    #   smoke tests usados no CI e como fallback
    src/                 #   helpers de exemplo (/app/src)
  icp-brasil/            # raízes + ACs oficiais da ICP-Brasil (ITI) -> /opt/icp-brasil
  patch_chromedriver.py  # usado só durante o build (montado, não entra na imagem)
legacy/Dockerfile.trixie # Dockerfile anterior à imagem enxuta (referência, fora do release)
recipes/                 # receitas plug and play (shutup-and-run, Docker local, internet do cliente, servidor ARM)
tests/
  unit/                  # testes rápidos no host (sem Docker)
  image/                 # testes que rodam DENTRO da imagem
examples/
  server/                # N workers em um servidor: docker-compose (4 workers) e workers.sh
  compose/               # docker-compose de worker, standby, debug e Caddy
  scripts/               # scripts Python de exemplo
docs/                    # guias (worker, certificados A1/CA, VNC, testes) e baseline da imagem
scripts/                 # test-image.sh (portão), run-recipe.py, image-snapshot.sh, release-notes.sh, update-icp-brasil.py
.github/workflows/       # ci.yml (PR), build-push-ghcr.yml (release com testes), nightly.yml
```

Só o que está em `image/` e o `requirements.txt` entram no contexto de build
(o [`.dockerignore`](.dockerignore) é uma allowlist).

---

## Desenvolvimento

### Testes unitários (segundos, sem Docker)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

### Build local igual ao de produção

```bash
docker build -f Dockerfile.trixie \
  --build-arg BUILD_PJEOFFICE=1 --build-arg ENABLE_PDF_TOOLS=1 \
  --build-arg ENABLE_VNC=1 --build-arg ENABLE_NOVNC=1 \
  -t rpa-worker:local .
```

### Portão de qualidade da imagem

O mesmo script roda no CI de todo PR, antes de todo release e toda noite:

```bash
scripts/test-image.sh rpa-worker:local                     # completo
RUN_ONLINE_TESTS=0 scripts/test-image.sh rpa-worker:local  # sem internet
```

Ele valida o contrato da imagem, todos os browsers (local e na página do projeto no
GitHub), certificado A1 (ICP de teste), relay de saída, Xvfb/OpenBox/PJeOffice/VNC/noVNC, worker em loop, execução única, propagação de
erro e modo standby. Veja [`docs/TESTING.md`](docs/TESTING.md).

### Comparar a imagem antes/depois de uma mudança

```bash
scripts/image-snapshot.sh ghcr.io/nailtongomes/rpa-worker-selenium:latest snapshots/latest
scripts/image-snapshot.sh rpa-worker:local snapshots/local
diff -ru snapshots/latest snapshots/local
```

Mais detalhes em [`docs/TESTING.md`](docs/TESTING.md).

---

## Documentação

- [recipes/](recipes/README.md) — receitas plug and play (PC com shutup-and-run, Docker local, internet do cliente, servidor ARM)
- [docs/WORKER.md](docs/WORKER.md) — worker em loop e modo standby
- [docs/EGRESS_RELAY.md](docs/EGRESS_RELAY.md) — relay de saída (internet do cliente): variáveis, requisitos do relay e rotina de teste
- [docs/A1_CERTIFICATE_GUIDE.md](docs/A1_CERTIFICATE_GUIDE.md) — certificado A1: `a1cert`, `.p7s`, PAdES, `a1_check.py` e problemas conhecidos
- [docs/CA_RUNTIME_MANAGEMENT.md](docs/CA_RUNTIME_MANAGEMENT.md) — CAs em tempo de execução
- [docs/VNC_QUICKSTART.md](docs/VNC_QUICKSTART.md) — debug visual com VNC/noVNC
- [docs/VNC_CADDY_PROXY.md](docs/VNC_CADDY_PROXY.md) — VNC atrás de proxy reverso
- [docs/FULL_SMOKE_TEST.md](docs/FULL_SMOKE_TEST.md) — smoke test completo
- [docs/TESTING.md](docs/TESTING.md) — estratégia de testes
- [AGENTS.md](AGENTS.md) — guia para agentes de IA trabalhando neste repositório

## Licença

[MIT](LICENSE)
