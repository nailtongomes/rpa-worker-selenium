#!/usr/bin/env python3
"""
Smoke Test for RPA Worker Selenium
Minimal viable test with SeleniumBase and fallback to requests.

Environment Variables:
- TARGET_URL: URL to test (default: https://www.n3wizards.com/index/)
- CACHE_DIR: Directory to save screenshots/HTML (default: /data)
- TEST_HELPERS: Test helper scripts functionality (default: 0)
"""

import os
import datetime
import pathlib
import sys
import importlib.util
import re


# Configuration
TARGET_URL = os.getenv("TARGET_URL", "https://www.n3wizards.com/index/")
CACHE_DIR = pathlib.Path(os.getenv("CACHE_DIR", "/data"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TEST_HELPERS = os.getenv("TEST_HELPERS", "0") == "1"


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
