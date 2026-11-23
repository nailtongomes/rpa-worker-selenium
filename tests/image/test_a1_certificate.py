#!/usr/bin/env python3
"""
Certificado digital A1 (roda DENTRO da imagem, sem internet).

Usa uma ICP de teste gerada na hora (a1_testkit) para validar o caminho completo
que os scripts de produção percorrem com um A1 real:

  URL + senha → abrir .pfx (moderno, 3DES, RC2) → .p7s attached/detached → PAdES
  → Java (PJeOffice) → NSS do Chrome/Firefox → browser apresenta o certificado a
  um servidor HTTPS local que EXIGE certificado de cliente → limpeza.

Os controles negativos garantem que o servidor recusa quem não apresenta o A1.
"""

import http.server
import os
import subprocess
import sys
import threading
from functools import partial
from pathlib import Path

import pytest

sys.path.insert(0, "/app")

import a1_testkit as kit  # noqa: E402
import a1cert  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.trixie]

PASSWORD = "S3nh@ de-teste_2026"


# --- fixtures ------------------------------------------------------------------

@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    return kit.make_test_pki(tmp_path_factory.mktemp("pki"), PASSWORD)


@pytest.fixture(scope="module")
def cert(pki):
    return a1cert.load_pfx(pki["pfx"], PASSWORD)


@pytest.fixture(scope="module")
def pki_url(pki):
    """Servidor HTTP servindo os .pfx de teste (fluxo A1_PFX_URL)."""
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(pki["pfx"].parent))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    return kit.make_sample_pdf(tmp_path_factory.mktemp("pdf") / "peticao.pdf")


@pytest.fixture(scope="module")
def mtls(cert):
    with kit.MTLSServer(list(cert.chain) + [cert.certificate]) as server:
        yield server


@pytest.fixture
def chrome_with_cert(cert, mtls):
    a1cert.install_chrome(cert, [mtls.origin])
    yield
    a1cert.uninstall_chrome(cert)


@pytest.fixture
def firefox_profile(tmp_path):
    """Cópia do profile da imagem (o original não é alterado pelo teste)."""
    import shutil

    profile = tmp_path / "firefox-profile"
    shutil.copytree(a1cert.FIREFOX_PROFILE_DIR, profile)
    return profile


def _subject(opener, url):
    driver = opener()  # sem retry: se o browser não abre, a imagem está quebrada
    try:
        return kit.read_subject(driver, url)
    finally:
        driver.quit()


def _modes():
    """headless sempre; com janela quando houver Xvfb (cenário do portão)."""
    return [True, pytest.param(False, marks=pytest.mark.requires_display)]


def _skip_headful_without_display(headless):
    if not headless and not kit.has_display():
        pytest.skip("sem servidor X (rode com USE_XVFB=1)")


# --- abrir o .pfx ------------------------------------------------------------------

@pytest.mark.parametrize("variant, pbe", [("pfx", "PBES2"), ("pfx_3des", "TripleDES"), ("pfx_rc2", "RC2")])
def test_open_pfx_formats(pki, variant, pbe):
    """A1 antigos usam 3DES/RC2, que o OpenSSL 3 só abre com o provider legacy."""
    if variant not in pki:
        pytest.fail("openssl da imagem não gera RC2 (provider legacy ausente)")
    cert = a1cert.load_pfx(pki[variant], PASSWORD)
    assert cert.subject_cn == f"{kit.TEST_HOLDER}:{kit.TEST_CPF}"
    assert cert.cpf == kit.TEST_CPF
    assert cert.issuer_cn == kit.TEST_CA_CN
    assert len(cert.chain) == 1
    assert pbe in cert.pbe
    assert cert.is_valid_now and cert.days_left >= 360


def test_wrong_password_has_clear_message(pki):
    with pytest.raises(a1cert.A1Error, match="senha incorreta"):
        a1cert.load_pfx(pki["wrong_password"], PASSWORD)


def test_expired_certificate_detected(pki):
    cert = a1cert.load_pfx(pki["expired"], PASSWORD)
    assert not cert.is_valid_now
    assert cert.days_left < 0


def test_password_and_nickname_never_leak(cert):
    assert PASSWORD not in repr(cert)
    assert PASSWORD not in str(cert.summary())
    assert ":" not in cert.nickname


def test_load_from_env_url_and_password_file(pki, pki_url, tmp_path, monkeypatch):
    """Fluxo de produção: A1_PFX_URL + A1_PFX_PASSWORD_FILE (tem prioridade)."""
    secret = tmp_path / "senha"
    secret.write_text(PASSWORD + "\n")
    monkeypatch.setenv("A1_PFX_URL", f"{pki_url}/{pki['pfx'].name}")
    monkeypatch.setenv("A1_PFX_PASSWORD", "ignorada")
    monkeypatch.setenv("A1_PFX_PASSWORD_FILE", str(secret))
    monkeypatch.delenv("A1_PFX_PATH", raising=False)
    cert = a1cert.load_from_env(tmp_path / "download")
    assert cert.cpf == kit.TEST_CPF
    assert oct(cert.path.stat().st_mode & 0o777) == "0o600"


def test_load_from_env_url_unreachable(pki_url, monkeypatch, tmp_path):
    monkeypatch.setenv("A1_PFX_URL", f"{pki_url}/nao-existe.pfx")
    monkeypatch.setenv("A1_PFX_PASSWORD", PASSWORD)
    monkeypatch.delenv("A1_PFX_PASSWORD_FILE", raising=False)
    monkeypatch.delenv("A1_PFX_PATH", raising=False)
    monkeypatch.setattr(a1cert.time, "sleep", lambda s: None)
    with pytest.raises(a1cert.A1Error, match="não foi possível baixar"):
        a1cert.load_from_env(tmp_path)


# --- assinaturas ---------------------------------------------------------------------

def test_pdf_to_p7s_attached(cert, pdf, pki, tmp_path):
    """PDF → .p7s com o PDF embutido; openssl valida assinatura e cadeia."""
    from cryptography import x509

    p7s = a1cert.sign_p7s(cert, pdf, tmp_path / "peticao.pdf.p7s")
    assert a1cert.p7s_content(p7s) == pdf.read_bytes()
    ca = x509.load_pem_x509_certificate(pki["ca"].read_bytes())
    assert a1cert.verify_p7s(p7s, ca_certs=[ca]) == pdf.read_bytes()


def test_p7s_is_cades_bes(cert, pdf, tmp_path):
    """Atributos assinados exigidos pela ICP-Brasil (CAdES-BES)."""
    from asn1crypto import cms

    p7s = a1cert.sign_p7s(cert, pdf, tmp_path / "x.p7s")
    signer = cms.ContentInfo.load(p7s.read_bytes())["content"]["signer_infos"][0]
    attrs = {a["type"].native for a in signer["signed_attrs"]}
    assert {"content_type", "message_digest", "signing_certificate_v2"} <= attrs
    assert signer["digest_algorithm"]["algorithm"].native == "sha256"


def test_tampered_p7s_is_rejected(cert, pdf, tmp_path):
    p7s = a1cert.sign_p7s(cert, pdf, tmp_path / "x.p7s")
    data = bytearray(p7s.read_bytes())
    marker = data.find(b"%PDF-")
    assert marker > 0, "conteúdo do PDF não está no .p7s"
    data[marker] ^= 0x01
    p7s.write_bytes(bytes(data))
    with pytest.raises(a1cert.A1Error):
        a1cert.verify_p7s(p7s, ca_certs=cert.chain)


def test_p7s_detached(cert, pdf, tmp_path):
    p7s = a1cert.sign_p7s(cert, pdf, tmp_path / "d.p7s", attached=False)
    assert a1cert.p7s_content(p7s) is None
    assert a1cert.verify_p7s(p7s, content=pdf, ca_certs=cert.chain) == pdf.read_bytes()


def test_signed_pdf_pades(cert, pdf, tmp_path):
    signed = a1cert.sign_pdf(cert, pdf, tmp_path / "assinado.pdf")
    assert a1cert.verify_pdf(signed, cert.chain) == [(True, True, True)]


# --- Java (PJeOffice) e NSS -----------------------------------------------------------

@pytest.mark.parametrize("variant", ["pfx", "pfx_3des", "pfx_rc2"])
def test_java_reads_pfx(pki, variant):
    """O PJeOffice (Java 21) precisa abrir o .pfx, inclusive nos formatos legados."""
    assert a1cert.java_can_read(a1cert.load_pfx(pki[variant], PASSWORD))


def test_non_ascii_password_is_flagged_for_java(cert, tmp_path):
    """Senha com acento: Python e NSS abrem, mas o Java (PJeOffice) não.

    O a1cert aponta o motivo e export_pfx regrava o .pfx com senha ASCII.
    """
    accented = a1cert.export_pfx(cert, tmp_path / "acento.pfx", "senha-çã")
    reopened = a1cert.load_pfx(accented, "senha-çã")
    assert reopened.cpf == kit.TEST_CPF
    if not a1cert.java_can_read(reopened):
        assert "fora do ASCII" in (a1cert.java_password_problem(reopened) or "")
    fixed = a1cert.load_pfx(a1cert.export_pfx(reopened, tmp_path / "ascii.pfx", "senha-ca"), "senha-ca")
    assert a1cert.java_password_problem(fixed) is None
    assert a1cert.java_can_read(fixed)


def test_nss_import_and_cleanup(cert, tmp_path):
    db = tmp_path / "nssdb"
    nickname = a1cert.install_nss(cert, db)
    assert nickname in a1cert.nss_nicknames(db)
    assert a1cert.nss_has_private_key(db, nickname)
    a1cert.install_nss(cert, db)  # reimportar não duplica
    assert a1cert.nss_nicknames(db).count(nickname) == 1
    a1cert.remove_nss(cert, db)
    assert a1cert.nss_nicknames(db) == []


def test_chrome_policy_written_and_removed(cert, chrome_with_cert, mtls):
    import json

    for d in a1cert.CHROME_POLICY_DIRS:
        policy = json.loads((d / a1cert.CHROME_POLICY_FILE).read_text())
        rule = json.loads(policy["AutoSelectCertificateForUrls"][0])
        assert rule == {"pattern": mtls.origin, "filter": {"ISSUER": {"CN": kit.TEST_CA_CN}}}


# --- browsers apresentam o certificado --------------------------------------------------

def test_mtls_server_rejects_browser_without_certificate(mtls):
    """Controle negativo: sem A1 no NSS, o servidor não entrega a página."""
    assert _subject(lambda: kit.open_chrome(headless=True), mtls.url) == ""


@pytest.mark.parametrize("headless", _modes())
def test_chrome_presents_certificate(cert, chrome_with_cert, mtls, headless):
    _skip_headful_without_display(headless)
    assert _subject(lambda: kit.open_chrome(headless), mtls.url) == cert.subject_cn


@pytest.mark.parametrize("headless", _modes())
def test_seleniumbase_uc_presents_certificate(cert, chrome_with_cert, mtls, headless):
    _skip_headful_without_display(headless)
    assert _subject(lambda: kit.open_seleniumbase(uc=True, headless=headless), mtls.url) == cert.subject_cn


def test_firefox_without_certificate_is_rejected(firefox_profile, mtls):
    assert _subject(lambda: kit.open_firefox(str(firefox_profile), True), mtls.url) == ""


@pytest.mark.parametrize("headless", _modes())
def test_firefox_presents_certificate(cert, firefox_profile, mtls, headless):
    _skip_headful_without_display(headless)
    a1cert.install_firefox(cert, firefox_profile)
    assert "Select Automatically" in (firefox_profile / "user.js").read_text()
    assert _subject(lambda: kit.open_firefox(str(firefox_profile), headless), mtls.url) == cert.subject_cn


# --- verificador de linha de comando ------------------------------------------------------

def test_a1_check_cli_end_to_end(pki, pki_url, tmp_path):
    """/app/a1_check.py com URL + arquivo de senha: tudo ✅ e a senha não aparece."""
    secret = tmp_path / "senha"
    secret.write_text(PASSWORD)
    env = {k: v for k, v in os.environ.items() if not k.startswith("A1_")}
    env.update(A1_PFX_URL=f"{pki_url}/{pki['pfx_rc2'].name}", A1_PFX_PASSWORD_FILE=str(secret),
               A1_WORK_DIR=str(tmp_path / "work"))
    result = subprocess.run(
        [sys.executable, "/app/a1_check.py", "--out", str(tmp_path / "out"), "--browsers", "chrome,firefox"],
        capture_output=True, text=True, timeout=600, env=env,
    )
    output = result.stdout + result.stderr
    print(output)
    assert result.returncode == 0, output
    assert "❌" not in output
    assert PASSWORD not in output
    assert (tmp_path / "out" / "documento.pdf.p7s").is_file()
    assert not list((tmp_path / "work").glob("*.pfx")), "o .pfx baixado não foi apagado"


# --- a1_check com casos comuns de certificados reais -------------------------------------

def _run_check(pfx: Path, password: str, tmp_path: Path, *extra: str):
    secret = tmp_path / "senha"
    secret.write_text(password)
    env = {k: v for k, v in os.environ.items() if not k.startswith("A1_")}
    env.update(A1_PFX_PATH=str(pfx), A1_PFX_PASSWORD_FILE=str(secret), A1_WORK_DIR=str(tmp_path / "work"))
    report = tmp_path / "a1-check.json"
    result = subprocess.run(
        [sys.executable, "/app/a1_check.py", "--out", str(tmp_path / "out"), "--json", str(report), *extra],
        capture_output=True, text=True, timeout=600, env=env,
    )
    output = result.stdout + result.stderr
    print(output)
    assert password not in output, "a senha apareceu na saída"
    import json

    return result.returncode, output, json.loads(report.read_text())


def test_a1_check_pfx_without_chain_passes_with_warning(cert, tmp_path):
    """Muitos .pfx são exportados sem as ACs: deve funcionar, com aviso."""
    import dataclasses

    pfx = a1cert.export_pfx(dataclasses.replace(cert, chain=[]), tmp_path / "sem-cadeia.pfx", "Senha-123")
    rc, output, report = _run_check(pfx, "Senha-123", tmp_path, "--browsers", "chrome")
    assert rc == 0, output
    assert report["ok"] is True and report["avisos"] >= 1
    assert any(s["passo"] == "cadeia" and s["status"] == "aviso" for s in report["passos"])
    assert report["certificado"]["cpf"] == kit.TEST_CPF


def test_a1_check_wrong_password_fails_cleanly(pki, tmp_path):
    rc, output, report = _run_check(pki["pfx"], "senha-errada", tmp_path)
    assert rc == 1
    assert "senha incorreta" in output and "Traceback" not in output
    assert report["ok"] is False


def test_a1_check_flags_non_ascii_password_for_pjeoffice(cert, tmp_path):
    pfx = a1cert.export_pfx(cert, tmp_path / "acento.pfx", "senha-ção")
    rc, output, report = _run_check(pfx, "senha-ção", tmp_path, "--browsers", "chrome")
    java = [s for s in report["passos"] if s["passo"].startswith("Java")]
    if java and java[0]["status"] == "erro":
        assert rc == 1 and "fora do ASCII" in java[0]["detalhe"]
    else:  # um Java futuro que aceite senha não-ASCII
        assert rc == 0, output
