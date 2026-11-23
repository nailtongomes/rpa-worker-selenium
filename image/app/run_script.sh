#!/bin/bash
# Script to run Python automation scripts inside the container
# Usage: ./run_script.sh <script_path>

if [ -z "$1" ]; then
    echo "Usage: $0 <script_path>"
    echo "Example: $0 /app/src/my_script.py"
    exit 1
fi

SCRIPT_PATH=$1

# Start Xvfb for virtual display (if needed for non-headless mode)
Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &
XVFB_PID=$!

# Run the Python script
python "$SCRIPT_PATH"
EXIT_CODE=$?

# Clean up Xvfb
if [ -n "$XVFB_PID" ]; then
    kill $XVFB_PID 2>/dev/null
fi

exit $EXIT_CODE
