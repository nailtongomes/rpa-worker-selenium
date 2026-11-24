#!/usr/bin/env python3
"""
Contrato da imagem de produção (roda DENTRO da imagem, sem rede, em segundos).

Verifica o que os scripts de automação esperam encontrar: caminhos, binários,
versões casadas de browser/driver, profile do Firefox com NSS, diretório de
policies do Chrome gravável, pacotes Python importáveis e defaults de ambiente.

EXPECT_FEATURES lista os recursos opcionais esperados na imagem
(padrão = imagem publicada: pjeoffice,pdf,vnc,novnc). Ex.: build sem PJeOffice
-> EXPECT_FEATURES=pdf,vnc,novnc.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.trixie]

FEATURES = set(filter(None, os.getenv("EXPECT_FEATURES", "pjeoffice,pdf,vnc,novnc").split(",")))
FIREFOX_PROFILE = Path("/root/.mozilla/firefox/selenium.default-release")


def _run(*cmd: str) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"{' '.join(cmd)} falhou: {result.stderr or result.stdout}"
    return (result.stdout or result.stderr).strip()


def _requires(feature: str):
    return pytest.mark.skipif(feature not in FEATURES, reason=f"recurso '{feature}' não esperado nesta imagem")


# --- Arquivos do /app ---------------------------------------------------------

@pytest.mark.parametrize(
    "path, executable",
    [
        ("/app/entrypoint.sh", True),
        ("/app/script_downloader.py", True),
        ("/app/smoke_test.py", True),
        ("/app/task_server.py", True),
        ("/app/test_browser_drivers.py", False),
        ("/app/a1cert.py", False),
        ("/app/a1_testkit.py", False),
        ("/app/a1_check.py", True),
        ("/app/egress_proxy.py", True),
        ("/app/egress_check.py", True),
        ("/app/egress_testkit.py", True),
        ("/app/preflight.py", True),
        ("/app/pjeoffice_check.py", True),
        ("/app/requirements.txt", False),
    ],
)
def test_app_files(path, executable):
    p = Path(path)
    assert p.is_file(), f"{path} ausente"
    if executable:
        assert os.access(p, os.X_OK), f"{path} não é executável"


def test_app_dirs():
    for d in ["/app/src", "/app/logs", "/app/tmp", "/app/recordings", "/app/.pki"]:
        assert Path(d).is_dir(), f"{d} ausente"


# --- Browsers e drivers ------------------------------------------------------

def test_chrome_and_chromedriver_versions_match():
    chrome = re.search(r"(\d+\.\d+\.\d+\.\d+)", _run("chrome", "--version")).group(1)
    driver = re.search(r"(\d+\.\d+\.\d+\.\d+)", _run("chromedriver", "--version")).group(1)
    assert chrome == driver, f"Chrome {chrome} x ChromeDriver {driver}"


def test_firefox_and_geckodriver_present():
    assert "Firefox" in _run("firefox", "--version")
    assert "geckodriver" in _run("geckodriver", "--version")


def test_firefox_profile_with_nss():
    assert FIREFOX_PROFILE.is_dir(), f"{FIREFOX_PROFILE} ausente"
    for name in ["cert9.db", "key4.db"]:
        assert (FIREFOX_PROFILE / name).is_file(), f"{name} ausente no profile do Firefox"
    _run("certutil", "-d", f"sql:{FIREFOX_PROFILE}", "-L")


def test_seleniumbase_uc_driver_prewarmed():
    import seleniumbase

    drivers = Path(seleniumbase.__file__).parent / "drivers"
    assert (drivers / "uc_driver").exists(), "uc_driver não foi pré-baixado no build"


@pytest.mark.parametrize("policy_dir", ["/etc/opt/chrome/policies/managed", "/etc/opt/chrome_for_testing/policies/managed"])
def test_chrome_policy_dir_writable(policy_dir, tmp_path):
    """Scripts gravam AutoSelectCertificateForUrls aqui em runtime."""
    d = Path(policy_dir)
    assert d.is_dir(), f"{policy_dir} ausente"
    probe = d / f"_contract_probe_{os.getpid()}.json"
    try:
        probe.write_text(json.dumps({"AutoSelectCertificateForUrls": []}))
        assert json.loads(probe.read_text()) == {"AutoSelectCertificateForUrls": []}
    finally:
        probe.unlink(missing_ok=True)


# --- Ferramentas do sistema --------------------------------------------------

@pytest.mark.parametrize(
    "tool",
    ["Xvfb", "openbox", "xdotool", "wmctrl", "xclip", "xdpyinfo", "certutil", "pk12util", "openssl", "keytool",
     "unzip", "curl"],
)
def test_system_tools(tool):
    assert shutil.which(tool), f"{tool} não encontrado no PATH"


@_requires("pjeoffice")
def test_pjeoffice_installed():
    assert os.access("/opt/pjeoffice/pjeoffice-pro.sh", os.X_OK)
    assert shutil.which("java"), "Java (necessário ao PJeOffice) ausente"


# ELF e_machine: x86-64 = 62, AArch64 = 183
ELF_MACHINE = {"x86_64": 62, "aarch64": 183}


def _elf_machine(path: str) -> int:
    with open(path, "rb") as fh:
        header = fh.read(20)
    assert header[:4] == b"\x7fELF", f"{path} não é um executável ELF"
    return int.from_bytes(header[18:20], "little")


@pytest.mark.parametrize("binary", [
    "/opt/chrome/chrome", "/usr/local/bin/chromedriver", "/opt/firefox/firefox-bin", "/usr/local/bin/geckodriver",
    pytest.param("/opt/pjeoffice/jre/bin/java", marks=_requires("pjeoffice")),
])
def test_binaries_match_the_machine(binary):
    """Imagem amd64 e arm64 (:latest-arm64): browsers, drivers e o Java do PJeOffice da arquitetura certa.
    No arm64 o PJeOffice traz um JRE x86-64 que é trocado no build; este teste pega se a troca falhar."""
    machine = os.uname().machine
    assert machine in ELF_MACHINE, f"arquitetura não suportada: {machine}"
    assert _elf_machine(os.path.realpath(binary)) == ELF_MACHINE[machine], f"{binary} não é {machine}"


@_requires("pjeoffice")
def test_pjeoffice_jre_runs():
    out = _run("/opt/pjeoffice/jre/bin/java", "-version")
    assert 'version "1.8' in out, out


@_requires("pdf")
@pytest.mark.parametrize("tool", ["convert", "gs"])
def test_pdf_tools(tool):
    assert shutil.which(tool)


@_requires("vnc")
def test_vnc_installed():
    assert shutil.which("x11vnc")


@_requires("novnc")
def test_novnc_installed():
    assert Path("/opt/novnc/vnc.html").is_file()
    assert shutil.which("websockify")


# --- Python ------------------------------------------------------------------

# módulo importável -> pacote do requirements.txt
PY_MODULES = [
    "selenium", "seleniumbase", "pyvirtualdisplay", "bs4", "lxml", "ftfy", "pandas", "openpyxl",
    "PyPDF2", "fitz", "endesive", "asn1crypto", "cryptography", "oscrypto", "reportlab", "qrcode", "cv2", "PIL",
    "pyautogui", "pyperclip", "requests", "urllib3", "httpx", "flask", "jwt", "pyotp", "filelock",
    "twocaptcha", "psutil", "pytz", "tinydb", "pymongo", "typing_extensions", "boto3", "yaml",
]


@pytest.mark.parametrize("module", PY_MODULES)
def test_python_module_available(module):
    assert importlib.util.find_spec(module) is not None, f"módulo {module} não instalado"


def test_python_is_venv():
    import sys

    assert sys.prefix == "/opt/venv", f"Python fora do venv: {sys.prefix}"


# --- Defaults de ambiente ----------------------------------------------------

@pytest.mark.parametrize(
    "var, expected",
    [
        ("LANG", "pt_BR.UTF-8"),
        ("TZ", "America/Sao_Paulo"),
        ("SCREEN_WIDTH", "1600"),
        ("SCREEN_HEIGHT", "900"),
        ("MOZ_ALLOW_ROOT", "1"),
        ("VNC_PORT", "5900"),
        ("NOVNC_PORT", "6080"),
    ],
)
def test_env_defaults(var, expected):
    assert os.environ.get(var) == expected, f"{var}={os.environ.get(var)!r}, esperado {expected!r}"


def test_locale_available():
    assert "pt_BR.utf8" in _run("locale", "-a")


def test_a1cert_importable_from_user_scripts():
    """Scripts baixados de SCRIPT_URL rodam em /tmp: `import a1cert` vem do PYTHONPATH do entrypoint."""
    result = subprocess.run(
        ["python", "-c", "import a1cert, a1_testkit; print(a1cert.__file__)"],
        capture_output=True, text=True, cwd="/tmp", timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "/app/a1cert.py"


def test_icp_brasil_bundle():
    """Raízes + ACs oficiais da ICP-Brasil em /opt/icp-brasil, legíveis pelo openssl da imagem."""
    import sys

    sys.path.insert(0, "/app")
    import a1cert

    roots = a1cert.icp_brasil_certs(roots_only=True)
    every = a1cert.icp_brasil_certs()
    assert len(roots) >= 8 and len(every) - len(roots) > 100
    assert json.loads(Path("/opt/icp-brasil/manifest.json").read_text())["acs"] == len(every) - len(roots)
    # amostra: uma AC intermediária fecha cadeia até uma raiz com o openssl da imagem
    import types

    root = a1cert.verify_chain(types.SimpleNamespace(certificate=every[-1], chain=[]))
    assert root.startswith("Autoridade Certificadora Raiz Brasileira v")


def test_icp_brasil_not_in_system_trust_store():
    """As ACs servem só para validar o A1: TLS do sistema e dos browsers não muda."""
    bundle = Path("/etc/ssl/certs/ca-certificates.crt").read_text()
    assert "Raiz Brasileira" not in bundle


def test_egress_relay_off_by_default():
    """Sem EGRESS_PROXY_URL o container sai direto: nenhuma variável/policy de proxy."""
    if os.getenv("EGRESS_PROXY_URL") or os.getenv("EGRESS_PROXY_URL_FILE"):
        pytest.skip("relay ligado neste container")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        assert not os.getenv(name), f"{name} definido sem relay"
    for d in ["/etc/opt/chrome/policies/managed", "/etc/opt/chrome_for_testing/policies/managed"]:
        assert not Path(d, "egress_proxy.json").exists()
    assert not Path("/opt/firefox/distribution/policies.json").exists()
