#!/bin/bash
# Entrypoint script for RPA Worker Selenium with script downloading
# Handles downloading scripts from URLs and executing them
# Optionally starts Xvfb, OpenBox, and PJeOffice services

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

# PIDs for background processes
XVFB_PID=""
OPENBOX_PID=""
PJEOFFICE_PID=""
FFMPEG_PID=""
VNC_PID=""
NOVNC_PID=""

# Setup directories with proper permissions
setup_directories() {
    echo "[entrypoint] Setting up directories..."
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

# Signal handling for graceful shutdown
handle_sigterm() {
    echo "[entrypoint] Received shutdown signal, cleaning up..."
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
        echo "[entrypoint] Xvfb disabled (USE_XVFB=${USE_XVFB})"
        return 0
    fi
    
    echo "[entrypoint] Starting Xvfb on display ${DISPLAY}..."
    
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
            echo "[entrypoint] ERROR: Xvfb failed to start"
            return 1
        fi
    done
    
    echo "[entrypoint] Xvfb started successfully (PID: ${XVFB_PID})"
    return 0
}

# Start OpenBox window manager
start_openbox() {
    if [ "${USE_OPENBOX}" != "1" ]; then
        echo "[entrypoint] OpenBox disabled (USE_OPENBOX=${USE_OPENBOX})"
        return 0
    fi
    
    # OpenBox requires Xvfb to be running
    if [ "${USE_XVFB}" != "1" ]; then
        echo "[entrypoint] WARNING: OpenBox requires Xvfb (USE_XVFB=1), skipping OpenBox"
        return 0
    fi
    
    echo "[entrypoint] Setting up OpenBox configuration..."
    
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
    
    echo "[entrypoint] Starting OpenBox window manager..."
    openbox --sm-disable &
    OPENBOX_PID=$!
    
    # Give OpenBox time to initialize
    sleep 2
    
    echo "[entrypoint] OpenBox started (PID: ${OPENBOX_PID})"
    return 0
}

# Start PJeOffice
start_pjeoffice() {
    if [ "${USE_PJEOFFICE}" != "1" ]; then
        echo "[entrypoint] PJeOffice disabled (USE_PJEOFFICE=${USE_PJEOFFICE})"
        return 0
    fi
    
    if [ ! -f "${PJEOFFICE_EXECUTABLE}" ]; then
        echo "[entrypoint] PJeOffice not installed at ${PJEOFFICE_EXECUTABLE}, skipping"
        return 0
    fi
    
    echo "[entrypoint] Starting PJeOffice from ${PJEOFFICE_EXECUTABLE}..."
    "${PJEOFFICE_EXECUTABLE}" &
    PJEOFFICE_PID=$!
    
    echo "[entrypoint] PJeOffice started (PID: ${PJEOFFICE_PID})"
    return 0
}

# Start screen recording
start_screen_recording() {
    if [ "${USE_SCREEN_RECORDING}" != "1" ]; then
        echo "[entrypoint] Screen recording disabled (USE_SCREEN_RECORDING=${USE_SCREEN_RECORDING})"
        return 0
    fi
    
    # Screen recording requires Xvfb to be running
    if [ "${USE_XVFB}" != "1" ]; then
        echo "[entrypoint] WARNING: Screen recording requires Xvfb (USE_XVFB=1), skipping recording"
        return 0
    fi
    
    echo "[entrypoint] Starting screen recording..."
    
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
        echo "[entrypoint] Screen recording started (PID: ${FFMPEG_PID})"
        echo "[entrypoint] Recording to: ${output_file}"
        return 0
    else
        echo "[entrypoint] ERROR: Failed to start screen recording"
        FFMPEG_PID=""
        return 1
    fi
}

# Start VNC server for remote debugging
start_vnc() {
    if [ "${USE_VNC}" != "1" ]; then
        echo "[entrypoint] VNC server disabled (USE_VNC=${USE_VNC})"
        return 0
    fi
    
    # VNC requires Xvfb to be running
    if [ "${USE_XVFB}" != "1" ]; then
        echo "[entrypoint] WARNING: VNC server requires Xvfb (USE_XVFB=1), skipping VNC"
        return 0
    fi
    
    echo "[entrypoint] Starting VNC server..."
    
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
        echo "[entrypoint] VNC server started successfully (PID: ${VNC_PID})"
        echo "[entrypoint] VNC server listening on port: ${vnc_port}"
        echo "[entrypoint] Connect with: vncviewer <container-ip>:${vnc_port}"
        echo "[entrypoint] Or use port mapping: docker run -p ${vnc_port}:${vnc_port} ..."
        return 0
    else
        echo "[entrypoint] WARNING: Failed to start VNC server"
        VNC_PID=""
        return 1
    fi
}

# Start noVNC with websockify for browser-based VNC access
start_novnc() {
    if [ "${USE_NOVNC}" != "1" ]; then
        echo "[entrypoint] noVNC disabled (USE_NOVNC=${USE_NOVNC})"
        return 0
    fi
    
    # noVNC requires VNC to be running
    if [ "${USE_VNC}" != "1" ]; then
        echo "[entrypoint] WARNING: noVNC requires VNC server (USE_VNC=1), skipping noVNC"
        return 0
    fi
    
    # Check if noVNC is installed
    if [ ! -d "/opt/novnc" ] || [ ! -d "/opt/websockify" ]; then
        echo "[entrypoint] WARNING: noVNC or websockify not installed, skipping noVNC"
        return 0
    fi
    
    echo "[entrypoint] Starting noVNC with websockify..."
    
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
        echo "[entrypoint] noVNC started successfully (PID: ${NOVNC_PID})"
        echo "[entrypoint] noVNC listening on port: ${novnc_port}"
        echo "[entrypoint] Access via browser: http://<container-ip>:${novnc_port}/vnc.html"
        echo "[entrypoint] Or with port mapping: docker run -p ${novnc_port}:${novnc_port} ..."
        return 0
    else
        echo "[entrypoint] WARNING: Failed to start noVNC"
        NOVNC_PID=""
        return 1
    fi
}

# Function to download and execute a script
download_and_execute() {
    echo "[entrypoint] Checking for SCRIPT_URL environment variable..."
    
    if [ -n "$SCRIPT_URL" ]; then
        echo "[entrypoint] SCRIPT_URL detected: $SCRIPT_URL"
        
        # Run the script downloader
        python /app/script_downloader.py
        DOWNLOAD_EXIT=$?
        
        if [ $DOWNLOAD_EXIT -ne 0 ]; then
            echo "[entrypoint] ERROR: Script download failed"
            exit $DOWNLOAD_EXIT
        fi
        
        # Determine the downloaded script path
        # The downloader saves to /tmp with filename extracted from URL
        SCRIPT_PATH=$(python -c "
import os
from script_downloader import get_filename_from_url
url = os.getenv('SCRIPT_URL')
if url:
    print(f'/tmp/{get_filename_from_url(url)}')
" 2>/dev/null)
        
        if [ -f "$SCRIPT_PATH" ]; then
            echo "[entrypoint] Executing downloaded script: $SCRIPT_PATH"
            exec python "$SCRIPT_PATH"
        else
            echo "[entrypoint] ERROR: Downloaded script not found at $SCRIPT_PATH"
            exit 1
        fi
    fi
}

# Main execution
main() {
    echo "[entrypoint] Starting RPA Worker Selenium..."
    
    # Setup directories
    setup_directories
    
    # Start optional services
    start_xvfb
    start_openbox
    start_pjeoffice
    start_vnc
    start_novnc
    start_screen_recording
    
    # Check if SCRIPT_URL is set
    if [ -n "$SCRIPT_URL" ]; then
        download_and_execute
    else
        # No SCRIPT_URL, execute arguments as normal
        echo "[entrypoint] Executing command: $@"
        exec "$@"
    fi
}

main "$@"
