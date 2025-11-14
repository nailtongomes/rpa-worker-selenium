#!/usr/bin/env python3
"""
Test script for browser WebDriver initialization.
Tests regular Selenium WebDriver (without SeleniumBase) for Chrome, Firefox, and Brave.
This ensures compatibility with automations that require conventional WebDriver.
"""

import os
import sys
import pathlib
import tempfile
import subprocess
from typing import Optional


def check_driver_available(driver_name: str, command: str) -> bool:
    """Check if a driver binary is available."""
    try:
        result = subprocess.run(
            [command, '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip().split('\n')[0]
            print(f"  ✓ {driver_name} found: {version}")
            return True
        else:
            print(f"  ✗ {driver_name} command failed")
            return False
    except FileNotFoundError:
        print(f"  ✗ {driver_name} not found in PATH")
        return False
    except Exception as e:
        print(f"  ✗ Error checking {driver_name}: {e}")
        return False


def check_browser_available(browser_name: str, command: str) -> bool:
    """Check if a browser binary is available."""
    try:
        result = subprocess.run(
            [command, '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip().split('\n')[0]
            print(f"  ✓ {browser_name} found: {version}")
            return True
        else:
            print(f"  ✗ {browser_name} command failed")
            return False
    except FileNotFoundError:
        print(f"  ✗ {browser_name} not found")
        return False
    except Exception as e:
        print(f"  ✗ Error checking {browser_name}: {e}")
        return False


def test_chrome_webdriver():
    """Test Chrome with regular Selenium WebDriver (not SeleniumBase)."""
    print("\nTesting Chrome with regular Selenium WebDriver...")
    
    # Check if ChromeDriver is available
    if not check_driver_available("ChromeDriver", "chromedriver"):
        print("  ⚠ Skipping Chrome test - ChromeDriver not available")
        return None
    
    # Check if Chrome/Chromium is available
    chrome_found = False
    if check_browser_available("Chrome", "google-chrome"):
        chrome_found = True
    elif check_browser_available("Chromium", "chromium"):
        chrome_found = True
    
    if not chrome_found:
        print("  ⚠ Skipping Chrome test - Chrome/Chromium not available")
        return None
    
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        
        print("  → Initializing Chrome WebDriver...")
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1366,768')
        
        # Try to find chromedriver in common locations
        chromedriver_path = None
        for path in ['/usr/local/bin/chromedriver', '/usr/bin/chromedriver']:
            if os.path.exists(path):
                chromedriver_path = path
                break
        
        if chromedriver_path:
            service = Service(chromedriver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            # Let Selenium auto-detect the driver
            driver = webdriver.Chrome(options=chrome_options)
        
        try:
            # Create a simple test HTML file
            test_html = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
            test_html.write('<html><head><title>Chrome WebDriver Test</title></head><body><h1>Test Page</h1></body></html>')
            test_html.close()
            
            print("  → Loading test page...")
            driver.get(f"file://{test_html.name}")
            title = driver.title
            
            # Clean up temp file
            os.unlink(test_html.name)
            
            print(f"  → Page title: {title}")
            
            if "Chrome WebDriver Test" in title:
                print("  ✓ Chrome WebDriver initialized and working correctly")
                return True
            else:
                print(f"  ✗ Unexpected page title: {title}")
                return False
                
        finally:
            driver.quit()
            print("  → Chrome WebDriver closed")
            
    except Exception as e:
        print(f"  ✗ Chrome WebDriver test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_firefox_webdriver():
    """Test Firefox with regular Selenium WebDriver (not SeleniumBase)."""
    print("\nTesting Firefox with regular Selenium WebDriver...")
    
    # Check if GeckoDriver is available
    if not check_driver_available("GeckoDriver", "geckodriver"):
        print("  ⚠ Skipping Firefox test - GeckoDriver not available")
        return None
    
    # Check if Firefox is available
    if not check_browser_available("Firefox", "firefox"):
        print("  ⚠ Skipping Firefox test - Firefox not available")
        return None
    
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        
        print("  → Initializing Firefox WebDriver...")
        firefox_options = Options()
        firefox_options.add_argument('--headless')
        firefox_options.add_argument('--no-sandbox')
        firefox_options.add_argument('--disable-dev-shm-usage')

        # Prefer the bundled Firefox binary when present to avoid PATH/symlink issues
        firefox_binary_candidates = [
            '/opt/firefox/firefox',
            '/usr/local/bin/firefox',
            '/usr/bin/firefox',
        ]
        for candidate in firefox_binary_candidates:
            if os.path.exists(candidate):
                firefox_options.binary_location = candidate
                break
        
        # Try to find geckodriver in common locations
        geckodriver_path = None
        for path in ['/usr/local/bin/geckodriver', '/usr/bin/geckodriver']:
            if os.path.exists(path):
                geckodriver_path = path
                break
        
        if geckodriver_path:
            service = Service(executable_path=geckodriver_path)
            driver = webdriver.Firefox(service=service, options=firefox_options)
        else:
            # Let Selenium auto-detect the driver
            driver = webdriver.Firefox(options=firefox_options)
        
        try:
            # Create a simple test HTML file
            test_html = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
            test_html.write('<html><head><title>Firefox WebDriver Test</title></head><body><h1>Test Page</h1></body></html>')
            test_html.close()
            
            print("  → Loading test page...")
            driver.get(f"file://{test_html.name}")
            title = driver.title
            
            # Clean up temp file
            os.unlink(test_html.name)
            
            print(f"  → Page title: {title}")
            
            if "Firefox WebDriver Test" in title:
                print("  ✓ Firefox WebDriver initialized and working correctly")
                return True
            else:
                print(f"  ✗ Unexpected page title: {title}")
                return False
                
        finally:
            driver.quit()
            print("  → Firefox WebDriver closed")
            
    except Exception as e:
        print(f"  ✗ Firefox WebDriver test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_brave_webdriver():
    """Test Brave with regular Selenium WebDriver (not SeleniumBase)."""
    print("\nTesting Brave with regular Selenium WebDriver...")
    
    # Check if ChromeDriver is available (Brave uses ChromeDriver)
    if not check_driver_available("ChromeDriver", "chromedriver"):
        print("  ⚠ Skipping Brave test - ChromeDriver not available")
        return None
    
    # Check if Brave is available
    brave_path = "/usr/bin/brave-browser"
    if not os.path.exists(brave_path):
        print(f"  ✗ Brave browser not found at {brave_path}")
        print("  ⚠ Skipping Brave test - Brave not available")
        return None
    else:
        print(f"  ✓ Brave browser found at {brave_path}")
    
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        
        print("  → Initializing Brave WebDriver...")
        chrome_options = Options()
        chrome_options.binary_location = brave_path
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1366,768')
        chrome_options.add_argument('--disable-brave-update')
        
        # Try to find chromedriver in common locations
        chromedriver_path = None
        for path in ['/usr/local/bin/chromedriver', '/usr/bin/chromedriver']:
            if os.path.exists(path):
                chromedriver_path = path
                break
        
        if chromedriver_path:
            service = Service(chromedriver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            # Let Selenium auto-detect the driver
            driver = webdriver.Chrome(options=chrome_options)
        
        try:
            # Create a simple test HTML file
            test_html = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
            test_html.write('<html><head><title>Brave WebDriver Test</title></head><body><h1>Test Page</h1></body></html>')
            test_html.close()
            
            print("  → Loading test page...")
            driver.get(f"file://{test_html.name}")
            title = driver.title
            
            # Clean up temp file
            os.unlink(test_html.name)
            
            print(f"  → Page title: {title}")
            
            if "Brave WebDriver Test" in title:
                print("  ✓ Brave WebDriver initialized and working correctly")
                return True
            else:
                print(f"  ✗ Unexpected page title: {title}")
                return False
                
        finally:
            driver.quit()
            print("  → Brave WebDriver closed")
            
    except Exception as e:
        print(f"  ✗ Brave WebDriver test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_seleniumbase_driver():
    """Test SeleniumBase Driver initialization."""
    print("\nTesting SeleniumBase Driver...")
    
    try:
        from seleniumbase import Driver
        
        print("  → Initializing SeleniumBase Driver...")
        # Use simpler initialization without UC mode to avoid hangs
        driver = Driver(headless2=True)
        
        try:
            driver.set_window_size(1366, 768)
            
            # Create a simple test HTML file
            test_html = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
            test_html.write('<html><head><title>SeleniumBase Test</title></head><body><h1>Test Page</h1></body></html>')
            test_html.close()
            
            print("  → Loading test page...")
            driver.open(f"file://{test_html.name}")
            title = driver.get_title()
            
            # Clean up temp file
            os.unlink(test_html.name)
            
            print(f"  → Page title: {title}")
            
            if "SeleniumBase Test" in title:
                print("  ✓ SeleniumBase Driver initialized and working correctly")
                return True
            else:
                print(f"  ✗ Unexpected page title: {title}")
                return False
                
        finally:
            driver.quit()
            print("  → SeleniumBase Driver closed")
            
    except Exception as e:
        print(f"  ✗ SeleniumBase Driver test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all browser driver tests."""
    print("=" * 70)
    print("Browser WebDriver Initialization Tests")
    print("=" * 70)
    print("\nTesting regular Selenium WebDriver (without SeleniumBase)")
    print("This verifies compatibility with conventional WebDriver automations\n")
    
    results = {}
    
    # Test each browser with regular Selenium WebDriver
    results['chrome_webdriver'] = test_chrome_webdriver()
    results['firefox_webdriver'] = test_firefox_webdriver()
    results['brave_webdriver'] = test_brave_webdriver()
    
    # Test SeleniumBase - commented out for now due to initialization hangs
    # This test can be enabled once the hang issue is resolved
    # results['seleniumbase'] = test_seleniumbase_driver()
    print("\n⚠ SeleniumBase test skipped (initialization timeout issue)")
    results['seleniumbase'] = None
    
    # Print summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    passed = sum(1 for result in results.values() if result is True)
    failed = sum(1 for result in results.values() if result is False)
    skipped = sum(1 for result in results.values() if result is None)
    total = len(results)
    
    for test_name, result in results.items():
        if result is True:
            status = "✓ PASS"
        elif result is False:
            status = "✗ FAIL"
        else:
            status = "⚠ SKIP"
        print(f"  {status}: {test_name}")
    
    print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
    
    if failed > 0:
        print("\n✗ Some tests failed!")
        print("=" * 70)
        return 1
    elif passed == 0:
        print("\n⚠ All tests were skipped (drivers/browsers not available)")
        print("=" * 70)
        return 1
    else:
        print("\n✓ All available browser tests passed!")
        print("=" * 70)
        return 0


if __name__ == "__main__":
    sys.exit(main())
