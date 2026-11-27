#!/bin/bash
# =============================================================================
# test-image.sh — portão de qualidade da imagem (CI do PR, release e nightly)
#
# Roda todos os cenários contra UMA imagem já construída e falha (exit 1) se
# qualquer um falhar. O release só publica a imagem se este script passar.
#
# Uso:
#   scripts/test-image.sh <imagem> [dir-resultados]
#
# Exemplos:
#   scripts/test-image.sh rpa-worker:local
#   RUN_ONLINE_TESTS=0 scripts/test-image.sh rpa-worker:local   # sem internet
#
# Variáveis:
#   RUN_ONLINE_TESTS  1 (padrão) inclui a visita à página do projeto no GitHub
#   EXPECT_FEATURES   recursos opcionais esperados (padrão: pjeoffice,pdf,vnc,novnc)
#   DOCKER_RUN_ARGS   argumentos extras para todo `docker run` (ex.: proxy/CA)
#   STABILITY_EXTERNAL_URLS  sites dos testes externos de estabilidade (padrão: browser_stability.py)
#   STABILITY_DURATION       segundos da sessão prolongada (padrão: 120)
#
# Resultados em <dir-resultados>: junit-*.xml, screenshots/, logs/, stability/, summary.md
# =============================================================================
set -uo pipefail

if [ "$#" -lt 1 ]; then
    sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi

IMAGE="$1"
RESULTS="$(mkdir -p "${2:-./test-results}" && cd "${2:-./test-results}" && pwd)"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
RUN_ONLINE_TESTS="${RUN_ONLINE_TESTS:-1}"
EXPECT_FEATURES="${EXPECT_FEATURES:-pjeoffice,pdf,vnc,novnc}"
read -r -a EXTRA_ARGS <<< "${DOCKER_RUN_ARGS:-}"

mkdir -p "$RESULTS/logs" "$RESULTS/screenshots"
chmod -R 777 "$RESULTS" 2>/dev/null || true

PASSED=()
FAILED=()
FIXTURE_PORT=8765
FIXTURE_URL="http://127.0.0.1:${FIXTURE_PORT}"

PYTEST="pytest -p no:cacheprovider -p no:seleniumbase --timeout=300 --maxfail=5 -rA"
ONLINE_FILTER=""
if [ "$RUN_ONLINE_TESTS" != "1" ]; then
    ONLINE_FILTER="not online"
fi

# --- helpers ------------------------------------------------------------------

group_start() { if [ "${GITHUB_ACTIONS:-}" = "true" ]; then echo "::group::$1"; else echo; echo "=== $1"; fi; }
group_end()   { if [ "${GITHUB_ACTIONS:-}" = "true" ]; then echo "::endgroup::"; fi; }

record() {
    local name="$1" rc="$2"
    if [ "$rc" -eq 0 ]; then
        PASSED+=("$name")
        echo "✅ $name"
    else
        FAILED+=("$name")
        echo "❌ $name (exit $rc)"
        if [ "${GITHUB_ACTIONS:-}" = "true" ]; then echo "::error title=test-image::$name falhou (exit $rc)"; fi
    fi
}

# docker run padrão: repo montado (somente leitura), resultados graváveis, cwd gravável
run_in_image() {
    timeout 1200 docker run --rm --shm-size=2g \
        -v "$REPO:/repo:ro" -v "$RESULTS:/results" -w /tmp \
        -e EXPECT_FEATURES="$EXPECT_FEATURES" \
        -e TEST_ARTIFACTS_DIR=/results/screenshots \
        "${EXTRA_ARGS[@]}" "$@"
}

# Sobe um servidor HTTP com tests/image/fixtures dentro do container e então
# executa o entrypoint normal da imagem (como em produção).
FIXTURE_SERVER='python3 -m http.server '"$FIXTURE_PORT"' -d /repo/tests/image/fixtures >/dev/null 2>&1 & '
WITH_FIXTURES="${FIXTURE_SERVER}"'sleep 1; exec /app/entrypoint.sh "$@"'

marker_filter() {
    local extra="$1"
    if [ -n "$ONLINE_FILTER" ] && [ -n "$extra" ]; then
        echo "-m \"$extra and $ONLINE_FILTER\""
    elif [ -n "$ONLINE_FILTER" ]; then
        echo "-m \"$ONLINE_FILTER\""
    elif [ -n "$extra" ]; then
        echo "-m \"$extra\""
    fi
}

# --- cenários -----------------------------------------------------------------

scenario_contract() {
    run_in_image "$IMAGE" bash -c \
        "$PYTEST --junitxml=/results/junit-contract.xml /repo/tests/image/test_contract.py"
}

scenario_headless_no_display() {
    # Sem Xvfb: o que roda headless precisa funcionar sem servidor X
    run_in_image "$IMAGE" bash -c \
        "$PYTEST $(marker_filter 'not requires_display') --junitxml=/results/junit-headless.xml /repo/tests/image/test_browsers.py"
}

scenario_full_services() {
    # Configuração de produção: Xvfb + OpenBox + PJeOffice + VNC + noVNC. O PJeOffice sobe com
    # PJEOFFICE_JAVA_XMX (launcher copiado): o teste de assinatura dele roda assim; a receita
    # shutup-and-run cobre o launcher original.
    run_in_image \
        -e USE_XVFB=1 -e USE_OPENBOX=1 -e USE_PJEOFFICE=1 -e USE_VNC=1 -e USE_NOVNC=1 -e PJEOFFICE_JAVA_XMX=512m \
        "$IMAGE" bash -c "sleep 8 && $PYTEST $(marker_filter '') --junitxml=/results/junit-full.xml \
            /repo/tests/image/test_services.py /repo/tests/image/test_browsers.py \
            /repo/tests/image/trixie_integration_test.py"
}

scenario_a1_certificate() {
    # Certificado A1 com ICP de teste gerada na hora: .pfx por URL + senha, formatos
    # legados, .p7s attached, PAdES, Java (PJeOffice), NSS e Chrome/UC/Firefox
    # apresentando o certificado a um servidor HTTPS local que exige certificado de cliente
    # + /app/preflight.py (browsers + A1 num JSON só)
    run_in_image -e USE_XVFB=1 -e USE_OPENBOX=1 \
        "$IMAGE" bash -c "sleep 6 && $PYTEST --junitxml=/results/junit-a1.xml /repo/tests/image/test_a1_certificate.py \
            /repo/tests/image/test_preflight.py"
}

scenario_recipe_shutup_and_run() {
    # recipes/shutup-and-run/teste-a1.json como o shutup-and-run roda num PC compartilhado:
    # 1 CPU, 2 GB sem swap, --init, pids 4096, sem portas, certificado repassado (somente
    # leitura) em /run/shutup-and-run/... -> preflight (browsers + A1 + Java) precisa passar.
    # A ICP de teste fica fora de $RESULTS (não vai para os artefatos) e é apagada no fim.
    local pki log="$RESULTS/logs/recipe-shutup-and-run.log" rc=1 arg
    local password='Senha-Receita-7' docker_args=()
    pki="$(mktemp -d)" && chmod 777 "$pki"
    if run_in_image -v "$pki:/pki" --entrypoint python "$IMAGE" -c \
        "import sys; sys.path.insert(0, '/app'); import a1_testkit as k; k.make_test_pki('/pki/icp', '${password}')"; then
        printf '%s' "$password" > "$pki/senha.txt"
        for arg in "${EXTRA_ARGS[@]}"; do docker_args+=("--docker-arg=$arg"); done
        timeout 1200 python3 "$REPO/scripts/run-recipe.py" "$REPO/recipes/shutup-and-run/teste-a1.json" \
            --image "$IMAGE" --pfx "$pki/icp/a1.pfx" --password-file "$pki/senha.txt" "${docker_args[@]}" > "$log" 2>&1
        rc=$?
        grep -E '✅|⚠️|❌' "$log" | tail -25
        if grep -q "$password" "$log"; then echo "a senha do certificado apareceu no log"; rc=1; fi
        grep -q "Firefox apresenta o certificado" "$log" || { echo "A1 não foi testado nos browsers"; rc=1; }
        grep -q "worker pronto" "$log" || { echo "preflight não aprovou o worker"; rc=1; }
    else
        echo "não gerou a ICP de teste"
    fi
    # arquivos criados pelo root do container: apagados por ele
    docker run --rm -v "$pki:/pki" --entrypoint rm "$IMAGE" -rf /pki/icp >/dev/null 2>&1
    rm -rf "$pki"
    return "$rc"
}

# Relay de teste dentro do container ("internet falsa": responde a qualquer host com o
# IP 203.0.113.7 e grava os destinos), iniciado antes do entrypoint, como um relay real.
RELAY_FAKE_IP="203.0.113.7"
RELAY_PASSWORD='S3nh@-relay'
with_relay() {  # $1 = socks5|http, $2 = porta
    echo "python /app/egress_testkit.py relay --protocol $1 --listen 127.0.0.1:$2 --user rpa \
--password '${RELAY_PASSWORD}' --fake-ip ${RELAY_FAKE_IP} --record /tmp/egress-records.jsonl >/dev/null 2>&1 & \
sleep 1; exec /app/entrypoint.sh \"\$@\""
}

scenario_egress_relay() {
    # EGRESS_PROXY_URL (SOCKS5 com senha): Python, curl, Java/PJeOffice, Chrome, UC e
    # Firefox saem pelo relay; DNS resolvido no relay; WebRTC sem vazamento; localhost
    # direto; certificado A1 (mTLS local) continua funcionando com o relay ligado
    run_in_image -e USE_XVFB=1 -e USE_OPENBOX=1 \
        -e EGRESS_PROXY_URL='socks5://rpa:S3nh%40-relay@127.0.0.1:1080' \
        -e EGRESS_CHECK_URL=http://check.egress-test.invalid/ip -e EGRESS_EXPECTED_IP="$RELAY_FAKE_IP" \
        -e EGRESS_TEST_RECORDS=/tmp/egress-records.jsonl \
        --entrypoint bash "$IMAGE" -c "$(with_relay socks5 1080)" _ \
        bash -c "sleep 6 && $PYTEST --junitxml=/results/junit-egress.xml /repo/tests/image/test_egress.py \
            /repo/tests/image/test_a1_certificate.py -k 'test_egress or presents_certificate'"
}

scenario_egress_failures() {
    # Proxy HTTP com senha funciona; relay fora do ar ou senha errada => o container
    # NÃO executa nada (EGRESS_REQUIRED=1, padrão); EGRESS_REQUIRED=0 só avisa
    local log="$RESULTS/logs/egress-failures.log" rc ok=0
    : > "$log"

    echo "--- proxy HTTP com senha" >> "$log"
    run_in_image -e EGRESS_PROXY_URL='http://rpa:S3nh%40-relay@127.0.0.1:3129' -e EGRESS_CHECK_URL=off \
        --entrypoint bash "$IMAGE" -c "$(with_relay http 3129)" _ \
        python -c "import requests; print('IP', requests.get('http://h.egress-test.invalid/ip', timeout=20).text)" \
        >> "$log" 2>&1
    grep -q "IP ${RELAY_FAKE_IP}" "$log" || { echo "proxy HTTP: requests não saiu pelo relay"; ok=1; }

    echo "--- relay fora do ar (EGRESS_REQUIRED padrão)" >> "$log"
    run_in_image -e EGRESS_PROXY_URL='socks5://rpa:x@127.0.0.1:9' "$IMAGE" echo SHOULD-NOT-RUN >> "$log" 2>&1
    rc=$?
    { [ "$rc" -ne 0 ] && ! grep -q "^SHOULD-NOT-RUN" "$log"; } || { echo "relay fora do ar não parou o container"; ok=1; }

    echo "--- senha errada" >> "$log"
    run_in_image -e EGRESS_PROXY_URL='socks5://rpa:senha-errada-123@127.0.0.1:1080' \
        --entrypoint bash "$IMAGE" -c "$(with_relay socks5 1080)" _ echo SHOULD-NOT-RUN >> "$log" 2>&1
    rc=$?
    { [ "$rc" -ne 0 ] && grep -q "usuário ou senha incorretos" "$log"; } || { echo "senha errada não parou o container"; ok=1; }
    if grep -q "senha-errada-123" "$log"; then echo "a senha do relay apareceu no log"; ok=1; fi

    echo "--- relay fora do ar com EGRESS_REQUIRED=0" >> "$log"
    run_in_image -e EGRESS_PROXY_URL='socks5://127.0.0.1:9' -e EGRESS_REQUIRED=0 "$IMAGE" echo RAN-WITH-WARNING \
        >> "$log" 2>&1 || { echo "EGRESS_REQUIRED=0 não deveria parar"; ok=1; }
    grep -q "^RAN-WITH-WARNING" "$log" || { echo "EGRESS_REQUIRED=0: comando não executou"; ok=1; }

    echo "--- esquema inválido" >> "$log"
    run_in_image -e EGRESS_PROXY_URL='ftp://relay:21' "$IMAGE" echo SHOULD-NOT-RUN >> "$log" 2>&1
    rc=$?
    [ "$rc" -ne 0 ] || { echo "esquema inválido não parou o container"; ok=1; }

    grep -E "egress|Egress|IP |RAN-WITH|SHOULD-NOT" "$log" | head -20
    return "$ok"
}

scenario_smoke_test() {
    # /app/smoke_test.py é o script padrão da imagem: precisa falhar se o browser falhar
    run_in_image \
        -e USE_XVFB=1 -e USE_OPENBOX=1 -e USE_PJEOFFICE=1 -e CHECK_PROCESSES=1 \
        -e TARGET_URL="$FIXTURE_URL/index.html" -e CACHE_DIR=/results/smoke \
        --entrypoint bash "$IMAGE" -c "$WITH_FIXTURES" _ \
        bash -c "sleep 6 && python /app/smoke_test.py"
}

scenario_worker_loop() {
    # WORKER_LOOP=1: baixa SCRIPT_URL + HELPER_URLS e executa ao menos 2 iterações.
    # As URLs levam usuário/senha e tokens na query: nenhum deles pode aparecer no log.
    local name="rpa-test-loop-$$" log="$RESULTS/logs/worker-loop.log" ok=1
    local script_url="http://rpa:SEGREDO-USER-1@127.0.0.1:${FIXTURE_PORT}/job_ok.py?token=SEGREDO-QUERY-2&ref=main"
    docker rm -f "$name" >/dev/null 2>&1
    docker run -d --name "$name" --shm-size=2g -v "$REPO:/repo:ro" "${EXTRA_ARGS[@]}" \
        -e SCRIPT_URL="$script_url" -e HELPER_URLS="$FIXTURE_URL/helper_mod.py?sig=SEGREDO-HELPER-3" \
        -e WORKER_ID=loop-test -e WORKER_LOOP=1 -e WORKER_RESTART_DELAY=2 -e WORKER_TIMEOUT=60 \
        --entrypoint bash "$IMAGE" -c "$WITH_FIXTURES" _ >/dev/null || return 1
    for _ in $(seq 1 60); do
        if [ "$(docker logs "$name" 2>&1 | grep -c 'JOB-OK worker=loop-test HELPER-OK')" -ge 2 ]; then
            ok=0
            break
        fi
        sleep 1
    done
    docker logs "$name" > "$log" 2>&1
    docker rm -f "$name" >/dev/null 2>&1
    grep -E "iteration|JOB-OK|Downloading" "$log" | head -8
    if [ "$(grep -c '📊 Recursos de job_ok.py' "$log")" -lt 2 ]; then
        echo "o loop não mostrou o resumo de recursos a cada iteração"
        ok=1
    fi
    if grep -q "SEGREDO-" "$log"; then
        echo "token/senha das URLs apareceu no log:"
        grep "SEGREDO-" "$log" | head -3
        ok=1
    fi
    return "$ok"
}

scenario_loop_cleanup() {
    # WORKER_LOOP=1 com um script que deixa um Chrome órfão e trava ignorando o SIGTERM:
    # no WORKER_TIMEOUT ele recebe SIGTERM, WORKER_KILL_AFTER depois SIGKILL, e o Chrome
    # esquecido (com o perfil temporário) some antes da próxima iteração
    local name="rpa-test-loop-cleanup-$$" log="$RESULTS/logs/loop-cleanup.log" ok=1 left=""
    docker rm -f "$name" >/dev/null 2>&1
    docker run -d --name "$name" --shm-size=2g -v "$REPO:/repo:ro" "${EXTRA_ARGS[@]}" \
        -e SCRIPT_URL="$FIXTURE_URL/job_stuck.py" -e WORKER_LOOP=1 \
        -e WORKER_TIMEOUT=8 -e WORKER_KILL_AFTER=3 -e WORKER_RESTART_DELAY=30 \
        --entrypoint bash "$IMAGE" -c "$WITH_FIXTURES" _ >/dev/null || return 1
    for _ in $(seq 1 90); do
        docker logs "$name" 2>&1 | grep -q "Waiting 30s before next iteration" && break
        sleep 1
    done
    # durante a espera: nem o script travado nem o Chrome dele podem continuar rodando
    left="$(docker exec "$name" sh -c 'pgrep -af "job_stuck.py|job-stuck" | grep -v pgrep; ls -d /tmp/.org.chromium.Chromium.job-stuck 2>/dev/null' 2>&1)"
    docker logs "$name" > "$log" 2>&1
    docker rm -f "$name" >/dev/null 2>&1
    grep -E "JOB-STUCK|timed out|Closing|Waiting" "$log" | head -8
    if ! grep -q "JOB-STUCK travado" "$log"; then
        echo "o script não rodou"
    elif ! grep -q "ignored SIGTERM: killed after 3s more" "$log"; then
        echo "o script travado não foi morto com SIGKILL"
    elif ! grep -q "Closing [0-9]* browser/driver process(es) left by the iteration" "$log"; then
        echo "a limpeza não fechou o Chrome esquecido"
    elif [ -n "$left" ]; then
        echo "sobrou da iteração:"
        echo "$left"
    else
        ok=0
    fi
    return "$ok"
}

scenario_preflight_on_start() {
    # PREFLIGHT_ON_START=1: preflight depois dos serviços e antes da primeira tarefa.
    # Passou -> o script roda; falhou (A1 que não existe) -> o container para com exit 1 sem rodar.
    local log_ok="$RESULTS/logs/preflight-on-start-ok.log" log_fail="$RESULTS/logs/preflight-on-start-fail.log"
    local rc_ok rc_fail ok=0
    run_in_image -e PREFLIGHT_ON_START=1 -e PREFLIGHT_ARGS="--browsers chrome --clock-url off" \
        -e SCRIPT_URL="$FIXTURE_URL/job_ok.py" -e HELPER_URLS="$FIXTURE_URL/helper_mod.py" -e WORKER_ID=preflight \
        --entrypoint bash "$IMAGE" -c "$WITH_FIXTURES" _ > "$log_ok" 2>&1
    rc_ok=$?
    run_in_image -e PREFLIGHT_ON_START=1 -e PREFLIGHT_ARGS="--browsers none --clock-url off" \
        -e A1_PFX_PATH=/nao/existe.pfx -e SCRIPT_URL="$FIXTURE_URL/job_ok.py" \
        -e HELPER_URLS="$FIXTURE_URL/helper_mod.py" -e WORKER_ID=preflight \
        --entrypoint bash "$IMAGE" -c "$WITH_FIXTURES" _ > "$log_fail" 2>&1
    rc_fail=$?
    grep -hE "PREFLIGHT_ON_START|Preflight|JOB-OK" "$log_ok" "$log_fail"
    echo "exit com preflight ok=$rc_ok, com preflight falhando=$rc_fail"
    [ "$rc_ok" -eq 0 ] && grep -q "Preflight passed" "$log_ok" && grep -q "JOB-OK worker=preflight" "$log_ok" \
        || { echo "preflight ok não deixou o script rodar"; ok=1; }
    [ "$rc_fail" -eq 1 ] && grep -q "Preflight failed: stopping before the first task" "$log_fail" \
        || { echo "preflight falhando não parou o container com exit 1"; ok=1; }
    if grep -q "JOB-OK" "$log_fail"; then
        echo "o script rodou mesmo com o preflight falhando"
        ok=1
    fi
    return "$ok"
}

scenario_restart_stale_locks() {
    # O mesmo container subindo de novo (docker restart, política de restart): o /tmp guarda o
    # lock do Xvfb anterior, com um PID que na nova partida é de outro processo. Antes o Xvfb
    # recusava ("Server is already active for display 99") e o container caía. Também: travas
    # velhas de perfil do Chrome/Firefox e um log acima de LOG_MAX_MB.
    local name="rpa-test-restart-$$" log="$RESULTS/logs/restart-stale-locks.log" ok=1 rc
    local leave_behind='xdpyinfo -display :99 >/dev/null && echo XVFB-OK
        mkdir -p /app/perfil && ln -sfn "$(hostname)-$$" /app/perfil/SingletonLock
        ln -sfn "127.0.0.1:+$$" /root/.mozilla/firefox/selenium.default-release/lock
        head -c 2097152 /dev/zero > /app/logs/grande.log'
    docker rm -f "$name" >/dev/null 2>&1
    docker run --name "$name" "${EXTRA_ARGS[@]}" -e USE_XVFB=1 -e USE_OPENBOX=1 -e LOG_MAX_MB=1 \
        "$IMAGE" bash -c "$leave_behind" > /dev/null 2>&1
    timeout 120 docker start -a "$name" > "$log" 2>&1
    rc=$?
    docker rm -f "$name" >/dev/null 2>&1
    grep -E "stale|Xvfb|XVFB-OK|Rotated|Fatal" "$log" | head -8
    if [ "$rc" -ne 0 ]; then
        echo "a segunda partida falhou (exit $rc)"
    elif ! grep -q "Removed stale Xvfb lock /tmp/.X99-lock" "$log" || ! grep -q "XVFB-OK" "$log"; then
        echo "o lock velho do Xvfb não foi removido ou o Xvfb não subiu"
    elif ! grep -q "Removed 2 stale browser profile lock(s)" "$log"; then
        echo "travas velhas do Chrome/Firefox não foram removidas"
    elif ! grep -q "Rotated /app/logs/grande.log" "$log"; then
        echo "log acima de LOG_MAX_MB não foi rodado"
    else
        ok=0
    fi
    return "$ok"
}

scenario_vnc_password() {
    # VNC_PASSWORD: o VNC passa a exigir senha (RFB security type 2, nunca 1 = sem senha),
    # a senha não fica no argv nem chega ao comando/script, e VNC_VIEW_ONLY=1 vira -viewonly.
    # Sem senha (cenário de serviços) continua aberto como sempre.
    local log="$RESULTS/logs/vnc-password.log"
    run_in_image -e USE_XVFB=1 -e USE_VNC=1 -e VNC_PASSWORD=S3nha-VNC -e VNC_VIEW_ONLY=1 \
        "$IMAGE" bash -c 'sleep 2
            python3 - <<PY
import socket, time
for _ in range(20):
    try:
        s = socket.create_connection(("127.0.0.1", 5900), timeout=5)
        break
    except OSError:
        time.sleep(0.5)
version = s.recv(12)
s.sendall(b"RFB 003.008\n")
n = s.recv(1)[0]
types = list(s.recv(n))
print(f"RFB {version.decode().strip()} security types: {types}")
assert types and 1 not in types and 2 in types, "VNC sem senha"
print("VNC-SENHA-OK")
PY
            echo "senha no ambiente do comando: $(env | grep -c VNC_PASSWORD=)"
            echo "senha no argv: $(ps -eo args | grep -c "[S]3nha-VNC")"
            echo "arquivo da senha: $(ls /tmp/.x11vnc-passwd 2>/dev/null | wc -l)"
            ps -eo args | grep -q "[x]11vnc.*-viewonly" && echo "VIEW-ONLY-OK"' > "$log" 2>&1
    grep -E "security types|senha|VNC|VIEW" "$log" | grep -v "S3nha" | head -8
    grep -q "VNC-SENHA-OK" "$log" && grep -q "VIEW-ONLY-OK" "$log" \
        && grep -q "senha no ambiente do comando: 0" "$log" && grep -q "senha no argv: 0" "$log" \
        && grep -q "arquivo da senha: 0" "$log" && grep -q "password required, view only" "$log" \
        && ! grep -q "S3nha-VNC" "$log"
}

scenario_script_sha256() {
    # SCRIPT_SHA256: hash certo roda; hash errado não roda, não tenta de novo e sai com erro
    local log_ok="$RESULTS/logs/sha256-ok.log" log_bad="$RESULTS/logs/sha256-bad.log" rc_ok rc_bad ok=0 good
    good="$(sha256sum "$REPO/tests/image/fixtures/job_ok.py" | cut -d' ' -f1)"
    run_in_image -e SCRIPT_URL="$FIXTURE_URL/job_ok.py" -e HELPER_URLS="$FIXTURE_URL/helper_mod.py" \
        -e SCRIPT_SHA256="$good" -e WORKER_ID=sha --entrypoint bash "$IMAGE" -c "$WITH_FIXTURES" _ > "$log_ok" 2>&1
    rc_ok=$?
    run_in_image -e SCRIPT_URL="$FIXTURE_URL/job_ok.py" -e HELPER_URLS="$FIXTURE_URL/helper_mod.py" \
        -e SCRIPT_SHA256="$(printf '0%.0s' $(seq 1 64))" -e WORKER_ID=sha \
        --entrypoint bash "$IMAGE" -c "$WITH_FIXTURES" _ > "$log_bad" 2>&1
    rc_bad=$?
    grep -hE "SHA-256|SCRIPT_SHA256|JOB-OK|attempt" "$log_ok" "$log_bad"
    echo "exit com hash certo=$rc_ok, com hash errado=$rc_bad"
    [ "$rc_ok" -eq 0 ] && grep -q "JOB-OK worker=sha" "$log_ok" || { echo "hash certo não rodou o script"; ok=1; }
    [ "$rc_bad" -ne 0 ] && grep -q "does not match SCRIPT_SHA256" "$log_bad" || { echo "hash errado não parou"; ok=1; }
    if grep -q "JOB-OK" "$log_bad" || grep -q "Download attempt 2" "$log_bad"; then
        echo "hash errado: o script rodou ou o download foi repetido"
        ok=1
    fi
    return "$ok"
}

scenario_egress_loop() {
    # WORKER_LOOP=1 com relay: se o relay cair, a iteração é pulada (o script não roda
    # sem a saída certa) e o worker volta sozinho quando o relay volta
    local name="rpa-test-egress-loop-$$" log="$RESULTS/logs/egress-loop.log" ok=1 jobs_down jobs_now
    count_jobs() { docker logs "$name" 2>&1 | grep -c 'JOB-OK worker=egress-loop'; }
    count_skips() { docker logs "$name" 2>&1 | grep -c 'Egress relay unavailable, skipping'; }
    docker rm -f "$name" >/dev/null 2>&1
    docker run -d --name "$name" --shm-size=2g -v "$REPO:/repo:ro" "${EXTRA_ARGS[@]}" \
        -e EGRESS_PROXY_URL='socks5://rpa:S3nh%40-relay@127.0.0.1:1080' \
        -e EGRESS_CHECK_URL=http://check.egress-test.invalid/ip -e EGRESS_EXPECTED_IP="$RELAY_FAKE_IP" \
        -e SCRIPT_URL="$FIXTURE_URL/job_ok.py" -e HELPER_URLS="$FIXTURE_URL/helper_mod.py" \
        -e WORKER_ID=egress-loop -e WORKER_LOOP=1 -e WORKER_RESTART_DELAY=2 -e WORKER_TIMEOUT=60 \
        --entrypoint bash "$IMAGE" -c "${FIXTURE_SERVER}$(with_relay socks5 1080)" _ >/dev/null || return 1

    wait_for() {  # $1 = condição (função), $2 = segundos
        local _
        for _ in $(seq 1 "$2"); do "$1" && return 0; sleep 1; done
        return 1
    }
    has_job() { [ "$(count_jobs)" -ge 1 ]; }
    has_two_skips() { [ "$(count_skips)" -ge 2 ]; }
    job_after_recovery() { [ "$(count_jobs)" -gt "$jobs_down" ]; }

    if wait_for has_job 90; then
        echo "relay no ar: $(count_jobs) iteração(ões); derrubando o relay"
        docker exec "$name" pkill -f "egress_testkit.py relay"
        if wait_for has_two_skips 90; then
            jobs_down="$(count_jobs)"
            sleep 12
            jobs_now="$(count_jobs)"
            if [ "$jobs_now" -ne "$jobs_down" ]; then
                echo "o script rodou com o relay fora do ar ($jobs_down -> $jobs_now)"
            else
                echo "relay fora do ar: iterações puladas ($(count_skips)); religando o relay"
                docker exec -d "$name" python /app/egress_testkit.py relay --protocol socks5 \
                    --listen 127.0.0.1:1080 --user rpa --password "$RELAY_PASSWORD" --fake-ip "$RELAY_FAKE_IP"
                if wait_for job_after_recovery 60; then
                    echo "relay de volta: o worker retomou sozinho"
                    ok=0
                else
                    echo "o worker não retomou depois que o relay voltou"
                fi
            fi
        else
            echo "o loop não detectou o relay fora do ar"
        fi
    else
        echo "nenhuma iteração rodou com o relay no ar"
    fi
    docker logs "$name" > "$log" 2>&1
    docker rm -f "$name" >/dev/null 2>&1
    grep -E "iteration|JOB-OK|Egress relay" "$log" | tail -8
    return "$ok"
}

# Recebe o POST do fim do container e os pings dentro do próprio container (fixtures/log_receiver.py)
RECEIVER_PORT=8766
with_receiver() {
    echo "${FIXTURE_SERVER}python3 /repo/tests/image/fixtures/log_receiver.py ${RECEIVER_PORT} $1 >/dev/null 2>&1 & \
sleep 1; exec /app/entrypoint.sh \"\$@\""
}

scenario_end_of_container_report() {
    # Container efêmero que falha (exit 3) com tudo ligado: ping antes/depois, telas da falha,
    # status.json e POST no fim com as últimas linhas + worker.txt + telas. Segredos das URLs fora do log.
    local log="$RESULTS/logs/end-of-container.log" got="$RESULTS/end-of-container.jsonl" rc ok=0
    rm -f "$got"
    run_in_image -e USE_XVFB=1 -e SCRIPT_URL="$FIXTURE_URL/job_fail.py" \
        -e LOG_POST_URL="http://127.0.0.1:${RECEIVER_PORT}/hook/SEGREDO-HOOK?token=SEGREDO-Q" \
        -e LOG_POST_FULL=1 -e LOG_POST_LINES=40 -e SCREENSHOT_ON_FAIL=1 -e SCREENSHOT_INTERVAL=1 \
        -e PING_URL="http://127.0.0.1:${RECEIVER_PORT}/ping/SEGREDO-PING" -e WORKER_STATUS=1 \
        --entrypoint bash "$IMAGE" -c "$(with_receiver /results/end-of-container.jsonl)" _ > "$log" 2>&1
    rc=$?
    grep -E "JOB-FAIL|📸|📤|⚠️" "$log" | head -8
    [ "$rc" -eq 3 ] || { echo "exit code do container: $rc (esperado 3)"; ok=1; }
    if grep -q "SEGREDO" "$log"; then echo "segredo da URL apareceu no log:"; grep "SEGREDO" "$log" | head -3; ok=1; fi
    python3 - "$got" <<'PY' || ok=1
import json, sys
entries = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
pings = [e["caminho"] for e in entries if e["caminho"].startswith("/ping/")]
assert pings == ["/ping/SEGREDO-PING/start", "/ping/SEGREDO-PING/3"], pings
(post,) = [e for e in entries if e["caminho"].startswith("/hook/")]
assert post["metodo"] == "POST"
data = json.loads(post["campos"]["dados"])
assert data["exit_code"] == 3 and data["motivo"] == "falha" and data["modo"] == "script", data
assert data["script"] == "job_fail.py" and data["linhas"] <= 40 and "JOB-FAIL" in data["log"]
assert data["recursos"]["exit_code"] == 3, data.get("recursos")
status = data["status"]
assert status["contadores"]["falha"] == 1 and status["ultima"]["exit_code"] == 3, status
assert "xvfb_s" in status["partida"] and "total_s" in status["partida"], status
files = post["arquivos"]
assert "Starting RPA Worker" in files["log"]["texto"] and "JOB-FAIL" in files["log"]["texto"]
telas = [f for k, f in files.items() if k.startswith("tela_")]
assert telas and all(f["inicio"].startswith("ffd8") and f["bytes"] > 1000 for f in telas), telas
print(f"POST: {data['linhas']} linhas, worker.txt {files['log']['bytes']} bytes, {len(telas)} tela(s); pings {pings}")
PY
    return "$ok"
}

scenario_loop_idle_and_stop() {
    # WORKER_LOOP=1 com script sem trabalho (exit 75): espera dobra até WORKER_IDLE_MAX_DELAY, status.json
    # conta as rodadas; `docker stop` no meio da espera termina na hora e manda o log (motivo "parado")
    local name="rpa-test-loop-idle-$$" log="$RESULTS/logs/loop-idle-stop.log" got="$RESULTS/loop-idle.jsonl"
    local ok=0 status="" began elapsed
    rm -f "$got"
    docker rm -f "$name" >/dev/null 2>&1
    docker run -d --name "$name" -v "$REPO:/repo:ro" -v "$RESULTS:/results" "${EXTRA_ARGS[@]}" \
        -e SCRIPT_URL="$FIXTURE_URL/job_idle.py" -e WORKER_LOOP=1 -e RESOURCE_SUMMARY=0 \
        -e WORKER_RESTART_DELAY=1 -e WORKER_IDLE_EXIT_CODE=75 -e WORKER_IDLE_MAX_DELAY=4 -e WORKER_STATUS=1 \
        -e LOG_POST_URL="http://127.0.0.1:${RECEIVER_PORT}/hook" \
        --entrypoint bash "$IMAGE" -c "$(with_receiver /results/loop-idle.jsonl)" _ >/dev/null || return 1
    for _ in $(seq 1 60); do
        docker logs "$name" 2>&1 | grep -q "3 in a row): next iteration in 4s" && break
        sleep 1
    done
    sleep 1
    status="$(docker exec "$name" cat /app/logs/status.json 2>&1)"
    began=$(date +%s)
    docker stop -t 10 "$name" >/dev/null
    elapsed=$(( $(date +%s) - began ))
    docker logs "$name" > "$log" 2>&1
    docker rm -f "$name" >/dev/null 2>&1
    grep -E "Nothing to do|📤|shutdown" "$log" | head -6
    echo "docker stop levou ${elapsed}s"
    grep -q "1 in a row): next iteration in 2s" "$log" && grep -q "2 in a row): next iteration in 4s" "$log" \
        || { echo "a espera não dobrou (2s, 4s)"; ok=1; }
    grep -q "Script failed with exit code: 75" "$log" && { echo "exit 75 contou como falha"; ok=1; }
    [ "$elapsed" -le 8 ] || { echo "docker stop esperou demais (${elapsed}s): o trap não rodou durante a espera"; ok=1; }
    printf '%s' "$status" | python3 -c '
import json, sys
s = json.load(sys.stdin)
assert s["modo"] == "loop" and s["contadores"]["sem_trabalho"] >= 3 and s["contadores"]["falha"] == 0, s
assert s["ultima"]["resultado"] == "sem_trabalho" and s["fase"] in ("esperando", "executando"), s
print("status.json:", s["fase"], s["contadores"])' || ok=1
    python3 - "$got" <<'PY' || ok=1
import json, sys
(post,) = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
data = post["json"]
assert data["motivo"] == "parado" and data["modo"] == "loop" and data["exit_code"] == 0, data
assert "JOB-IDLE" in data["log"] and data["status"]["fase"] == "encerrado", data["status"]
print("POST no docker stop:", data["motivo"], data["linhas"], "linhas")
PY
    return "$ok"
}

scenario_single_run_ok() {
    local log="$RESULTS/logs/single-run-ok.log" rc
    run_in_image -e SCRIPT_URL="$FIXTURE_URL/job_ok.py" -e HELPER_URLS="$FIXTURE_URL/helper_mod.py" \
        -e WORKER_ID=single --entrypoint bash "$IMAGE" -c "$WITH_FIXTURES" _ > "$log" 2>&1
    rc=$?
    grep "JOB-OK" "$log" || { echo "marcador JOB-OK ausente"; return 1; }
    # primeira linha do log: qual imagem é; no fim: CPU/memória da execução (resource_usage.py)
    grep -m1 "Imagem " "$log" || { echo "linha da imagem ausente no log"; return 1; }
    grep -A3 "📊 Recursos de job_ok.py (exit 0" "$log" || { echo "resumo de recursos ausente"; return 1; }
    grep -q '^RESOURCE_SUMMARY {.*"exit_code": 0' "$log" || { echo "linha RESOURCE_SUMMARY ausente"; return 1; }
    # divisão por processo (o script dura menos que uma amostra: o grupo dele é conferido no cenário de limites)
    grep -q '^RESOURCE_SUMMARY {.*"processos": {' "$log" || { echo "divisão por processo ausente"; return 1; }
    return "$rc"
}

scenario_single_run_failure_propagates() {
    # Um script que falha precisa devolver exit != 0 (orquestradores dependem disso)
    local log="$RESULTS/logs/single-run-fail.log" rc
    run_in_image -e SCRIPT_URL="$FIXTURE_URL/job_fail.py" \
        --entrypoint bash "$IMAGE" -c "$WITH_FIXTURES" _ > "$log" 2>&1
    rc=$?
    echo "exit code do container: $rc"
    grep -q "JOB-FAIL" "$log" || { echo "script não executou"; return 1; }
    # o medidor de recursos fica no meio e não pode mudar o exit code (job_fail.py sai com 3)
    grep -q "📊 Recursos de job_fail.py (exit 3" "$log" || { echo "resumo de recursos sem o exit 3"; return 1; }
    [ "$rc" -eq 3 ]
}

scenario_limits_and_resources() {
    # Container apertado (shm 64 MB, 1 GB, meia CPU, como um PC mal configurado):
    # o preflight avisa (sem reprovar) e o resource_usage lê os limites e mede um pico conhecido.
    local log="$RESULTS/logs/limits-and-resources.log" rc ok=0
    timeout 600 docker run --rm --shm-size=64m -m 1g --cpus 0.5 -e USE_PJEOFFICE=1 \
        -v "$RESULTS:/results" "${EXTRA_ARGS[@]}" --entrypoint bash "$IMAGE" -c '
            python /app/preflight.py --browsers none --clock-url off --json /results/preflight-limits.json
            echo "preflight exit=$?"
            RESOURCE_LOG=/tmp/r.jsonl python /app/resource_usage.py run --label pico.py -- python -c "
import time
blocos = [bytearray(300 * 1024 * 1024)]
for b in blocos:
    b[::4096] = b\"x\" * len(b[::4096])
time.sleep(3)
"
            python /app/resource_usage.py report /tmp/r.jsonl' > "$log" 2>&1
    rc=$?
    grep -E "/dev/shm|memória|CPU|preflight exit|📊|pico|reserva" "$log" | head -20
    [ "$rc" -eq 0 ] || { echo "exit $rc"; ok=1; }
    grep -q "preflight exit=0" "$log" || { echo "avisos do ambiente reprovaram o worker"; ok=1; }
    grep -q "⚠️  /dev/shm: 0,1 GB" "$log" || { echo "sem aviso de /dev/shm pequeno"; ok=1; }
    grep -q "⚠️  memória: limite 1,0 GB" "$log" || { echo "sem aviso de memória para o PJeOffice"; ok=1; }
    grep -q "⚠️  CPU: limite 0.5" "$log" || { echo "sem aviso de meia CPU"; ok=1; }
    grep -q "(limite 1,00 GB" "$log" || { echo "resource_usage não leu o limite de memória"; ok=1; }
    python3 - "$log" <<'PY' || ok=1
import json, sys
line = next(l for l in open(sys.argv[1], encoding="utf-8") if l.startswith("RESOURCE_SUMMARY "))
s = json.loads(line.split(" ", 1)[1])
peak, cpu = s["memoria"]["pico_mb"], s["limites"]["cpu_nucleos"]
script_peak = s["processos"]["script"]["memoria_pico_mb"]
print(f"pico medido {peak} MB (alocados 300 MB; {script_peak} MB no grupo do script), limite de CPU {cpu}")
assert peak >= 300, "o pico não incluiu os 300 MB alocados"
assert script_peak >= 300, "a divisão por processo não pôs os 300 MB no script"
assert cpu == 0.5, "limite de CPU errado"
PY
    return "$ok"
}

# --- estabilidade do browser (image/app/browser_stability.py) --------------------------------
# Limites de um worker em produção. O script roda pelo entrypoint (serviços como em produção);
# relatórios e, em falha, o diagnóstico (log do ChromeDriver, processos, cgroup...) ficam em stability/.
STABILITY_LIMITS=(--memory=2g --cpus=1 --shm-size=2g --init)
STABILITY_UC_SCENARIOS="modos,sequencial,sessoes,recuperacao,uc_especial"

stability_container() {  # <label> <log> [args do docker] -- [args do browser_stability.py]
    local label="$1" log="$2" docker_args=()
    shift 2
    while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do docker_args+=("$1"); shift; done
    shift
    timeout 900 docker run --rm "${STABILITY_LIMITS[@]}" -v "$RESULTS:/results" \
        -e STABILITY_EXTERNAL_URLS="${STABILITY_EXTERNAL_URLS:-}" "${docker_args[@]}" "${EXTRA_ARGS[@]}" \
        "$IMAGE" python /app/browser_stability.py --out /results/stability --label "$label" "$@" > "$log" 2>&1
}

stability_show() {
    grep -E '^\[[0-9: -]+\] (✅|❌|⚠️|⏭️|🏷️|🔎)' "$1" | cut -c1-260
}

scenario_stability_alone() {
    # Um container sozinho: referência de tempos, regressão do UC (4xx/5xx/reCAPTCHA) e sites externos
    # (falha de site é aviso; sessão/driver perdido reprova). Headful em Xvfb como os workers.
    local log="$RESULTS/logs/stability-base.log" rc ext=()
    mkdir -p "$RESULTS/stability" && chmod 777 "$RESULTS/stability"
    [ "$RUN_ONLINE_TESTS" = "1" ] && ext=(--external)
    stability_container base "$log" -e USE_XVFB=1 -e USE_OPENBOX=1 -- \
        --mode uc-headful --scenarios sequencial,uc_especial "${ext[@]}"
    rc=$?
    stability_show "$log"
    return "$rc"
}

scenario_stability_concurrent() {
    # Três containers ao mesmo tempo, mesma imagem e mesmos limites: sem e com PJeOffice (só isso muda
    # entre os dois) e uma sessão UC headless de STABILITY_DURATION segundos. Reprova se qualquer um perder
    # sessão/driver/browser, falhar um cenário local ou tiver OOM; degradação de tempo só gera aviso.
    local labels=(sem-pjeoffice com-pjeoffice prolongada) pids=() i rc ok=0
    mkdir -p "$RESULTS/stability" && chmod 777 "$RESULTS/stability"
    stability_container sem-pjeoffice "$RESULTS/logs/stability-sem-pjeoffice.log" \
        -e USE_XVFB=1 -e USE_OPENBOX=1 -- --mode uc-headful --scenarios "$STABILITY_UC_SCENARIOS" &
    pids+=($!)
    stability_container com-pjeoffice "$RESULTS/logs/stability-com-pjeoffice.log" \
        -e USE_XVFB=1 -e USE_OPENBOX=1 -e USE_PJEOFFICE=1 -- --mode uc-headful --scenarios "$STABILITY_UC_SCENARIOS" &
    pids+=($!)
    stability_container prolongada "$RESULTS/logs/stability-prolongada.log" -- \
        --mode uc-headless --scenarios prolongada --duration "${STABILITY_DURATION:-120}" &
    pids+=($!)
    for i in 0 1 2; do
        wait "${pids[$i]}"
        rc=$?
        echo "--- ${labels[$i]} (exit $rc)"
        stability_show "$RESULTS/logs/stability-${labels[$i]}.log"
        [ "$rc" -eq 0 ] || ok=1
    done
    python3 - "$RESULTS/stability" <<'PY' || ok=1
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
rows, med, fails = [], {}, []
for label in ("base", "sem-pjeoffice", "com-pjeoffice", "prolongada"):
    f = out / f"{label}.json"
    if not f.exists():
        rows.append(f"| {label} | sem relatório | | | | | |"); fails.append(label); continue
    r = json.loads(f.read_text())
    navs = sorted(t for c in r["cenarios"] for t in [c["navegacoes"].get("mediana_s")] if t is not None)
    seq = next((c["navegacoes"].get("mediana_s") for c in r["cenarios"] if c["cenario"] == "sequencial"), None)
    med[label] = seq
    rec = r["recursos"]
    pje = (r.get("ambiente_fim") or {}).get("servicos", {}).get("pjeoffice", {})
    n = sum(c["navegacoes"].get("n", 0) for c in r["cenarios"])
    rows.append(f"| {label} | {'✅' if r['resultado'] == 'ok' else '❌'} | {n} | "
                f"{seq if seq is not None else '-'} s | {rec.get('memoria_pico_mb')} / {rec.get('memoria_limite_mb')} MB | "
                f"{rec.get('oom_kill')} | {rec.get('zombies_fim')} | "
                f"{(str(pje.get('rss_mb')) + ' MB') if pje.get('rodando') else '-'} |")
    if r["resultado"] != "ok" or rec.get("oom_kill"):
        fails.append(label)
table = ["### 🧭 Estabilidade do browser (2 GB, 1 CPU, shm 2 GB, --init)", "",
         "| container | resultado | navegações | mediana sequencial | pico de memória / limite | OOM kill | zombies | PJeOffice |",
         "|---|---|---|---|---|---|---|---|", *rows, ""]
if med.get("base") and med.get("sem-pjeoffice"):
    ratio = med["sem-pjeoffice"] / med["base"]
    note = f"Degradação com 3 containers simultâneos: mediana {ratio:.1f}x a do container sozinho"
    table.append(("⚠️ " if ratio > 3 else "") + note + (" (acima de 3x: conferir a máquina)" if ratio > 3 else ""))
if med.get("sem-pjeoffice") and med.get("com-pjeoffice"):
    table.append(f"Com PJeOffice: mediana {med['com-pjeoffice'] / med['sem-pjeoffice']:.1f}x a sem PJeOffice")
text = "\n".join(table) + "\n"
(out / "resumo.md").write_text(text, encoding="utf-8")
print(text)
sys.exit(1 if fails else 0)
PY
    return "$ok"
}

scenario_passthrough_command() {
    run_in_image "$IMAGE" python --version | tee "$RESULTS/logs/passthrough.log" | grep -q "Python 3"
}

scenario_standby() {
    # WORKER_MODE=standby: servidor HTTP responde /health e exige token em /task
    local name="rpa-test-standby-$$" ok=1 health="" auth=""
    docker rm -f "$name" >/dev/null 2>&1
    docker run -d --name "$name" "${EXTRA_ARGS[@]}" -e WORKER_MODE=standby -e TASK_AUTH_TOKEN=test-token \
        "$IMAGE" >/dev/null || return 1
    for _ in $(seq 1 30); do
        health="$(docker exec "$name" curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health 2>/dev/null)"
        [ "$health" = "200" ] && break
        sleep 1
    done
    auth="$(docker exec "$name" curl -s -o /dev/null -w '%{http_code}' -X POST \
        -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8080/task 2>/dev/null)"
    echo "/health=$health  /task sem token=$auth"
    docker logs "$name" > "$RESULTS/logs/standby.log" 2>&1
    docker rm -f "$name" >/dev/null 2>&1
    [ "$health" = "200" ] && [ "$auth" = "401" ] && ok=0
    return "$ok"
}

# --- execução -----------------------------------------------------------------

echo "🧪 Testando $IMAGE (online=$RUN_ONLINE_TESTS, features=$EXPECT_FEATURES)"
echo "   resultados: $RESULTS"

SCENARIOS=(
    "contrato da imagem:scenario_contract"
    "browsers headless sem display:scenario_headless_no_display"
    "serviços + browsers + integração (Xvfb/OpenBox/PJeOffice/VNC/noVNC):scenario_full_services"
    "certificado A1 (ICP de teste, .p7s, PAdES, Java, browsers com mTLS):scenario_a1_certificate"
    "receita shutup-and-run (teste-a1.json com 1 CPU, 2 GB e certificado repassado):scenario_recipe_shutup_and_run"
    "relay de saída (EGRESS_PROXY_URL - todo o tráfego, DNS, WebRTC, A1):scenario_egress_relay"
    "relay de saída - proxy HTTP e falhas (relay fora do ar, senha errada):scenario_egress_failures"
    "smoke_test.py (falha se o browser falhar):scenario_smoke_test"
    "worker em loop (SCRIPT_URL + HELPER_URLS, tokens fora do log):scenario_worker_loop"
    "worker em loop com relay - pula iteração com o relay fora do ar:scenario_egress_loop"
    "worker em loop - script travado (SIGTERM ignorado) morto com SIGKILL e Chrome esquecido fechado:scenario_loop_cleanup"
    "preflight na partida (PREFLIGHT_ON_START=1) - ok roda o script, falha para com exit 1:scenario_preflight_on_start"
    "restart do mesmo container - lock velho do Xvfb, travas de perfil e log grande:scenario_restart_stale_locks"
    "VNC com senha (VNC_PASSWORD) e só visualização (VNC_VIEW_ONLY):scenario_vnc_password"
    "SCRIPT_SHA256 - hash certo roda, errado não roda nem tenta de novo:scenario_script_sha256"
    "fim do container - POST do log com telas da falha, ping e status.json:scenario_end_of_container_report"
    "loop sem trabalho (WORKER_IDLE_EXIT_CODE) - espera dobra e docker stop envia o log:scenario_loop_idle_and_stop"
    "execução única com SCRIPT_URL:scenario_single_run_ok"
    "falha do script propaga exit code:scenario_single_run_failure_propagates"
    "limites do container - avisos do preflight e resumo de recursos (shm 64 MB, 1 GB, 0,5 CPU):scenario_limits_and_resources"
    "estabilidade do browser - container sozinho (UC headful, reCAPTCHA/4xx/5xx, sites externos):scenario_stability_alone"
    "estabilidade do browser - 3 containers simultâneos (sem e com PJeOffice, sessão de 120 s, 2 GB e 1 CPU):scenario_stability_concurrent"
    "comando direto (passthrough):scenario_passthrough_command"
    "modo standby (HTTP):scenario_standby"
)

for entry in "${SCENARIOS[@]}"; do
    title="${entry%%:*}"
    fn="${entry##*:}"
    group_start "$title"
    "$fn"
    rc=$?
    group_end
    record "$title" "$rc"
done

{
    echo "### 🧪 Testes da imagem \`$IMAGE\`"
    echo
    for name in "${PASSED[@]}"; do echo "- ✅ $name"; done
    for name in "${FAILED[@]}"; do echo "- ❌ $name"; done
    echo
    echo "Online: \`$RUN_ONLINE_TESTS\` · Features: \`$EXPECT_FEATURES\`"
    if [ -f "$RESULTS/stability/resumo.md" ]; then echo; cat "$RESULTS/stability/resumo.md"; fi
} > "$RESULTS/summary.md"

echo
cat "$RESULTS/summary.md"

if [ "${#FAILED[@]}" -gt 0 ]; then
    echo
    echo "❌ ${#FAILED[@]} cenário(s) falharam"
    exit 1
fi
echo
echo "✅ Todos os ${#PASSED[@]} cenários passaram"
