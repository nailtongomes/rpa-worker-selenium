#!/usr/bin/env python3
"""
Example Worker Script for RPA Tasks

This is an example script that demonstrates how to create a worker script
that runs continuously and performs RPA tasks.

The script should:
1. Perform its RPA tasks
2. Handle errors gracefully
3. Exit when done (container will restart automatically)
4. Optionally check for max runtime internally

Place your actual RPA scripts in /app/src/ and reference them via SCRIPT_NAME
environment variable in docker-compose.worker.yml
"""

import time
import sys
from datetime import datetime
from pathlib import Path

# Add /app/src to path if running in Docker environment
import os
if os.path.exists('/app/src'):
    sys.path.insert(0, '/app/src')


def main():
    """
    Main worker function.
    Replace this with your actual RPA logic.
    """
    print("=" * 80)
    print("[worker_script] Example RPA Worker Started")
    print(f"[worker_script] Start time: {datetime.now()}")
    print("=" * 80)
    
    try:
        # Example: Perform RPA tasks in a loop
        iteration = 0
        max_iterations = 10  # Limit iterations for example
        
        while iteration < max_iterations:
            iteration += 1
            print(f"\n[worker_script] Iteration {iteration}/{max_iterations}")
            print(f"[worker_script] Current time: {datetime.now()}")
            
            # Example RPA task simulation
            print("[worker_script] Performing RPA task...")
            
            # Here you would typically:
            # 1. Initialize Selenium WebDriver
            # 2. Navigate to target websites
            # 3. Perform automation tasks
            # 4. Extract/process data
            # 5. Save results to database or files
            
            # Example: Simple task simulation
            example_task()
            
            # Sleep between iterations
            print("[worker_script] Task completed, waiting before next iteration...")
            time.sleep(10)  # Wait 10 seconds between tasks
            
            # In a real worker, you might check:
            # - Database for new tasks
            # - Queue for jobs
            # - Schedule for periodic tasks
        
        print("\n" + "=" * 80)
        print(f"[worker_script] Worker completed {iteration} iterations")
        print(f"[worker_script] End time: {datetime.now()}")
        print("=" * 80)
        print("[worker_script] Exiting normally (container will restart)")
        return 0
    
    except KeyboardInterrupt:
        print("\n[worker_script] Interrupted by user")
        return 0
    
    except Exception as e:
        print(f"\n[worker_script] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


def example_task():
    """
    Example RPA task.
    Replace this with your actual automation logic.
    """
    print("  [task] Checking for work...")
    time.sleep(2)
    
    print("  [task] Executing automation...")
    time.sleep(3)
    
    print("  [task] Saving results...")
    time.sleep(1)
    
    print("  [task] ✓ Task completed successfully")


def example_with_selenium():
    """
    Example of using Selenium for automation.
    Uncomment and modify for your needs.
    """
    # from selenium import webdriver
    # from selenium.webdriver.chrome.options import Options
    # from selenium.webdriver.common.by import By
    # from selenium.webdriver.support.ui import WebDriverWait
    # from selenium.webdriver.support import expected_conditions as EC
    
    # print("  [selenium] Initializing Chrome driver...")
    # options = Options()
    # options.add_argument('--headless')
    # options.add_argument('--no-sandbox')
    # options.add_argument('--disable-dev-shm-usage')
    # options.add_argument('--disable-gpu')
    
    # driver = webdriver.Chrome(options=options)
    
    # try:
    #     print("  [selenium] Navigating to website...")
    #     driver.get('https://example.com')
    #     
    #     print("  [selenium] Waiting for page load...")
    #     WebDriverWait(driver, 10).until(
    #         EC.presence_of_element_located((By.TAG_NAME, "h1"))
    #     )
    #     
    #     print("  [selenium] Extracting data...")
    #     title = driver.title
    #     print(f"  [selenium] Page title: {title}")
    #     
    #     print("  [selenium] ✓ Selenium task completed")
    # 
    # finally:
    #     driver.quit()
    pass


if __name__ == '__main__':
    sys.exit(main())
