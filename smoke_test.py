#!/usr/bin/env python3
"""
Smoke Test for RPA Worker Selenium
Minimal viable test with SeleniumBase and fallback to requests.

Environment Variables:
- TARGET_URL: URL to test (default: https://www.n3wizards.com/index/)
- CACHE_DIR: Directory to save screenshots/HTML (default: /data)
- TEST_HELPERS: Test helper scripts functionality (default: 0)
- CHECK_PROCESSES: Check if Xvfb and PJeOffice processes are alive (default: 0)
"""

import os
import datetime
import pathlib
import sys
import importlib.util
import re
import subprocess


# Configuration
TARGET_URL = os.getenv("TARGET_URL", "https://www.n3wizards.com/index/")
CACHE_DIR = pathlib.Path(os.getenv("CACHE_DIR", "/data"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TEST_HELPERS = os.getenv("TEST_HELPERS", "0") == "1"
CHECK_PROCESSES = os.getenv("CHECK_PROCESSES", "0") == "1"


def extract_title_from_html(html_content):
    """
    Extract title from HTML content using regex.
    More robust than simple string splitting.
    
    Args:
        html_content: HTML content as string
        
    Returns:
        str: Extracted title or "Desconhecido" if not found
    """
    # Use regex to find the first title tag (case-insensitive)
    match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
    
    if match:
        title = match.group(1).strip()
        # Clean up whitespace and newlines
        title = re.sub(r'\s+', ' ', title)
        return title if title else "Desconhecido"
    
    return "Desconhecido"


def check_process_alive(process_name):
    """
    Check if a process is running by name.
    
    Args:
        process_name: Name of the process to check
        
    Returns:
        bool: True if process is running, False otherwise
    """
    try:
        result = subprocess.run(
            ['pgrep', '-f', process_name],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[smoke] Error checking process {process_name}: {e}")
        return False


def check_xvfb_alive():
    """
    Check if Xvfb (virtual display) is running.
    
    Returns:
        bool: True if Xvfb is running, False otherwise
    """
    display = os.getenv("DISPLAY", ":99")
    
    # Check if Xvfb process is running
    if not check_process_alive("Xvfb"):
        print(f"[smoke] ✗ Xvfb process not running")
        return False
    
    print(f"[smoke] ✓ Xvfb process is alive")
    
    # Try to check if display is accessible
    try:
        result = subprocess.run(
            ['xdpyinfo', '-display', display],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"[smoke] ✓ Display {display} is accessible")
            return True
        else:
            print(f"[smoke] ✗ Display {display} is not accessible")
            return False
    except Exception as e:
        print(f"[smoke] ⚠ Could not verify display accessibility: {e}")
        # If xdpyinfo is not available but process is running, still consider it OK
        return True


def check_pjeoffice_alive():
    """
    Check if PJeOffice process is running.
    
    Returns:
        bool: True if PJeOffice is running or not required, False if required but not running
    """
    use_pjeoffice = os.getenv("USE_PJEOFFICE", "0") == "1"
    
    if not use_pjeoffice:
        print("[smoke] PJeOffice not enabled (USE_PJEOFFICE=0), skipping check")
        return True
    
    # Check if PJeOffice is installed
    pjeoffice_path = "/opt/pjeoffice/pjeoffice-pro.sh"
    if not os.path.exists(pjeoffice_path):
        print(f"[smoke] ✗ PJeOffice not installed at {pjeoffice_path}")
        return False
    
    # Check if PJeOffice process is running
    if check_process_alive("pjeoffice"):
        print("[smoke] ✓ PJeOffice process is alive")
        return True
    else:
        print("[smoke] ✗ PJeOffice process not running")
        return False


def check_processes():
    """
    Check if required processes are alive.
    
    Returns:
        bool: True if all required processes are alive, False otherwise
    """
    if not CHECK_PROCESSES:
        print("[smoke] Process checks disabled (CHECK_PROCESSES=0)")
        return True
    
    print("[smoke] Checking required processes...")
    
    results = []
    
    # Check Xvfb if USE_XVFB is enabled
    use_xvfb = os.getenv("USE_XVFB", "0") == "1"
    if use_xvfb:
        print("[smoke] Checking Xvfb (USE_XVFB=1)...")
        results.append(check_xvfb_alive())
    else:
        print("[smoke] Xvfb not enabled (USE_XVFB=0), skipping check")
    
    # Check PJeOffice if USE_PJEOFFICE is enabled
    use_pjeoffice = os.getenv("USE_PJEOFFICE", "0") == "1"
    if use_pjeoffice:
        print("[smoke] Checking PJeOffice (USE_PJEOFFICE=1)...")
        results.append(check_pjeoffice_alive())
    else:
        print("[smoke] PJeOffice not enabled (USE_PJEOFFICE=0), skipping check")
    
    # If no processes were checked, return True
    if not results:
        print("[smoke] No processes to check")
        return True
    
    # Return True only if all checks passed
    all_passed = all(results)
    if all_passed:
        print("[smoke] ✓ All process checks passed")
    else:
        print("[smoke] ✗ Some process checks failed")
    
    return all_passed


def test_helper_scripts():
    """
    Test helper scripts functionality if they exist.
    
    This function tests helper scripts when TEST_HELPERS environment variable is set.
    If TEST_HELPERS is not set, the test is skipped (returns True).
    If TEST_HELPERS is set but helpers can't be imported, it fails (returns False).
    This is intentional - when explicitly testing helpers, their absence is a failure.
    
    Returns:
        bool: True if test passed or skipped, False if failed
    """
    if not TEST_HELPERS:
        print("[smoke] Skipping helper scripts test (TEST_HELPERS not set)")
        return True
    
    print("[smoke] Testing helper scripts functionality...")
    
    # Add /app/src to path if it exists
    src_dir = pathlib.Path("/app/src")
    if src_dir.exists() and str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    
    try:
        # Try to import helper1
        import helper1
        print("[smoke] ✓ Successfully imported helper1")
        
        # Test helper1 functions
        test_url = TARGET_URL
        is_valid = helper1.validate_url(test_url)
        normalized = helper1.normalize_url(test_url)
        print(f"[smoke] ✓ helper1.validate_url('{test_url}') = {is_valid}")
        print(f"[smoke] ✓ helper1.normalize_url('{test_url}') = '{normalized}'")
        
        # Try to import helper2
        import helper2
        print("[smoke] ✓ Successfully imported helper2")
        
        # Test helper2 functions
        domain = helper2.extract_domain(test_url)
        print(f"[smoke] ✓ helper2.extract_domain('{test_url}') = '{domain}'")
        
        test_text = "  Example   Test  "
        clean = helper2.clean_text(test_text)
        print(f"[smoke] ✓ helper2.clean_text('{test_text}') = '{clean}'")
        
        print("[smoke] ✓ All helper scripts tests passed")
        return True
        
    except ImportError as e:
        print(f"[smoke] ✗ Failed to import helper scripts: {e}")
        return False
    except Exception as e:
        print(f"[smoke] ✗ Error testing helper scripts: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """
    Main function to run smoke test.
    Tries SeleniumBase first, falls back to requests if unavailable.
    """
    # Check processes first if requested
    if CHECK_PROCESSES and not check_processes():
        print("[smoke] Process checks failed")
        return 1
    
    # Test helper scripts first if requested
    if TEST_HELPERS and not test_helper_scripts():
        print("[smoke] Helper scripts test failed")
        return 1
    
    # Check if seleniumbase is available
    seleniumbase_available = importlib.util.find_spec("seleniumbase") is not None
    
    if seleniumbase_available:
        # Execute using SeleniumBase
        try:
            from seleniumbase import Driver
            print("[smoke] Usando SeleniumBase")
            
            # headless2 uses Chrome's modern headless mode
            driver = Driver(uc=True, headless2=True, incognito=True)
            
            try:
                driver.set_window_size(1366, 768)
                driver.open(TARGET_URL)
                
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                out = CACHE_DIR / f"smoke_{ts}.png"
                driver.save_screenshot(str(out))
                
                print(f"[smoke] título: {driver.get_title()}")
                print(f"[smoke] screenshot salvo em: {out}")
                
                return 0
                
            finally:
                driver.quit()
                
        except Exception as e:
            print(f"[smoke] Erro ao usar SeleniumBase: {e}")
            # Fallback to requests if there's an error during execution
            seleniumbase_available = False
    
    if not seleniumbase_available:
        # Fallback to requests
        try:
            import requests
            from urllib.parse import urlparse
            
            print("[smoke] Usando requests (fallback)")
            
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Make HTTP request
            response = requests.get(TARGET_URL, timeout=30)
            
            # Save response content
            out_html = CACHE_DIR / f"smoke_{ts}.html"
            with open(out_html, "w", encoding="utf-8") as f:
                f.write(response.text)
            
            # Extract title from HTML using helper function
            title = extract_title_from_html(response.text)
            
            print(f"[smoke] título: {title}")
            print(f"[smoke] status code: {response.status_code}")
            print(f"[smoke] HTML salvo em: {out_html}")
            
            # Save info file
            with open(CACHE_DIR / f"smoke_{ts}_info.txt", "w") as f:
                f.write(f"URL: {TARGET_URL}\n")
                f.write(f"Status: {response.status_code}\n")
                f.write(f"Título: {title}\n")
                f.write(f"Headers:\n{str(response.headers)}\n")
            
            return 0
            
        except ImportError:
            print("[smoke] ERRO: Nem seleniumbase nem requests estão disponíveis")
            return 1
        except Exception as e:
            print(f"[smoke] ERRO ao usar requests: {e}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
