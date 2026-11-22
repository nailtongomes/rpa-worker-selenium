#!/usr/bin/env python3
"""
Test script for screen recording functionality.
This script can be used to manually test screen recording with a simple browser automation.
"""

import os
import sys
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


def test_screen_recording():
    """
    Test automation with screen recording.
    This script opens a browser, navigates to a page, and performs simple actions.
    """
    print("[test] Starting screen recording test...")
    
    # Check if screen recording is enabled
    use_recording = os.getenv("USE_SCREEN_RECORDING", "0")
    print(f"[test] USE_SCREEN_RECORDING={use_recording}")
    
    if use_recording == "1":
        recording_dir = os.getenv("RECORDING_DIR", "/app/recordings")
        print(f"[test] Recording will be saved to: {recording_dir}")
    
    # Configure Chrome options
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    
    # Set window size to match the recording resolution
    width = os.getenv("SCREEN_WIDTH", "1366")
    height = os.getenv("SCREEN_HEIGHT", "768")
    chrome_options.add_argument(f'--window-size={width},{height}')
    
    try:
        # Create service with explicit chromedriver path
        service = Service('/usr/local/bin/chromedriver')
        
        # Create driver
        print("[test] Creating Chrome driver...")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        print("[test] Navigating to example.com...")
        driver.get("https://example.com")
        time.sleep(2)
        
        print(f"[test] Page title: {driver.title}")
        
        # Perform some simple actions
        print("[test] Getting page source length...")
        page_source_length = len(driver.page_source)
        print(f"[test] Page source length: {page_source_length} characters")
        
        # Wait a bit more to capture more video
        print("[test] Waiting 3 seconds to capture more video...")
        time.sleep(3)
        
        # Navigate to another page
        print("[test] Navigating to example.org...")
        driver.get("https://example.org")
        time.sleep(2)
        
        print(f"[test] Page title: {driver.title}")
        
        # Take a screenshot
        screenshot_path = "/data/test_screenshot.png"
        if os.path.exists("/data"):
            driver.save_screenshot(screenshot_path)
            print(f"[test] Screenshot saved to: {screenshot_path}")
        
        print("[test] Test completed successfully!")
        
        # Clean up
        driver.quit()
        
        return 0
        
    except Exception as e:
        print(f"[test] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(test_screen_recording())
