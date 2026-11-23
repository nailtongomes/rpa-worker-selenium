# Testes

A regra é simples: **nenhuma imagem chega à `:latest` sem passar pelo mesmo portão de
qualidade** — `scripts/test-image.sh` — e nenhuma falha de teste é mascarada.

| Nível | Onde roda | Tempo | Quando |
|---|---|---|---|
| `tests/unit/` | host, sem Docker | ~5 s | todo PR (`ci.yml` → `unit-tests`) |
| `scripts/test-image.sh` | dentro da imagem | ~3–5 min | todo PR, **antes de todo release**, toda noite |

## Testes unitários (`tests/unit/`)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Cobrem: entrypoint (sintaxe, shellcheck, defaults do contrato, ordem dos serviços,
SIGTERM), Dockerfile x `.dockerignore` x build-args, `script_downloader` (com servidor
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
| contrato da imagem | `tests/image/test_contract.py`: arquivos de `/app`, Chrome = ChromeDriver, Firefox + profile com NSS, policies do Chrome graváveis, ferramentas (xdotool, certutil, ImageMagick, Java, x11vnc, noVNC...), módulos Python, defaults de ambiente |
| browsers headless sem display | `tests/image/test_browsers.py` sem Xvfb |
| serviços + browsers + integração | Xvfb + OpenBox + PJeOffice + VNC + noVNC ligados: `test_services.py`, `test_browsers.py` (inclui UC headful) e `trixie_integration_test.py` |
| `smoke_test.py` | o script padrão da imagem agora **falha** se o browser falhar |
| worker em loop | `WORKER_LOOP=1` baixa `SCRIPT_URL` + `HELPER_URLS` e executa ≥ 2 iterações |
| execução única | `SCRIPT_URL` executa e o helper de `/app/src` é importável |
| falha propaga exit code | script com `sys.exit(3)` => container termina com erro |
| comando direto | `docker run <imagem> python --version` |
| modo standby | `/health` = 200 e `/task` sem token = 401 |

Os cenários com script usam um servidor HTTP **dentro do container** servindo
`tests/image/fixtures/` (página de teste, `job_ok.py`, `job_fail.py`, `helper_mod.py`),
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
| `build-push-ghcr.yml` | push na `main` que muda `Dockerfile.trixie`, `requirements.txt` ou `image/**` (ou manual) | build (sem push) → `test-image.sh` na **mesma** imagem → diff com a `:latest` atual → `docker push` das tags `latest`, `sha-<7>`, `YYYYMMDD-HHMMSS` |
| `nightly.yml` | todo dia 04:17 (Brasília) e manual | build **sem cache** + `test-image.sh` + relatório do que mudaria (Debian/PyPI) + variante com FFmpeg (gravação de tela) |

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
- `oscrypto` está no `requirements.txt` para os scripts de automação; o teste garante que
  ele carrega o backend OpenSSL.
