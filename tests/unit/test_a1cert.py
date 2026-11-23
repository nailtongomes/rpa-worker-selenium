"""
Testes rápidos (host) da biblioteca de certificado A1 (image/app/a1cert.py).

O caminho completo (openssl, NSS, Java e browsers) é testado dentro da imagem
em tests/image/test_a1_certificate.py.
"""

import json

import pytest

pytest.importorskip("cryptography")

import a1_testkit as kit  # noqa: E402
import a1cert  # noqa: E402

PASSWORD = "senha-de-teste"


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    return kit.make_test_pki(tmp_path_factory.mktemp("pki"), PASSWORD)


@pytest.fixture(scope="module")
def cert(pki):
    return a1cert.load_pfx(pki["pfx"], PASSWORD)


def test_icp_brasil_fields(cert):
    assert cert.subject_cn == f"{kit.TEST_HOLDER}:{kit.TEST_CPF}"
    assert cert.cpf == kit.TEST_CPF
    assert cert.cnpj is None
    assert cert.issuer_cn == kit.TEST_CA_CN
    assert len(cert.chain) == 1
    assert cert.is_valid_now


def test_nickname_is_nss_safe_and_stable(cert, pki):
    assert ":" not in cert.nickname  # ':' separa token:apelido no NSS
    assert cert.nickname == a1cert.load_pfx(pki["pfx_3des"], PASSWORD).nickname


def test_password_never_in_repr_or_summary(cert):
    assert PASSWORD not in repr(cert)
    assert PASSWORD not in json.dumps(cert.summary())


def test_wrong_password(pki):
    with pytest.raises(a1cert.A1Error, match="senha incorreta"):
        a1cert.load_pfx(pki["wrong_password"], PASSWORD)


def test_missing_file(tmp_path):
    with pytest.raises(a1cert.A1Error, match="não foi possível ler"):
        a1cert.load_pfx(tmp_path / "nao-existe.pfx", PASSWORD)


def test_expired(pki):
    expired = a1cert.load_pfx(pki["expired"], PASSWORD)
    assert not expired.is_valid_now and expired.days_left < 0


def test_password_file_has_priority(tmp_path, monkeypatch):
    secret = tmp_path / "senha"
    secret.write_text("do-arquivo\n")
    monkeypatch.setenv("A1_PFX_PASSWORD", "da-variavel")
    monkeypatch.setenv("A1_PFX_PASSWORD_FILE", str(secret))
    assert a1cert.password_from_env() == "do-arquivo"
    monkeypatch.delenv("A1_PFX_PASSWORD_FILE")
    assert a1cert.password_from_env() == "da-variavel"


def test_password_required(monkeypatch):
    monkeypatch.delenv("A1_PFX_PASSWORD", raising=False)
    monkeypatch.delenv("A1_PFX_PASSWORD_FILE", raising=False)
    with pytest.raises(a1cert.A1Error, match="A1_PFX_PASSWORD"):
        a1cert.password_from_env()


def test_load_from_env_requires_source(monkeypatch):
    monkeypatch.setenv("A1_PFX_PASSWORD", PASSWORD)
    monkeypatch.delenv("A1_PFX_URL", raising=False)
    monkeypatch.delenv("A1_PFX_PATH", raising=False)
    with pytest.raises(a1cert.A1Error, match="A1_PFX_URL"):
        a1cert.load_from_env()


def test_load_from_env_path(pki, monkeypatch):
    monkeypatch.setenv("A1_PFX_PASSWORD", PASSWORD)
    monkeypatch.setenv("A1_PFX_PATH", str(pki["pfx"]))
    monkeypatch.delenv("A1_PFX_PASSWORD_FILE", raising=False)
    assert a1cert.load_from_env().cpf == kit.TEST_CPF


def test_chrome_policy_filters_by_issuer(cert):
    policy = a1cert.chrome_policy(cert, ["https://pje.tjrn.jus.br", "[*.]jus.br"])
    rules = [json.loads(r) for r in policy["AutoSelectCertificateForUrls"]]
    assert [r["pattern"] for r in rules] == ["https://pje.tjrn.jus.br", "[*.]jus.br"]
    assert all(r["filter"] == {"ISSUER": {"CN": kit.TEST_CA_CN}} for r in rules)


def test_install_chrome_writes_policy_files(cert, tmp_path, monkeypatch):
    monkeypatch.setattr(a1cert, "install_nss", lambda c, d: c.nickname)
    dirs = [tmp_path / "chrome", tmp_path / "chrome_for_testing"]
    written = a1cert.install_chrome(cert, ["https://exemplo.jus.br"], policy_dirs=dirs)
    assert written == [d / a1cert.CHROME_POLICY_FILE for d in dirs]
    assert all("AutoSelectCertificateForUrls" in json.loads(p.read_text()) for p in written)


def test_p7s_attached_roundtrip_in_python(cert):
    pytest.importorskip("endesive")  # na imagem; no host é opcional
    p7s = a1cert.sign_bytes_p7s(cert, b"conteudo")
    from asn1crypto import cms

    info = cms.ContentInfo.load(p7s)
    assert info["content"]["encap_content_info"]["content"].native == b"conteudo"


def test_export_pfx_with_new_password(cert, tmp_path):
    exported = a1cert.export_pfx(cert, tmp_path / "nova.pfx", "nova-senha", legacy=True)
    assert oct(exported.stat().st_mode & 0o777) == "0o600"
    assert a1cert.load_pfx(exported, "nova-senha").fingerprint == cert.fingerprint


def test_java_password_problem_flags_non_ascii(cert, tmp_path):
    assert a1cert.java_password_problem(cert) is None
    accented = a1cert.load_pfx(a1cert.export_pfx(cert, tmp_path / "a.pfx", "senha-ç"), "senha-ç")
    assert "ASCII" in a1cert.java_password_problem(accented)


@pytest.mark.parametrize(
    "raw, expected",
    [
        (b"\x04\x05hello", b"hello"),
        (b"\xa0\x07\x04\x05hello", b"hello"),
        (b"\x13\x03abc", b"abc"),
        (b"\x02\x01\x05", b"\x02\x01\x05"),  # INTEGER: não é desembrulhado
    ],
)
def test_der_unwrap(raw, expected):
    assert a1cert._der_unwrap(raw) == expected
