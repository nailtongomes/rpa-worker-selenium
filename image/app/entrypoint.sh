#!/bin/bash
# Entrypoint script for RPA Worker Selenium with script downloading
# Handles downloading scripts from URLs and executing them
# Optionally starts Xvfb, OpenBox, and PJeOffice services
# Supports loop execution with auto-restart and runtime Chrome profile download

set -e

# Export environment variables for child processes
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
export LANG=${LANG:-pt_BR.UTF-8}
export LC_ALL=${LC_ALL:-pt_BR.UTF-8}
export TZ=${TZ:-America/Sao_Paulo}
export DISPLAY=${DISPLAY:-:99}
export PYTHONPATH="/app:/app/src${PYTHONPATH:+:${PYTHONPATH}}"

# PJeOffice paths - configurable via environment variables
export PJEOFFICE_CONFIG_DIR=${PJEOFFICE_CONFIG_DIR:-/app/.pjeoffice-pro}
export PJEOFFICE_CONFIG_FILE=${PJEOFFICE_CONFIG_FILE:-${PJEOFFICE_CONFIG_DIR}/pjeoffice-pro.config}
export PJEOFFICE_EXECUTABLE=${PJEOFFICE_EXECUTABLE:-/opt/pjeoffice/pjeoffice-pro.sh}
# Max Java heap of PJeOffice (e.g. 512m). Empty keeps the launcher's own -Xmx2048m.
export PJEOFFICE_JAVA_XMX=${PJEOFFICE_JAVA_XMX:-}

# Screen recording configuration
export RECORDING_DIR=${RECORDING_DIR:-/app/recordings}
export RECORDING_FILENAME=${RECORDING_FILENAME:-recording_$(date +%Y%m%d_%H%M%S).mp4}

# Worker configuration
export WORKER_MODE=${WORKER_MODE:-pull}
export WORKER_LOOP=${WORKER_LOOP:-0}
export WORKER_TIMEOUT=${WORKER_TIMEOUT:-3600}  # 1 hour default
export WORKER_RESTART_DELAY=${WORKER_RESTART_DELAY:-120}  # 2 minutes default
# Loop mode: seconds between SIGTERM and SIGKILL when an iteration hits WORKER_TIMEOUT
export WORKER_KILL_AFTER=${WORKER_KILL_AFTER:-30}
# Loop mode: close browsers/drivers left behind by an iteration (0 keeps them)
export WORKER_CLEANUP=${WORKER_CLEANUP:-1}

# Run /app/preflight.py after the services start and stop the container if it fails
# (off by default). PREFLIGHT_ARGS: extra options, e.g. "--browsers chrome --url https://...".
export PREFLIGHT_ON_START=${PREFLIGHT_ON_START:-0}
export PREFLIGHT_ARGS=${PREFLIGHT_ARGS:-}

# Resource summary after each script run (CPU/memory average and peaks, for sizing).
# See /app/resource_usage.py; RESOURCE_LOG="" keeps only the log lines.
export RESOURCE_SUMMARY=${RESOURCE_SUMMARY:-1}
export RESOURCE_SAMPLE_SECS=${RESOURCE_SAMPLE_SECS:-1}
export RESOURCE_LOG=${RESOURCE_LOG:-/app/logs/resources.jsonl}
export RESOURCE_PROCESSES=${RESOURCE_PROCESSES:-1}  # 0: no per-process breakdown

# Files in /app/logs above this size (MB) are rotated (one .1 copy kept); 0 (default) never rotates
export LOG_MAX_MB=${LOG_MAX_MB:-0}

# End of the container (optional): LOG_POST_URL_FILE (preferred) or LOG_POST_URL receives a POST
# with the last LOG_POST_LINES lines, exit code and duration; LOG_POST_FULL=1 attaches the whole
# log (worker.txt). See /app/worker_events.py.
export LOG_POST_LINES=${LOG_POST_LINES:-100}
export LOG_POST_FULL=${LOG_POST_FULL:-0}
export LOG_POST_TIMEOUT=${LOG_POST_TIMEOUT:-8}  # seconds; docker stop waits 10 s by default
export WORKER_LOG=/app/logs/worker.log

# Screenshots of the Xvfb screen when a script fails (off by default): one every
# SCREENSHOT_INTERVAL seconds while it runs, the last ones kept in /app/logs/falhas/<date>/
export SCREENSHOT_ON_FAIL=${SCREENSHOT_ON_FAIL:-0}
export SCREENSHOT_INTERVAL=${SCREENSHOT_INTERVAL:-10}
export SCREENSHOT_KEEP=${SCREENSHOT_KEEP:-20}

# Loop mode: a script exiting with WORKER_IDLE_EXIT_CODE had nothing to do; each such iteration
# in a row doubles the wait (WORKER_RESTART_DELAY x2, x4...) up to WORKER_IDLE_MAX_DELAY seconds
export WORKER_IDLE_EXIT_CODE=${WORKER_IDLE_EXIT_CODE:-}
export WORKER_IDLE_MAX_DELAY=${WORKER_IDLE_MAX_DELAY:-1800}

# /app/logs/status.json with phase, iteration, last run, counters and startup times (off by default)
export WORKER_STATUS=${WORKER_STATUS:-0}
# PING_URL / PING_URL_FILE (optional): healthchecks.io-style ping before and after each run

# VNC: VNC_PASSWORD_FILE (preferred) or VNC_PASSWORD asks for a password; VNC_VIEW_ONLY=1
# lets viewers watch without clicking or typing. Without a password VNC stays open, as always.
export VNC_VIEW_ONLY=${VNC_VIEW_ONLY:-0}

# Task server configuration (for standby mode)
export TASK_SERVER_PORT=${TASK_SERVER_PORT:-8080}
export TASK_AUTH_TOKEN=${TASK_AUTH_TOKEN:-}

# Firefox Profile
export FIREFOX_PROFILE_DIR=${FIREFOX_PROFILE_DIR:-/root/.mozilla/firefox/selenium.default-release}

# Egress relay (optional, off by default): all outbound traffic leaves through
# EGRESS_PROXY_URL (socks5://, http:// or https://, with user:password) instead of
# the server's own connection. See docs/EGRESS_RELAY.md.
export EGRESS_REQUIRED=${EGRESS_REQUIRED:-1}
export EGRESS_LOCAL_PORT=${EGRESS_LOCAL_PORT:-3128}

# PIDs for background processes
XVFB_PID=""
OPENBOX_PID=""
PJEOFFICE_PID=""
FFMPEG_PID=""
VNC_PID=""
NOVNC_PID=""
EGRESS_PID=""
CHILD_PID=""
SCREEN_WATCH_PID=""
STOPPED_BY_SIGNAL=0

# Timestamp function for logging
log_timestamp() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]"
}

# Which image is running (revision, build, architecture, browsers): /app/image_info.json
log_image_info() {
    local info
    info="$(python /app/image_info.py 2>/dev/null)" || info="🏷️  Imagem: versão desconhecida"
    echo "$(log_timestamp) ${info}"
}

# Setup directories with proper permissions
setup_directories() {
    echo "$(log_timestamp) 🖥️  Setting up directories..."
    local dirs=("/app/logs" "/app/tmp" "/app/src" "${RECORDING_DIR}")
    
    for dir in "${dirs[@]}"; do
        if [ ! -d "$dir" ]; then
            mkdir -p "$dir" 2>/dev/null || true
        fi
    done
    
    # Setup PJeOffice directory if PJeOffice is installed
    if [ -d "/opt/pjeoffice" ]; then
        mkdir -p "${PJEOFFICE_CONFIG_DIR}" 2>/dev/null || true
        chmod 755 "${PJEOFFICE_CONFIG_DIR}" 2>/dev/null || true
    fi
    
    # Setup PKI directory for runtime certificate management
    # Note: .pki/nssdb subdirectory is NOT created here - Python manages it at runtime
    # This ensures full control over the NSS database lifecycle (create/reset/import/delete)
    if [ ! -d "/app/.pki" ]; then
        mkdir -p /app/.pki 2>/dev/null || true
        chmod 700 /app/.pki 2>/dev/null || true
    fi
    
    # Same for root user's PKI directory (when running as root)
    if [ ! -d "/root/.pki" ]; then
        mkdir -p /root/.pki 2>/dev/null || true
        chmod 700 /root/.pki 2>/dev/null || true
    fi

    rotate_logs
    return 0
}

# Logs in /app/logs (relay, VNC, resources.jsonl, the scripts' own) grow forever in a
# long-running worker: above LOG_MAX_MB the file is copied to <file>.1 and emptied in place
# (copy + truncate, so a process still writing to it keeps working).
rotate_logs() {
    local max="${LOG_MAX_MB}" file size
    [ "${max}" -gt 0 ] 2>/dev/null || return 0
    for file in /app/logs/*.log /app/logs/*.jsonl; do
        [ -f "$file" ] || continue
        size="$(stat -c %s "$file" 2>/dev/null)" || continue
        if [ "$size" -gt $((max * 1024 * 1024)) ]; then
            cp -f "$file" "${file}.1" && : > "$file"
            echo "$(log_timestamp) 🗂️  Rotated ${file} ($((size / 1024 / 1024)) MB > ${max} MB; previous content in ${file}.1)"
        fi
    done
    return 0
}

# Locks left by a previous run of this same container (docker restart, restart policy):
# /tmp survives a restart and the PID written in a lock usually belongs to another live
# process in the new run (PIDs repeat in containers, often it is the new Xvfb's own PID),
# so Xvfb refuses to start ("Server is already active for display") and Chrome/Firefox
# think the profile is in use. Runs before any service or browser starts; a lock whose
# owner is really running (an Xvfb on the display, any browser) is left alone.
clear_stale_locks() {
    local display_num lock pid file
    local removed=0
    display_num="${DISPLAY#*:}"
    display_num="${display_num%%.*}"
    lock="/tmp/.X${display_num}-lock"
    if [ -e "$lock" ]; then
        pid="$(tr -dc '0-9' < "$lock" 2>/dev/null)" || pid=""
        if [ -z "$pid" ] || [ "$(cat "/proc/${pid}/comm" 2>/dev/null)" != "Xvfb" ]; then
            rm -f "$lock" "/tmp/.X11-unix/X${display_num}"
            echo "$(log_timestamp) 🧹 Removed stale Xvfb lock ${lock} (from a previous run)"
        fi
    fi

    [ -z "$(browser_pids)" ] || return 0
    # Chrome: Singleton* in any profile (tmp, /app, /root, volumes under them);
    # Firefox: the "lock" symlink of the profile
    while IFS= read -r -d '' file; do
        rm -f "$file"
        removed=$((removed + 1))
    done < <(find /tmp /app /root -maxdepth 6 \( -name SingletonLock -o -name SingletonSocket \
        -o -name SingletonCookie \) -print0 2>/dev/null)
    if [ -L "${FIREFOX_PROFILE_DIR}/lock" ] || [ -e "${FIREFOX_PROFILE_DIR}/lock" ]; then
        rm -f "${FIREFOX_PROFILE_DIR}/lock" "${FIREFOX_PROFILE_DIR}/.parentlock"
        removed=$((removed + 1))
    fi
    if [ "$removed" -gt 0 ]; then
        echo "$(log_timestamp) 🧹 Removed ${removed} stale browser profile lock(s) (from a previous run)"
    fi
    remove_browser_temp
    return 0
}

# Download Chrome profile at runtime if not done at build time
download_chrome_profile() {
    if [ -z "$CHROME_PROFILE_URL" ]; then
        echo "$(log_timestamp) ℹ️  CHROME_PROFILE_URL not set, skipping profile download"
        return 0
    fi

    mkdir -p /usr/local/share

    local ZIP_NAME
    local DEST

    # Resolve ZIP name
    if [[ "$CHROME_PROFILE_URL" == *.zip ]]; then
        ZIP_NAME="$(basename "$CHROME_PROFILE_URL")"
    else
        ZIP_NAME="ProfileChrome.zip"
    fi

    DEST="/usr/local/share/$ZIP_NAME"

    # Export canonical path for downstream scripts
    export CHROME_PROFILE_ZIP_PATH="$DEST"

    # If already present, skip download
    if [ -s "$DEST" ]; then
        echo "$(log_timestamp) ✅ Chrome profile ZIP already present: $DEST"
        echo "$(log_timestamp) 📦 CHROME_PROFILE_ZIP_PATH=$CHROME_PROFILE_ZIP_PATH"
        return 0
    fi

    echo "$(log_timestamp) ⬇️  Downloading Chrome profile ZIP to $DEST ..."
    
    if curl -fsSL "$CHROME_PROFILE_URL" -o "$DEST"; then
        if unzip -tq "$DEST" >/dev/null 2>&1; then
            echo "$(log_timestamp) ✅ Chrome profile ZIP downloaded successfully"
            echo "$(log_timestamp) 📦 CHROME_PROFILE_ZIP_PATH=$CHROME_PROFILE_ZIP_PATH"
            return 0
        else
            echo "$(log_timestamp) ❌ Downloaded file is not a valid ZIP"
            rm -f "$DEST"
            unset CHROME_PROFILE_ZIP_PATH
            return 1
        fi
    else
        echo "$(log_timestamp) ❌ Failed to download Chrome profile ZIP"
        unset CHROME_PROFILE_ZIP_PATH
        return 1
    fi
}

# Stop (EGRESS_REQUIRED=1) or warn when the egress relay does not work
egress_fail() {
    echo "$(log_timestamp) ❌ Egress relay failed: $1"
    if [ "${EGRESS_REQUIRED}" = "1" ]; then
        echo "$(log_timestamp) ❌ EGRESS_REQUIRED=1: stopping so no traffic leaves through the server's own connection"
        exit 1
    fi
    echo "$(log_timestamp) ⚠️  EGRESS_REQUIRED=0: continuing; outbound traffic fails until the relay works"
}

# Route all outbound traffic through the egress relay (optional)
setup_egress_proxy() {
    if [ -z "${EGRESS_PROXY_URL:-}" ] && [ -z "${EGRESS_PROXY_URL_FILE:-}" ]; then
        python /app/egress_proxy.py unconfigure >/dev/null 2>&1 || true
        echo "$(log_timestamp) ℹ️  EGRESS_PROXY_URL not set, using the server's internet connection"
        return 0
    fi

    local env_lines result
    if ! env_lines="$(python /app/egress_proxy.py env --port "${EGRESS_LOCAL_PORT}" 2>&1)"; then
        egress_fail "${env_lines}"
        return 0
    fi

    echo "$(log_timestamp) 🌐 Starting egress relay forwarder on 127.0.0.1:${EGRESS_LOCAL_PORT}..."
    # Restarted automatically if it ever exits; clients never fall back to a direct connection
    (
        while true; do
            python /app/egress_proxy.py serve --listen "127.0.0.1:${EGRESS_LOCAL_PORT}" >> /app/logs/egress_proxy.log 2>&1
            sleep 1
        done
    ) &
    EGRESS_PID=$!

    # HTTP(S)_PROXY, NO_PROXY and JAVA_TOOL_OPTIONS for every child process
    eval "${env_lines}"
    python /app/egress_proxy.py configure --port "${EGRESS_LOCAL_PORT}" >/dev/null

    if result="$(python /app/egress_proxy.py check --port "${EGRESS_LOCAL_PORT}" 2>&1)"; then
        echo "$(log_timestamp) ✅ Outbound traffic via egress relay (exit: ${result})"
    else
        egress_fail "${result}"
    fi
}

setup_firefox_profile() {
    echo "$(log_timestamp) 🦊 Setting up Firefox profile..."

    mkdir -p /root/.mozilla/firefox
    mkdir -p "${FIREFOX_PROFILE_DIR}"

    # Inicializa NSS do perfil se ainda não existir
    if [ ! -f "${FIREFOX_PROFILE_DIR}/cert9.db" ]; then
        certutil -d "sql:${FIREFOX_PROFILE_DIR}" -N --empty-password || true
    fi

    echo "$(log_timestamp) ✅ Firefox profile ready: ${FIREFOX_PROFILE_DIR}"
}

# Signal handling for graceful shutdown
handle_sigterm() {
    STOPPED_BY_SIGNAL=1
    echo "$(log_timestamp) 🛑 Received shutdown signal, cleaning up..."
    [ -n "$SCREEN_WATCH_PID" ] && kill -TERM "$SCREEN_WATCH_PID" 2>/dev/null || true
    [ -n "$NOVNC_PID" ] && kill -TERM "$NOVNC_PID" 2>/dev/null || true
    [ -n "$VNC_PID" ] && kill -TERM "$VNC_PID" 2>/dev/null || true
    [ -n "$FFMPEG_PID" ] && kill -TERM "$FFMPEG_PID" 2>/dev/null || true
    [ -n "$XVFB_PID" ] && kill -TERM "$XVFB_PID" 2>/dev/null || true
    [ -n "$OPENBOX_PID" ] && kill -TERM "$OPENBOX_PID" 2>/dev/null || true
    [ -n "$PJEOFFICE_PID" ] && kill -TERM "$PJEOFFICE_PID" 2>/dev/null || true
    [ -n "$EGRESS_PID" ] && kill -TERM "$EGRESS_PID" 2>/dev/null || true
    
    # Wait a moment for FFmpeg to finalize the recording
    if [ -n "$FFMPEG_PID" ]; then
        sleep 2
    fi
    
    exit 0
}

trap handle_sigterm SIGTERM SIGINT
trap on_exit EXIT

# --- What happened, for whoever watches from outside (all optional, off by default) ---

log_post_enabled() {
    [ -n "${LOG_POST_URL:-}" ] || [ -n "${LOG_POST_URL_FILE:-}" ]
}

ping_enabled() {
    [ -n "${PING_URL:-}" ] || [ -n "${PING_URL_FILE:-}" ]
}

# LOG_POST_URL: the entrypoint's output (and the scripts') also goes to /app/logs/worker.log, read
# by the POST at the end. docker logs keeps receiving everything, stdout and stderr apart. The tee
# processes ignore INT/TERM: if they died first, the next echo would kill the entrypoint (SIGPIPE).
capture_output() {
    log_post_enabled || return 0
    mkdir -p "$(dirname "${WORKER_LOG}")" 2>/dev/null || true
    : > "${WORKER_LOG}" 2>/dev/null || return 0
    exec > >(trap '' INT TERM; exec tee -a "${WORKER_LOG}") 2> >(trap '' INT TERM; exec tee -a "${WORKER_LOG}" >&2)
}

# Runs "$@" and returns its exit code. With LOG_POST_URL, "$@" runs in the background and the shell
# waits with `wait`: bash only runs the SIGTERM trap after a foreground command ends, which on
# `docker stop` is too late (everything is killed 10 s later) for the POST at the end.
run_child() {
    if ! log_post_enabled; then
        "$@"
        return $?
    fi
    "$@" <&0 &
    CHILD_PID=$!
    local rc=0
    wait "$CHILD_PID" || rc=$?
    CHILD_PID=""
    return "$rc"
}

# WORKER_STATUS=1: updates /app/logs/status.json (see worker_events.py status)
worker_status() {
    [ "${WORKER_STATUS}" = "1" ] || return 0
    python /app/worker_events.py status "$@" || true
}

# PING_URL: start | end <exit code>. Never stops the worker.
worker_ping() {
    ping_enabled || return 0
    if [ "$1" = "start" ]; then
        timeout 15 python /app/worker_events.py ping start || true
    else
        timeout 15 python /app/worker_events.py ping end --exit-code "$2" || true
    fi
}

# SCREENSHOT_ON_FAIL=1: screenshots while the script runs (needs the Xvfb display)
screen_watch_start() {
    [ "${SCREENSHOT_ON_FAIL}" = "1" ] || return 0
    if ! xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
        echo "$(log_timestamp) ⚠️  SCREENSHOT_ON_FAIL=1 needs a display (USE_XVFB=1): no screenshots"
        return 0
    fi
    rm -rf /app/tmp/telas
    python /app/worker_events.py screens watch --dir /app/tmp/telas --interval "${SCREENSHOT_INTERVAL}" &
    SCREEN_WATCH_PID=$!
}

# $1 = exit code: a failure keeps the screenshots (plus one taken now) in /app/logs/falhas/<date>/
screen_watch_stop() {
    [ -n "$SCREEN_WATCH_PID" ] || return 0
    kill -TERM "$SCREEN_WATCH_PID" 2>/dev/null || true
    wait "$SCREEN_WATCH_PID" 2>/dev/null || true
    SCREEN_WATCH_PID=""
    if [ "$1" -ne 0 ]; then
        python /app/worker_events.py screens keep --dir /app/tmp/telas --keep "${SCREENSHOT_KEEP}" || true
    fi
    rm -rf /app/tmp/telas
}

# Before each run of the script (single run or loop iteration)
before_execution() {
    worker_status fase=executando "iteracao=$1" execucao.inicio=@now
    worker_ping start
    screen_watch_start
}

# After each run: $1 = exit code, $2 = start (epoch), $3 = "idle" when the script had nothing to do
after_execution() {
    local rc="$1" duration=$(( $(date +%s) - $2 )) result
    case "$rc" in
        0) result=ok ;;
        124|137) result=tempo_esgotado ;;
        *) result=falha ;;
    esac
    [ "${3:-}" = "idle" ] && result=sem_trabalho
    if [ "$result" = "sem_trabalho" ]; then
        screen_watch_stop 0
        worker_ping end 0
    else
        screen_watch_stop "$rc"
        worker_ping end "$rc"
    fi
    worker_status "ultima.exit_code=${rc}" "ultima.resultado=${result}" "ultima.duracao_s=${duration}" \
        ultima.fim=@now "+contadores.${result}" "~execucao"
}

# EXIT trap: final status and, with LOG_POST_URL, the POST with the log (within LOG_POST_TIMEOUT)
on_exit() {
    local rc=$?
    trap - EXIT
    [ -n "$SCREEN_WATCH_PID" ] && kill -TERM "$SCREEN_WATCH_PID" 2>/dev/null
    worker_status fase=encerrado "exit_code=${rc}"
    if log_post_enabled; then
        local post_timeout="${LOG_POST_TIMEOUT}"
        [ "$post_timeout" -ge 1 ] 2>/dev/null || post_timeout=8
        local args=(--exit-code "$rc" --mode "${WORKER_RUN_MODE:-}" --started-at "${WORKER_STARTED_AT:-0}"
                    --timeout "${post_timeout}")
        [ "${STOPPED_BY_SIGNAL}" = "1" ] && args+=(--stopped)
        timeout -k 1 "$(( post_timeout + 1 ))" python /app/worker_events.py post "${args[@]}" || true
    fi
    exit "$rc"
}

# Start Xvfb virtual display
start_xvfb() {
    if [ "${USE_XVFB}" != "1" ]; then
        echo "$(log_timestamp) ℹ️  Xvfb disabled (USE_XVFB=${USE_XVFB})"
        return 0
    fi
    
    echo "$(log_timestamp) 🖥️  Starting Xvfb on display ${DISPLAY}..."
    
    # Create X11 socket directory
    mkdir -p /tmp/.X11-unix 2>/dev/null || true
    chmod 1777 /tmp/.X11-unix 2>/dev/null || true
    
    # An X server already answering on this display (shared /tmp/.X11-unix, entrypoint run
    # twice): use it instead of failing to start a second one
    if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
        echo "$(log_timestamp) ✅ X server already running on ${DISPLAY}, using it"
        return 0
    fi

    # Get screen dimensions
    local width=${SCREEN_WIDTH:-1366}
    local height=${SCREEN_HEIGHT:-768}
    
    # Start Xvfb in background
    Xvfb "${DISPLAY}" -screen 0 "${width}x${height}x24" -nolisten tcp &
    XVFB_PID=$!
    
    # Wait for Xvfb to be ready (if it exits, its error is right above in the log)
    local attempt=0
    while ! xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; do
        if ! kill -0 "$XVFB_PID" 2>/dev/null; then
            echo "$(log_timestamp) ❌ Xvfb exited during startup (see its error above)"
            XVFB_PID=""
            return 1
        fi
        sleep 1
        attempt=$((attempt + 1))
        if [ $attempt -ge 10 ]; then
            echo "$(log_timestamp) ❌ Xvfb failed to start"
            return 1
        fi
    done
    
    echo "$(log_timestamp) ✅ Xvfb started successfully (PID: ${XVFB_PID})"
    return 0
}

# Start OpenBox window manager
start_openbox() {
    if [ "${USE_OPENBOX}" != "1" ]; then
        echo "$(log_timestamp) ℹ️  OpenBox disabled (USE_OPENBOX=${USE_OPENBOX})"
        return 0
    fi
    
    # OpenBox requires Xvfb to be running
    if [ "${USE_XVFB}" != "1" ]; then
        echo "$(log_timestamp) ⚠️  OpenBox requires Xvfb (USE_XVFB=1), skipping OpenBox"
        return 0
    fi
    
    echo "$(log_timestamp) 🪟 Setting up OpenBox configuration..."
    
    # Create OpenBox configuration directory
    mkdir -p "${HOME}/.config/openbox" 2>/dev/null || true
    
    # Create a minimal menu.xml if it doesn't exist
    if [ ! -f "${HOME}/.config/openbox/menu.xml" ]; then
        cat > "${HOME}/.config/openbox/menu.xml" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_menu xmlns="http://openbox.org/3.4/menu">
    <menu id="root-menu" label="Openbox 3">
        <item label="Terminal">
            <action name="Execute">
                <command>xterm</command>
            </action>
        </item>
        <separator />
        <item label="Exit">
            <action name="Exit">
                <prompt>no</prompt>
            </action>
        </item>
    </menu>
</openbox_menu>
EOF
    fi
    
    echo "$(log_timestamp) 🪟 Starting OpenBox window manager..."
    openbox --sm-disable &
    OPENBOX_PID=$!
    
    # Give OpenBox time to initialize
    sleep 2
    
    echo "$(log_timestamp) ✅ OpenBox started (PID: ${OPENBOX_PID})"
    return 0
}

# Start PJeOffice
start_pjeoffice() {
    if [ "${USE_PJEOFFICE}" != "1" ]; then
        echo "$(log_timestamp) ℹ️  PJeOffice disabled (USE_PJEOFFICE=${USE_PJEOFFICE})"
        return 0
    fi
    
    if [ ! -f "${PJEOFFICE_EXECUTABLE}" ]; then
        echo "$(log_timestamp) ⚠️  PJeOffice not installed at ${PJEOFFICE_EXECUTABLE}, skipping"
        return 0
    fi
    
    local launcher="${PJEOFFICE_EXECUTABLE}"
    if [ -n "${PJEOFFICE_JAVA_XMX}" ]; then
        launcher="$(pjeoffice_launcher_with_xmx "${PJEOFFICE_JAVA_XMX}")" || launcher="${PJEOFFICE_EXECUTABLE}"
    fi

    echo "$(log_timestamp) 📄 Starting PJeOffice from ${launcher}..."
    "${launcher}" &
    PJEOFFICE_PID=$!
    
    echo "$(log_timestamp) ✅ PJeOffice started (PID: ${PJEOFFICE_PID})"
    return 0
}

# The PJeOffice launcher hardcodes -Xmx2048m (as much as a 2 GB container): with
# PJEOFFICE_JAVA_XMX the same launcher runs from a copy next to it (it finds its files by its
# own directory) with only -Xmx changed. Prints the launcher to run; fails (with a warning) when
# the value or the launcher is not what we expect, and the original launcher is used.
pjeoffice_launcher_with_xmx() {
    local xmx="$1" custom
    if ! [[ "$xmx" =~ ^[0-9]+[mMgG]$ ]]; then
        echo "$(log_timestamp) ⚠️  PJEOFFICE_JAVA_XMX=${xmx} is not like 512m or 1g; keeping the launcher's -Xmx" >&2
        return 1
    fi
    if ! grep -q -- '-Xmx[0-9]*[mMgG]' "${PJEOFFICE_EXECUTABLE}"; then
        echo "$(log_timestamp) ⚠️  no -Xmx in ${PJEOFFICE_EXECUTABLE}; PJEOFFICE_JAVA_XMX ignored" >&2
        return 1
    fi
    custom="$(dirname "${PJEOFFICE_EXECUTABLE}")/.pjeoffice-xmx.sh"
    sed "s/-Xmx[0-9]*[mMgG]/-Xmx${xmx}/" "${PJEOFFICE_EXECUTABLE}" > "$custom" && chmod 755 "$custom" || return 1
    echo "$(log_timestamp) ☕ PJeOffice Java heap limited to ${xmx} (PJEOFFICE_JAVA_XMX)" >&2
    echo "$custom"
}

# Start screen recording
start_screen_recording() {
    if [ "${USE_SCREEN_RECORDING}" != "1" ]; then
        echo "$(log_timestamp) ℹ️  Screen recording disabled (USE_SCREEN_RECORDING=${USE_SCREEN_RECORDING})"
        return 0
    fi
    
    # Screen recording requires Xvfb to be running
    if [ "${USE_XVFB}" != "1" ]; then
        echo "$(log_timestamp) ⚠️  Screen recording requires Xvfb (USE_XVFB=1), skipping recording"
        return 0
    fi
    
    echo "$(log_timestamp) 🎥 Starting screen recording..."
    
    # Ensure recording directory exists
    mkdir -p "${RECORDING_DIR}" 2>/dev/null || true
    
    # Get screen dimensions
    local width=${SCREEN_WIDTH:-1366}
    local height=${SCREEN_HEIGHT:-768}
    
    # Construct full output path
    local output_file="${RECORDING_DIR}/${RECORDING_FILENAME}"
    
    # Start FFmpeg to record the screen
    # Using x11grab to capture from the Xvfb display
    # Options:
    #   -video_size: screen resolution
    #   -framerate: frames per second (15 fps for smaller file size)
    #   -f x11grab: use X11 screen capture
    #   -i :99: capture from display :99
    #   -c:v libx264: use H.264 codec for good compression
    #   -preset ultrafast: fastest encoding (lower CPU usage)
    #   -pix_fmt yuv420p: pixel format for compatibility
    ffmpeg -video_size "${width}x${height}" \
           -framerate 15 \
           -f x11grab \
           -i "${DISPLAY}" \
           -c:v libx264 \
           -preset ultrafast \
           -pix_fmt yuv420p \
           "${output_file}" \
           > /dev/null 2>&1 &
    
    FFMPEG_PID=$!
    
    # Wait a moment to ensure FFmpeg started successfully
    sleep 1
    
    if ps -p "$FFMPEG_PID" > /dev/null 2>&1; then
        echo "$(log_timestamp) ✅ Screen recording started (PID: ${FFMPEG_PID})"
        echo "$(log_timestamp) 📁 Recording to: ${output_file}"
        return 0
    else
        echo "$(log_timestamp) ❌ Failed to start screen recording"
        FFMPEG_PID=""
        return 1
    fi
}

# Start VNC server for remote debugging
start_vnc() {
    if [ "${USE_VNC}" != "1" ]; then
        echo "$(log_timestamp) ℹ️  VNC server disabled (USE_VNC=${USE_VNC})"
        return 0
    fi
    
    # VNC requires Xvfb to be running
    if [ "${USE_XVFB}" != "1" ]; then
        echo "$(log_timestamp) ⚠️  WARNING: VNC server requires Xvfb (USE_XVFB=1), skipping VNC"
        return 0
    fi
    
    echo "$(log_timestamp) 🖥️  Starting VNC server..."
    
    # Get VNC port configuration
    local vnc_port=${VNC_PORT:-5900}

    # Password (optional): written to a 0600 file that x11vnc reads and deletes (rm:), never
    # in argv; the variable is dropped so the scripts do not inherit it
    local auth=(-nopw) auth_note="no password"
    local password_file=/tmp/.x11vnc-passwd
    if [ -n "${VNC_PASSWORD_FILE:-}" ] || [ -n "${VNC_PASSWORD:-}" ]; then
        (
            umask 077
            if [ -n "${VNC_PASSWORD_FILE:-}" ]; then
                head -n 1 "${VNC_PASSWORD_FILE}"
            else
                printf '%s\n' "${VNC_PASSWORD}"
            fi
        ) > "$password_file" 2>/dev/null
        unset VNC_PASSWORD
        if [ -s "$password_file" ]; then
            auth=(-passwdfile "rm:${password_file}")
            auth_note="password required"
        else
            rm -f "$password_file"
            echo "$(log_timestamp) ⚠️  VNC_PASSWORD_FILE unreadable or empty: skipping VNC (it would be open without a password)"
            return 0
        fi
    fi
    if [ "${VNC_VIEW_ONLY}" = "1" ]; then
        auth+=(-viewonly)
        auth_note="${auth_note}, view only"
    fi
    
    # Start x11vnc server
    # Options:
    #   -display: specify X display to connect to
    #   -forever: keep listening for new connections (don't exit after first client disconnects)
    #   -shared: allow multiple VNC clients to connect simultaneously
    #   -rfbport: VNC server port
    #   -nopw / -passwdfile: no password (trusted networks only) or VNC_PASSWORD(_FILE)
    #   -viewonly: VNC_VIEW_ONLY=1
    #   -bg: run in background
    #   -o: log file location
    x11vnc -display "${DISPLAY}" \
           -forever \
           -shared \
           -rfbport "${vnc_port}" \
           "${auth[@]}" \
           -bg \
           -o /app/logs/x11vnc.log
    
    # Get the PID of x11vnc
    # Wait a moment for x11vnc to start and write its PID
    sleep 1
    VNC_PID=$(pgrep -f "x11vnc.*${DISPLAY}" | head -1)
    
    if [ -n "$VNC_PID" ] && ps -p "$VNC_PID" > /dev/null 2>&1; then
        echo "$(log_timestamp) ✅ VNC server started successfully (PID: ${VNC_PID})"
        echo "$(log_timestamp) 🌐 VNC server listening on port: ${vnc_port} (${auth_note})"
        echo "$(log_timestamp) 💡 Connect with: vncviewer <container-ip>:${vnc_port}"
        return 0
    else
        echo "$(log_timestamp) ⚠️  Failed to start VNC server"
        VNC_PID=""
        return 1
    fi
}

# Start noVNC with websockify for browser-based VNC access
start_novnc() {
    if [ "${USE_NOVNC}" != "1" ]; then
        echo "$(log_timestamp) ℹ️  noVNC disabled (USE_NOVNC=${USE_NOVNC})"
        return 0
    fi
    
    # noVNC requires VNC to be running
    if [ "${USE_VNC}" != "1" ]; then
        echo "$(log_timestamp) ⚠️  noVNC requires VNC server (USE_VNC=1), skipping noVNC"
        return 0
    fi
    
    # Check if noVNC is installed
    if [ ! -d "/opt/novnc" ] || ! command -v websockify &> /dev/null; then
        echo "$(log_timestamp) ⚠️  noVNC or websockify not installed, skipping noVNC"
        return 0
    fi
    
    echo "$(log_timestamp) 🌐 Starting noVNC with websockify..."
    
    # Get configuration
    local vnc_port=${VNC_PORT:-5900}
    local novnc_port=${NOVNC_PORT:-6080}
    
    # Start websockify to proxy VNC through WebSocket for noVNC
    # Options:
    #   --web: path to noVNC web files
    #   localhost:5900: VNC server to connect to
    #   0.0.0.0:6080: WebSocket server to listen on (accessible from outside container)
    /usr/local/bin/websockify --web /opt/novnc 0.0.0.0:${novnc_port} localhost:${vnc_port} > /app/logs/novnc.log 2>&1 &
    
    NOVNC_PID=$!
    
    # Wait a moment for websockify to start
    sleep 2
    
    if [ -n "$NOVNC_PID" ] && ps -p "$NOVNC_PID" > /dev/null 2>&1; then
        echo "$(log_timestamp) ✅ noVNC started successfully (PID: ${NOVNC_PID})"
        echo "$(log_timestamp) 🌐 noVNC listening on port: ${novnc_port}"
        echo "$(log_timestamp) 💡 Access via browser: http://<container-ip>:${novnc_port}/vnc.html"
        return 0
    else
        echo "$(log_timestamp) ⚠️  Failed to start noVNC"
        NOVNC_PID=""
        return 1
    fi
}

# URL safe for logs: hides user:password and every query value (tokens, signatures).
# The URL goes through stdin so it never shows up in `ps`.
mask_url() {
    printf '%s' "$1" | python /app/script_downloader.py --mask 2>/dev/null || echo "***"
}

# Function to download script with retry and backoff
download_script_with_retry() {
    local url="$1"
    local max_time=90
    local attempt=1
    local wait_time=5
    local start_time
    start_time=$(date +%s)

    echo "$(log_timestamp) ⬇️  Downloading script from: $(mask_url "$url")"

    while true; do
        local current_time
        current_time=$(date +%s)
        local elapsed=$((current_time - start_time))

        if [ $elapsed -ge $max_time ]; then
            echo "$(log_timestamp) ❌ Download timeout after ${elapsed}s (max ${max_time}s)"
            return 1
        fi

        echo "$(log_timestamp) 🔄 Download attempt $attempt (elapsed: ${elapsed}s)..."

        # Run the script downloader (exit 3: SCRIPT_SHA256 mismatch, retrying does not help)
        local rc=0
        python /app/script_downloader.py || rc=$?
        if [ "$rc" -eq 0 ]; then
            echo "$(log_timestamp) ✅ Script downloaded successfully"
            return 0
        fi
        if [ "$rc" -eq 3 ]; then
            echo "$(log_timestamp) ❌ The downloaded script does not match SCRIPT_SHA256: not running it"
            return 1
        fi

        attempt=$((attempt + 1))

        # Exponential backoff: 5s, 10s, 20s, 40s
        echo "$(log_timestamp) ⏳ Waiting ${wait_time}s before retry..."
        sleep $wait_time
        wait_time=$((wait_time * 2))

        # Cap wait time at 40s
        if [ $wait_time -gt 40 ]; then
            wait_time=40
        fi
    done
}

# Runs "$@" and, with RESOURCE_SUMMARY=1, prints how much CPU/memory the container used
# meanwhile (average, p95, peak). The exit code is the command's own.
run_measured() {
    local label="$1"
    shift
    if [ "${RESOURCE_SUMMARY}" = "1" ] && [ -f /app/resource_usage.py ]; then
        python /app/resource_usage.py run --label "${label}" -- "$@"
    else
        "$@"
    fi
}

# Function to download and execute a script
download_and_execute() {
    echo "$(log_timestamp) 🔍 Checking for SCRIPT_URL environment variable..."

    if [ -n "$SCRIPT_URL" ]; then
        echo "$(log_timestamp) 🎯 SCRIPT_URL detected: $(mask_url "$SCRIPT_URL")"

        # Download with retry logic
        if ! download_script_with_retry "$SCRIPT_URL"; then
            echo "$(log_timestamp) ❌ ERROR: Script download failed after retries"
            return 1
        fi

        # Determine the downloaded script path
        SCRIPT_PATH=$(python -c "
import os
import sys
sys.path.insert(0, '/app')
from script_downloader import get_filename_from_url

url = os.getenv('SCRIPT_URL')
if url:
    print(f'/tmp/{get_filename_from_url(url)}')
else:
    sys.exit(1)
")

        # Validate script exists
        if [ -z "$SCRIPT_PATH" ]; then
            echo "$(log_timestamp) ❌ ERROR: Failed to determine script path"
            return 1
        fi

        if [ ! -f "$SCRIPT_PATH" ]; then
            echo "$(log_timestamp) ❌ ERROR: Downloaded script not found at $SCRIPT_PATH"
            return 1
        fi

        echo "$(log_timestamp) ▶️  Executing downloaded script: $SCRIPT_PATH"
        run_measured "$(basename "$SCRIPT_PATH")" python "$SCRIPT_PATH"
        return $?
    else
        echo "$(log_timestamp) ℹ️  SCRIPT_URL not set, running default smoke test..."
        run_measured smoke_test.py python /app/smoke_test.py
        return $?
    fi
}

# Before each loop iteration: with the egress relay on, is it still working?
# Same check as at startup (EGRESS_CHECK_URL; "off" only probes the relay itself).
# Without the relay this is a no-op.
egress_ready() {
    [ -n "${EGRESS_PID}" ] || return 0
    local result
    if result="$(python /app/egress_proxy.py check --port "${EGRESS_LOCAL_PORT}" 2>&1)"; then
        return 0
    fi
    echo "$(log_timestamp) ⚠️  Egress relay unavailable, skipping this iteration: ${result}"
    return 1
}

# PIDs of browsers and drivers (Chrome, Firefox, chromedriver, uc_driver, geckodriver).
# Matched by executable, so services (Xvfb, OpenBox, PJeOffice, VNC, relay) never match.
browser_pids() {
    local link exe pid
    for link in /proc/[0-9]*/exe; do
        exe="$(readlink "$link" 2>/dev/null)" || continue
        case "$exe" in
            /opt/chrome/*|/opt/firefox/*|*/chromedriver|*/chromedriver\ *|*/uc_driver|*/uc_driver\ *|*/geckodriver|*/geckodriver\ *) ;;
            *) continue ;;
        esac
        pid="${link#/proc/}"
        echo "${pid%/exe}"
    done
}

# After each loop iteration: browsers/drivers the script left open (crash, timeout, no quit())
# keep using CPU and memory in the next one. Close them (TERM, then KILL after 5s) and remove
# their temporary profiles. WORKER_CLEANUP=0 skips this.
cleanup_iteration() {
    [ "${WORKER_CLEANUP}" = "1" ] || return 0
    local pids count waited=0
    pids="$(browser_pids)"
    if [ -n "$pids" ]; then
        count="$(echo "$pids" | wc -l)"
        echo "$(log_timestamp) 🧹 Closing ${count} browser/driver process(es) left by the iteration..."
        # shellcheck disable=SC2086
        kill -TERM $pids 2>/dev/null || true
        while [ -n "$(browser_pids)" ] && [ "$waited" -lt 5 ]; do
            sleep 1
            waited=$((waited + 1))
        done
        pids="$(browser_pids)"
        if [ -n "$pids" ]; then
            # shellcheck disable=SC2086
            kill -KILL $pids 2>/dev/null || true
            sleep 1
        fi
    fi
    if [ -z "$(browser_pids)" ]; then
        remove_browser_temp
    fi
    return 0
}

# Temporary profiles of browsers that are no longer running (chromedriver/geckodriver create
# them per session; killed browsers leave them behind, and /dev/shm counts as memory).
# Only call it when no browser is running.
remove_browser_temp() {
    rm -rf /tmp/.org.chromium.Chromium.* /tmp/.com.google.Chrome.* /tmp/rust_mozprofile* \
        /dev/shm/.org.chromium.Chromium.* /dev/shm/.com.google.Chrome.* 2>/dev/null || true
}

# PREFLIGHT_ON_START=1: is the worker ready (browsers, A1, relay, PJeOffice)? Runs once, after
# the services start and before the first task; a failure stops the container (exit 1).
preflight_on_start() {
    [ "${PREFLIGHT_ON_START}" = "1" ] || return 0
    local args=()
    read -r -a args <<< "${PREFLIGHT_ARGS}"
    echo "$(log_timestamp) 🩺 PREFLIGHT_ON_START=1: checking the worker before the first task..."
    if python /app/preflight.py --json /app/logs/preflight.json "${args[@]}"; then
        echo "$(log_timestamp) ✅ Preflight passed (report: /app/logs/preflight.json)"
        return 0
    fi
    echo "$(log_timestamp) ❌ Preflight failed: stopping before the first task (report: /app/logs/preflight.json)"
    exit 1
}

# WORKER_IDLE_EXIT_CODE: a valid exit code (1-255, not 124/137 used by the timeout), or empty
idle_exit_code() {
    local code="${WORKER_IDLE_EXIT_CODE}"
    [ -n "$code" ] || return 0
    if [[ "$code" =~ ^[0-9]+$ ]] && [ "$code" -ge 1 ] && [ "$code" -le 255 ] \
        && [ "$code" -ne 124 ] && [ "$code" -ne 137 ]; then
        echo "$code"
    fi
}

# Wait after $1 idle iterations in a row: WORKER_RESTART_DELAY doubled once per idle iteration,
# never above WORKER_IDLE_MAX_DELAY (nor below WORKER_RESTART_DELAY)
idle_delay() {
    local count="$1" delay="${WORKER_RESTART_DELAY}" cap="${WORKER_IDLE_MAX_DELAY}"
    [ "$delay" -ge 1 ] 2>/dev/null || delay=1
    [ "$cap" -ge "$delay" ] 2>/dev/null || cap="$delay"
    while [ "$count" -gt 0 ] && [ "$delay" -lt "$cap" ]; do
        delay=$((delay * 2))
        count=$((count - 1))
    done
    [ "$delay" -le "$cap" ] || delay="$cap"
    echo "$delay"
}

# Execute script in loop mode with restart
execute_with_loop() {
    echo "$(log_timestamp) 🔁 Worker loop mode enabled (timeout: ${WORKER_TIMEOUT}s + ${WORKER_KILL_AFTER}s to stop, restart delay: ${WORKER_RESTART_DELAY}s)"

    # The iteration runs in a child bash (so `timeout` can kill it) using the same
    # functions as single-run mode
    export -f log_timestamp mask_url download_script_with_retry run_measured download_and_execute

    local iteration=1 idle_code idle_count=0
    idle_code="$(idle_exit_code)"
    if [ -n "${WORKER_IDLE_EXIT_CODE}" ] && [ -z "$idle_code" ]; then
        echo "$(log_timestamp) ⚠️  WORKER_IDLE_EXIT_CODE=${WORKER_IDLE_EXIT_CODE} ignored (use 1-255, except 124 and 137)"
    elif [ -n "$idle_code" ]; then
        echo "$(log_timestamp) 💤 Exit code ${idle_code} means \"nothing to do\": waits double up to ${WORKER_IDLE_MAX_DELAY}s"
    fi

    while true; do
        echo ""
        if ! egress_ready; then
            local retry_delay="${WORKER_RESTART_DELAY}"
            [ "${retry_delay}" -ge 10 ] 2>/dev/null || retry_delay=10
            echo "$(log_timestamp) 💤 Checking the egress relay again in ${retry_delay}s..."
            run_child sleep "${retry_delay}" || true
            continue
        fi

        echo "$(log_timestamp) 🚀 Starting iteration #${iteration}..."
        local began exit_code=0 idle=""
        began=$(date +%s)
        before_execution "${iteration}"

        # Execute script with timeout: SIGTERM to the whole iteration at WORKER_TIMEOUT,
        # SIGKILL WORKER_KILL_AFTER seconds later if it is still running. The child bash
        # traps TERM so it waits for the script: if bash died first, timeout would return
        # at once and a script that ignores SIGTERM would keep running into the next iteration.
        run_child timeout --kill-after="${WORKER_KILL_AFTER}" "${WORKER_TIMEOUT}" bash -c 'trap : TERM; download_and_execute' || exit_code=$?
        if [ $exit_code -eq 0 ]; then
            echo "$(log_timestamp) ✅ Script completed successfully"
        elif [ $exit_code -eq 124 ]; then
            echo "$(log_timestamp) ⏱️  Script timed out after ${WORKER_TIMEOUT}s (stopped with SIGTERM)"
        elif [ $exit_code -eq 137 ]; then
            echo "$(log_timestamp) ⏱️  Script timed out after ${WORKER_TIMEOUT}s and ignored SIGTERM: killed after ${WORKER_KILL_AFTER}s more"
        elif [ -n "$idle_code" ] && [ $exit_code -eq "$idle_code" ]; then
            idle=idle
        else
            echo "$(log_timestamp) ❌ Script failed with exit code: $exit_code"
        fi

        after_execution "$exit_code" "$began" "$idle"
        cleanup_iteration
        rotate_logs

        iteration=$((iteration + 1))

        local delay="${WORKER_RESTART_DELAY}"
        if [ -n "$idle" ]; then
            idle_count=$((idle_count + 1))
            delay="$(idle_delay "$idle_count")"
            echo "$(log_timestamp) 💤 Nothing to do (exit ${exit_code}, ${idle_count} in a row): next iteration in ${delay}s"
        else
            idle_count=0
            echo "$(log_timestamp) 💤 Waiting ${delay}s before next iteration..."
        fi
        worker_status fase=esperando "proxima_em=@in:${delay}"
        run_child sleep "${delay}" || true
    done
}

# Main execution
# How the container will run (status.json and the POST at the end)
run_mode() {
    if [ "${WORKER_MODE}" = "standby" ]; then
        echo standby
    elif [ "${WORKER_LOOP}" = "1" ]; then
        echo loop
    elif [ -n "$SCRIPT_URL" ]; then
        echo script
    else
        echo comando
    fi
}

# WORKER_STATUS=1: how long each enabled service took to start (status.json "partida").
# timed_start <name> <its USE_* value> <function>
STARTUP_TIMES=()
timed_start() {
    local name="$1" enabled="$2" began elapsed
    shift 2
    if [ "${WORKER_STATUS}" != "1" ] || [ "$enabled" != "1" ]; then
        "$@"
        return
    fi
    began=$(date +%s%N)
    "$@"
    elapsed=$(( ($(date +%s%N) - began) / 1000000 ))
    STARTUP_TIMES+=("partida.${name}_s=$((elapsed / 1000)).$(( (elapsed % 1000) / 100 ))")
}

# Single run with SCRIPT_URL: the container's exit code is the script's
run_single() {
    local began exit_code=0
    began=$(date +%s)
    before_execution 1
    run_child download_and_execute || exit_code=$?
    after_execution "$exit_code" "$began"
    return "$exit_code"
}

main() {
    export WORKER_STARTED_AT WORKER_RUN_MODE
    WORKER_STARTED_AT="$(date +%s)"
    WORKER_RUN_MODE="$(run_mode)"
    capture_output
    echo "$(log_timestamp) 🚀 Starting RPA Worker Selenium..."
    log_image_info
    
    # Setup directories
    setup_directories
    worker_status --init "modo=${WORKER_RUN_MODE}" fase=iniciando
    clear_stale_locks
    setup_firefox_profile

    # Optional egress relay: must come before any download
    setup_egress_proxy

    # Download Chrome profile at runtime if needed
    download_chrome_profile
    
    # Start optional services
    local services_began
    services_began=$(date +%s%N)
    timed_start xvfb "${USE_XVFB}" start_xvfb
    timed_start openbox "${USE_OPENBOX}" start_openbox
    timed_start pjeoffice "${USE_PJEOFFICE}" start_pjeoffice
    timed_start vnc "${USE_VNC}" start_vnc
    timed_start novnc "${USE_NOVNC}" start_novnc
    start_screen_recording

    # Optional: stop here if the worker is not ready (PREFLIGHT_ON_START=1)
    timed_start preflight "${PREFLIGHT_ON_START}" preflight_on_start
    if [ "${WORKER_STATUS}" = "1" ]; then
        local total_ms=$(( ($(date +%s%N) - services_began) / 1000000 ))
        worker_status fase=pronto "${STARTUP_TIMES[@]}" \
            "partida.total_s=$((total_ms / 1000)).$(( (total_ms % 1000) / 100 ))"
    fi
    
    # Check if we're in standby mode (HTTP server)
    if [ "${WORKER_MODE}" = "standby" ]; then
        echo "$(log_timestamp) 🌐 Worker mode: STANDBY (HTTP server)"
        echo "$(log_timestamp) 🚀 Starting task server on port ${TASK_SERVER_PORT}..."
        worker_status fase=standby
        local rc=0
        run_child python /app/task_server.py || rc=$?
        exit "$rc"
    fi
    
    # Check if we're in loop mode or single execution mode
    if [ "${WORKER_LOOP}" = "1" ]; then
        execute_with_loop
    elif [ -n "$SCRIPT_URL" ]; then
        # Single execution with SCRIPT_URL
        run_single
    else
        # No SCRIPT_URL and no loop mode, execute arguments as normal
        if log_post_enabled; then
            echo "$(log_timestamp) ⚠️  LOG_POST_URL does not apply to a direct command (it replaces the entrypoint): nothing is sent at the end"
        fi
        echo "$(log_timestamp) ▶️  Executing command: $*"
        exec "$@"
    fi
}

main "$@"
