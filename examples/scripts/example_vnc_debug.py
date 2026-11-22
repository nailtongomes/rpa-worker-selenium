#!/usr/bin/env python3
"""
Example script demonstrating VNC remote debugging.
This script performs a simple web automation that you can observe via VNC.
"""

import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def create_chrome_driver():
    """Create and configure Chrome WebDriver."""
    print("[script] Configuring Chrome WebDriver...")
    
    # Configure Chrome options
    chrome_options = Options()
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    
    # Note: NOT using --headless so it displays in the virtual X display
    # This allows VNC to show the browser window
    
    # Create service with explicit chromedriver path
    service = Service('/usr/local/bin/chromedriver')
    
    # Create and return driver
    driver = webdriver.Chrome(service=service, options=chrome_options)
    print("[script] Chrome WebDriver created successfully")
    
    return driver


def demonstrate_vnc_debugging(driver):
    """
    Perform web automation that can be observed via VNC.
    This function intentionally includes delays so viewers can observe the actions.
    """
    print("[script] Starting VNC debugging demonstration...")
    print("[script] Connect with VNC client to see the browser in action!")
    print("[script] Example: vncviewer localhost:5900")
    print()
    
    # Visit example.com
    print("[script] Step 1: Navigating to example.com...")
    driver.get("https://example.com")
    print(f"[script] Page title: {driver.title}")
    time.sleep(3)  # Pause to allow VNC viewer to observe
    
    # Maximize window for better viewing
    print("[script] Step 2: Maximizing browser window...")
    driver.maximize_window()
    time.sleep(2)
    
    # Find and highlight the heading
    print("[script] Step 3: Finding page elements...")
    try:
        heading = driver.find_element(By.TAG_NAME, "h1")
        print(f"[script] Found heading: {heading.text}")
        
        # Scroll to element
        driver.execute_script("arguments[0].scrollIntoView(true);", heading)
        time.sleep(2)
        
        # Highlight the element (observers can see this via VNC)
        driver.execute_script(
            "arguments[0].style.border='3px solid red'", 
            heading
        )
        print("[script] Highlighted heading with red border (visible via VNC)")
        time.sleep(3)
        
    except Exception as e:
        print(f"[script] Could not find heading: {e}")
    
    # Visit another page
    print("[script] Step 4: Navigating to another page...")
    driver.get("https://www.python.org")
    print(f"[script] Page title: {driver.title}")
    time.sleep(3)
    
    # Take a screenshot for comparison
    print("[script] Step 5: Taking screenshot...")
    screenshot_path = "/app/logs/vnc_demo_screenshot.png"
    driver.save_screenshot(screenshot_path)
    print(f"[script] Screenshot saved to: {screenshot_path}")
    time.sleep(2)
    
    # Return to example.com
    print("[script] Step 6: Returning to example.com...")
    driver.get("https://example.com")
    time.sleep(2)
    
    print("[script] Demonstration complete!")
    print("[script] If you were connected via VNC, you saw all these browser actions live!")


def main():
    """Main execution function."""
    print("=" * 70)
    print("VNC Remote Debugging Demonstration")
    print("=" * 70)
    print()
    print("This script demonstrates the VNC remote debugging feature.")
    print("You can observe the browser automation in real-time via VNC.")
    print()
    print("To use VNC:")
    print("1. Run this container with: docker run -e USE_XVFB=1 -e USE_VNC=1 -p 5900:5900 ...")
    print("2. Connect with a VNC client: vncviewer localhost:5900")
    print("3. Watch the browser automation happen live!")
    print()
    print("=" * 70)
    print()
    
    driver = None
    try:
        # Create driver
        driver = create_chrome_driver()
        
        # Run demonstration
        demonstrate_vnc_debugging(driver)
        
        print()
        print("[script] ✓ Script completed successfully!")
        return 0
        
    except Exception as e:
        print(f"[script] ✗ Error occurred: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        # Clean up
        if driver:
            print("[script] Closing browser...")
            time.sleep(2)  # Final pause before cleanup
            driver.quit()
            print("[script] Browser closed")


if __name__ == "__main__":
    import sys
    sys.exit(main())
