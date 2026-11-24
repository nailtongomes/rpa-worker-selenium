# AGENTS.md — guia para agentes de IA

Este repositório produz **uma única imagem de produção**:
`ghcr.io/nailtongomes/rpa-worker-selenium:latest`, construída a partir de
[`Dockerfile.trixie`](Dockerfile.trixie). O mesmo Dockerfile gera também a variante ARM64
(`:latest-arm64`, mesmo contrato) para servidores Ampere/Graviton. Ela roda automações (Selenium/SeleniumBase,
Chrome e Firefox, PJeOffice, certificados A1) contra sistemas judiciais brasileiros
e **está em produção**. Toda mudança deve preservar o comportamento atual,
a menos que o objetivo da tarefa seja justamente mudá-lo.

## Regra de ouro: o contrato da imagem

Usuários da imagem dependem do que está abaixo. Não mude nada disso sem pedido explícito:

- `ENTRYPOINT ["/app/entrypoint.sh"]`, `WORKDIR /app`, execução como root.
- Caminhos: `/app/entrypoint.sh`, `/app/script_downloader.py`, `/app/smoke_test.py`,
  `/app/task_server.py`, `/app/test_browser_drivers.py`, `/app/src/`, `/opt/chrome`,
  `/opt/firefox`, `/opt/pjeoffice`, `/opt/venv`, `/opt/novnc`,
  `/root/.mozilla/firefox/selenium.default-release`, `/etc/opt/chrome*/policies/managed`,
  `/app/a1cert.py` (API usada pelos scripts), `/app/a1_check.py`, `/app/egress_proxy.py`, `/app/egress_check.py`,
  `/app/preflight.py`, `/app/pjeoffice_check.py`, `/app/resource_usage.py`, `/app/image_info.py`
  (+ `/app/image_info.json`, gravado no build), `/opt/icp-brasil/` (`raizes.pem`, `acs.pem`).
- Variáveis de ambiente e seus defaults (`USE_*`, `WORKER_*`, `SCRIPT_URL`, `HELPER_URLS`,
  `CHROME_PROFILE_URL`, `TASK_*`, `SCREEN_*`, `PJEOFFICE_*`, `A1_PFX_*`, `EGRESS_*`, `RESOURCE_*`, `PREFLIGHT_*`).
  Sem `EGRESS_PROXY_URL` o container sai direto, como sempre (recurso opcional, só alguns clientes). Os defaults do entrypoint
  estão travados em `tests/unit/test_entrypoint.py`.
- Build-args usados pelo release: `BUILD_PJEOFFICE=1`, `ENABLE_PDF_TOOLS=1`,
  `ENABLE_VNC=1`, `ENABLE_NOVNC=1`, `CHROME_PROFILE_URL`, `SELENIUMBASE_REFRESH`,
  `IMAGE_REVISION`/`IMAGE_CREATED` (só a identificação, na última camada).

Para conferir se uma mudança alterou o contrato, compare snapshots
(veja "Validação" abaixo).

## Mapa do repositório

| Caminho | Papel |
|---|---|
| `Dockerfile.trixie` | imagem de produção (multi-stage: downloads → runtime) |
| `requirements.txt` | pacotes Python da imagem |
| `image/app/` | **tudo** que vai para `/app` na imagem (`COPY image/app/ /app/`) |
| `image/app/a1cert.py` | certificado A1: abrir `.pfx`, NSS do Chrome/Firefox, policy, `.p7s`, PAdES, limpeza |
| `image/app/a1_check.py`, `a1_testkit.py` | verificador do A1 e ferramentas de teste (ICP de teste, servidor mTLS local) |
| `image/app/egress_proxy.py`, `egress_check.py`, `egress_testkit.py` | relay de saída: repassador local + config de browsers/Python/Java, verificador e relay de referência/teste |
| `image/app/preflight.py` | "o worker está pronto?": browsers + `a1_check` + `egress_check` num JSON |
| `image/app/resource_usage.py` | CPU/memória de cada execução pelo cgroup (média, p95, pico, sugestão de reserva) e por grupo de processos pelo `/proc` (Chrome, PJeOffice, Xvfb, script...); o entrypoint e o standby rodam o script através dele (`RESOURCE_SUMMARY=1`); `report` junta `/app/logs/resources.jsonl` |
| `image/app/image_info.py` | qual imagem é esta: grava `/app/image_info.json` no build (`IMAGE_REVISION`), primeira linha do log e `"imagem"` no preflight |
| `image/app/pjeoffice_check.py` | o PJeOffice assina? Chrome clica em "Testar" na página local dele (127.0.0.1:8800), xdotool responde a senha; usado pelo `a1_check` com `USE_PJEOFFICE=1` |
| `image/icp-brasil/` | raízes (fingerprint fixado) + ACs oficiais da ICP-Brasil (ITI) → `/opt/icp-brasil`; só para validar cadeia do A1, fora do trust store |
| `image/patch_chromedriver.py` | usado só no build (montado com `--mount=type=bind` na camada que copia o ChromeDriver; nunca entra na imagem) |
| `legacy/Dockerfile.trixie` | Dockerfile anterior à imagem enxuta (3,8 GB), só referência: nenhum workflow o usa |
| `.dockerignore` | **allowlist**: só `requirements.txt` e `image/` entram no contexto |
| `tests/unit/` | testes rápidos no host (sem Docker) — rodam com `pytest` |
| `tests/image/` | testes que rodam dentro da imagem (contrato, serviços, browsers, integração) + `fixtures/` |
| `recipes/` | receitas plug and play (JSON do shutup-and-run, compose, scripts modelo); validadas por `tests/unit/test_recipes.py`, e a de teste do A1 roda no portão |
| `examples/server/` | N workers num servidor: compose com 4 workers + `workers.sh` (docker run) |
| `examples/compose/` | compose de worker, standby, debug (VNC) e Caddy |
| `examples/scripts/` | scripts de exemplo (não vão para a imagem) |
| `docs/` | guias de uso; `docs/baseline/` tem a foto da imagem de produção |
| `scripts/` | `test-image.sh` (portão), `run-recipe.py` (roda uma receita do shutup-and-run com o Docker local), `image-snapshot.sh`, `release-notes.sh` (notas do GitHub Release) e `update-icp-brasil.py` |
| `.github/workflows/ci.yml` | CI de PR: unit tests + build igual ao release + `test-image.sh` |
| `.github/workflows/build-push-ghcr.yml` | release: build → `test-image.sh` → push para o GHCR |
| `.github/workflows/nightly.yml` | build diário sem cache + `test-image.sh` + relatório de drift |
| `.github/dependabot.yml` | PR semanal agrupado atualizando as GitHub Actions |

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
(Chrome for Testing). A versão precisa existir para `linux64` **e** `linux-arm64` (Chrome for
Testing, desde a 153), e o Firefox/GeckoDriver para `linux-x86_64`/`linux64` **e** `linux-aarch64`.
Valide com os testes de imagem antes de mesclar (o CI roda o portão nas duas arquiteturas).

**ARM64 (`:latest-arm64`):** o Dockerfile escolhe os downloads por `TARGETARCH` (amd64/arm64; outra
arquitetura falha no build). O PJeOffice só existe para x64: no arm64 o JRE embutido é trocado pelo Zulu 8
com JavaFX para aarch64 (`ARG PJEOFFICE_JRE_ARM64_URL`/`_SHA256`, conferir o SHA-256 na API da Azul ao
atualizar). Nada de QEMU: CI, release e nightly usam o runner `ubuntu-24.04-arm`. O arm64 nunca recebe a tag
`latest` (sufixo `-arm64`).

**Adicionar um pacote do sistema:** use `apt-get install -y --no-install-recommends`
e termine o mesmo `RUN` com `rm -rf /var/lib/apt/lists/*`. Coloque-o perto de pacotes
do mesmo tipo e lembre que camadas mais acima invalidam o cache de tudo que vem depois.
Manuais, documentação e traduções que não são pt/en já ficam de fora (`/etc/dpkg/dpkg.cfg.d/90-rpa-worker-slim`).

**Tamanho da imagem:** `chown`/`chmod`/patch/`pip install` numa camada posterior gravam uma **segunda cópia**
de cada arquivo tocado (um `chown -R /opt/venv` separado custava ~670 MB). Mexa nos arquivos na mesma camada
que os cria; `tests/unit/test_dockerfile.py` trava isso para a venv e o ChromeDriver. Para ver o peso de cada
camada: `docker history --format '{{.Size}}\t{{.CreatedBy}}' <imagem>`.

**Mexer no certificado A1:** a API pública é `image/app/a1cert.py` (scripts de produção importam).
Mantenha as assinaturas das funções e a regra de nunca expor a senha (log, argv, repr). Qualquer
mudança precisa passar em `tests/image/test_a1_certificate.py` (Chrome, UC e Firefox com mTLS).
O teste do PJeOffice (`pjeoffice_check.py`) digita a senha só pela entrada padrão do xdotool e devolve a
configuração do PJeOffice como estava.

**Mexer no relay de saída:** com `EGRESS_PROXY_URL` definido, **nada** pode sair direto: não
adicione downloads antes de `setup_egress_proxy` no `main()` do entrypoint, nem fallback direto no
repassador. A senha do relay nunca vai para log, variáveis exportadas ou `repr`. Valide com
`tests/image/test_egress.py` e os cenários de relay do `test-image.sh`.

**Atualizar as ACs da ICP-Brasil:** `scripts/update-icp-brasil.py` (baixa do ITI, confere o SHA-512
publicado, o fingerprint das raízes e a cadeia de cada AC). O nightly avisa quando o ITI muda. Raiz nova
exige conferir o fingerprint e fixá-lo no script **e** em `tests/unit/test_a1cert.py`.

**Logs com URL:** nunca registre `SCRIPT_URL`/`HELPER_URLS`/URLs de usuário cruas: use `mask_url`
(bash, entrypoint) ou `script_downloader.mask_url`/`mask_text` (Python).

**Mexer nas receitas (`recipes/`):** elas são copiadas e rodadas como estão. As do shutup-and-run seguem o
contrato dele (campos aceitos, `cpu` ≤ 1 e `memory` ≤ 2g do perfil `shared-pc`, certificado nos caminhos fixos
`/run/shutup-and-run/...`); `tests/unit/test_recipes.py` trava isso e o portão roda `teste-a1.json`. Segredos só
como `secret_env: null` ou arquivo; URLs de exemplo em `example.com`; portas só em `127.0.0.1`.

**Medidor de recursos (`resource_usage.py`):** fica entre o entrypoint/standby e o script. Ele nunca pode
mudar o exit code (sinal vira 128+N, como no shell) nem segurar a saída do script (stdout/stderr herdados).
O comando direto (`docker run imagem <comando>`) continua com `exec`, sem o medidor no meio.
O preflight só avisa sobre o ambiente (shm, disco, memória, CPU, relógio); nada ali reprova o worker,
e a conferência do relógio nunca sai direto quando há relay. A divisão por processo lê a PSS
(`smaps_rollup`, cara) só a cada `PSS_REFRESH_SECS`: o medidor não pode pesar na CPU que ele mede.

**Loop (`WORKER_LOOP=1`):** a iteração roda em `timeout --kill-after` num `bash -c 'trap : TERM; ...'`.
O `trap` faz o bash esperar o script depois do SIGTERM; sem ele o `timeout` voltaria na hora e um script
que ignora o SIGTERM continuaria rodando. Depois de cada iteração, `cleanup_iteration` fecha só browsers e
drivers, reconhecidos pelo executável (`/opt/chrome`, `/opt/firefox`, chromedriver, uc_driver,
geckodriver). Serviços (Xvfb, OpenBox, PJeOffice, VNC, relay) nunca entram nessa lista.
`PREFLIGHT_ON_START=1` roda depois dos serviços e antes do primeiro script (e do standby).

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
3. **Portão de qualidade na imagem** (o mesmo do CI e do release):
   ```bash
   scripts/test-image.sh rpa-worker:local
   ```
   Para depurar um teste isolado, rode pytest dentro da imagem com `-p no:seleniumbase`
   (o plugin do SeleniumBase aborta com pytest-timeout) e diretório de trabalho gravável
   (`-w /tmp`). Veja `docs/TESTING.md`.
4. **Contrato preservado:**
   ```bash
   scripts/image-snapshot.sh ghcr.io/nailtongomes/rpa-worker-selenium:latest snapshots/latest
   scripts/image-snapshot.sh rpa-worker:local snapshots/local
   diff -ru snapshots/latest snapshots/local
   ```
   Diferenças esperadas devem ser explicadas. Atualizações do Debian ou do PyPI desde o
   último release são normais; mudanças de path, env ou entrypoint não são.

## CI e release

- `ci.yml` (todo PR): `unit-tests` → build com as mesmas flags do release →
  `scripts/test-image.sh` (bloqueante) → ClearCote (informativo, `continue-on-error`). O job `image`
  roda em matriz: amd64 (`ubuntu-latest`) e arm64 (`ubuntu-24.04-arm`), os dois bloqueantes.
- `build-push-ghcr.yml` (push na `main` que muda `Dockerfile.trixie`, `requirements.txt`,
  `image/**` ou o próprio workflow; ou manual): build com `load` e **sem push** →
  `scripts/test-image.sh` na mesma imagem → diff com a `:latest` atual → `docker push` das
  tags `latest`, `sha-<7>`, `YYYYMMDD-HHMMSS` → GitHub Release com digest, PRs, diff da imagem e
  comandos de rollback (`scripts/release-notes.sh`, informativo). Em matriz: o arm64 publica as mesmas
  tags com sufixo `-arm64` (sem GitHub Release próprio). Mantém 10 versões no GHCR (5 por arquitetura).
- `nightly.yml`: build diário sem cache + portão + relatório do que mudaria + variante FFmpeg.
- Regras travadas em `tests/unit/test_workflows.py`: push só depois do portão, mesmas flags
  em CI/nightly/release, nenhum `|| exit 0`. Passos informativos usam `continue-on-error`.

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
- Certificado A1 real **nunca** vai para o GitHub (nem em secrets): os testes usam a ICP de teste de
  `a1_testkit.py`; o A1 real é validado no servidor com `python /app/a1_check.py`. A senha
  nunca é registrada em log nem passada em linha de comando (`pk12util -w`, `keytool -storepass:file`).
- `EGRESS_PROXY_URL` contém a senha do relay: prefira `EGRESS_PROXY_URL_FILE`; o repassador nunca
  a registra (`Upstream.masked`).
- VNC/noVNC não têm senha: só para debug em rede confiável ou atrás de proxy com auth
  (`docs/VNC_CADDY_PROXY.md`).
- `CHROME_PROFILE_URL` vira `ENV` na imagem publicada. É uma decisão consciente do mantenedor.

## Backlog da reforma

- [x] **Fase 0:** baseline da imagem de produção (`docs/baseline/`) e `scripts/image-snapshot.sh`.
- [x] **Fase 1:** remoção das imagens legadas, nova estrutura (`image/`, `tests/`, `examples/`, `docs/`),
  `.dockerignore` em allowlist, `COPY` explícito, SeleniumBase sempre na versão mais recente,
  compose de exemplo corrigidos, testes unitários consolidados e rodando no CI.
- [x] **Fase 2:** release só publica após `scripts/test-image.sh` na mesma imagem; gatilho inclui
  `image/**` e `requirements.txt`; um único build igual ao de produção no CI; sem `|| exit 0`;
  testes de browser offline (fixtures locais) + online (página do projeto); `smoke_test.py`
  falha se o browser falhar; build noturno sem cache com relatório de drift.
- [x] **Certificado A1:** `a1cert.py` (API), `a1_check.py` (verificador para o A1 real, no servidor),
  `a1_testkit.py` (ICP de teste + servidor mTLS) e cenário no portão; Actions em Node 24 + Dependabot.
- [x] **Relay de saída:** `EGRESS_PROXY_URL` (SOCKS5/HTTP com senha) para todo o tráfego, fail-closed,
  DNS no relay, WebRTC/QUIC bloqueados, `egress_check.py` e cenários no portão.
- [x] **Quick wins:** URLs com token mascaradas nos logs; relay conferido antes de cada iteração do
  loop; `/app/preflight.py`; ACs da ICP-Brasil em `/opt/icp-brasil` (`verify_chain`); GitHub Release
  com notas e rollback; loop do entrypoint sem duplicação (usa as mesmas funções via `export -f`).
- [x] **Receitas:** `recipes/` (shutup-and-run: teste do A1, rotina, tarefa por poll; Docker local com noVNC;
  worker na VPS saindo pela internet do cliente), `scripts/run-recipe.py` e cenário no portão; o preflight tenta
  de novo um browser lento (aviso, não falha).
- [x] **ARM64:** `:latest-arm64` (Chrome for Testing/Firefox ARM, PJeOffice com Zulu 8 FX aarch64), portão em
  runner ARM nativo no CI/release/nightly; teste de assinatura do PJeOffice pela página local
  (`pjeoffice_check.py`) no portão e no preflight; receita `recipes/servidor-arm/`.
- [x] **Ambiente e dimensionamento:** preflight confere `/dev/shm`, disco, memória, CPU e relógio (avisos);
  versão da imagem na primeira linha do log e no preflight (`image_info.py`); resumo de CPU/memória por
  execução com sugestão de reserva e relatório de várias execuções (`resource_usage.py`).
- [x] **Imagem enxuta:** de 3,8 GB para ~2,6 GB sem mudar o que a imagem faz: venv e ChromeDriver sem cópia
  duplicada entre camadas; sem Java 21 (o `java`/`keytool` do PATH é o Java 8 do PJeOffice), sem o ffmpeg do
  PJeOffice (stub), sem `pcsc-tools`/Perl, sem traduções fora pt/en, manuais e testes do pandas/numpy. Dockerfile
  anterior em `legacy/`.
- [x] **Operação do worker:** divisão do resumo de recursos por processo e momento dos picos; loop com SIGKILL
  para script travado (`WORKER_KILL_AFTER`) e limpeza de browsers/drivers esquecidos entre iterações
  (`WORKER_CLEANUP`); `PREFLIGHT_ON_START=1` para falhar na partida.
- [ ] **Fase 3:** alinhar `requirements.txt` com o que de fato roda (`cryptography`, `psutil`,
  `oscrypto`); revisar `set -e` x falha no download do profile.
