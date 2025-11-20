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


def get_binary_path(command: str) -> Optional[str]:
    """Get the full path to a binary command."""
    try:
        result = subprocess.run(
            ['which', command],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None

def has_x_server(display: str) -> bool:
    if not display:
        return False
    try:
        proc = subprocess.run(
            ["xdpyinfo", "-display", display],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return proc.returncode == 0
    except FileNotFoundError:
        # xdpyinfo não instalado => assume que não tem X
        return False
    except Exception:
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
    """Test Chrome with regular Selenium WebDriver (not SeleniumBase) - DEPRECATED.
    Use test_chrome_progressive() for comprehensive testing."""
    print("\n⚠ test_chrome_webdriver() is deprecated. Use test_chrome_progressive() instead.")
    return test_chrome_progressive()


def test_chrome_progressive():
    """
    Progressive test for Chrome:
      1) Chrome binary in headless mode via CLI
      2) WebDriver Chrome in headless mode
      3) WebDriver Chrome in headful mode (if DISPLAY available)
    """
    print("\n==============================")
    print("Progressive Test: Chrome")
    print("==============================")

    results = {
        "cli_headless": None,
        "webdriver_headless": None,
        "webdriver_headful": None,
    }

    # ---------------------------------------------------------
    # 0. Check for Chrome and ChromeDriver binaries
    # ---------------------------------------------------------
    print("\n[Stage 0] Checking Chrome and ChromeDriver binaries...")
    if not check_driver_available("ChromeDriver", "chromedriver"):
        print("  ⚠ ChromeDriver not available. Aborting Chrome tests.")
        return results

    # Check if Chrome/Chromium is available
    chrome_binary = None
    if check_browser_available("Chrome", "google-chrome"):
        chrome_binary = get_binary_path("google-chrome") or "google-chrome"
    elif check_browser_available("Chromium", "chromium"):
        chrome_binary = get_binary_path("chromium") or "chromium"
    
    if not chrome_binary:
        print("  ⚠ Chrome/Chromium not available. Aborting Chrome tests.")
        return results

    # ---------------------------------------------------------
    # 1. CLI Test: Chrome headless without Selenium
    # ---------------------------------------------------------
    print("\n[Stage 1] Testing Chrome headless via CLI (without Selenium)...")
    try:
        # Version check
        cmd_version = [chrome_binary, "--headless=new", "--version"]
        print(f"  → Running: {' '.join(cmd_version)}")
        proc = subprocess.run(cmd_version, capture_output=True, text=True, timeout=15)
        print("  → stdout:", proc.stdout.strip())
        print("  → stderr:", proc.stderr.strip())
        if proc.returncode != 0:
            print(f"  ✗ Chrome headless failed (code={proc.returncode})")
            results["cli_headless"] = False
            # If binary already fails here, no point testing WebDriver
            return results
        else:
            print("  ✓ Chrome headless (CLI) OK")
            results["cli_headless"] = True

        # Simple screenshot to validate rendering
        test_png = "/tmp/chrome_cli_test.png"
        cmd_ss = [chrome_binary, "--headless=new", "--screenshot=" + test_png, 
                  "--window-size=1366,768", "--disable-gpu", "https://example.com"]
        print(f"  → Running: {' '.join(cmd_ss)}")
        proc2 = subprocess.run(cmd_ss, capture_output=True, text=True, timeout=30)
        print("  → stdout:", proc2.stdout.strip())
        print("  → stderr:", proc2.stderr.strip())
        if proc2.returncode == 0 and os.path.exists(test_png):
            print("  ✓ Headless screenshot generated successfully:", test_png)
        else:
            print("  ⚠ Screenshot not generated, but Chrome at least executed.")
    except Exception as e:
        print(f"  ✗ Error running Chrome via CLI: {e}")
        results["cli_headless"] = False
        return results

    # ---------------------------------------------------------
    # 2. WebDriver in headless mode
    # ---------------------------------------------------------
    print("\n[Stage 2] Testing Chrome WebDriver in headless mode...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1366,768")
        chrome_options.binary_location = chrome_binary

        # Find chromedriver path
        chromedriver_path = None
        for path in ["/usr/local/bin/chromedriver", "/usr/bin/chromedriver"]:
            if os.path.exists(path):
                chromedriver_path = path
                break

        log_file = "/tmp/chromedriver_headless.log" if not os.path.exists("/app") else "/app/logs/chromedriver_headless.log"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        if chromedriver_path:
            print(f"  → Using chromedriver at: {chromedriver_path}")
            service = Service(
                executable_path=chromedriver_path,
                log_output=open(log_file, "w")
            )
        else:
            print("  → Using chromedriver from PATH (without explicit path)")
            service = Service(log_output=open(log_file, "w"))

        print("  → Initializing Chrome WebDriver (headless)...")
        driver = webdriver.Chrome(service=service, options=chrome_options)

        try:
            test_html = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False)
            test_html.write(
                "<html><head><title>Chrome WebDriver Test</title></head>"
                "<body><h1>Test Page</h1></body></html>"
            )
            test_html.close()

            print("  → Loading test page (file://)...")
            driver.get(f"file://{test_html.name}")
            title = driver.title
            os.unlink(test_html.name)

            print(f"  → Page title: {title}")

            if "Chrome WebDriver Test" in title:
                print("  ✓ Chrome WebDriver (headless) OK")
                results["webdriver_headless"] = True
            else:
                print("  ✗ Unexpected title")
                results["webdriver_headless"] = False

        finally:
            driver.quit()
            print("  → Chrome WebDriver (headless) closed")

    except Exception as e:
        print(f"  ✗ Chrome WebDriver headless failed: {e}")
        import traceback
        traceback.print_exc()
        print("  ↳ Check the log:", "/app/logs/chromedriver_headless.log")
        results["webdriver_headless"] = False

    # ---------------------------------------------------------
    # 3. WebDriver in headful mode (if DISPLAY available)
    # ---------------------------------------------------------
    display = os.environ.get("DISPLAY")
    if not has_x_server(display):
        print("\n[Stage 3] No X server detected. Skipping headful test.")
        results["webdriver_headful"] = None
        return results

    print(f"\n[Stage 3] Testing Chrome WebDriver in headful mode (DISPLAY={display})...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        chrome_options = Options()
        # No --headless here
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1366,768")
        chrome_options.binary_location = chrome_binary

        chromedriver_path = None
        for path in ["/usr/local/bin/chromedriver", "/usr/bin/chromedriver"]:
            if os.path.exists(path):
                chromedriver_path = path
                break

        log_file = "/tmp/chromedriver_headful.log" if not os.path.exists("/app") else "/app/logs/chromedriver_headful.log"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        if chromedriver_path:
            print(f"  → Using chromedriver at: {chromedriver_path}")
            service = Service(
                executable_path=chromedriver_path,
                log_output=open(log_file, "w")
            )
        else:
            service = Service(log_output=open(log_file, "w"))

        print("  → Initializing Chrome WebDriver (headful)...")
        driver = webdriver.Chrome(service=service, options=chrome_options)

        try:
            test_html = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False)
            test_html.write(
                "<html><head><title>Chrome WebDriver Headful Test</title></head>"
                "<body><h1>Test Page</h1></body></html>"
            )
            test_html.close()

            print("  → Loading test page (file://)...")
            driver.get(f"file://{test_html.name}")
            title = driver.title
            os.unlink(test_html.name)

            print(f"  → Page title: {title}")

            if "Chrome WebDriver Headful Test" in title:
                print("  ✓ Chrome WebDriver (headful) OK")
                results["webdriver_headful"] = True
            else:
                print("  ✗ Unexpected title")
                results["webdriver_headful"] = False

        finally:
            driver.quit()
            print("  → Chrome WebDriver (headful) closed")

    except Exception as e:
        print(f"  ✗ Chrome WebDriver headful failed: {e}")
        import traceback
        traceback.print_exc()
        print("  ↳ Check the log:", "/app/logs/chromedriver_headful.log")
        results["webdriver_headful"] = False

    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------
    print("\nChrome Summary (progressive):")
    for stage, result in results.items():
        if result is True:
            status = "✓ OK"
        elif result is False:
            status = "✗ FAILED"
        else:
            status = "⚠ SKIPPED"
        print(f"  {stage}: {status}")

    return results


def test_firefox_webdriver():
    """Test Firefox with regular Selenium WebDriver (not SeleniumBase) - DEPRECATED.
    Use test_firefox_progressive() for comprehensive testing."""
    print("\n⚠ test_firefox_webdriver() is deprecated. Use test_firefox_progressive() instead.")
    return test_firefox_progressive()

def test_firefox_progressive():
    """
    Teste progressivo do Firefox:
      1) Binário Firefox em headless via CLI
      2) WebDriver Firefox em headless
      3) WebDriver Firefox em modo headful (se DISPLAY disponível)
    """
    print("\n==============================")
    print("Teste progressivo: Firefox")
    print("==============================")

    results = {
        "cli_headless": None,
        "webdriver_headless": None,
        "webdriver_headful": None,
    }

    # ---------------------------------------------------------
    # 0. Verificar presença de Firefox e GeckoDriver
    # ---------------------------------------------------------
    print("\n[Etapa 0] Verificando binários Firefox e GeckoDriver...")
    if not check_driver_available("GeckoDriver", "geckodriver"):
        print("  ⚠ GeckoDriver não disponível. Abortando testes do Firefox.")
        return results

    if not check_browser_available("Firefox", "firefox"):
        print("  ⚠ Firefox não disponível. Abortando testes do Firefox.")
        return results

    # ---------------------------------------------------------
    # 1. Teste CLI: Firefox headless sem Selenium
    # ---------------------------------------------------------
    print("\n[Etapa 1] Testando Firefox headless via CLI (sem Selenium)...")
    try:
        # Versão
        cmd_version = ["firefox", "--headless", "--version"]
        print(f"  → Executando: {' '.join(cmd_version)}")
        proc = subprocess.run(cmd_version, capture_output=True, text=True, timeout=15)
        print("  → stdout:", proc.stdout.strip())
        print("  → stderr:", proc.stderr.strip())
        if proc.returncode != 0:
            print(f"  ✗ Firefox headless falhou (code={proc.returncode})")
            results["cli_headless"] = False
            # Se o binário já falha aqui, nem adianta testar WebDriver
            return results
        else:
            print("  ✓ Firefox headless (CLI) OK")
            results["cli_headless"] = True

        # Screenshot simples para validar renderização
        test_png = "/tmp/firefox_cli_test.png"
        cmd_ss = ["firefox", "--headless", "--screenshot", test_png, "https://example.com"]
        print(f"  → Executando: {' '.join(cmd_ss)}")
        proc2 = subprocess.run(cmd_ss, capture_output=True, text=True, timeout=30)
        print("  → stdout:", proc2.stdout.strip())
        print("  → stderr:", proc2.stderr.strip())
        if proc2.returncode == 0 and os.path.exists(test_png):
            print("  ✓ Screenshot headless gerado com sucesso:", test_png)
        else:
            print("  ⚠ Screenshot não gerado, mas Firefox pelo menos executou.")
    except Exception as e:
        print(f"  ✗ Erro ao executar Firefox via CLI: {e}")
        results["cli_headless"] = False
        return results

    # ---------------------------------------------------------
    # 2. WebDriver em headless
    # ---------------------------------------------------------
    print("\n[Etapa 2] Testando Firefox WebDriver em modo headless...")
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service

        firefox_options = Options()
        firefox_options.add_argument("--headless")
        firefox_options.add_argument("--width=1366")
        firefox_options.add_argument("--height=768")
        # Use the full path to the binary if available
        firefox_binary = get_binary_path("firefox") or "/usr/local/bin/firefox"
        if os.path.exists(firefox_binary):
            firefox_options.binary_location = firefox_binary

        # Descobrir caminho do geckodriver
        geckodriver_path = None
        for path in ["/usr/local/bin/geckodriver", "/usr/bin/geckodriver"]:
            if os.path.exists(path):
                geckodriver_path = path
                break

        log_file = "/tmp/geckodriver_headless.log" if not os.path.exists("/app") else "/app/logs/geckodriver_headless.log"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        if geckodriver_path:
            print(f"  → Usando geckodriver em: {geckodriver_path}")
            service = Service(
                executable_path=geckodriver_path,
                log_output=open(log_file, "w")
            )
        else:
            print("  → Usando geckodriver do PATH (sem caminho explícito)")
            service = Service(log_output=open(log_file, "w"))

        print("  → Inicializando WebDriver Firefox (headless)...")
        driver = webdriver.Firefox(service=service, options=firefox_options)

        try:
            test_html = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False)
            test_html.write(
                "<html><head><title>Firefox WebDriver Test</title></head>"
                "<body><h1>Test Page</h1></body></html>"
            )
            test_html.close()

            print("  → Carregando página de teste (file://)...")
            driver.get(f"file://{test_html.name}")
            title = driver.title
            os.unlink(test_html.name)

            print(f"  → Título da página: {title}")

            if "Firefox WebDriver Test" in title:
                print("  ✓ WebDriver Firefox (headless) OK")
                results["webdriver_headless"] = True
            else:
                print("  ✗ Título inesperado")
                results["webdriver_headless"] = False

        finally:
            driver.quit()
            print("  → WebDriver Firefox (headless) fechado")

    except Exception as e:
        print(f"  ✗ WebDriver Firefox headless falhou: {e}")
        import traceback
        traceback.print_exc()
        print("  ↳ Verifique o log:", "/app/logs/geckodriver_headless.log")
        results["webdriver_headless"] = False

    # Se já falhou no headless, podemos tentar headful pra comparar
    # ---------------------------------------------------------
    # 3. WebDriver em modo headful (se DISPLAY disponível)
    # ---------------------------------------------------------
    display = os.environ.get("DISPLAY")
    if not has_x_server(display):
        print("\n[Etapa 3] Nenhum servidor X detectado. Pulando teste headful.")
        results["webdriver_headful"] = None
        return results

    print(f"\n[Etapa 3] Testando Firefox WebDriver em modo headful (DISPLAY={display})...")
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service

        firefox_options = Options()
        # Sem --headless aqui
        # Use the full path to the binary if available
        firefox_binary = get_binary_path("firefox") or "/usr/local/bin/firefox"
        if os.path.exists(firefox_binary):
            firefox_options.binary_location = firefox_binary

        geckodriver_path = None
        for path in ["/usr/local/bin/geckodriver", "/usr/bin/geckodriver"]:
            if os.path.exists(path):
                geckodriver_path = path
                break

        log_file = "/tmp/geckodriver_headful.log" if not os.path.exists("/app") else "/app/logs/geckodriver_headful.log"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        if geckodriver_path:
            print(f"  → Usando geckodriver em: {geckodriver_path}")
            service = Service(
                executable_path=geckodriver_path,
                log_output=open(log_file, "w")
            )
        else:
            service = Service(log_output=open(log_file, "w"))

        print("  → Inicializando WebDriver Firefox (headful)...")
        driver = webdriver.Firefox(service=service, options=firefox_options)

        try:
            test_html = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False)
            test_html.write(
                "<html><head><title>Firefox WebDriver Headful Test</title></head>"
                "<body><h1>Test Page</h1></body></html>"
            )
            test_html.close()

            print("  → Carregando página de teste (file://)...")
            driver.get(f"file://{test_html.name}")
            title = driver.title
            os.unlink(test_html.name)

            print(f"  → Título da página: {title}")

            if "Firefox WebDriver Headful Test" in title:
                print("  ✓ WebDriver Firefox (headful) OK")
                results["webdriver_headful"] = True
            else:
                print("  ✗ Título inesperado")
                results["webdriver_headful"] = False

        finally:
            driver.quit()
            print("  → WebDriver Firefox (headful) fechado")

    except Exception as e:
        print(f"  ✗ WebDriver Firefox headful falhou: {e}")
        import traceback
        traceback.print_exc()
        print("  ↳ Verifique o log:", "/app/logs/geckodriver_headful.log")
        results["webdriver_headful"] = False

    # ---------------------------------------------------------
    # Sumário
    # ---------------------------------------------------------
    print("\nResumo Firefox (progressivo):")
    for stage, result in results.items():
        if result is True:
            status = "✓ OK"
        elif result is False:
            status = "✗ FALHOU"
        else:
            status = "⚠ PULADO"
        print(f"  {stage}: {status}")

    return results


def test_brave_webdriver():
    """Test Brave with regular Selenium WebDriver (not SeleniumBase) - DEPRECATED.
    Use test_brave_progressive() for comprehensive testing."""
    print("\n⚠ test_brave_webdriver() is deprecated. Use test_brave_progressive() instead.")
    return test_brave_progressive()


def test_brave_progressive():
    """
    Progressive test for Brave:
      1) Brave binary in headless mode via CLI
      2) WebDriver Brave in headless mode
      3) WebDriver Brave in headful mode (if DISPLAY available)
    """
    print("\n==============================")
    print("Progressive Test: Brave")
    print("==============================")

    results = {
        "cli_headless": None,
        "webdriver_headless": None,
        "webdriver_headful": None,
    }

    # ---------------------------------------------------------
    # 0. Check for Brave and ChromeDriver binaries
    # ---------------------------------------------------------
    print("\n[Stage 0] Checking Brave and ChromeDriver binaries...")
    if not check_driver_available("ChromeDriver", "chromedriver"):
        print("  ⚠ ChromeDriver not available. Aborting Brave tests.")
        return results

    # Check if Brave is available
    brave_path = "/usr/bin/brave-browser"
    if not os.path.exists(brave_path):
        print(f"  ✗ Brave browser not found at {brave_path}")
        print("  ⚠ Brave not available. Aborting Brave tests.")
        return results
    else:
        print(f"  ✓ Brave browser found at {brave_path}")

    # ---------------------------------------------------------
    # 1. CLI Test: Brave headless without Selenium
    # ---------------------------------------------------------
    print("\n[Stage 1] Testing Brave headless via CLI (without Selenium)...")
    try:
        # Version check
        cmd_version = [brave_path, "--headless=new", "--version"]
        print(f"  → Running: {' '.join(cmd_version)}")
        proc = subprocess.run(cmd_version, capture_output=True, text=True, timeout=15)
        print("  → stdout:", proc.stdout.strip())
        print("  → stderr:", proc.stderr.strip())
        if proc.returncode != 0:
            print(f"  ✗ Brave headless failed (code={proc.returncode})")
            results["cli_headless"] = False
            # If binary already fails here, no point testing WebDriver
            return results
        else:
            print("  ✓ Brave headless (CLI) OK")
            results["cli_headless"] = True

        # Simple screenshot to validate rendering
        test_png = "/tmp/brave_cli_test.png"
        cmd_ss = [brave_path, "--headless=new", "--screenshot=" + test_png,
                  "--window-size=1366,768", "--disable-gpu", "--disable-brave-update", 
                  "https://example.com"]
        print(f"  → Running: {' '.join(cmd_ss)}")
        proc2 = subprocess.run(cmd_ss, capture_output=True, text=True, timeout=30)
        print("  → stdout:", proc2.stdout.strip())
        print("  → stderr:", proc2.stderr.strip())
        if proc2.returncode == 0 and os.path.exists(test_png):
            print("  ✓ Headless screenshot generated successfully:", test_png)
        else:
            print("  ⚠ Screenshot not generated, but Brave at least executed.")
    except Exception as e:
        print(f"  ✗ Error running Brave via CLI: {e}")
        results["cli_headless"] = False
        return results

    # ---------------------------------------------------------
    # 2. WebDriver in headless mode
    # ---------------------------------------------------------
    print("\n[Stage 2] Testing Brave WebDriver in headless mode...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        chrome_options = Options()
        chrome_options.binary_location = brave_path
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1366,768")
        chrome_options.add_argument("--disable-brave-update")

        # Find chromedriver path
        chromedriver_path = None
        for path in ["/usr/local/bin/chromedriver", "/usr/bin/chromedriver"]:
            if os.path.exists(path):
                chromedriver_path = path
                break

        log_file = "/tmp/bravedriver_headless.log" if not os.path.exists("/app") else "/app/logs/bravedriver_headless.log"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        if chromedriver_path:
            print(f"  → Using chromedriver at: {chromedriver_path}")
            service = Service(
                executable_path=chromedriver_path,
                log_output=open(log_file, "w")
            )
        else:
            print("  → Using chromedriver from PATH (without explicit path)")
            service = Service(log_output=open(log_file, "w"))

        print("  → Initializing Brave WebDriver (headless)...")
        driver = webdriver.Chrome(service=service, options=chrome_options)

        try:
            test_html = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False)
            test_html.write(
                "<html><head><title>Brave WebDriver Test</title></head>"
                "<body><h1>Test Page</h1></body></html>"
            )
            test_html.close()

            print("  → Loading test page (file://)...")
            driver.get(f"file://{test_html.name}")
            title = driver.title
            os.unlink(test_html.name)

            print(f"  → Page title: {title}")

            if "Brave WebDriver Test" in title:
                print("  ✓ Brave WebDriver (headless) OK")
                results["webdriver_headless"] = True
            else:
                print("  ✗ Unexpected title")
                results["webdriver_headless"] = False

        finally:
            driver.quit()
            print("  → Brave WebDriver (headless) closed")

    except Exception as e:
        print(f"  ✗ Brave WebDriver headless failed: {e}")
        import traceback
        traceback.print_exc()
        print("  ↳ Check the log:", "/app/logs/bravedriver_headless.log")
        results["webdriver_headless"] = False

    # ---------------------------------------------------------
    # 3. WebDriver in headful mode (if DISPLAY available)
    # ---------------------------------------------------------
    display = os.environ.get("DISPLAY")
    if not has_x_server(display):
        print("\n[Stage 3] No X server detected. Skipping headful test.")
        results["webdriver_headful"] = None
        return results

    print(f"\n[Stage 3] Testing Brave WebDriver in headful mode (DISPLAY={display})...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        chrome_options = Options()
        chrome_options.binary_location = brave_path
        # No --headless here
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1366,768")
        chrome_options.add_argument("--disable-brave-update")

        chromedriver_path = None
        for path in ["/usr/local/bin/chromedriver", "/usr/bin/chromedriver"]:
            if os.path.exists(path):
                chromedriver_path = path
                break

        log_file = "/tmp/bravedriver_headful.log" if not os.path.exists("/app") else "/app/logs/bravedriver_headful.log"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        if chromedriver_path:
            print(f"  → Using chromedriver at: {chromedriver_path}")
            service = Service(
                executable_path=chromedriver_path,
                log_output=open(log_file, "w")
            )
        else:
            service = Service(log_output=open(log_file, "w"))

        print("  → Initializing Brave WebDriver (headful)...")
        driver = webdriver.Chrome(service=service, options=chrome_options)

        try:
            test_html = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False)
            test_html.write(
                "<html><head><title>Brave WebDriver Headful Test</title></head>"
                "<body><h1>Test Page</h1></body></html>"
            )
            test_html.close()

            print("  → Loading test page (file://)...")
            driver.get(f"file://{test_html.name}")
            title = driver.title
            os.unlink(test_html.name)

            print(f"  → Page title: {title}")

            if "Brave WebDriver Headful Test" in title:
                print("  ✓ Brave WebDriver (headful) OK")
                results["webdriver_headful"] = True
            else:
                print("  ✗ Unexpected title")
                results["webdriver_headful"] = False

        finally:
            driver.quit()
            print("  → Brave WebDriver (headful) closed")

    except Exception as e:
        print(f"  ✗ Brave WebDriver headful failed: {e}")
        import traceback
        traceback.print_exc()
        print("  ↳ Check the log:", "/app/logs/bravedriver_headful.log")
        results["webdriver_headful"] = False

    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------
    print("\nBrave Summary (progressive):")
    for stage, result in results.items():
        if result is True:
            status = "✓ OK"
        elif result is False:
            status = "✗ FAILED"
        else:
            status = "⚠ SKIPPED"
        print(f"  {stage}: {status}")

    return results


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
    print("\nProgressive Testing - CLI, Headless WebDriver, and Headful WebDriver")
    print("This verifies browser compatibility in different execution modes\n")
    
    results = {}
    
    # Test each browser with progressive tests (CLI, headless, headful)
    results['chrome'] = test_chrome_progressive()
    results['firefox'] = test_firefox_progressive()
    results['brave'] = test_brave_progressive()
    
    # Test SeleniumBase - commented out for now due to initialization hangs
    # This test can be enabled once the hang issue is resolved
    # results['seleniumbase'] = test_seleniumbase_driver()
    print("\n⚠ SeleniumBase test skipped (initialization timeout issue)")
    results['seleniumbase'] = None
    
    # Print comprehensive summary
    print("\n" + "=" * 70)
    print("Comprehensive Test Summary")
    print("=" * 70)
    
    # Count statistics for each browser
    total_tests = 0
    passed_tests = 0
    failed_tests = 0
    skipped_tests = 0
    
    for browser_name, browser_results in results.items():
        if browser_results is None:
            # Browser test was skipped entirely
            print(f"\n{browser_name.upper()}: ⚠ SKIPPED")
            skipped_tests += 1
        elif isinstance(browser_results, dict):
            # Progressive test results
            print(f"\n{browser_name.upper()}:")
            for stage, result in browser_results.items():
                total_tests += 1
                if result is True:
                    status = "✓ PASS"
                    passed_tests += 1
                elif result is False:
                    status = "✗ FAIL"
                    failed_tests += 1
                else:
                    status = "⚠ SKIP"
                    skipped_tests += 1
                print(f"  {stage}: {status}")
        else:
            # Legacy test result (boolean)
            total_tests += 1
            if browser_results is True:
                status = "✓ PASS"
                passed_tests += 1
            elif browser_results is False:
                status = "✗ FAIL"
                failed_tests += 1
            else:
                status = "⚠ SKIP"
                skipped_tests += 1
            print(f"\n{browser_name.upper()}: {status}")
    
    print(f"\n{'=' * 70}")
    print(f"Total Tests: {total_tests} | Passed: {passed_tests} | Failed: {failed_tests} | Skipped: {skipped_tests}")
    print(f"{'=' * 70}")
    
    if failed_tests > 0:
        print("\n✗ Some tests failed!")
        print("=" * 70)
        return 1
    elif passed_tests == 0:
        print("\n⚠ All tests were skipped (drivers/browsers not available)")
        print("=" * 70)
        return 1
    else:
        print("\n✓ All available browser tests passed!")
        print("=" * 70)
        return 0


if __name__ == "__main__":
    sys.exit(main())
