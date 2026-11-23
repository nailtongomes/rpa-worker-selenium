# Testes

Os testes ficam em dois níveis, separados por onde rodam:

| Pasta | Onde roda | Tempo | O que garante |
|---|---|---|---|
| `tests/unit/` | host, sem Docker | segundos | entrypoint (sintaxe, shellcheck, defaults, ordem dos serviços), Dockerfile x `.dockerignore`, build-args do release, `script_downloader`, `task_server`, compose de exemplo |
| `tests/image/` | **dentro** da imagem | minutos | browsers, SeleniumBase, Xvfb/OpenBox, PDF/imagem, certificados |

Além deles, a imagem traz smoke tests próprios em `/app` (`smoke_test.py`,
`test_browser_drivers.py`, `smoke_test_clearcote.py`, `full_smoke_test.py`), usados pelo CI.

## Testes unitários

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest                       # usa testpaths = tests/unit (pytest.ini)
```

O `pytest.ini` coloca `image/app` no `PYTHONPATH`, então os testes importam
`script_downloader`, `smoke_test`, `task_server` etc. direto do código que vai para a imagem.
O teste de shellcheck é pulado se o `shellcheck` não estiver instalado (no CI ele está).

## Testes dentro da imagem

Os testes de `tests/` **não** são copiados para a imagem de produção. Para rodá-los,
monte o repositório no container:

```bash
docker run --rm --shm-size=2g -v "$PWD:/repo:ro" -w /tmp \
  -e USE_XVFB=1 -e USE_OPENBOX=1 \
  rpa-worker:local \
  bash -c "sleep 5 && pytest -p no:cacheprovider -p no:seleniumbase --timeout=180 \
           -m 'trixie and integration' /repo/tests/image/trixie_integration_test.py"
```

- `-p no:seleniumbase`: o plugin pytest do SeleniumBase aborta a sessão se `--timeout`
  (pytest-timeout) for usado. Os testes usam `Driver`/`sb_cdp` diretamente, então o plugin
  não é necessário.
- `-w /tmp`: o SeleniumBase grava `downloaded_files/` no diretório atual; o repo está montado
  como somente leitura.

Ou use o script, que faz build + três rodadas (sem display, com Xvfb, com Xvfb + OpenBox):

```bash
scripts/test_trixie_docker.sh all     # build + testes
scripts/test_trixie_docker.sh test    # só testes (imagem rpa-worker-trixie:test já construída)
```

Certificado A1 (opcional): defina `A1_P12_PATH` e `A1_P12_PASSWORD` e monte o arquivo.
Sem eles, os testes de certificado são pulados.

## Validação real dos browsers: `tests/image/test_project_page.py`

Abre a página do próprio projeto (`https://github.com/nailtongomes/rpa-worker-selenium/`)
e confere que o título contém `rpa-worker-selenium` com:

- `requests` (isola problema de rede de problema de browser)
- Selenium + Chrome headless (chromedriver da imagem)
- SeleniumBase headless, UC headless e **UC headful no Xvfb/OpenBox** (modo de produção)
- Firefox headless e headful com o profile `selenium.default-release`

Cada caso tenta até 3 vezes e **falha** se o browser não carregar a página.
No CI é um passo bloqueante. Localmente:

```bash
docker run --rm --shm-size=2g -v "$PWD:/repo:ro" -w /tmp -e USE_XVFB=1 -e USE_OPENBOX=1 \
  rpa-worker:local bash -c "sleep 5 && pytest -p no:cacheprovider -p no:seleniumbase \
  --timeout=300 -v /repo/tests/image/test_project_page.py"
```

Outra URL/título: `-e PROJECT_URL=... -e EXPECTED_TEXT=...`.
Os smoke tests da imagem (`smoke_test.py`, `full_smoke_test.py`, `test_browser_drivers.py`)
também usam a página do projeto como URL padrão.

## Comparando imagens (antes/depois)

`scripts/image-snapshot.sh` gera uma "foto" determinística de uma imagem: versões de
browsers e drivers, `pip freeze`, `dpkg`, variáveis de ambiente (segredos mascarados),
entrypoint e arquivos de `/app`, `/opt` e `/usr/local/bin`.

```bash
scripts/image-snapshot.sh ghcr.io/nailtongomes/rpa-worker-selenium:latest snapshots/latest
scripts/image-snapshot.sh rpa-worker:local snapshots/local
diff -ru snapshots/latest snapshots/local
```

A foto da imagem de produção usada como referência na reorganização está em
[`docs/baseline/`](baseline/).

## CI (`.github/workflows/smoke-test.yml`)

| Job | O que faz |
|---|---|
| `unit-tests` | `pytest` no host (~1 min) |
| `trixie-smoke-test` | build base + `smoke_test.py`, `test_browser_drivers.py`, ClearCote, profile do Firefox |
| `trixie-pjeoffice-test` | build com PJeOffice + processos Xvfb/OpenBox/PJeOffice |
| `trixie-novnc-test` | build com VNC/noVNC + processos |
| `trixie-screen-recording-test` | build com FFmpeg + arquivo `.mp4` gerado |
| `trixie-integration-test` | build **idêntico ao do release** + `tests/image/test_project_page.py` (**bloqueante**) + `tests/image/trixie_integration_test.py` (ainda não bloqueia, ver abaixo) |

### Limitações conhecidas (tratadas na Fase 2)

- Os passos de integração terminam com `|| exit 0`: falhas aparecem no log, mas não quebram o CI.
  Até a Fase 1 a suíte **nem chegava a rodar**: os testes não estavam na imagem e o
  `--timeout` derrubava o plugin do SeleniumBase.
- Resultado atual da suíte (idêntico na `:latest` de produção e na imagem reorganizada):
  14 passam, 3 pulados (A1 sem certificado, `xwd`) e 3 falham:
  `test_chrome_cdp` (título `None`), `test_read_pdf_with_pymupdf` (documento usado após
  `close()`) e `test_oscrypto_not_installed` (ver abaixo).
- `smoke_test.py` retorna sucesso mesmo quando o SeleniumBase falha (cai no fallback com
  `requests`), então não detecta Chrome quebrado. Selenium, SeleniumBase e UC funcionam
  normalmente quando testados diretamente.
- O release (`build-push-ghcr.yml`) não espera o CI: publica `:latest` mesmo com teste vermelho.
- São 5 builds com combinações diferentes de flags; nenhum é idêntico ao de produção
  (`BUILD_PJEOFFICE=1 ENABLE_PDF_TOOLS=1 ENABLE_VNC=1 ENABLE_NOVNC=1`).
- `tests/image/trixie_integration_test.py` exige que `oscrypto` **não** esteja instalado,
  mas o `requirements.txt` o instala explicitamente. Decidir qual dos dois está certo.
