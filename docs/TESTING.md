# Testes

A regra é simples: **nenhuma imagem chega à `:latest` sem passar pelo mesmo portão de
qualidade** — `scripts/test-image.sh` — e nenhuma falha de teste é mascarada.

| Nível | Onde roda | Tempo | Quando |
|---|---|---|---|
| `tests/unit/` | host, sem Docker | ~5 s | todo PR (`ci.yml` → `unit-tests`) |
| `scripts/test-image.sh` | dentro da imagem | ~3–5 min | todo PR, **antes de todo release**, toda noite |

O portão roda duas vezes: na imagem amd64 (`:latest`, runner `ubuntu-latest`) e na arm64
(`:latest-arm64`, runner `ubuntu-24.04-arm`, nativo, sem emulação). Os mesmos cenários valem para as duas;
o contrato confere que Chrome, drivers, Firefox e o Java do PJeOffice são da arquitetura da máquina.

## Testes unitários (`tests/unit/`)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Cobrem: entrypoint (sintaxe, shellcheck, defaults do contrato, ordem dos serviços,
SIGTERM, espera sem trabalho, POST no fim), `worker_events` (status.json, ping, envio do log, URLs fora do log),
`browser_stability` (classificação das falhas, servidor de falhas controladas, cgroup, `/proc`, porta do driver),
Dockerfile x `.dockerignore` x build-args (SeleniumBase fixo, policy de pop-ups, drivers do SeleniumBase = ChromeDriver da imagem), `script_downloader` (com servidor
HTTP local), `task_server`, `smoke_test`, exemplos de compose, scripts `.sh` e **as regras
dos workflows** (`test_workflows.py`): o release só faz push depois do portão, CI/nightly
constroem com as mesmas flags do release e não existe `|| exit 0` em nenhum workflow.

## Portão da imagem (`scripts/test-image.sh`)

```bash
docker build -f Dockerfile.trixie --build-arg BUILD_PJEOFFICE=1 --build-arg ENABLE_PDF_TOOLS=1 \
  --build-arg ENABLE_VNC=1 --build-arg ENABLE_NOVNC=1 -t rpa-worker:local .

scripts/test-image.sh rpa-worker:local                       # completo (precisa de internet)
RUN_ONLINE_TESTS=0 scripts/test-image.sh rpa-worker:local    # só offline
```

Cenários (cada um é um `docker run` separado; qualquer falha => exit 1):

| Cenário | O que garante |
|---|---|
| contrato da imagem | `tests/image/test_contract.py`: arquivos de `/app`, `/app/image_info.json` batendo com a arquitetura e os browsers, cgroup legível para o resumo de recursos, Chrome = ChromeDriver, Firefox + profile com NSS, policies do Chrome graváveis, ferramentas (xdotool, certutil, ImageMagick, Java, x11vnc, noVNC...), módulos Python, defaults de ambiente |
| browsers headless sem display | `tests/image/test_browsers.py` sem Xvfb |
| serviços + browsers + integração | Xvfb + OpenBox + PJeOffice (com `PJEOFFICE_JAVA_XMX=512m`, conferido no processo Java) + VNC + noVNC ligados: `test_services.py` (inclui o **teste de assinatura do PJeOffice**: o Chrome clica em "Testar" na página local dele, o PJeOffice pede a senha, assina com um A1 de teste e devolve nome/CPF; senha errada precisa ser recusada), `test_browsers.py` (inclui UC headful) e `trixie_integration_test.py` |
| certificado A1 | `tests/image/test_a1_certificate.py` + `test_preflight.py` com uma ICP de teste gerada na hora: `.pfx` por URL + senha (AES, 3DES e RC2), senha errada/certificado vencido, PDF → `.p7s` attached (CAdES-BES) e detached, PDF assinado (PAdES), Java/PJeOffice lendo o `.pfx`, importação/limpeza no NSS, e Chrome, SeleniumBase UC e Firefox (headless e com janela) apresentando o certificado a um servidor HTTPS local que **exige** certificado de cliente; controles negativos sem o certificado; `/app/a1_check.py` e `/app/preflight.py` de ponta a ponta |
| receita shutup-and-run | [`recipes/shutup-and-run/teste-a1.json`](../recipes/shutup-and-run/teste-a1.json) rodada por `scripts/run-recipe.py` como o shutup-and-run roda num PC compartilhado (1 CPU, 2 GB sem swap, `--init`, pids 4096, sem portas, certificado repassado somente leitura em `/run/shutup-and-run/...`): o `preflight.py` precisa aprovar browsers + A1 + Java + assinatura no PJeOffice, e a senha não pode aparecer no log |
| relay de saída | `tests/image/test_egress.py` com relay SOCKS5 de teste ("internet falsa"): Python, curl, Java do PJeOffice, Chrome, UC e Firefox saem pelo relay; DNS resolvido no relay (hosts `.invalid`); WebRTC sem IP; policies em `chrome://policy`; localhost direto; A1 (mTLS) junto; `preflight.py` com o relay |
| relay de saída: proxy HTTP e falhas | proxy HTTP com senha; relay fora do ar, senha errada e esquema inválido **param** o container; `EGRESS_REQUIRED=0` só avisa; senha fora do log |
| `smoke_test.py` | o script padrão da imagem agora **falha** se o browser falhar |
| worker em loop | `WORKER_LOOP=1` baixa `SCRIPT_URL` + `HELPER_URLS` e executa ≥ 2 iterações, com o resumo de recursos em cada uma; as URLs levam usuário/senha e tokens na query, e nenhum deles pode aparecer no log |
| worker em loop com relay | relay derrubado no meio do loop: as iterações são puladas (o script não roda) e o worker retoma sozinho quando o relay volta |
| worker em loop: script travado | `job_stuck.py` deixa um Chrome aberto fora do grupo de processos e ignora o SIGTERM: no `WORKER_TIMEOUT` ele recebe SIGTERM, `WORKER_KILL_AFTER` depois SIGKILL, e antes da próxima iteração não sobra nem o script, nem o Chrome, nem o perfil temporário dele |
| restart do mesmo container | o container roda, sai e sobe de novo (`docker start`): o lock velho do Xvfb é removido e o Xvfb sobe (antes: "Server is already active for display 99" e o container caía); travas velhas de perfil do Chrome/Firefox somem; um log acima de `LOG_MAX_MB` é rodado |
| VNC com senha | `VNC_PASSWORD` + `VNC_VIEW_ONLY=1`: o servidor só oferece autenticação por senha (RFB tipo 2), com `-viewonly`; a senha não aparece no argv, no ambiente do comando nem em arquivo |
| `SCRIPT_SHA256` | hash certo roda o script; hash errado não roda, não tenta baixar de novo e sai com erro |
| preflight na partida | `PREFLIGHT_ON_START=1`: preflight ok deixa o script rodar; preflight falhando (A1 que não existe) para o container com exit 1 sem rodar o script |
| fim do container: log, telas, ping e status | Execução única que falha (exit 3), com `LOG_POST_URL` (token no caminho e na query), `LOG_POST_FULL=1`, `SCREENSHOT_ON_FAIL=1`, `PING_URL` e `WORKER_STATUS=1`, conferido num receptor dentro do container (`fixtures/log_receiver.py`). O exit code continua 3. Os pings são `/start` e `/3`. O POST multipart traz: no campo `dados`, as últimas linhas, `motivo` "falha", o resumo de recursos e o `status` (contadores e partida do Xvfb); o `worker.txt` completo; e as telas em JPEG. Nenhum segredo das URLs aparece no log. |
| loop sem trabalho + `docker stop` | `job_idle.py` sai com 75 e `WORKER_IDLE_EXIT_CODE=75`: a espera dobra (2 s, 4 s, 4 s, com teto de 4) e nada conta como falha. O `status.json` mostra `sem_trabalho` ≥ 3. O `docker stop` no meio da espera termina na hora e envia o log com `motivo` "parado". |
| execução única | `SCRIPT_URL` executa e o helper de `/app/src` é importável; o log começa com a linha da imagem e termina com o resumo de recursos (`📊` e `RESOURCE_SUMMARY`, com a divisão por processo) |
| falha propaga exit code | script com `sys.exit(3)` => container termina com exit 3, mesmo com o medidor de recursos no meio |
| limites do container | `--shm-size=64m -m 1g --cpus 0.5` com `USE_PJEOFFICE=1`: o preflight avisa sobre `/dev/shm`, memória e CPU **sem reprovar**; o `resource_usage.py` lê os limites e mede um pico de 300 MB alocados, atribuídos ao grupo do script na divisão por processo |
| estabilidade do browser: container sozinho | `/app/browser_stability.py` com 2 GB, 1 CPU, shm 2 GB, `--init` e Xvfb: `sequencial` e `uc_especial` (UC abrindo 503, reCAPTCHA e 403, a regressão do SeleniumBase 4.58) em `uc-headful`, + `externos` (páginas de teste do Selenium e httpbingo) com `RUN_ONLINE_TESTS=1`; site fora do ar é aviso, sessão/driver perdido reprova |
| estabilidade do browser: 3 containers simultâneos | mesmos limites, ao mesmo tempo: sem PJeOffice e com PJeOffice (`modos`, `sequencial`, `sessoes`, `recuperacao`, `uc_especial`) e uma sessão `prolongada` de 120 s; tabela com pico de memória, OOM kill, zombies, RSS do PJeOffice e degradação de tempo (aviso acima de 3x). Relatórios e diagnóstico das falhas em `test-results/stability/` ([detalhes](CHROMEDRIVER_STABILITY.md)) |
| comando direto | `docker run <imagem> python --version` |
| modo standby | `/health` = 200 e `/task` sem token = 401 |

Os cenários com script usam um servidor HTTP **dentro do container** servindo
`tests/image/fixtures/` (página de teste, `job_ok.py`, `job_fail.py`, `job_stuck.py`, `job_idle.py`, `helper_mod.py`),
então não dependem de serviços externos.

Resultados em `test-results/`: `junit-*.xml`, `screenshots/` (cada browser salva a tela),
`logs/` e `summary.md` (vai para o resumo do GitHub Actions).

### `tests/image/test_browsers.py`: online e offline

Cada browser abre **dois alvos** e confere o título:

- `local`: página de `tests/image/fixtures` (sem internet)
- `project`: `https://github.com/nailtongomes/rpa-worker-selenium/` (marker `online`)

Browsers: Selenium + Chrome headless, SeleniumBase headless, UC headless,
**UC headful no Xvfb/OpenBox** (modo de produção), Firefox headless/headful com o profile
`selenium.default-release` e SeleniumBase + Firefox. Há ainda um teste que digita e clica
num formulário com o driver UC. Cada visita tenta 3 vezes e **falha** se o browser não
carregar a página. Se só o alvo `project` falhar, o problema é rede/GitHub, não a imagem.

Outra URL: `-e PROJECT_URL=... -e EXPECTED_TEXT=...` (via `DOCKER_RUN_ARGS`).

### Rodando um teste isolado dentro da imagem

```bash
docker run --rm --shm-size=2g -v "$PWD:/repo:ro" -w /tmp -e USE_XVFB=1 -e USE_OPENBOX=1 \
  rpa-worker:local bash -c "sleep 5 && pytest -p no:cacheprovider -p no:seleniumbase \
  --timeout=300 -v /repo/tests/image/test_browsers.py -k uc_headful"
```

- `-p no:seleniumbase`: o plugin pytest do SeleniumBase aborta a sessão com `--timeout`
  (pytest-timeout); os testes usam `Driver`/`sb_cdp` diretamente.
- `-w /tmp`: o SeleniumBase grava `downloaded_files/` no diretório atual.

## Workflows

| Workflow | Quando | O que faz |
|---|---|---|
| `ci.yml` | todo PR e push na `main` | `unit-tests` → build com as flags do release → `test-image.sh` → ClearCote (informativo) |
| `build-push-ghcr.yml` | push na `main` que muda `Dockerfile.trixie`, `requirements.txt` ou `image/**` (ou manual) | build (sem push) → `test-image.sh` na **mesma** imagem → diff com a `:latest` atual → `docker push` das tags `latest`, `sha-<7>`, `YYYYMMDD-HHMMSS` → GitHub Release (`scripts/release-notes.sh`: digest, PRs, mudanças na imagem, rollback) |
| `nightly.yml` | todo dia 04:17 (Brasília) e manual | build **sem cache** + `test-image.sh` + relatório do que mudaria (Debian/PyPI) + **canário do SeleniumBase** (o mais novo do PyPI com `browser_stability.py`; verde = pode subir `SELENIUMBASE_VERSION`) + variante com FFmpeg (gravação de tela) + ACs da ICP-Brasil x ITI (falha se o ITI publicou AC nova: rode `scripts/update-icp-brasil.py`) |

Se o portão falhar no release, **nada é publicado** e a `:latest` atual continua em
produção. Falhas do nightly chegam por e-mail (notificação padrão do GitHub para workflows
agendados).

## Comparando imagens (antes/depois)

```bash
scripts/image-snapshot.sh ghcr.io/nailtongomes/rpa-worker-selenium:latest snapshots/latest
scripts/image-snapshot.sh rpa-worker:local snapshots/local
diff -ru snapshots/latest snapshots/local
```

A foto da imagem de produção usada como referência está em [`docs/baseline/`](baseline/).

## Achados documentados

- **SeleniumBase + Firefox precisa de servidor X mesmo em headless** (Selenium puro não).
  Em produção há sempre Xvfb; os testes refletem isso.
- **No modo UC do SeleniumBase, use `driver.get()`**: `driver.open()` desconecta o
  chromedriver e a chamada seguinte falha (era o bug do antigo `smoke_test.py`).
- **SeleniumBase 4.58+ no modo UC** perdia a sessão ~60 s depois de abrir página 4xx/5xx/reCAPTCHA
  (`Connection refused` na porta do ChromeDriver): o pop-up do `window.open()` era bloqueado. A imagem libera
  pop-ups por policy e o portão tem o cenário `uc_especial` ([detalhes](CHROMEDRIVER_STABILITY.md)).
- `oscrypto` está no `requirements.txt` para os scripts de automação; o teste garante que
  ele carrega o backend OpenSSL.
