#!/bin/bash
# =============================================================================
# workers.sh — sobe e gerencia N workers RPA com docker run (sem compose)
#
# Uso (nesta pasta, com o .env preenchido):
#   ./workers.sh start [N]     sobe N workers (padrão: 4), um a cada START_DELAY s
#   ./workers.sh stop          para e remove todos os workers
#   ./workers.sh restart [N]   stop + start
#   ./workers.sh update [N]    baixa a imagem mais recente e recria os workers
#   ./workers.sh status        lista workers, estado, uso de CPU/RAM e, com WORKER_STATUS=1, a fase de cada um
#   ./workers.sh logs <NN>     acompanha os logs de um worker (ex.: logs 02)
#
# Configuração:
#   .env                        SCRIPT_URL, segredos etc. (compartilhado)
#   workers/rpa-worker-NN.env   opcional: sobrescreve variáveis só daquele worker
#                               (ex.: SCRIPT_URL, CHROME_PROFILE_URL)
#
# Variáveis do próprio script (exporte antes de chamar):
#   RPA_IMAGE         imagem (padrão: ghcr.io/nailtongomes/rpa-worker-selenium:latest)
#   WORKER_PREFIX     prefixo dos nomes (padrão: rpa-worker)
#   WORKER_MEM_LIMIT  RAM por worker (padrão: 2g)
#   WORKER_CPUS       CPUs por worker (padrão: 1.0)
#   START_DELAY       segundos entre o start de cada worker (padrão: 15)
#   DATA_DIR          pasta de dados (padrão: ./data)
#
# Formato do .env: KEY=valor, sem aspas e sem "export" (formato do docker --env-file).
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"

RPA_IMAGE="${RPA_IMAGE:-ghcr.io/nailtongomes/rpa-worker-selenium:latest}"
WORKER_PREFIX="${WORKER_PREFIX:-rpa-worker}"
WORKER_MEM_LIMIT="${WORKER_MEM_LIMIT:-2g}"
WORKER_CPUS="${WORKER_CPUS:-1.0}"
START_DELAY="${START_DELAY:-15}"
DATA_DIR="${DATA_DIR:-$PWD/data}"
ENV_FILE="${ENV_FILE:-.env}"
LABEL="rpa-worker-selenium.role=worker"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

worker_name() { printf '%s-%02d' "$WORKER_PREFIX" "$1"; }

running_workers() {
    docker ps -a --filter "label=$LABEL" --format '{{.Names}}' | sort
}

require_env_file() {
    if [ ! -f "$ENV_FILE" ]; then
        echo "ERRO: $ENV_FILE não encontrado. Rode: cp ../../.env.example $ENV_FILE e preencha SCRIPT_URL." >&2
        exit 1
    fi
    if ! grep -qE '^SCRIPT_URL=.+' "$ENV_FILE"; then
        echo "ERRO: SCRIPT_URL não definido em $ENV_FILE" >&2
        exit 1
    fi
}

start_one() {
    local index="$1"
    local name
    name="$(worker_name "$index")"

    if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
        log "⚠️  $name já existe, pulando (use restart para recriar)"
        return 0
    fi

    local data="$DATA_DIR/$name"
    mkdir -p "$data/db" "$data/src" "$data/tmp" "$data/logs"

    # .env comum + override opcional do worker (o último vence)
    local env_args=(--env-file "$ENV_FILE")
    if [ -f "workers/$name.env" ]; then
        env_args+=(--env-file "workers/$name.env")
    fi

    docker run -d \
        --name "$name" \
        --hostname "$name" \
        --label "$LABEL" \
        --restart always \
        --init \
        --user 0 \
        --shm-size 2g \
        --memory "$WORKER_MEM_LIMIT" \
        --cpus "$WORKER_CPUS" \
        --stop-timeout 30 \
        --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
        -e WORKER_ID="$name" \
        -e WORKER_LOOP=1 \
        -e USE_XVFB=1 \
        -e USE_OPENBOX=1 \
        "${env_args[@]}" \
        -v "$data/db:/app/db" \
        -v "$data/src:/app/src" \
        -v "$data/tmp:/app/tmp" \
        -v "$data/logs:/app/logs" \
        "$RPA_IMAGE" >/dev/null

    log "✅ $name iniciado"
}

cmd_start() {
    local count="${1:-4}"
    require_env_file
    log "🚀 Subindo $count worker(s) com $RPA_IMAGE"
    local i
    for i in $(seq 1 "$count"); do
        start_one "$i"
        # Escalona o início para não abrir todos os navegadores/logins ao mesmo tempo
        if [ "$i" -lt "$count" ]; then
            sleep "$START_DELAY"
        fi
    done
    cmd_status
}

cmd_stop() {
    local names
    names="$(running_workers)"
    if [ -z "$names" ]; then
        log "ℹ️  Nenhum worker em execução"
        return 0
    fi
    log "🛑 Parando: $(echo "$names" | tr '\n' ' ')"
    # shellcheck disable=SC2086
    docker stop $names >/dev/null
    # shellcheck disable=SC2086
    docker rm $names >/dev/null
    log "✅ Workers removidos (dados em $DATA_DIR preservados)"
}

cmd_status() {
    docker ps -a --filter "label=$LABEL" \
        --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
    local names
    names="$(docker ps --filter "label=$LABEL" --format '{{.Names}}')"
    if [ -n "$names" ]; then
        echo
        # shellcheck disable=SC2086
        docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' $names
        # Com WORKER_STATUS=1 no .env: o que cada worker está fazendo (/app/logs/status.json)
        local name line header=""
        for name in $names; do
            line="$(docker exec "$name" python -c '
import json
s = json.load(open("/app/logs/status.json"))
u, c = s.get("ultima", {}), s.get("contadores", {})
print(s.get("fase", "?"), "desde", s.get("desde", "?")[11:19], "· iteração", s.get("iteracao", "-"),
      "· última:", u.get("resultado", "-"), "(%ss)" % u.get("duracao_s", "-"),
      "· ok/falha/tempo/sem trabalho:", c.get("ok", 0), c.get("falha", 0), c.get("tempo_esgotado", 0), c.get("sem_trabalho", 0))
' 2>/dev/null)" || continue
            [ -n "$header" ] || { echo; echo "Estado (WORKER_STATUS=1):"; header=1; }
            echo "  ${name}: ${line}"
        done
    fi
}

cmd_logs() {
    local index="${1:?informe o número do worker, ex.: ./workers.sh logs 02}"
    docker logs -f --tail 200 "$(worker_name "$((10#$index))")"
}

cmd_update() {
    local count="${1:-}"
    if [ -z "$count" ]; then
        count="$(running_workers | wc -l)"
        [ "$count" -gt 0 ] || count=4
    fi
    log "⬇️  Baixando $RPA_IMAGE"
    docker pull "$RPA_IMAGE"
    cmd_stop
    cmd_start "$count"
}

case "${1:-}" in
    start)   cmd_start "${2:-4}" ;;
    stop)    cmd_stop ;;
    restart) cmd_stop; cmd_start "${2:-4}" ;;
    update)  cmd_update "${2:-}" ;;
    status)  cmd_status ;;
    logs)    cmd_logs "${2:-}" ;;
    *)
        sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'
        exit 1
        ;;
esac
