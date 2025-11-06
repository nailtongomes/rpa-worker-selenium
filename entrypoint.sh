#!/bin/bash
# Entrypoint script for RPA Worker Selenium with script downloading
# Handles downloading scripts from URLs and executing them

set -e

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

# Check if SCRIPT_URL is set
if [ -n "$SCRIPT_URL" ]; then
    download_and_execute
else
    # No SCRIPT_URL, execute arguments as normal
    exec "$@"
fi
