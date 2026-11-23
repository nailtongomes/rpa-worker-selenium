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
#
# Resultados em <dir-resultados>: junit-*.xml, screenshots/, logs/, summary.md
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
    # Configuração de produção: Xvfb + OpenBox + PJeOffice + VNC + noVNC
    run_in_image \
        -e USE_XVFB=1 -e USE_OPENBOX=1 -e USE_PJEOFFICE=1 -e USE_VNC=1 -e USE_NOVNC=1 \
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
    if grep -q "SEGREDO-" "$log"; then
        echo "token/senha das URLs apareceu no log:"
        grep "SEGREDO-" "$log" | head -3
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

scenario_single_run_ok() {
    local log="$RESULTS/logs/single-run-ok.log" rc
    run_in_image -e SCRIPT_URL="$FIXTURE_URL/job_ok.py" -e HELPER_URLS="$FIXTURE_URL/helper_mod.py" \
        -e WORKER_ID=single --entrypoint bash "$IMAGE" -c "$WITH_FIXTURES" _ > "$log" 2>&1
    rc=$?
    grep "JOB-OK" "$log" || { echo "marcador JOB-OK ausente"; return 1; }
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
    [ "$rc" -ne 0 ]
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
    "execução única com SCRIPT_URL:scenario_single_run_ok"
    "falha do script propaga exit code:scenario_single_run_failure_propagates"
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
