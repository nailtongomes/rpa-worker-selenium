# rpa-worker-selenium

Imagem Docker de produção para automação web (RPA) em sistemas judiciais brasileiros:
**Chrome + Firefox + Selenium/SeleniumBase**, execução *headful* com Xvfb + OpenBox,
**PJeOffice Pro** e suporte a certificados digitais (A1/NSS).

```bash
docker pull ghcr.io/nailtongomes/rpa-worker-selenium:latest
```

A imagem é construída a partir de [`Dockerfile.trixie`](Dockerfile.trixie) (Debian 13 "Trixie")
e publicada no GHCR pelo GitHub Actions a cada mudança na `main`.

---

## O que vem na imagem

| Componente | Versão / origem | Observação |
|---|---|---|
| Debian | 13 (Trixie) | locale `pt_BR.UTF-8`, `TZ=America/Sao_Paulo` |
| Python | 3.13 (venv em `/opt/venv`) | pacotes em [`requirements.txt`](requirements.txt) |
| Google Chrome for Testing + ChromeDriver | `ARG CHROME_VERSION` | mesma versão, baixados juntos |
| Firefox ESR (pt-BR) + GeckoDriver | `ARG FIREFOX_VERSION` / `ARG GECKODRIVER_VERSION` | profile `selenium.default-release` com NSS pronto |
| SeleniumBase | **sempre a mais recente do PyPI** no momento do release | camada própria, renovada a cada release |
| PJeOffice Pro + Java 21 | 2.5.16 | `BUILD_PJEOFFICE=1` no release |
| ImageMagick + Ghostscript | Debian | `ENABLE_PDF_TOOLS=1` no release |
| x11vnc + noVNC | Debian / GitHub | `ENABLE_VNC=1`, `ENABLE_NOVNC=1` no release |
| FFmpeg (gravação de tela) | — | **não incluso** na imagem publicada (`ENABLE_FFMPEG=0`) |

As versões exatas da imagem atual estão registradas em
[`docs/baseline/`](docs/baseline/) (gerado por `scripts/image-snapshot.sh`).

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
Guia completo: [`docs/A1_CERTIFICATE_GUIDE.md`](docs/A1_CERTIFICATE_GUIDE.md); exemplo:
[`examples/scripts/example_a1_certificate.py`](examples/scripts/example_a1_certificate.py).

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
| `HELPER_URLS` | — | Scripts auxiliares (separados por vírgula), salvos em `/app/src` |
| `WORKER_MODE` | `pull` | `pull` (baixa e executa) ou `standby` (servidor HTTP em `/app/task_server.py`) |
| `WORKER_LOOP` | `0` | `1` = executa em loop infinito |
| `WORKER_TIMEOUT` | `3600` | Timeout por iteração/tarefa (s) |
| `WORKER_RESTART_DELAY` | `120` | Pausa entre iterações (s) |
| `TASK_SERVER_PORT` | `8080` | Porta do modo standby |
| `TASK_AUTH_TOKEN` | — | Token Bearer do modo standby |
| `A1_PFX_URL` / `A1_PFX_PATH` | — | Certificado A1 (`.pfx`) por URL ou arquivo montado; usado por `a1cert.load_from_env()` |
| `A1_PFX_PASSWORD` / `A1_PFX_PASSWORD_FILE` | — | Senha do A1 (o arquivo, via Docker secret, tem prioridade e não aparece no `docker inspect`) |
| `CHROME_PROFILE_URL` | — | `.zip` de profile do Chrome; baixado no boot para `/usr/local/share/<nome>.zip`, caminho exportado em `CHROME_PROFILE_ZIP_PATH` |

### Display e serviços

| Variável | Padrão | Descrição |
|---|---|---|
| `USE_XVFB` | `0` | Display virtual (`DISPLAY=:99`) |
| `USE_OPENBOX` | `0` | Window manager (requer Xvfb) — necessário para diálogos de certificado |
| `USE_PJEOFFICE` | `0` | Inicia o PJeOffice Pro no boot |
| `USE_VNC` / `VNC_PORT` | `0` / `5900` | Servidor VNC sem senha (requer Xvfb) |
| `USE_NOVNC` / `NOVNC_PORT` | `0` / `6080` | VNC pelo navegador (requer VNC) |
| `SCREEN_WIDTH` × `SCREEN_HEIGHT` | `1600` × `900` | Resolução do Xvfb |
| `USE_SCREEN_RECORDING` | `0` | Grava a tela com FFmpeg (exige imagem com `ENABLE_FFMPEG=1`) |
| `PJEOFFICE_EXECUTABLE` | `/opt/pjeoffice/pjeoffice-pro.sh` | Executável do PJeOffice |
| `PJEOFFICE_CONFIG_DIR` | `/app/.pjeoffice-pro` | Configuração do PJeOffice |
| `FIREFOX_PROFILE_DIR` | `/root/.mozilla/firefox/selenium.default-release` | Profile do Firefox com NSS |

---

## Release, tags e rollback

Um push na `main` que muda `Dockerfile.trixie`, `requirements.txt` ou `image/` dispara o
release: **build → `scripts/test-image.sh` na mesma imagem → push**. Se algum teste falhar,
nada é publicado e a `:latest` atual continua valendo. Um build noturno sem cache avisa
antes quando Debian/PyPI quebrarem algo.

Cada release publica três tags:

| Tag | Uso |
|---|---|
| `latest` | produção |
| `sha-<7 chars>` | imagem de um commit específico |
| `YYYYMMDD-HHMMSS` | imagem de um momento específico (rollback) |

Rollback: troque `:latest` pela tag anterior no seu compose/Kestra
(`docker pull ghcr.io/nailtongomes/rpa-worker-selenium:<tag>`).

---

## Estrutura do repositório

```
Dockerfile.trixie        # a imagem de produção
requirements.txt         # pacotes Python da imagem
image/
  app/                   # tudo que vai para /app dentro da imagem
    entrypoint.sh        #   orquestra Xvfb/OpenBox/PJeOffice/VNC e executa SCRIPT_URL
    script_downloader.py #   download de SCRIPT_URL e HELPER_URLS
    task_server.py       #   modo standby (HTTP)
    smoke_test.py ...    #   smoke tests usados no CI e como fallback
    src/                 #   helpers de exemplo (/app/src)
  patch_chromedriver.py  # usado só durante o build
tests/
  unit/                  # testes rápidos no host (sem Docker)
  image/                 # testes que rodam DENTRO da imagem
examples/
  server/                # N workers em um servidor: docker-compose (4 workers) e workers.sh
  compose/               # docker-compose de worker, standby, debug e Caddy
  scripts/               # scripts Python de exemplo
docs/                    # guias (worker, certificados A1/CA, VNC, testes) e baseline da imagem
scripts/                 # test-image.sh (portão de qualidade) e image-snapshot.sh
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
GitHub), certificado A1 (ICP de teste), Xvfb/OpenBox/PJeOffice/VNC/noVNC, worker em loop, execução única, propagação de
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

- [docs/WORKER.md](docs/WORKER.md) — worker em loop e modo standby
- [docs/A1_CERTIFICATE_GUIDE.md](docs/A1_CERTIFICATE_GUIDE.md) — certificado A1: `a1cert`, `.p7s`, PAdES, `a1_check.py` e problemas conhecidos
- [docs/CA_RUNTIME_MANAGEMENT.md](docs/CA_RUNTIME_MANAGEMENT.md) — CAs em tempo de execução
- [docs/VNC_QUICKSTART.md](docs/VNC_QUICKSTART.md) — debug visual com VNC/noVNC
- [docs/VNC_CADDY_PROXY.md](docs/VNC_CADDY_PROXY.md) — VNC atrás de proxy reverso
- [docs/FULL_SMOKE_TEST.md](docs/FULL_SMOKE_TEST.md) — smoke test completo
- [docs/TESTING.md](docs/TESTING.md) — estratégia de testes
- [AGENTS.md](AGENTS.md) — guia para agentes de IA trabalhando neste repositório

## Licença

[MIT](LICENSE)
