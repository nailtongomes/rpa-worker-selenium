#!/usr/bin/env python3
"""
Validação real dos browsers da imagem: abre a página do próprio projeto no
GitHub e confere o título.

Diferente de /app/smoke_test.py (que cai num fallback com `requests` quando o
SeleniumBase falha), estes testes FALHAM se qualquer browser/driver não
conseguir carregar a página. Rodam dentro da imagem, com o repo montado:

    docker run --rm --shm-size=2g -v "$PWD:/repo:ro" -w /tmp \\
      -e USE_XVFB=1 -e USE_OPENBOX=1 rpa-worker:local \\
      bash -c "sleep 5 && pytest -p no:cacheprovider -p no:seleniumbase \\
               --timeout=300 -v /repo/tests/image/test_project_page.py"

Variáveis:
    PROJECT_URL     URL visitada (padrão: página do projeto no GitHub)
    EXPECTED_TEXT   texto esperado no título (padrão: rpa-worker-selenium)
"""

import os
import shutil
import subprocess
import time

import pytest

PROJECT_URL = os.getenv("PROJECT_URL", "https://github.com/nailtongomes/rpa-worker-selenium/")
EXPECTED_TEXT = os.getenv("EXPECTED_TEXT", "rpa-worker-selenium")
FIREFOX_PROFILE = os.getenv("FIREFOX_PROFILE_DIR", "/root/.mozilla/firefox/selenium.default-release")
ATTEMPTS = 3

pytestmark = [pytest.mark.integration, pytest.mark.trixie, pytest.mark.online]


def _has_display() -> bool:
    display = os.getenv("DISPLAY")
    if not display or shutil.which("xdpyinfo") is None:
        return False
    return subprocess.run(["xdpyinfo", "-display", display], capture_output=True).returncode == 0


def _visit(open_driver, url: str = PROJECT_URL) -> str:
    """Abre um driver, visita a URL e devolve o título; tenta até ATTEMPTS vezes."""
    last_error = None
    for attempt in range(1, ATTEMPTS + 1):
        driver = None
        try:
            driver = open_driver()
            driver.get(url)
            for _ in range(20):  # até ~10 s para o título aparecer
                if EXPECTED_TEXT in (driver.title or ""):
                    break
                time.sleep(0.5)
            return driver.title or ""
        except Exception as exc:  # noqa: BLE001 - reportado no assert final
            last_error = exc
            print(f"tentativa {attempt}/{ATTEMPTS} falhou: {type(exc).__name__}: {exc}")
            time.sleep(3 * attempt)
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:  # noqa: BLE001
                    pass
    pytest.fail(f"não foi possível abrir {url}: {last_error}")


def _assert_project_title(title: str) -> None:
    print(f"título: {title!r}")
    assert EXPECTED_TEXT in title, f"título inesperado para {PROJECT_URL}: {title!r}"


# ---------------------------------------------------------------------------
# HTTP puro (isola problema de rede de problema de browser)
# ---------------------------------------------------------------------------

def test_requests_reaches_project_page():
    import requests

    resp = requests.get(PROJECT_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0 rpa-worker-selenium-ci"})
    assert resp.status_code == 200
    assert EXPECTED_TEXT in resp.text


# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------

def test_selenium_chrome_headless():
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    def open_driver():
        opts = webdriver.ChromeOptions()
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1366,768"):
            opts.add_argument(arg)
        return webdriver.Chrome(service=Service("/usr/local/bin/chromedriver"), options=opts)

    _assert_project_title(_visit(open_driver))


def test_seleniumbase_headless():
    from seleniumbase import Driver

    _assert_project_title(_visit(lambda: Driver(headless=True)))


def test_seleniumbase_uc_headless():
    from seleniumbase import Driver

    _assert_project_title(_visit(lambda: Driver(uc=True, incognito=True, headless=True)))


@pytest.mark.requires_display
def test_seleniumbase_uc_headful():
    """Modo usado em produção: UC + janela real no Xvfb/OpenBox."""
    if not _has_display():
        pytest.skip("sem display (rode com USE_XVFB=1)")
    from seleniumbase import Driver

    _assert_project_title(_visit(lambda: Driver(uc=True, incognito=True, headless=False)))


# ---------------------------------------------------------------------------
# Firefox (com o profile + NSS criados no build)
# ---------------------------------------------------------------------------

def _firefox(headless: bool):
    from selenium import webdriver
    from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
    from selenium.webdriver.firefox.options import Options

    def open_driver():
        opts = Options()
        if headless:
            opts.add_argument("--headless")
        if os.path.isdir(FIREFOX_PROFILE):
            opts.profile = FirefoxProfile(FIREFOX_PROFILE)
        return webdriver.Firefox(options=opts)

    return open_driver


def test_firefox_headless_with_profile():
    _assert_project_title(_visit(_firefox(headless=True)))


@pytest.mark.requires_display
def test_firefox_headful_with_profile():
    if not _has_display():
        pytest.skip("sem display (rode com USE_XVFB=1)")
    _assert_project_title(_visit(_firefox(headless=False)))
