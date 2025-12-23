#!/usr/bin/env python3
"""
Worker Wrapper Script for RPA Workers

This script wraps the execution of RPA scripts and handles:
1. Automatic restart after maximum runtime hours
2. Clean exit to trigger container restart
3. Script execution from SCRIPT_NAME or SCRIPT_URL
4. Error handling and logging

Environment Variables:
    SCRIPT_NAME: Name of the Python script to run (e.g., "my_script.py")
                 Script should be in /app/src/ or /app/
    SCRIPT_URL: Alternative to SCRIPT_NAME - URL to download script from
    MAX_RUN_HOURS: Maximum hours before forcing restart (default: 3)

Exit Codes:
    0: Normal completion (will trigger container restart due to restart: always)
    1: Error occurred
    2: Maximum runtime exceeded (forces restart)
"""

import os
import sys
import time
import signal
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# Configuration from environment variables
SCRIPT_NAME = os.getenv('SCRIPT_NAME', 'worker_script.py')
SCRIPT_URL = os.getenv('SCRIPT_URL', '')
MAX_RUN_HOURS = float(os.getenv('MAX_RUN_HOURS', '3'))

# Paths
APP_DIR = Path('/app')
SRC_DIR = APP_DIR / 'src'
LOGS_DIR = APP_DIR / 'logs'

# Ensure logs directory exists
LOGS_DIR.mkdir(parents=True, exist_ok=True)


class WorkerWrapper:
    """Wrapper for RPA worker scripts with automatic restart."""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.max_runtime = timedelta(hours=MAX_RUN_HOURS)
        self.script_process = None
        self.should_exit = False
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
    
    def _handle_signal(self, signum, frame):
        """Handle shutdown signals gracefully."""
        print(f"[worker_wrapper] Received signal {signum}, initiating graceful shutdown...")
        self.should_exit = True
        
        # Terminate the script process if running
        if self.script_process and self.script_process.poll() is None:
            print("[worker_wrapper] Terminating script process...")
            self.script_process.terminate()
            
            # Wait up to 10 seconds for graceful termination
            try:
                self.script_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print("[worker_wrapper] Force killing script process...")
                self.script_process.kill()
                self.script_process.wait()
    
    def _check_max_runtime(self):
        """Check if maximum runtime has been exceeded."""
        elapsed = datetime.now() - self.start_time
        if elapsed >= self.max_runtime:
            print(f"[worker_wrapper] Maximum runtime of {MAX_RUN_HOURS} hours exceeded")
            print(f"[worker_wrapper] Elapsed time: {elapsed}")
            return True
        return False
    
    def _find_script(self):
        """Find the script to execute."""
        # If SCRIPT_URL is provided, use script downloader
        if SCRIPT_URL:
            print(f"[worker_wrapper] SCRIPT_URL provided: {SCRIPT_URL}")
            print("[worker_wrapper] Script will be downloaded by entrypoint")
            return None  # Let entrypoint handle it
        
        # Try to find script in various locations
        script_paths = [
            SRC_DIR / SCRIPT_NAME,
            APP_DIR / SCRIPT_NAME,
            Path(SCRIPT_NAME),  # Absolute path or relative to current dir
        ]
        
        for script_path in script_paths:
            if script_path.exists() and script_path.is_file():
                print(f"[worker_wrapper] Found script: {script_path}")
                return script_path
        
        print(f"[worker_wrapper] ERROR: Script not found: {SCRIPT_NAME}")
        print(f"[worker_wrapper] Searched in: {[str(p) for p in script_paths]}")
        return None
    
    def _run_script(self, script_path):
        """Run the script and monitor its execution."""
        print(f"[worker_wrapper] Starting script: {script_path}")
        print(f"[worker_wrapper] Maximum runtime: {MAX_RUN_HOURS} hours")
        print(f"[worker_wrapper] Start time: {self.start_time}")
        print("-" * 80)
        
        try:
            # Start the script as a subprocess
            self.script_process = subprocess.Popen(
                ['python', str(script_path)],
                stdout=sys.stdout,
                stderr=sys.stderr,
                cwd=str(APP_DIR)
            )
            
            # Monitor the script execution
            while True:
                # Check if script has finished
                exit_code = self.script_process.poll()
                if exit_code is not None:
                    print("-" * 80)
                    print(f"[worker_wrapper] Script exited with code: {exit_code}")
                    return exit_code
                
                # Check if we should exit (signal received)
                if self.should_exit:
                    print("[worker_wrapper] Shutdown requested")
                    return 0
                
                # Check if maximum runtime exceeded
                if self._check_max_runtime():
                    print("[worker_wrapper] Terminating script due to maximum runtime")
                    self.script_process.terminate()
                    
                    try:
                        self.script_process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        print("[worker_wrapper] Force killing script...")
                        self.script_process.kill()
                        self.script_process.wait()
                    
                    return 2  # Exit code 2 indicates max runtime exceeded
                
                # Sleep briefly before checking again
                time.sleep(5)
        
        except Exception as e:
            print(f"[worker_wrapper] ERROR: Exception during script execution: {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    def run(self):
        """Main execution loop."""
        print("=" * 80)
        print("[worker_wrapper] RPA Worker Wrapper Started")
        print(f"[worker_wrapper] Script: {SCRIPT_NAME}")
        print(f"[worker_wrapper] Max Runtime: {MAX_RUN_HOURS} hours")
        print(f"[worker_wrapper] Start Time: {self.start_time}")
        print("=" * 80)
        
        # If SCRIPT_URL is set, let entrypoint handle the download and execution
        if SCRIPT_URL:
            print("[worker_wrapper] SCRIPT_URL detected, but this should be handled by entrypoint")
            print("[worker_wrapper] This wrapper should not be used with SCRIPT_URL")
            print("[worker_wrapper] Use: command: python /app/script_downloader.py")
            return 1
        
        # Find the script
        script_path = self._find_script()
        if not script_path:
            print("[worker_wrapper] ERROR: Cannot proceed without a valid script")
            print("[worker_wrapper] Please set SCRIPT_NAME environment variable")
            print("[worker_wrapper] and ensure the script exists in /app/src/ or /app/")
            return 1
        
        # Run the script
        exit_code = self._run_script(script_path)
        
        # Print summary
        print("=" * 80)
        print("[worker_wrapper] Execution Summary")
        print(f"[worker_wrapper] Exit Code: {exit_code}")
        print(f"[worker_wrapper] Start Time: {self.start_time}")
        print(f"[worker_wrapper] End Time: {datetime.now()}")
        print(f"[worker_wrapper] Duration: {datetime.now() - self.start_time}")
        print("=" * 80)
        
        # Exit codes:
        # 0: Normal completion (will restart due to restart: always)
        # 1: Error occurred
        # 2: Maximum runtime exceeded (forces restart)
        return exit_code


def main():
    """Main entry point."""
    wrapper = WorkerWrapper()
    exit_code = wrapper.run()
    
    # Always exit to trigger container restart (due to restart: always policy)
    print(f"[worker_wrapper] Exiting with code {exit_code} (container will restart)")
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
