# AGENTS.md — guia para agentes de IA

Este repositório produz **uma única imagem de produção**:
`ghcr.io/nailtongomes/rpa-worker-selenium:latest`, construída a partir de
[`Dockerfile.trixie`](Dockerfile.trixie). Ela roda automações (Selenium/SeleniumBase,
Chrome e Firefox, PJeOffice, certificados A1) contra sistemas judiciais brasileiros
e **está em produção**. Toda mudança deve preservar o comportamento atual,
a menos que o objetivo da tarefa seja justamente mudá-lo.

## Regra de ouro: o contrato da imagem

Usuários da imagem dependem do que está abaixo. Não mude nada disso sem pedido explícito:

- `ENTRYPOINT ["/app/entrypoint.sh"]`, `WORKDIR /app`, execução como root.
- Caminhos: `/app/entrypoint.sh`, `/app/script_downloader.py`, `/app/smoke_test.py`,
  `/app/task_server.py`, `/app/test_browser_drivers.py`, `/app/src/`, `/opt/chrome`,
  `/opt/firefox`, `/opt/pjeoffice`, `/opt/venv`, `/opt/novnc`,
  `/root/.mozilla/firefox/selenium.default-release`, `/etc/opt/chrome*/policies/managed`.
- Variáveis de ambiente e seus defaults (`USE_*`, `WORKER_*`, `SCRIPT_URL`, `HELPER_URLS`,
  `CHROME_PROFILE_URL`, `TASK_*`, `SCREEN_*`, `PJEOFFICE_*`). Os defaults do entrypoint
  estão travados em `tests/unit/test_entrypoint.py`.
- Build-args usados pelo release: `BUILD_PJEOFFICE=1`, `ENABLE_PDF_TOOLS=1`,
  `ENABLE_VNC=1`, `ENABLE_NOVNC=1`, `CHROME_PROFILE_URL`, `SELENIUMBASE_REFRESH`.

Para conferir se uma mudança alterou o contrato, compare snapshots
(veja "Validação" abaixo).

## Mapa do repositório

| Caminho | Papel |
|---|---|
| `Dockerfile.trixie` | imagem de produção (multi-stage: downloads → runtime) |
| `requirements.txt` | pacotes Python da imagem |
| `image/app/` | **tudo** que vai para `/app` na imagem (`COPY image/app/ /app/`) |
| `image/patch_chromedriver.py` | usado só no build (aplicado e apagado na mesma camada) |
| `.dockerignore` | **allowlist**: só `requirements.txt` e `image/` entram no contexto |
| `tests/unit/` | testes rápidos no host (sem Docker) — rodam com `pytest` |
| `tests/image/` | testes que rodam dentro da imagem (montando o repo em `/repo`) |
| `examples/compose/` | compose de worker, standby, debug (VNC) e Caddy |
| `examples/scripts/` | scripts de exemplo (não vão para a imagem) |
| `docs/` | guias de uso; `docs/baseline/` tem a foto da imagem de produção |
| `scripts/` | ferramentas de dev: `image-snapshot.sh`, `test_trixie_*.sh` |
| `.github/workflows/build-push-ghcr.yml` | release: build + push para o GHCR |
| `.github/workflows/smoke-test.yml` | CI: testes unitários + builds de teste |

## Como fazer mudanças comuns

**Adicionar um arquivo ao `/app` da imagem:** coloque-o em `image/app/`. Nada fora de
`image/` chega à imagem. Se for executável, marque no git (`git update-index --chmod=+x`).

**Adicionar um pacote Python:** edite `requirements.txt`. O SeleniumBase é atualizado
para a versão mais recente do PyPI logo depois, na mesma camada. Ele pode passar por cima
de pins do `requirements.txt` (hoje: `psutil==6.1.0` → roda 7.2.2). Pacotes
instalados em camadas posteriores, como o `websockify` do noVNC, também podem fazer isso
(hoje: `cryptography<47` → roda 50.0.2).

**Atualizar Chrome/Firefox:** altere `ARG CHROME_VERSION`, `ARG FIREFOX_VERSION` e
`ARG GECKODRIVER_VERSION` no estágio builder. Chrome e ChromeDriver usam a mesma versão
(Chrome for Testing). Valide com os testes de imagem antes de mesclar.

**Adicionar um pacote do sistema:** use `apt-get install -y --no-install-recommends`
e termine o mesmo `RUN` com `rm -rf /var/lib/apt/lists/*`. Coloque-o perto de pacotes
do mesmo tipo e lembre que camadas mais acima invalidam o cache de tudo que vem depois.

**Mexer no entrypoint:** mantenha `set -e`, funções pequenas e o padrão de log
`$(log_timestamp) <emoji> mensagem`. Serviços que dependem de outro (OpenBox → Xvfb,
noVNC → VNC) devem checar a dependência e pular com aviso, não falhar.

## Validação (faça antes de concluir qualquer tarefa)

1. **Testes unitários** (segundos):
   ```bash
   pip install -r requirements-dev.txt && pytest
   ```
2. **Build igual ao de produção** (quando tocar em `Dockerfile.trixie`, `requirements.txt` ou `image/`):
   ```bash
   docker build -f Dockerfile.trixie --build-arg BUILD_PJEOFFICE=1 --build-arg ENABLE_PDF_TOOLS=1 \
     --build-arg ENABLE_VNC=1 --build-arg ENABLE_NOVNC=1 -t rpa-worker:local .
   ```
3. **Smoke tests na imagem:**
   ```bash
   docker run --rm rpa-worker:local python /app/test_browser_drivers.py
   docker run --rm -e USE_XVFB=1 -e USE_OPENBOX=1 -e USE_PJEOFFICE=1 -e CHECK_PROCESSES=1 \
     rpa-worker:local bash -c "sleep 5 && python /app/smoke_test.py"
   scripts/test_trixie_docker.sh test   # suíte tests/image (repo montado em /repo)
   ```
   Dentro da imagem, rode pytest sempre com `-p no:seleniumbase` quando usar `--timeout`
   (o plugin do SeleniumBase aborta com pytest-timeout) e com o diretório de trabalho gravável.
4. **Contrato preservado:**
   ```bash
   scripts/image-snapshot.sh ghcr.io/nailtongomes/rpa-worker-selenium:latest snapshots/latest
   scripts/image-snapshot.sh rpa-worker:local snapshots/local
   diff -ru snapshots/latest snapshots/local
   ```
   Diferenças esperadas devem ser explicadas. Atualizações do Debian ou do PyPI desde o
   último release são normais; mudanças de path, env ou entrypoint não são.

## CI e release

- `smoke-test.yml` roda em push/PR para `main`: `unit-tests` (pytest) e cinco builds do
  Trixie com combinações de flags.
- `build-push-ghcr.yml` roda em push para `main` quando `Dockerfile.trixie` ou o próprio
  workflow mudam (e manualmente via `workflow_dispatch`). Publica `latest`, `sha-<7>` e
  `YYYYMMDD-HHMMSS`, e mantém as 5 tags mais recentes no GHCR.
- **Atenção:** hoje o release não espera o CI e não dispara sozinho com mudanças em
  `image/` ou `requirements.txt`. Isso será resolvido na Fase 2 (ver backlog).

## Convenções

- **Bash:** `#!/bin/bash` + `set -e`; variáveis `local`; aspas em toda expansão; `shellcheck`
  sem erros (o CI verifica `--severity=error`).
- **Python:** 3.13, docstrings, type hints quando ajudarem, `logging` em código novo.
  Testes com `pytest`, usando `assert` (nunca `return True/False`).
- **YAML:** 2 espaços; compose sem o campo `version` (obsoleto).
- **Dockerfile:** comentários em inglês no estilo já existente; blocos opcionais
  controlados por `ARG ENABLE_*`/`BUILD_*`; nunca `COPY . .`.
- **Docs:** README e AGENTS em português; links relativos.

## Segurança

- Nunca commitar segredos (`.env`, `.pfx`, `.p12`, `.pem`, `.key`). Use `.env.example`.
- VNC/noVNC não têm senha: só para debug em rede confiável ou atrás de proxy com auth
  (`docs/VNC_CADDY_PROXY.md`).
- `CHROME_PROFILE_URL` vira `ENV` na imagem publicada. É uma decisão consciente do mantenedor.

## Backlog da reforma

- [x] **Fase 0:** baseline da imagem de produção (`docs/baseline/`) e `scripts/image-snapshot.sh`.
- [x] **Fase 1:** remoção das imagens legadas, nova estrutura (`image/`, `tests/`, `examples/`, `docs/`),
  `.dockerignore` em allowlist, `COPY` explícito, SeleniumBase sempre na versão mais recente,
  compose de exemplo corrigidos, testes unitários consolidados e rodando no CI.
- [ ] **Fase 2:** release só publica após testes na mesma imagem (`sha-*` → testes → promove `latest`);
  gatilho do release inclui `image/**` e `requirements.txt`; um único build igual ao de produção
  no CI; remover `|| exit 0`; testes de imagem sem depender de sites externos; build noturno.
- [ ] **Fase 3:** alinhar `requirements.txt` com o que de fato roda (`cryptography`, `psutil`,
  `oscrypto`); revisar `set -e` x falha no download do profile; remover duplicação do loop no entrypoint.
