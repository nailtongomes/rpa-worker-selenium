#!/usr/bin/env python3
"""
Task Server for RPA Worker Selenium - HTTP Standby Mode
Provides an HTTP endpoint to receive task payloads and trigger script execution on demand.

This server runs in standby mode waiting for POST requests with task payloads.
After receiving a valid task, it downloads and executes the script, then restarts
the container to clear memory and prepare for the next task.

Environment Variables:
- TASK_SERVER_PORT: Port to listen on (default: 8080)
- TASK_AUTH_TOKEN: Optional Bearer token for authentication
- WORKER_TIMEOUT: Timeout for script execution in seconds (default: 3600)
"""

import os
import sys
import json
import subprocess
import threading
import time
import pathlib
from datetime import datetime
from flask import Flask, request, jsonify
from script_downloader import download_file, get_filename_from_url

app = Flask(__name__)

# Global state to track if a task is currently executing
task_executing = False
task_lock = threading.Lock()

# Configuration from environment variables
TASK_SERVER_PORT = int(os.getenv("TASK_SERVER_PORT", "8080"))
TASK_AUTH_TOKEN = os.getenv("TASK_AUTH_TOKEN", "")
WORKER_TIMEOUT = int(os.getenv("WORKER_TIMEOUT", "3600"))


def log_timestamp():
    """Return formatted timestamp for logging."""
    return f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"


def validate_auth():
    """
    Validate authentication token if TASK_AUTH_TOKEN is set.
    
    Returns:
        tuple: (bool, str) - (is_valid, error_message)
    """
    if not TASK_AUTH_TOKEN:
        return True, None
    
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False, "Missing or invalid Authorization header"
    
    token = auth_header[7:]  # Remove "Bearer " prefix
    if token != TASK_AUTH_TOKEN:
        return False, "Invalid authentication token"
    
    return True, None


def validate_payload(payload):
    """
    Validate the task payload.
    
    Args:
        payload: JSON payload from the request
        
    Returns:
        tuple: (bool, str) - (is_valid, error_message)
    """
    # Check required fields
    if not payload:
        return False, "Empty payload"
    
    if "script_url" not in payload:
        return False, "Missing required field: script_url"
    
    if "script_name" not in payload:
        return False, "Missing required field: script_name"
    
    script_url = payload["script_url"]
    script_name = payload["script_name"]
    
    # Validate script_url is HTTPS
    if not script_url.startswith("https://"):
        return False, "script_url must use HTTPS protocol"
    
    # Validate script_name matches the URL
    url_filename = get_filename_from_url(script_url)
    if script_name != url_filename:
        return False, f"script_name '{script_name}' does not match URL filename '{url_filename}'"
    
    # Validate payload field if present
    if "payload" in payload:
        if not isinstance(payload["payload"], dict):
            return False, "payload field must be a JSON object"
    
    return True, None


def download_and_execute_script(script_url, script_name, task_payload=None):
    """
    Download and execute the specified script.
    After execution completes, triggers container restart.
    
    Args:
        script_url: URL of the script to download
        script_name: Name of the script file
        task_payload: Optional payload to pass to the script
    """
    global task_executing
    
    try:
        print(f"{log_timestamp()} ⬇️  Downloading script from: {script_url}")
        
        # Download the script to /tmp
        temp_path = pathlib.Path("/tmp")
        destination = temp_path / script_name
        
        # Set SCRIPT_URL for script_downloader.py
        os.environ["SCRIPT_URL"] = script_url
        
        # Download using script_downloader
        if not download_file(script_url, str(destination)):
            print(f"{log_timestamp()} ❌ Failed to download script")
            return
        
        # Make the script executable
        os.chmod(destination, 0o755)
        print(f"{log_timestamp()} ✅ Script downloaded successfully: {destination}")
        
        # If there's a payload, save it to a JSON file that the script can read
        if task_payload:
            payload_file = temp_path / "task_payload.json"
            with open(payload_file, 'w') as f:
                json.dump(task_payload, f, indent=2)
            os.environ["TASK_PAYLOAD_FILE"] = str(payload_file)
            print(f"{log_timestamp()} 📄 Task payload saved to: {payload_file}")
        
        print(f"{log_timestamp()} ▶️  Executing script with timeout {WORKER_TIMEOUT}s...")
        
        # Execute the script with timeout
        try:
            result = subprocess.run(
                ["python", str(destination)],
                timeout=WORKER_TIMEOUT,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                print(f"{log_timestamp()} ✅ Script completed successfully")
                print(result.stdout)
            else:
                print(f"{log_timestamp()} ❌ Script failed with exit code: {result.returncode}")
                print(result.stderr)
                
        except subprocess.TimeoutExpired:
            print(f"{log_timestamp()} ⏱️  Script timed out after {WORKER_TIMEOUT}s")
        
        print(f"{log_timestamp()} 🔄 Triggering container restart...")
        
        # Wait a moment to ensure logs are flushed
        time.sleep(2)
        
        # Exit with code 0 to trigger container restart (if restart policy is set)
        # The container orchestrator (Docker, Kubernetes) will restart the container
        sys.exit(0)
        
    except Exception as e:
        print(f"{log_timestamp()} ❌ Error executing script: {e}")
        import traceback
        traceback.print_exc()
        
        # Still trigger restart even on error to clear memory
        print(f"{log_timestamp()} 🔄 Triggering container restart after error...")
        time.sleep(2)
        sys.exit(1)
    
    finally:
        with task_lock:
            task_executing = False


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "mode": "standby",
        "task_executing": task_executing,
        "timestamp": datetime.now().isoformat()
    }), 200


@app.route('/task', methods=['POST'])
def receive_task():
    """
    Receive and execute a task.
    
    Expected JSON payload:
    {
        "script_url": "https://example.com/script.py",
        "script_name": "script.py",
        "payload": {
            "key": "value"
        }
    }
    
    Returns:
        JSON response with status
    """
    global task_executing
    
    print(f"{log_timestamp()} 🚀 Task received")
    
    # Validate authentication
    auth_valid, auth_error = validate_auth()
    if not auth_valid:
        print(f"{log_timestamp()} ❌ Authentication failed: {auth_error}")
        return jsonify({"error": auth_error}), 401
    
    # Check if another task is already executing
    with task_lock:
        if task_executing:
            print(f"{log_timestamp()} ⚠️  Task already executing")
            return jsonify({
                "error": "Another task is already executing",
                "status": "conflict"
            }), 409
        
        # Mark as executing
        task_executing = True
    
    try:
        # Get JSON payload
        try:
            payload = request.get_json()
        except Exception as e:
            with task_lock:
                task_executing = False
            print(f"{log_timestamp()} ❌ Invalid JSON: {e}")
            return jsonify({"error": f"Invalid JSON: {str(e)}"}), 400
        
        # Validate payload
        valid, error = validate_payload(payload)
        if not valid:
            with task_lock:
                task_executing = False
            print(f"{log_timestamp()} ❌ Invalid payload: {error}")
            return jsonify({"error": error}), 400
        
        script_url = payload["script_url"]
        script_name = payload["script_name"]
        task_payload = payload.get("payload")
        
        print(f"{log_timestamp()} ✅ Task validated successfully")
        print(f"{log_timestamp()} 📝 Script URL: {script_url}")
        print(f"{log_timestamp()} 📝 Script Name: {script_name}")
        
        # Start execution in a background thread
        # This allows us to return immediately while the script executes
        execution_thread = threading.Thread(
            target=download_and_execute_script,
            args=(script_url, script_name, task_payload),
            daemon=True
        )
        execution_thread.start()
        
        return jsonify({
            "status": "accepted",
            "message": "Task accepted and execution started",
            "script_url": script_url,
            "script_name": script_name
        }), 202
        
    except Exception as e:
        with task_lock:
            task_executing = False
        print(f"{log_timestamp()} ❌ Error processing task: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


def main():
    """Start the Flask server."""
    print(f"{log_timestamp()} 🚀 Starting Task Server in standby mode...")
    print(f"{log_timestamp()} 🌐 Listening on 0.0.0.0:{TASK_SERVER_PORT}")
    
    if TASK_AUTH_TOKEN:
        print(f"{log_timestamp()} 🔒 Authentication enabled (Bearer token required)")
    else:
        print(f"{log_timestamp()} ⚠️  Authentication disabled (TASK_AUTH_TOKEN not set)")
    
    print(f"{log_timestamp()} ⏱️  Script timeout: {WORKER_TIMEOUT}s")
    print(f"{log_timestamp()} 💡 Ready to receive tasks at POST /task")
    print(f"{log_timestamp()} 💡 Health check available at GET /health")
    
    # Run Flask server
    app.run(
        host='0.0.0.0',
        port=TASK_SERVER_PORT,
        debug=False,
        threaded=True
    )


if __name__ == "__main__":
    main()
