#!/bin/bash
# Entrypoint script for RPA Worker Selenium with script downloading
# Handles downloading scripts from URLs and executing them
# Optionally starts Xvfb, OpenBox, and PJeOffice services
# Supports loop execution with auto-restart and runtime Chrome profile download

set -e

# Export environment variables for child processes
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export DISPLAY=${DISPLAY:-:99}

# PJeOffice paths - configurable via environment variables
export PJEOFFICE_CONFIG_DIR=${PJEOFFICE_CONFIG_DIR:-/app/.pjeoffice-pro}
export PJEOFFICE_CONFIG_FILE=${PJEOFFICE_CONFIG_FILE:-${PJEOFFICE_CONFIG_DIR}/pjeoffice-pro.config}
export PJEOFFICE_EXECUTABLE=${PJEOFFICE_EXECUTABLE:-/opt/pjeoffice/pjeoffice-pro.sh}

# Screen recording configuration
export RECORDING_DIR=${RECORDING_DIR:-/app/recordings}
export RECORDING_FILENAME=${RECORDING_FILENAME:-recording_$(date +%Y%m%d_%H%M%S).mp4}

# Worker configuration
export WORKER_LOOP=${WORKER_LOOP:-0}
export WORKER_TIMEOUT=${WORKER_TIMEOUT:-3600}  # 1 hour default
export WORKER_RESTART_DELAY=${WORKER_RESTART_DELAY:-120}  # 2 minutes default

# PIDs for background processes
XVFB_PID=""
OPENBOX_PID=""
PJEOFFICE_PID=""
FFMPEG_PID=""
VNC_PID=""
NOVNC_PID=""

# Timestamp function for logging
log_timestamp() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]"
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
    
    return 0
}

# Download Chrome profile at runtime if not done at build time
download_chrome_profile() {
    if [ -z "$CHROME_PROFILE_URL" ]; then
        echo "$(log_timestamp) ℹ️  CHROME_PROFILE_URL not set, skipping profile download"
        return 0
    fi
    
    # Check if profile already exists from build time
    if [ -d "/usr/local/share/chrome-profile" ] && [ "$(ls -A /usr/local/share/chrome-profile 2>/dev/null)" ]; then
        echo "$(log_timestamp) ✅ Chrome profile already present from build time"
        return 0
    fi
    
    echo "$(log_timestamp) ⬇️  Downloading Chrome profile from runtime..."
    
    mkdir -p /usr/local/share/chrome-profile
    
    if curl -fsSL "$CHROME_PROFILE_URL" -o /tmp/chrome-profile.zip; then
        if unzip -q /tmp/chrome-profile.zip -d /usr/local/share/chrome-profile; then
            rm -f /tmp/chrome-profile.zip
            echo "$(log_timestamp) ✅ Chrome profile downloaded and extracted successfully"
            return 0
        else
            echo "$(log_timestamp) ❌ Failed to extract Chrome profile"
            rm -f /tmp/chrome-profile.zip
            return 1
        fi
    else
        echo "$(log_timestamp) ❌ Failed to download Chrome profile"
        return 1
    fi
}

# Signal handling for graceful shutdown
handle_sigterm() {
    echo "$(log_timestamp) 🛑 Received shutdown signal, cleaning up..."
    [ -n "$NOVNC_PID" ] && kill -TERM "$NOVNC_PID" 2>/dev/null || true
    [ -n "$VNC_PID" ] && kill -TERM "$VNC_PID" 2>/dev/null || true
    [ -n "$FFMPEG_PID" ] && kill -TERM "$FFMPEG_PID" 2>/dev/null || true
    [ -n "$XVFB_PID" ] && kill -TERM "$XVFB_PID" 2>/dev/null || true
    [ -n "$OPENBOX_PID" ] && kill -TERM "$OPENBOX_PID" 2>/dev/null || true
    [ -n "$PJEOFFICE_PID" ] && kill -TERM "$PJEOFFICE_PID" 2>/dev/null || true
    
    # Wait a moment for FFmpeg to finalize the recording
    if [ -n "$FFMPEG_PID" ]; then
        sleep 2
    fi
    
    exit 0
}

trap handle_sigterm SIGTERM SIGINT

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
    
    # Get screen dimensions
    local width=${SCREEN_WIDTH:-1366}
    local height=${SCREEN_HEIGHT:-768}
    
    # Start Xvfb in background
    Xvfb "${DISPLAY}" -screen 0 "${width}x${height}x24" -nolisten tcp &
    XVFB_PID=$!
    
    # Wait for Xvfb to be ready
    local attempt=0
    while ! xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; do
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
    
    echo "$(log_timestamp) 📄 Starting PJeOffice from ${PJEOFFICE_EXECUTABLE}..."
    "${PJEOFFICE_EXECUTABLE}" &
    PJEOFFICE_PID=$!
    
    echo "$(log_timestamp) ✅ PJeOffice started (PID: ${PJEOFFICE_PID})"
    return 0
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
        echo "$(log_timestamp) ⚠️  VNC server requires Xvfb (USE_XVFB=1), skipping VNC"
        return 0
    fi
    
    echo "$(log_timestamp) 🖥️  Starting VNC server..."
    
    # Get VNC port configuration
    local vnc_port=${VNC_PORT:-5900}
    
    # Start x11vnc server
    # Options:
    #   -display: specify X display to connect to
    #   -forever: keep listening for new connections (don't exit after first client disconnects)
    #   -shared: allow multiple VNC clients to connect simultaneously
    #   -rfbport: VNC server port
    #   -nopw: no password required (suitable for local/trusted networks)
    #   -bg: run in background
    #   -o: log file location
    x11vnc -display "${DISPLAY}" \
           -forever \
           -shared \
           -rfbport "${vnc_port}" \
           -nopw \
           -bg \
           -o /app/logs/x11vnc.log
    
    # Get the PID of x11vnc
    # Wait a moment for x11vnc to start and write its PID
    sleep 1
    VNC_PID=$(pgrep -f "x11vnc.*${DISPLAY}" | head -1)
    
    if [ -n "$VNC_PID" ] && ps -p "$VNC_PID" > /dev/null 2>&1; then
        echo "$(log_timestamp) ✅ VNC server started successfully (PID: ${VNC_PID})"
        echo "$(log_timestamp) 🌐 VNC server listening on port: ${vnc_port}"
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

# Function to download script with retry and backoff
download_script_with_retry() {
    local url="$1"
    local max_time=90
    local attempt=1
    local wait_time=5
    local start_time=$(date +%s)
    
    echo "$(log_timestamp) ⬇️  Downloading script from: $url"
    
    while true; do
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        
        if [ $elapsed -ge $max_time ]; then
            echo "$(log_timestamp) ❌ Download timeout after ${elapsed}s (max ${max_time}s)"
            return 1
        fi
        
        echo "$(log_timestamp) 🔄 Download attempt $attempt (elapsed: ${elapsed}s)..."
        
        # Run the script downloader
        if python /app/script_downloader.py; then
            echo "$(log_timestamp) ✅ Script downloaded successfully"
            return 0
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

# Function to download and execute a script
download_and_execute() {
    echo "$(log_timestamp) 🔍 Checking for SCRIPT_URL environment variable..."
    
    if [ -n "$SCRIPT_URL" ]; then
        echo "$(log_timestamp) 🎯 SCRIPT_URL detected: $SCRIPT_URL"
        
        # Download with retry logic
        if ! download_script_with_retry "$SCRIPT_URL"; then
            echo "$(log_timestamp) ❌ ERROR: Script download failed after retries"
            return 1
        fi
        
        # Determine the downloaded script path
        SCRIPT_PATH=$(python -c "
import os
import sys
try:
    from script_downloader import get_filename_from_url
    url = os.getenv('SCRIPT_URL')
    if url:
        print(f'/tmp/{get_filename_from_url(url)}')
    else:
        sys.exit(1)
except Exception as e:
    sys.stderr.write(f'Error getting script path: {e}\n')
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
        python "$SCRIPT_PATH"
        return $?
    else
        echo "$(log_timestamp) ℹ️  SCRIPT_URL not set, running default smoke test..."
        python /app/smoke_test.py
        return $?
    fi
}

# Execute script in loop mode with restart
execute_with_loop() {
    echo "$(log_timestamp) 🔁 Worker loop mode enabled (timeout: ${WORKER_TIMEOUT}s, restart delay: ${WORKER_RESTART_DELAY}s)"
    
    local iteration=1
    
    while true; do
        echo ""
        echo "$(log_timestamp) 🚀 Starting iteration #${iteration}..."
        
        # Execute script with timeout - call function directly
        if timeout ${WORKER_TIMEOUT} bash << 'SCRIPT_EOF'
            # Source the functions we need in this subshell
            log_timestamp() { echo "[$(date '+%Y-%m-%d %H:%M:%S')]"; }
            
            # Re-define download function in subshell
            download_script_with_retry() {
                local url="$1"
                local max_time=90
                local attempt=1
                local wait_time=5
                local start_time=$(date +%s)
                
                echo "$(log_timestamp) ⬇️  Downloading script from: $url"
                
                while true; do
                    local current_time=$(date +%s)
                    local elapsed=$((current_time - start_time))
                    
                    if [ $elapsed -ge $max_time ]; then
                        echo "$(log_timestamp) ❌ Download timeout after ${elapsed}s (max ${max_time}s)"
                        return 1
                    fi
                    
                    echo "$(log_timestamp) 🔄 Download attempt $attempt (elapsed: ${elapsed}s)..."
                    
                    if python /app/script_downloader.py; then
                        echo "$(log_timestamp) ✅ Script downloaded successfully"
                        return 0
                    fi
                    
                    attempt=$((attempt + 1))
                    echo "$(log_timestamp) ⏳ Waiting ${wait_time}s before retry..."
                    sleep $wait_time
                    wait_time=$((wait_time * 2))
                    
                    if [ $wait_time -gt 40 ]; then
                        wait_time=40
                    fi
                done
            }
            
            # Execute download and run
            if [ -n "$SCRIPT_URL" ]; then
                if ! download_script_with_retry "$SCRIPT_URL"; then
                    echo "$(log_timestamp) ❌ ERROR: Script download failed after retries"
                    exit 1
                fi
                
                SCRIPT_PATH=$(python -c "
import os
import sys
try:
    from script_downloader import get_filename_from_url
    url = os.getenv('SCRIPT_URL')
    if url:
        print(f'/tmp/{get_filename_from_url(url)}')
    else:
        sys.exit(1)
except Exception as e:
    sys.stderr.write(f'Error: {e}\n')
    sys.exit(1)
")
                
                if [ -z "$SCRIPT_PATH" ] || [ ! -f "$SCRIPT_PATH" ]; then
                    echo "$(log_timestamp) ❌ ERROR: Downloaded script not found"
                    exit 1
                fi
                
                echo "$(log_timestamp) ▶️  Executing downloaded script: $SCRIPT_PATH"
                python "$SCRIPT_PATH"
            else
                echo "$(log_timestamp) ℹ️  SCRIPT_URL not set, running default smoke test..."
                python /app/smoke_test.py
            fi
SCRIPT_EOF
        then
            echo "$(log_timestamp) ✅ Script completed successfully"
        else
            local exit_code=$?
            if [ $exit_code -eq 124 ]; then
                echo "$(log_timestamp) ⏱️  Script timed out after ${WORKER_TIMEOUT}s (forcing cleanup)"
            else
                echo "$(log_timestamp) ❌ Script failed with exit code: $exit_code"
            fi
        fi
        
        iteration=$((iteration + 1))
        
        echo "$(log_timestamp) 💤 Waiting ${WORKER_RESTART_DELAY}s before next iteration..."
        sleep ${WORKER_RESTART_DELAY}
        
        echo "$(log_timestamp) 🧹 Cleaning up for next iteration..."
        # Optional: Add cleanup tasks here (clear temp files, reset state, etc.)
    done
}

# Main execution
main() {
    echo "$(log_timestamp) 🚀 Starting RPA Worker Selenium..."
    
    # Setup directories
    setup_directories
    
    # Download Chrome profile at runtime if needed
    download_chrome_profile
    
    # Start optional services
    start_xvfb
    start_openbox
    start_pjeoffice
    start_vnc
    start_novnc
    start_screen_recording
    
    # Check if we're in loop mode or single execution mode
    if [ "${WORKER_LOOP}" = "1" ]; then
        execute_with_loop
    elif [ -n "$SCRIPT_URL" ]; then
        # Single execution with SCRIPT_URL
        download_and_execute
    else
        # No SCRIPT_URL and no loop mode, execute arguments as normal
        echo "$(log_timestamp) ▶️  Executing command: $@"
        exec "$@"
    fi
}

main "$@"
