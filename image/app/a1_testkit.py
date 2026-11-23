#!/usr/bin/env python3
"""
a1_testkit — ferramentas para TESTAR certificados A1 dentro da imagem.

- ``make_test_pki()``: ICP de teste (AC raiz + certificado de pessoa física no
  formato ICP-Brasil, com CPF no SubjectAltName) exportada em .pfx moderno e legado.
- ``MTLSServer``: servidor HTTPS local que EXIGE certificado de cliente e mostra
  o titular recebido. Serve para provar que o browser apresentou o A1.
- ``open_chrome`` / ``open_seleniumbase`` / ``open_firefox``: drivers configurados
  como em produção para abrir o ``MTLSServer``.

Usado por /app/a1_check.py e por tests/image/test_a1_certificate.py.
Nada aqui acessa a internet.
"""

from __future__ import annotations

import datetime as _dt
import html
import ipaddress
import os
import ssl
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Sequence

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

OK_TITLE = "A1-OK"
TEST_CPF = "12345678909"
TEST_HOLDER = "FULANO DE TESTE"
TEST_CA_CN = "AC TESTE RPA WORKER"


# --- ICP de teste ---------------------------------------------------------------

def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _name(cn: str, organization: str = "ICP-Teste") -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])


def _octet_string(value: bytes) -> bytes:
    assert len(value) < 128
    return b"\x04" + bytes([len(value)]) + value


def _pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def make_test_pki(out_dir: Path, password: str, days: int = 365, organization: str = "ICP-Teste") -> dict:
    """Gera a ICP de teste em ``out_dir``.

    Devolve caminhos: ``ca`` (PEM), ``pfx`` (AES/PBES2), ``pfx_3des`` (3DES),
    ``pfx_rc2`` (RC2-40 + 3DES, como A1 antigos; ausente se o OpenSSL não tiver
    o provider legacy), ``expired`` (.pfx vencido) e ``wrong_password``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=5)

    ca_key = _key()
    ca = (
        x509.CertificateBuilder()
        .subject_name(_name(TEST_CA_CN, organization)).issuer_name(_name(TEST_CA_CN, organization))
        .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now).not_valid_after(now + _dt.timedelta(days=days + 1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    def person(not_before: _dt.datetime, not_after: _dt.datetime):
        key = _key()
        # ICP-Brasil PF: nascimento (8) + CPF (11) + NIS (11) + RG (15) + órgão/UF (6)
        dados_pf = ("01011990" + TEST_CPF + "0" * 11 + "0" * 15 + "SSPRN ").encode()
        cert = (
            x509.CertificateBuilder()
            .subject_name(_name(f"{TEST_HOLDER}:{TEST_CPF}", organization)).issuer_name(ca.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(not_before).not_valid_after(not_after)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.KeyUsage(True, True, True, False, False, False, False, False, False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH,
                                                  ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
            .add_extension(x509.SubjectAlternativeName([
                x509.RFC822Name("fulano@teste.invalid"),
                x509.OtherName(x509.ObjectIdentifier("2.16.76.1.3.1"), _octet_string(dados_pf)),
            ]), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        return key, cert

    key, cert = person(now, now + _dt.timedelta(days=days))
    pw = password.encode()
    paths = {"ca": out_dir / "ca.pem", "password": password}
    paths["ca"].write_bytes(_pem(ca))

    def export(name: str, k, c, algorithm) -> Path:
        target = out_dir / name
        target.write_bytes(pkcs12.serialize_key_and_certificates(b"teste", k, c, [ca], algorithm))
        return target

    paths["pfx"] = export("a1.pfx", key, cert, serialization.BestAvailableEncryption(pw))
    legacy = (
        serialization.PrivateFormat.PKCS12.encryption_builder()
        .kdf_rounds(2048)
        .key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC)
        .hmac_hash(hashes.SHA1())
        .build(pw)
    )
    paths["pfx_3des"] = export("a1-3des.pfx", key, cert, legacy)

    # RC2-40: formato de muitos A1 antigos; só o openssl com -legacy gera.
    with tempfile.TemporaryDirectory() as tmp:
        key_pem, cert_pem, pw_file = Path(tmp) / "k.pem", Path(tmp) / "c.pem", Path(tmp) / "pw"
        key_pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
        cert_pem.write_bytes(_pem(cert) + _pem(ca))
        pw_file.write_text(password)
        rc2 = out_dir / "a1-rc2.pfx"
        try:
            result = subprocess.run(
                ["openssl", "pkcs12", "-export", "-legacy", "-certpbe", "PBE-SHA1-RC2-40", "-keypbe", "PBE-SHA1-3DES",
                 "-inkey", str(key_pem), "-in", str(cert_pem), "-out", str(rc2), "-passout", f"file:{pw_file}"],
                capture_output=True,
            )
            if result.returncode == 0:
                paths["pfx_rc2"] = rc2
        except OSError:
            pass  # sem openssl no PATH (ex.: testes unitários no host)

    old_key, old_cert = person(now - _dt.timedelta(days=400), now - _dt.timedelta(days=35))
    paths["expired"] = export("a1-vencido.pfx", old_key, old_cert, serialization.BestAvailableEncryption(pw))
    paths["wrong_password"] = export("a1-outra-senha.pfx", key, cert,
                                     serialization.BestAvailableEncryption(b"outra-senha"))
    return paths


def make_sample_pdf(path: Path, text: str = "Documento de teste do rpa-worker-selenium") -> Path:
    """PDF simples (reportlab) para testar assinaturas."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.drawString(72, 800, text)
    pdf.drawString(72, 780, _dt.datetime.now().isoformat(timespec="seconds"))
    pdf.save()
    return Path(path)


# --- Servidor HTTPS que exige certificado de cliente -----------------------------

class MTLSServer:
    """HTTPS em 127.0.0.1 que só aceita conexões com certificado de cliente.

    ``trusted`` são os certificados aceitos como âncora: a cadeia do .pfx (AC)
    e/ou o próprio certificado (aceito via VERIFY_X509_PARTIAL_CHAIN).
    A página devolvida tem título ``A1-OK`` e o titular em ``#subject``.
    O certificado do servidor é autoassinado e efêmero: os browsers devem
    ignorar erros de certificado do SERVIDOR (o que está em teste é o cliente).
    """

    def __init__(self, trusted: Sequence[x509.Certificate]):
        self.trusted = list(trusted)
        self.handshake_errors: list = []
        self.subjects: list = []
        self._tmp = tempfile.TemporaryDirectory()
        self._httpd: Optional[ThreadingHTTPServer] = None

    def _context(self) -> ssl.SSLContext:
        key = _key()
        now = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=5)
        name = _name("localhost")
        cert = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + _dt.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .sign(key, hashes.SHA256())
        )
        tmp = Path(self._tmp.name)
        (tmp / "server.pem").write_bytes(_pem(cert))
        (tmp / "server.key").write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                                           serialization.PrivateFormat.PKCS8,
                                                           serialization.NoEncryption()))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(tmp / "server.pem", tmp / "server.key")
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        ctx.load_verify_locations(cadata=b"".join(_pem(c) for c in self.trusted).decode())
        return ctx

    def __enter__(self) -> "MTLSServer":
        ctx = self._context()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - API do http.server
                peer = self.connection.getpeercert() or {}
                subject = dict(item[0] for item in peer.get("subject", ()))
                cn = subject.get("commonName", "")
                outer.subjects.append(cn)
                body = (f"<html><head><title>{OK_TITLE}</title></head><body>"
                        f"<p id='subject'>{html.escape(cn)}</p></body></html>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def finish_request(self, request, client_address):
                try:
                    request.settimeout(20)
                    tls = ctx.wrap_socket(request, server_side=True)
                except (ssl.SSLError, OSError) as exc:
                    outer.handshake_errors.append(str(exc))
                    return
                Handler(tls, client_address, self)

        self._httpd = Server(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    @property
    def url(self) -> str:
        assert self._httpd is not None
        return f"https://127.0.0.1:{self._httpd.server_address[1]}/"

    @property
    def origin(self) -> str:
        return self.url.rstrip("/")

    def __exit__(self, *exc) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        self._tmp.cleanup()


# --- Browsers -------------------------------------------------------------------

def has_display() -> bool:
    display = os.getenv("DISPLAY")
    if not display:
        return False
    return subprocess.run(["xdpyinfo", "-display", display], capture_output=True).returncode == 0


def open_chrome(headless: bool = True):
    """Selenium + Chrome for Testing, ignorando só o certificado do SERVIDOR local."""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    opts = webdriver.ChromeOptions()
    args = ["--no-sandbox", "--disable-dev-shm-usage", "--window-size=1366,768", "--ignore-certificate-errors"]
    if headless:
        args.append("--headless=new")
    for arg in args:
        opts.add_argument(arg)
    return webdriver.Chrome(service=Service("/usr/local/bin/chromedriver"), options=opts)


def open_seleniumbase(uc: bool = True, headless: bool = True):
    """SeleniumBase (UC por padrão, como em produção)."""
    from seleniumbase import Driver

    return Driver(uc=uc, headless=headless, chromium_arg="--ignore-certificate-errors")


def open_firefox(profile_dir: str, headless: bool = True):
    """Selenium + Firefox com o profile (NSS) informado."""
    from selenium import webdriver
    from selenium.webdriver.firefox.service import Service

    opts = webdriver.FirefoxOptions()
    if headless:
        opts.add_argument("-headless")
    opts.add_argument("-profile")
    opts.add_argument(str(profile_dir))
    opts.accept_insecure_certs = True
    opts.set_preference("security.default_personal_cert", "Select Automatically")
    return webdriver.Firefox(service=Service("/usr/local/bin/geckodriver"), options=opts)


def read_subject(driver, url: str, timeout: float = 20) -> str:
    """Abre ``url`` e devolve o titular mostrado pelo MTLSServer ('' se não chegou)."""
    from selenium.webdriver.common.by import By

    try:
        driver.get(url)
    except Exception:  # noqa: BLE001 - erro de TLS vira página de erro/exceção
        return ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if (driver.title or "") == OK_TITLE:
            return driver.find_element(By.ID, "subject").text
        time.sleep(0.5)
    return ""
