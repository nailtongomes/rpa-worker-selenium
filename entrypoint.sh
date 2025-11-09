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

# PIDs for background processes
XVFB_PID=""
OPENBOX_PID=""
PJEOFFICE_PID=""

# Setup directories with proper permissions
setup_directories() {
    echo "[entrypoint] Setting up directories..."
    local dirs=("/app/logs" "/app/tmp" "/app/src")
    
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
    
    # Setup PKI directory for certificates
    if [ ! -d "/app/.pki/nssdb" ]; then
        mkdir -p /app/.pki/nssdb 2>/dev/null || true
        chmod 700 /app/.pki/nssdb 2>/dev/null || true
    fi
    
    return 0
}

# Signal handling for graceful shutdown
handle_sigterm() {
    echo "[entrypoint] Received shutdown signal, cleaning up..."
    [ -n "$XVFB_PID" ] && kill -TERM "$XVFB_PID" 2>/dev/null || true
    [ -n "$OPENBOX_PID" ] && kill -TERM "$OPENBOX_PID" 2>/dev/null || true
    [ -n "$PJEOFFICE_PID" ] && kill -TERM "$PJEOFFICE_PID" 2>/dev/null || true
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
