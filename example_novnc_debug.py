#!/usr/bin/env python3
"""
Example script demonstrating browser-based VNC debugging with noVNC.

This script shows how to use the noVNC feature for remote debugging via browser.
It performs a simple web automation that you can observe in real-time through
your web browser by navigating to http://localhost:6080/vnc.html

To use this example:
1. Build the image:
   docker build -t rpa-worker-selenium .

2. Run with noVNC enabled:
   docker run --rm \
     -e USE_XVFB=1 \
     -e USE_VNC=1 \
     -e USE_NOVNC=1 \
     -p 6080:6080 \
     rpa-worker-selenium example_novnc_debug.py

3. Open your browser and navigate to:
   http://localhost:6080/vnc.html

4. Click "Connect" to view the automation in real-time

Note: The browser window will be visible in noVNC because we're NOT using headless mode.
"""

import time
import sys
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def main():
    print("=" * 60)
    print("noVNC Browser-Based Remote Debugging Example")
    print("=" * 60)
    print()
    print("This script demonstrates browser-based VNC access using noVNC.")
    print("You can view the automation in your browser at:")
    print("  http://localhost:6080/vnc.html")
    print()
    print("Starting in 5 seconds to give you time to connect...")
    print("=" * 60)
    print()
    
    # Wait 5 seconds to allow user to connect via noVNC
    for i in range(5, 0, -1):
        print(f"Starting in {i}...")
        time.sleep(1)
    
    print("\nStarting browser automation...")
    
    # Configure Chrome options (NOT headless so it's visible in noVNC)
    chrome_options = Options()
    # Remove headless mode to make browser visible in VNC
    # chrome_options.add_argument('--headless=new')  # COMMENTED OUT for visibility
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1366,768')
    
    # Create service with explicit chromedriver path
    service = Service('/usr/local/bin/chromedriver')
    
    try:
        # Create driver
        print("Launching Chrome browser...")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        print("✓ Browser launched successfully")
        
        # Test 1: Navigate to example.com
        print("\nTest 1: Navigating to example.com...")
        driver.get("https://example.com")
        print(f"✓ Page loaded: {driver.title}")
        time.sleep(3)  # Pause so you can see it in noVNC
        
        # Test 2: Find and highlight elements
        print("\nTest 2: Finding page elements...")
        try:
            # Find heading element
            heading = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "h1"))
            )
            print(f"✓ Found heading: {heading.text}")
            
            # Highlight the element (add yellow background)
            driver.execute_script(
                "arguments[0].style.backgroundColor = 'yellow';",
                heading
            )
            print("✓ Heading highlighted in yellow")
            time.sleep(2)
            
            # Find paragraph
            paragraph = driver.find_element(By.TAG_NAME, "p")
            driver.execute_script(
                "arguments[0].style.backgroundColor = 'lightblue';",
                paragraph
            )
            print("✓ Paragraph highlighted in light blue")
            time.sleep(2)
            
        except Exception as e:
            print(f"✗ Error finding elements: {e}")
        
        # Test 3: Navigate to another page
        print("\nTest 3: Navigating to Python.org...")
        driver.get("https://www.python.org")
        print(f"✓ Page loaded: {driver.title}")
        time.sleep(3)
        
        # Test 4: Scroll the page
        print("\nTest 4: Scrolling page...")
        for i in range(3):
            driver.execute_script("window.scrollBy(0, 300);")
            print(f"✓ Scrolled {(i+1) * 300}px")
            time.sleep(1)
        
        # Scroll back to top
        driver.execute_script("window.scrollTo(0, 0);")
        print("✓ Scrolled back to top")
        time.sleep(2)
        
        print("\n" + "=" * 60)
        print("✓ All tests completed successfully!")
        print("=" * 60)
        print("\nClosing browser in 5 seconds...")
        time.sleep(5)
        
        # Clean up
        driver.quit()
        print("✓ Browser closed")
        
        return 0
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
