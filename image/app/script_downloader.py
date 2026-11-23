#!/usr/bin/env python3
"""
Script Downloader for RPA Worker Selenium
Downloads Python scripts from URLs specified via environment variables.

Environment Variables:
- SCRIPT_URL: URL of the main script to download and execute (required)
- HELPER_URLS: Comma-separated list of helper script URLs to download (optional)
- SCRIPTS_DIR: Directory to save helper scripts (default: /app/src)
"""

import os
import sys
import pathlib
import requests
import hashlib
import re
from urllib.parse import urlparse, parse_qs, unquote

_CONTENT_DISP_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)

def _sanitize(name: str) -> str:
    # troca caracteres inválidos por "_"
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    # remove espaços nas pontas
    return name.strip()

def _ensure_py(name: str) -> str:
    p = pathlib.Path(name)
    return f"{p.stem}.py" if p.suffix.lower() != ".py" else p.name

def _from_content_disposition(headers: dict | None) -> str | None:
    if not headers:
        return None
    cd = None
    # normaliza chaves
    for k, v in headers.items():
        if k.lower() == "content-disposition":
            cd = v
            break
    if not cd:
        return None
    m = _CONTENT_DISP_RE.search(cd)
    if not m:
        return None
    return _sanitize(unquote(m.group(1)))

def download_file(url, destination_path):
    """
    Download a file from a URL to a destination path.
    
    Args:
        url: URL to download from
        destination_path: Path to save the file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        print(f"[downloader] Downloading from: {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        with open(destination_path, 'wb') as f:
            f.write(response.content)
        
        print(f"[downloader] Saved to: {destination_path}")
        return True
        
    except requests.RequestException as e:
        print(f"[downloader] ERROR downloading {url}: {e}")
        return False
    except IOError as e:
        print(f"[downloader] ERROR saving to {destination_path}: {e}")
        return False


def get_filename_from_url(url: str) -> str:
    """
    Retrocompatível:
    - se encontrar um segmento terminando em .py na URL, usa-o
    - senão, gera script_<md5prefix>.py (igual à ideia antiga)
    """
    parsed = urlparse(url)
    path = unquote(parsed.path or "")
    segments = [s for s in path.split("/") if s]

    # procura por .py em qualquer segmento (da direita p/ esquerda)
    for seg in reversed(segments):
        if seg.lower().endswith(".py"):
            return _sanitize(pathlib.Path(seg).name)

    # fallback estável
    url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
    return f"script_{url_hash}.py"


def choose_download_name(url: str, is_primary: bool = False, headers: dict | None = None) -> str:
    """
    Determina o nome de arquivo para salvar em disco.
    - is_primary=True => força main.py
    - is_primary=False => tenta Content-Disposition; senão, usa nome vindo da URL; se não houver, fallback script_<hash>.py
    """
    if is_primary:
        # principal sempre vira main.py
        return "main.py"

    # para auxiliares, dá preferência ao Content-Disposition (se tiver)
    name = _from_content_disposition(headers)
    if not name:
        # usa a função retrocompatível (mantém comportamento antigo)
        name = get_filename_from_url(url)

    # garante extensão .py (caso o servidor retorne sem .py)
    name = _ensure_py(name)
    return _sanitize(name)

def download_main_script(script_url, temp_dir="/tmp"):
    """
    Download the main script to be executed.
    
    Args:
        script_url: URL of the main script
        temp_dir: Directory to save the main script (default: /tmp)
        
    Returns:
        str: Path to the downloaded script, or None if failed
    """
    if not script_url:
        print("[downloader] ERROR: SCRIPT_URL not provided")
        return None
    
    temp_path = pathlib.Path(temp_dir)
    temp_path.mkdir(parents=True, exist_ok=True)
    
    filename = get_filename_from_url(script_url)
    destination = temp_path / filename
    
    if download_file(script_url, destination):
        # Make the script executable
        os.chmod(destination, 0o755)
        return str(destination)
    
    return None


def download_helper_scripts(helper_urls, scripts_dir="/app/src"):
    """
    Download helper scripts to the scripts directory.
    
    Args:
        helper_urls: Comma-separated list of URLs or list of URLs
        scripts_dir: Directory to save helper scripts
        
    Returns:
        list: List of paths to successfully downloaded helper scripts
    """
    if not helper_urls:
        print("[downloader] No helper scripts to download")
        return []
    
    # Handle both string and list inputs
    if isinstance(helper_urls, str):
        urls = [url.strip() for url in helper_urls.split(',') if url.strip()]
    else:
        urls = helper_urls
    
    if not urls:
        print("[downloader] No helper scripts to download")
        return []
    
    scripts_path = pathlib.Path(scripts_dir)
    scripts_path.mkdir(parents=True, exist_ok=True)
    
    downloaded = []
    print(f"[downloader] Downloading {len(urls)} helper script(s)...")
    
    for url in urls:
        filename = get_filename_from_url(url)
        destination = scripts_path / filename
        
        if download_file(url, destination):
            os.chmod(destination, 0o644)
            downloaded.append(str(destination))
        else:
            print(f"[downloader] WARNING: Failed to download helper: {url}")
    
    print(f"[downloader] Successfully downloaded {len(downloaded)}/{len(urls)} helper script(s)")
    return downloaded


def main():
    """
    Main function to handle script downloading.
    Downloads main script and optional helper scripts based on environment variables.
    """
    # Get environment variables
    script_url = os.getenv("SCRIPT_URL")
    helper_urls = os.getenv("HELPER_URLS")
    scripts_dir = os.getenv("SCRIPTS_DIR", "/app/src")
    
    print("[downloader] Script Downloader starting...")
    print(f"[downloader] SCRIPT_URL: {script_url or 'Not set'}")
    print(f"[downloader] HELPER_URLS: {helper_urls or 'Not set'}")
    print(f"[downloader] SCRIPTS_DIR: {scripts_dir}")
    
    # Download helper scripts first (if any)
    if helper_urls:
        download_helper_scripts(helper_urls, scripts_dir)
    
    # Download main script
    if script_url:
        main_script_path = download_main_script(script_url)
        
        if main_script_path:
            print(f"[downloader] Main script ready: {main_script_path}")
            print(f"[downloader] To execute: python {main_script_path}")
            return 0
        else:
            print("[downloader] ERROR: Failed to download main script")
            return 1
    else:
        print("[downloader] No SCRIPT_URL provided - nothing to download")
        return 0


if __name__ == "__main__":
    sys.exit(main())
