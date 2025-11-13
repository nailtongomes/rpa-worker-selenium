#!/usr/bin/env python3
"""
Alpine Smoke Test for RPA Worker Selenium
Comprehensive test suite specifically for Alpine-based Docker images.

This script tests:
- Chrome/Chromium browser with Selenium
- Firefox browser with Selenium
- SeleniumBase with Chrome
- Basic network connectivity
- File system operations

Environment Variables:
- TARGET_URL: URL to test (default: https://example.com)
- CACHE_DIR: Directory to save test outputs (default: /data)
- VERBOSE: Enable verbose output (default: 0)
"""

import os
import sys
import pathlib
import datetime
import subprocess
import tempfile
import json
from typing import Dict

# Configuration
TARGET_URL = os.getenv("TARGET_URL", "https://example.com")
CACHE_DIR = pathlib.Path(os.getenv("CACHE_DIR", "/data"))
VERBOSE = os.getenv("VERBOSE", "0") == "1"

# Ensure cache directory exists
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Test results tracking
test_results: Dict[str, Dict[str, any]] = {}


def log(message: str, level: str = "INFO") -> None:
    """Log a message with timestamp and level."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{timestamp}] [{level}]"
    print(f"{prefix} {message}")


def log_verbose(message: str) -> None:
    """Log verbose message only if VERBOSE is enabled."""
    if VERBOSE:
        log(message, "DEBUG")


def record_test(test_name: str, passed: bool, details: str = "") -> None:
    """Record test result."""
    test_results[test_name] = {
        "passed": passed,
        "details": details,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    status = "✓ PASS" if passed else "✗ FAIL"
    log(f"{status}: {test_name} - {details}")


def check_python_version() -> bool:
    """Check if Python version is compatible."""
    log("Testing Python version...")
    try:
        version = sys.version_info
        major, minor = version.major, version.minor
        
        if major >= 3 and minor >= 8:
            record_test("python_version", True, f"Python {major}.{minor} is compatible")
            return True
        else:
            record_test("python_version", False, f"Python {major}.{minor} is too old (requires 3.8+)")
            return False
    except Exception as e:
        record_test("python_version", False, f"Error checking Python version: {e}")
        return False


def check_chromedriver() -> bool:
    """Check if ChromeDriver is available."""
    log("Testing ChromeDriver availability...")
    try:
        result = subprocess.run(
            ['chromedriver', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            record_test("chromedriver_available", True, f"ChromeDriver found: {version}")
            return True
        else:
            record_test("chromedriver_available", False, "ChromeDriver command failed")
            return False
    except FileNotFoundError:
        record_test("chromedriver_available", False, "ChromeDriver not found in PATH")
        return False
    except Exception as e:
        record_test("chromedriver_available", False, f"Error checking ChromeDriver: {e}")
        return False


def check_geckodriver() -> bool:
    """Check if GeckoDriver (Firefox) is available."""
    log("Testing GeckoDriver availability...")
    try:
        result = subprocess.run(
            ['geckodriver', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip().split('\n')[0]
            record_test("geckodriver_available", True, f"GeckoDriver found: {version}")
            return True
        else:
            record_test("geckodriver_available", False, "GeckoDriver command failed")
            return False
    except FileNotFoundError:
        record_test("geckodriver_available", False, "GeckoDriver not found in PATH")
        return False
    except Exception as e:
        record_test("geckodriver_available", False, f"Error checking GeckoDriver: {e}")
        return False


def check_chromium_browser() -> bool:
    """Check if Chromium browser is available."""
    log("Testing Chromium browser availability...")
    try:
        # Try different possible Chromium commands
        commands = ['chromium-browser', 'chromium', 'google-chrome', 'chrome']
        for cmd in commands:
            try:
                result = subprocess.run(
                    [cmd, '--version'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    version = result.stdout.strip()
                    record_test("chromium_browser", True, f"Chromium found: {version}")
                    return True
            except FileNotFoundError:
                continue
        
        record_test("chromium_browser", False, "Chromium browser not found")
        return False
    except Exception as e:
        record_test("chromium_browser", False, f"Error checking Chromium: {e}")
        return False


def check_firefox_browser() -> bool:
    """Check if Firefox browser is available."""
    log("Testing Firefox browser availability...")
    try:
        result = subprocess.run(
            ['firefox', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            record_test("firefox_browser", True, f"Firefox found: {version}")
            return True
        else:
            record_test("firefox_browser", False, "Firefox command failed")
            return False
    except FileNotFoundError:
        record_test("firefox_browser", False, "Firefox not found in PATH")
        return False
    except Exception as e:
        record_test("firefox_browser", False, f"Error checking Firefox: {e}")
        return False


def test_chrome_selenium() -> bool:
    """Test basic Selenium with Chrome."""
    log("Testing Selenium with Chrome...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        
        # Try to find chromedriver
        chromedriver_path = None
        for path in ['/usr/local/bin/chromedriver', '/usr/bin/chromedriver']:
            if os.path.exists(path):
                chromedriver_path = path
                break
        
        if chromedriver_path:
            service = Service(chromedriver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            driver = webdriver.Chrome(options=chrome_options)
        
        try:
            # Create a simple local HTML file
            test_html = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
            test_html.write('<html><head><title>Alpine Chrome Test</title></head><body><h1>Test</h1></body></html>')
            test_html.close()
            
            driver.get(f"file://{test_html.name}")
            title = driver.title
            
            # Clean up
            os.unlink(test_html.name)
            
            # Save screenshot
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = CACHE_DIR / f"alpine_chrome_{timestamp}.png"
            driver.save_screenshot(str(screenshot_path))
            
            record_test("chrome_selenium", True, f"Chrome Selenium works, title: {title}")
            log_verbose(f"  Screenshot saved to: {screenshot_path}")
            return True
        finally:
            driver.quit()
            
    except Exception as e:
        record_test("chrome_selenium", False, f"Chrome Selenium failed: {e}")
        return False


def test_firefox_selenium() -> bool:
    """Test basic Selenium with Firefox."""
    log("Testing Selenium with Firefox...")
    
    # Check if Firefox and GeckoDriver are available
    if not check_geckodriver():
        record_test("firefox_selenium", False, "GeckoDriver not available")
        return False
    
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        
        firefox_options = Options()
        firefox_options.add_argument('--headless')
        firefox_options.add_argument('--no-sandbox')
        firefox_options.add_argument('--disable-dev-shm-usage')
        
        # Try to find geckodriver
        geckodriver_path = None
        for path in ['/usr/local/bin/geckodriver', '/usr/bin/geckodriver']:
            if os.path.exists(path):
                geckodriver_path = path
                break
        
        if geckodriver_path:
            service = Service(geckodriver_path)
            driver = webdriver.Firefox(service=service, options=firefox_options)
        else:
            driver = webdriver.Firefox(options=firefox_options)
        
        try:
            # Create a simple local HTML file
            test_html = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
            test_html.write('<html><head><title>Alpine Firefox Test</title></head><body><h1>Test</h1></body></html>')
            test_html.close()
            
            driver.get(f"file://{test_html.name}")
            title = driver.title
            
            # Clean up
            os.unlink(test_html.name)
            
            # Save screenshot
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = CACHE_DIR / f"alpine_firefox_{timestamp}.png"
            driver.save_screenshot(str(screenshot_path))
            
            record_test("firefox_selenium", True, f"Firefox Selenium works, title: {title}")
            log_verbose(f"  Screenshot saved to: {screenshot_path}")
            return True
        finally:
            driver.quit()
            
    except Exception as e:
        record_test("firefox_selenium", False, f"Firefox Selenium failed: {e}")
        return False


def test_seleniumbase_chrome() -> bool:
    """Test SeleniumBase with Chrome."""
    log("Testing SeleniumBase with Chrome...")
    try:
        from seleniumbase import Driver
        
        driver = Driver(headless2=True)
        
        try:
            driver.set_window_size(1366, 768)
            
            # Create a simple local HTML file
            test_html = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
            test_html.write('<html><head><title>Alpine SeleniumBase Test</title></head><body><h1>Test</h1></body></html>')
            test_html.close()
            
            driver.open(f"file://{test_html.name}")
            title = driver.get_title()
            
            # Clean up
            os.unlink(test_html.name)
            
            # Save screenshot
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = CACHE_DIR / f"alpine_seleniumbase_{timestamp}.png"
            driver.save_screenshot(str(screenshot_path))
            
            record_test("seleniumbase_chrome", True, f"SeleniumBase works, title: {title}")
            log_verbose(f"  Screenshot saved to: {screenshot_path}")
            return True
        finally:
            driver.quit()
            
    except Exception as e:
        record_test("seleniumbase_chrome", False, f"SeleniumBase failed: {e}")
        return False


def test_network_connectivity() -> bool:
    """Test network connectivity."""
    log("Testing network connectivity...")
    try:
        import requests
        
        response = requests.get(TARGET_URL, timeout=30)
        response.raise_for_status()
        
        record_test("network_connectivity", True, f"Network works, status: {response.status_code}")
        return True
        
    except Exception as e:
        record_test("network_connectivity", False, f"Network test failed: {e}")
        return False


def test_filesystem_operations() -> bool:
    """Test basic filesystem operations."""
    log("Testing filesystem operations...")
    try:
        # Test writing to cache directory
        test_file = CACHE_DIR / f"alpine_test_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(test_file, "w") as f:
            f.write("Alpine test content\n")
        
        # Test reading
        with open(test_file, "r") as f:
            content = f.read()
        
        # Clean up
        test_file.unlink()
        
        if content == "Alpine test content\n":
            record_test("filesystem_operations", True, "File read/write operations work")
            return True
        else:
            record_test("filesystem_operations", False, "File content mismatch")
            return False
            
    except Exception as e:
        record_test("filesystem_operations", False, f"Filesystem operations failed: {e}")
        return False


def generate_report() -> tuple:
    """Generate and print test report."""
    log("\n" + "=" * 80)
    log("ALPINE SMOKE TEST REPORT")
    log("=" * 80)
    
    total = len(test_results)
    passed = sum(1 for result in test_results.values() if result["passed"])
    failed = total - passed
    success_rate = (passed / total * 100) if total else 0.0
    
    log(f"\nTotal Tests: {total}")
    log(f"Passed: {passed}")
    log(f"Failed: {failed}")
    log(f"Success Rate: {success_rate:.1f}%\n")
    
    if failed > 0:
        log("Failed Tests:")
        for test_name, result in test_results.items():
            if not result["passed"]:
                log(f"  ✗ {test_name}: {result['details']}")
    
    log("\nDetailed Results:")
    for test_name, result in test_results.items():
        status = "✓ PASS" if result["passed"] else "✗ FAIL"
        log(f"  {status} {test_name}: {result['details']}")
    
    # Save report to file
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = CACHE_DIR / f"alpine_smoke_test_report_{timestamp}.json"
    
    report_data = {
        "timestamp": timestamp,
        "total_tests": total,
        "passed": passed,
        "failed": failed,
        "success_rate": success_rate,
        "tests": test_results
    }
    
    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2)
    
    log(f"\nReport saved to: {report_path}")
    log("=" * 80 + "\n")
    
    return passed, total


def main() -> int:
    """Main test execution."""
    log("=" * 80)
    log("ALPINE SMOKE TEST - RPA Worker Selenium")
    log("=" * 80)
    log(f"Target URL: {TARGET_URL}")
    log(f"Cache Directory: {CACHE_DIR}")
    log(f"Verbose: {VERBOSE}")
    log("=" * 80 + "\n")
    
    # Run all tests
    check_python_version()
    check_chromium_browser()
    check_firefox_browser()
    check_chromedriver()
    check_geckodriver()
    
    # Browser tests
    test_chrome_selenium()
    test_firefox_selenium()
    test_seleniumbase_chrome()
    
    # System tests
    test_network_connectivity()
    test_filesystem_operations()
    
    # Generate report
    passed, total = generate_report()
    
    # Return exit code
    if passed == total:
        log("✓ All tests passed!")
        return 0
    else:
        log(f"✗ {total - passed} test(s) failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
