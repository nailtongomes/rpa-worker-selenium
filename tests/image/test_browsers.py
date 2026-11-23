#!/usr/bin/env python3
"""
Validação real dos browsers da imagem (roda DENTRO da imagem).

Cada browser abre dois alvos e confere o título:
  - local:   página servida de tests/image/fixtures (sem internet)
  - project: https://github.com/nailtongomes/rpa-worker-selenium/ (marker `online`)

Ao contrário de um fallback com requests, estes testes FALHAM se o browser não
carregar a página. Para rodar só offline: pytest -m "not online".

Variáveis:
    PROJECT_URL     URL online (padrão: página do projeto no GitHub)
    EXPECTED_TEXT   texto esperado no título online (padrão: rpa-worker-selenium)
"""

import os
import re
import shutil
import subprocess
import time

import pytest

PROJECT_URL = os.getenv("PROJECT_URL", "https://github.com/nailtongomes/rpa-worker-selenium/")
EXPECTED_TEXT = os.getenv("EXPECTED_TEXT", "rpa-worker-selenium")
LOCAL_TITLE = "RPA Local Test"
FIREFOX_PROFILE = os.getenv("FIREFOX_PROFILE_DIR", "/root/.mozilla/firefox/selenium.default-release")
ATTEMPTS = 3

pytestmark = [pytest.mark.integration, pytest.mark.trixie]


def _has_display() -> bool:
    display = os.getenv("DISPLAY")
    if not display or shutil.which("xdpyinfo") is None:
        return False
    return subprocess.run(["xdpyinfo", "-display", display], capture_output=True).returncode == 0


@pytest.fixture(params=["local", pytest.param("project", marks=pytest.mark.online)])
def target(request, local_site):
    """(url, texto esperado no título)."""
    if request.param == "local":
        return f"{local_site}/index.html", LOCAL_TITLE
    return PROJECT_URL, EXPECTED_TEXT


def _visit(open_driver, target, artifacts_dir, name: str) -> str:
    """Abre o driver e visita a URL; devolve o título.

    Falha imediatamente se o browser/driver não inicia (imagem quebrada).
    Só a navegação é repetida (até ATTEMPTS vezes), pois pode oscilar com a rede.
    """
    url, expected = target
    driver = open_driver()  # sem retry: se o browser não abre, a imagem está quebrada
    try:
        last_error = None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                driver.get(url)
                for _ in range(20):  # até ~10 s para o título aparecer
                    if expected in (driver.title or ""):
                        break
                    time.sleep(0.5)
                title = driver.title or ""
                if expected in title:
                    break
                last_error = AssertionError(f"título inesperado em {url}: {title!r}")
            except Exception as exc:  # noqa: BLE001 - reportado abaixo
                last_error = exc
            print(f"tentativa {attempt}/{ATTEMPTS} falhou: {last_error}")
            time.sleep(3 * attempt)
        else:
            pytest.fail(f"{name}: não foi possível abrir {url}: {last_error}")

        label = "local" if "127.0.0.1" in url else "project"
        safe = re.sub(r"[^a-z0-9]+", "-", f"{name}-{label}".lower())
        driver.save_screenshot(str(artifacts_dir / f"{safe}.png"))
        print(f"{name} -> {url}: {title!r}")
        return title
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass


# --- Rede (isola problema de rede de problema de browser) -------------------

@pytest.mark.online
def test_requests_reaches_project_page():
    import requests

    resp = requests.get(PROJECT_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0 rpa-worker-selenium-ci"})
    assert resp.status_code == 200
    assert EXPECTED_TEXT in resp.text


# --- Chrome ------------------------------------------------------------------

def test_selenium_chrome_headless(target, artifacts_dir):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    def open_driver():
        opts = webdriver.ChromeOptions()
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1366,768"):
            opts.add_argument(arg)
        return webdriver.Chrome(service=Service("/usr/local/bin/chromedriver"), options=opts)

    _visit(open_driver, target, artifacts_dir, "selenium-chrome")


def test_seleniumbase_headless(target, artifacts_dir):
    from seleniumbase import Driver

    _visit(lambda: Driver(headless=True), target, artifacts_dir, "sb-chrome")


def test_seleniumbase_uc_headless(target, artifacts_dir):
    from seleniumbase import Driver

    _visit(lambda: Driver(uc=True, incognito=True, headless=True), target, artifacts_dir, "sb-uc")


@pytest.mark.requires_display
def test_seleniumbase_uc_headful(target, artifacts_dir):
    """Modo usado em produção: UC + janela real no Xvfb/OpenBox."""
    if not _has_display():
        pytest.skip("sem servidor X (rode com USE_XVFB=1)")
    from seleniumbase import Driver

    _visit(lambda: Driver(uc=True, incognito=True, headless=False), target, artifacts_dir, "sb-uc-headful")


# --- Firefox (profile + NSS criados no build) --------------------------------

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


def test_firefox_headless_with_profile(target, artifacts_dir):
    _visit(_firefox(headless=True), target, artifacts_dir, "firefox")


@pytest.mark.requires_display
def test_firefox_headful_with_profile(target, artifacts_dir):
    if not _has_display():
        pytest.skip("sem servidor X (rode com USE_XVFB=1)")
    _visit(_firefox(headless=False), target, artifacts_dir, "firefox-headful")


@pytest.mark.requires_display
def test_seleniumbase_firefox(target, artifacts_dir):
    """SeleniumBase + Firefox precisa de servidor X mesmo em headless."""
    if not _has_display():
        pytest.skip("SeleniumBase + Firefox requer Xvfb (USE_XVFB=1)")
    from seleniumbase import Driver

    _visit(lambda: Driver(browser="firefox", headless=True), target, artifacts_dir, "sb-firefox")


# --- Interação real com a página (offline) -----------------------------------

def test_seleniumbase_uc_interacts_with_form(local_site):
    """Digita, clica e lê o resultado: garante que o driver UC controla a página."""
    from seleniumbase import Driver

    driver = Driver(uc=True, incognito=True, headless=not _has_display())
    try:
        driver.get(f"{local_site}/index.html")
        driver.type("#name", "rpa")
        driver.click("#go")
        driver.assert_text("ok:rpa", "#out")
    finally:
        driver.quit()
