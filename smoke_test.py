#!/usr/bin/env python3
"""
Smoke Test for RPA Worker Selenium
Minimal viable test with SeleniumBase and fallback to requests.

Environment Variables:
- TARGET_URL: URL to test (default: https://www.n3wizards.com/index/)
- CACHE_DIR: Directory to save screenshots/HTML (default: /data)
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


def main():
    """
    Main function to run smoke test.
    Tries SeleniumBase first, falls back to requests if unavailable.
    """
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
                driver.wait_for_ready_state_complete()
                
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
