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


def _levels(findings):
    return {subject: level for level, subject, _ in findings}


def test_usage_findings_for_well_formed_certificate(cert):
    levels = _levels(a1cert.usage_findings(cert))
    assert levels["chave"] == "ok"
    assert levels["uso da chave"] == "ok"
    assert levels["uso estendido"] == "ok"
    assert levels["cadeia"] == "ok"


def test_usage_findings_warns_without_chain(cert):
    import dataclasses

    levels = _levels(a1cert.usage_findings(dataclasses.replace(cert, chain=[])))
    assert levels["cadeia"] == "aviso"


def test_usage_findings_detects_key_mismatch(cert, pki):
    import dataclasses

    other = a1cert.load_pfx(pki["expired"], PASSWORD)  # outra chave
    findings = a1cert.usage_findings(dataclasses.replace(cert, private_key=other.private_key))
    assert ("erro", "chave", "a chave privada não corresponde ao certificado") in findings


# --- ACs da ICP-Brasil empacotadas (image/icp-brasil) ------------------------------------

ICP_DIR = __import__("pathlib").Path(__file__).resolve().parents[2] / "image" / "icp-brasil"

# Fixado aqui de forma independente de scripts/update-icp-brasil.py: trocar uma raiz
# exige mudar os dois lugares (SHA-256 do DER, conferido no repositório do ITI).
ICP_ROOTS = {
    "CAA53FC6091C6951887C976E378F6EF89AA6377C55D97B6475422B71ED7E9B17",  # v5
    "3BDB9B509352F1D3D71C2BF64D9A38A4E6CEBDA27809D77F7AC476CBDE6E314A",  # v6
    "CD5406F61A8D5D08A3797DA044BE669C555C2D8B821D67577F0A2CE3A1A277E1",  # v8
    "CDD1149DCFC137C4C34FA844CF592CFBFEA05CB13B770AD5E1F0C7FC8C9C43BF",  # v9
    "6E0BFF069A26994C15DE2C4888CC54AF84882E5495B7FBF66BE9CCFFEC7489F6",  # v10
    "1406710058180FA4081AAB3F246F1702429C552A11FA3143B84C88CB3AB8E5E7",  # v11
    "D8478E37CE19C690CF657381E68FE600E4E1A042536830F06847E03E554C4B01",  # v12
    "2B07D0BC02C4A6E0478ED22D0D99E8F97E1827B269097696A7FEB6AAD30C3AC8",  # v13
}


def test_icp_brasil_roots_are_the_pinned_ones():
    from cryptography.hazmat.primitives import hashes

    roots = a1cert.icp_brasil_certs(roots_only=True, icp_dir=ICP_DIR)
    assert {r.fingerprint(hashes.SHA256()).hex().upper() for r in roots} == ICP_ROOTS
    for root in roots:
        assert root.subject == root.issuer
        assert "Autoridade Certificadora Raiz Brasileira" in root.subject.rfc4514_string()


def test_icp_brasil_intermediates_chain_to_pinned_roots(tmp_path, monkeypatch):
    """Toda AC empacotada fecha cadeia até uma raiz fixada (nenhuma AC 'solta')."""
    import types

    monkeypatch.setattr(a1cert, "WORK_DIR", tmp_path)
    roots = a1cert.icp_brasil_certs(roots_only=True, icp_dir=ICP_DIR)
    cas = a1cert.icp_brasil_certs(icp_dir=ICP_DIR)[len(roots):]
    assert len(cas) > 100
    for ca in cas:
        assert ca.subject != ca.issuer
        root = a1cert.verify_chain(types.SimpleNamespace(certificate=ca, chain=[]), icp_dir=ICP_DIR)
        assert root.startswith("Autoridade Certificadora Raiz Brasileira v"), ca.subject


def test_verify_chain_with_test_pki(pki, cert, tmp_path, monkeypatch):
    import dataclasses

    monkeypatch.setattr(a1cert, "WORK_DIR", tmp_path / "work")
    anchors = tmp_path / "icp"
    anchors.mkdir()
    (anchors / "raizes.pem").write_bytes(__import__("pathlib").Path(pki["ca"]).read_bytes())
    assert a1cert.verify_chain(cert, icp_dir=anchors) == kit.TEST_CA_CN
    # um .pfx de verdade não está na ICP-Brasil de teste, nem a ICP de teste na real
    with pytest.raises(a1cert.A1Error, match="unable to get local issuer"):
        a1cert.verify_chain(dataclasses.replace(cert, chain=[]), icp_dir=ICP_DIR)


def test_usage_findings_flags_fake_icp_brasil(tmp_path, monkeypatch):
    """Certificado que diz ser ICP-Brasil mas não fecha cadeia com as raízes do ITI: erro."""
    monkeypatch.setattr(a1cert, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(a1cert, "ICP_BRASIL_DIR", ICP_DIR)
    import dataclasses

    fake = a1cert.load_pfx(kit.make_test_pki(tmp_path / "pki", PASSWORD, organization="ICP-Brasil")["pfx"], PASSWORD)
    # .pfx com a cadeia: a raiz dele não é uma raiz do ITI -> erro
    level, message = next((lv, msg) for lv, subj, msg in a1cert.usage_findings(fake) if subj == "ICP-Brasil")
    assert level == "erro" and "self-signed" in message
    # .pfx sem a cadeia: AC desconhecida (pode ser AC nova, posterior ao pacote) -> aviso
    findings = a1cert.usage_findings(dataclasses.replace(fake, chain=[]))
    level, message = next((lv, msg) for lv, subj, msg in findings if subj == "ICP-Brasil")
    assert level == "aviso" and "AC emissora não está entre as ACs oficiais" in message


def test_usage_findings_icp_brasil_expired_chain_is_error(tmp_path, monkeypatch):
    """Cadeia conhecida mas inválida (aqui: certificado vencido) é erro, não aviso."""
    monkeypatch.setattr(a1cert, "WORK_DIR", tmp_path / "work")
    pki = kit.make_test_pki(tmp_path / "pki", PASSWORD, organization="ICP-Brasil")
    anchors = tmp_path / "icp"
    anchors.mkdir()
    (anchors / "raizes.pem").write_bytes(__import__("pathlib").Path(pki["ca"]).read_bytes())
    monkeypatch.setattr(a1cert, "ICP_BRASIL_DIR", anchors)
    findings = a1cert.usage_findings(a1cert.load_pfx(pki["expired"], PASSWORD))
    level, message = next((lv, msg) for lv, subj, msg in findings if subj == "ICP-Brasil")
    assert level == "erro" and "expired" in message


def test_usage_findings_icp_brasil_ok_with_its_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr(a1cert, "WORK_DIR", tmp_path / "work")
    pki = kit.make_test_pki(tmp_path / "pki", PASSWORD, organization="ICP-Brasil")
    anchors = tmp_path / "icp"
    anchors.mkdir()
    (anchors / "raizes.pem").write_bytes(__import__("pathlib").Path(pki["ca"]).read_bytes())
    monkeypatch.setattr(a1cert, "ICP_BRASIL_DIR", anchors)
    findings = a1cert.usage_findings(a1cert.load_pfx(pki["pfx"], PASSWORD))
    assert ("ok", "ICP-Brasil", f"cadeia válida até a {kit.TEST_CA_CN} (raízes do ITI)") in findings
