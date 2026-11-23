#!/usr/bin/env python3
"""
a1cert — certificado digital A1 (.pfx/.p12) nos browsers e em assinaturas.

Biblioteca para os scripts de automação (``import a1cert`` a partir de /app).
Faz o mesmo fluxo que costuma ser escrito à mão em cada script:

    cert = a1cert.load_from_env()          # A1_PFX_URL/A1_PFX_PATH + senha
    a1cert.install_chrome(cert, ["https://pje.tjxx.jus.br"])
    a1cert.install_firefox(cert)
    a1cert.sign_p7s(cert, "peticao.pdf")   # -> peticao.pdf.p7s (attached)
    a1cert.sign_pdf(cert, "peticao.pdf", "peticao-assinada.pdf")
    ...
    a1cert.uninstall(cert)                 # remove do NSS e as policies

Variáveis de ambiente:
    A1_PFX_URL            URL do .pfx/.p12
    A1_PFX_PATH           alternativa: arquivo local (volume)
    A1_PFX_PASSWORD       senha
    A1_PFX_PASSWORD_FILE  alternativa mais segura: arquivo com a senha (Docker secret)

A senha nunca é registrada em log nem passada em linha de comando
(pk12util recebe um arquivo temporário com permissão 600).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence, Union

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12

log = logging.getLogger("a1cert")

CHROME_NSS_DB = Path(os.path.expanduser("~")) / ".pki" / "nssdb"
FIREFOX_PROFILE_DIR = Path(os.getenv("FIREFOX_PROFILE_DIR", "/root/.mozilla/firefox/selenium.default-release"))
CHROME_POLICY_DIRS = (
    Path("/etc/opt/chrome/policies/managed"),
    Path("/etc/opt/chrome_for_testing/policies/managed"),
)
CHROME_POLICY_FILE = "auto_select_certificate.json"
WORK_DIR = Path(os.getenv("A1_WORK_DIR", "/tmp/a1"))

# OIDs ICP-Brasil no SubjectAltName (otherName)
OID_PF_DADOS = "2.16.76.1.3.1"   # nascimento(8) + CPF(11) + NIS(11) + RG...
OID_PJ_CNPJ = "2.16.76.1.3.3"    # CNPJ(14)

PathLike = Union[str, Path]


class A1Error(RuntimeError):
    """Erro com mensagem pronta para o usuário (nunca contém a senha)."""


# --- Modelo -------------------------------------------------------------------

@dataclass
class A1Certificate:
    """Certificado A1 carregado. ``password`` não aparece no repr."""

    path: Path
    password: str = field(repr=False)
    certificate: x509.Certificate = field(repr=False)
    private_key: object = field(repr=False)
    chain: list = field(default_factory=list, repr=False)
    pbe: str = ""

    @property
    def subject_cn(self) -> str:
        return _name_attr(self.certificate.subject, x509.NameOID.COMMON_NAME)

    @property
    def issuer_cn(self) -> str:
        return _name_attr(self.certificate.issuer, x509.NameOID.COMMON_NAME)

    @property
    def not_before(self) -> _dt.datetime:
        return self.certificate.not_valid_before_utc

    @property
    def not_after(self) -> _dt.datetime:
        return self.certificate.not_valid_after_utc

    @property
    def days_left(self) -> int:
        return (self.not_after - _dt.datetime.now(_dt.timezone.utc)).days

    @property
    def is_valid_now(self) -> bool:
        now = _dt.datetime.now(_dt.timezone.utc)
        return self.not_before <= now <= self.not_after

    @property
    def fingerprint(self) -> str:
        return self.certificate.fingerprint(hashes.SHA256()).hex()

    @property
    def nickname(self) -> str:
        """Apelido no NSS: estável e sem ':' (o CN ICP-Brasil tem 'NOME:CPF')."""
        return f"rpa-a1-{self.fingerprint[:12]}"

    @property
    def cpf(self) -> Optional[str]:
        value = _icp_other_name(self.certificate, OID_PF_DADOS)
        if value and len(value) >= 19 and value[8:19].isdigit():
            return value[8:19]
        match = re.search(r":(\d{11})$", self.subject_cn)
        return match.group(1) if match else None

    @property
    def cnpj(self) -> Optional[str]:
        value = _icp_other_name(self.certificate, OID_PJ_CNPJ)
        if value and value[:14].isdigit():
            return value[:14]
        return None

    def summary(self) -> dict:
        """Dados para log/relatório (sem segredos)."""
        return {
            "titular": self.subject_cn,
            "cpf": self.cpf,
            "cnpj": self.cnpj,
            "emissor": self.issuer_cn,
            "valido_de": self.not_before.isoformat(),
            "valido_ate": self.not_after.isoformat(),
            "dias_restantes": self.days_left,
            "cadeia": len(self.chain),
            "formato": self.pbe or "desconhecido",
            "sha256": self.fingerprint,
        }


def _name_attr(name: x509.Name, oid) -> str:
    attrs = name.get_attributes_for_oid(oid)
    return str(attrs[0].value) if attrs else name.rfc4514_string()


def _der_unwrap(data: bytes) -> bytes:
    """Remove camadas DER (tag explícita/string) até chegar ao conteúdo."""
    for _ in range(4):
        if len(data) < 2:
            break
        tag, length, offset = data[0], data[1], 2
        if length & 0x80:
            n = length & 0x7F
            length = int.from_bytes(data[2:2 + n], "big")
            offset = 2 + n
        if tag in (0xA0, 0x04, 0x0C, 0x13, 0x16, 0x1A) and offset + length <= len(data):
            data = data[offset:offset + length]
            continue
        break
    return data


def _icp_other_name(cert: x509.Certificate, oid: str) -> Optional[str]:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return None
    for other in san.get_values_for_type(x509.OtherName):
        if other.type_id.dotted_string == oid:
            return _der_unwrap(other.value).decode("latin-1", errors="replace")
    return None


# --- Diagnóstico ----------------------------------------------------------------

def usage_findings(cert: A1Certificate) -> list:
    """Problemas de uso conhecidos: [(nível, assunto, mensagem)], nível 'ok'|'aviso'|'erro'.

    Não substitui a validação jurídica da assinatura; aponta o que costuma quebrar
    login com certificado e assinatura em sistemas judiciais.
    """
    from cryptography.hazmat.primitives.asymmetric import ec, rsa

    found = []
    key = cert.private_key
    if isinstance(key, rsa.RSAPrivateKey):
        level = "ok" if key.key_size >= 2048 else "erro"
        found.append((level, "chave", f"RSA {key.key_size} bits"))
    elif isinstance(key, ec.EllipticCurvePrivateKey):
        found.append(("aviso", "chave", f"EC {key.curve.name}: sistemas e o PJeOffice esperam RSA"))
    else:
        found.append(("aviso", "chave", f"tipo de chave incomum: {type(key).__name__}"))

    if cert.certificate.public_key().public_numbers() != key.public_key().public_numbers():
        found.append(("erro", "chave", "a chave privada não corresponde ao certificado"))

    try:
        ku = cert.certificate.extensions.get_extension_for_class(x509.KeyUsage).value
        if not ku.digital_signature:
            found.append(("erro", "uso da chave", "sem digitalSignature: não serve para login nem assinatura"))
        elif not ku.content_commitment:
            found.append(("aviso", "uso da chave", "sem nonRepudiation: assinaturas ICP-Brasil costumam exigir"))
        else:
            found.append(("ok", "uso da chave", "digitalSignature + nonRepudiation"))
    except x509.ExtensionNotFound:
        found.append(("aviso", "uso da chave", "extensão KeyUsage ausente"))

    try:
        eku = cert.certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        if x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH in eku:
            found.append(("ok", "uso estendido", "clientAuth (login em sites com certificado)"))
        else:
            found.append(("aviso", "uso estendido", "sem clientAuth: o browser pode não oferecê-lo no login"))
    except x509.ExtensionNotFound:
        pass

    if not cert.chain:
        found.append(("aviso", "cadeia", "o .pfx não traz as ACs; exporte com a cadeia completa se um site recusar"))
    else:
        roots = [c for c in cert.chain if c.subject == c.issuer]
        names = ", ".join(_name_attr(c.subject, x509.NameOID.COMMON_NAME) for c in cert.chain)
        if roots:
            found.append(("ok", "cadeia", f"{len(cert.chain)} AC(s) até a raiz: {names}"))
        else:
            found.append(("aviso", "cadeia", f"sem a AC raiz ({names}); ok para a maioria dos sites"))
    orgs = {a.value for c in [cert.certificate, *cert.chain]
            for a in c.issuer.get_attributes_for_oid(x509.NameOID.ORGANIZATION_NAME)}
    if "ICP-Brasil" in orgs:
        found.append(("ok", "ICP-Brasil", "emitido na hierarquia ICP-Brasil"))
    return found


# --- Carregar -----------------------------------------------------------------

def password_from_env() -> str:
    """Lê a senha de A1_PFX_PASSWORD_FILE (preferido) ou A1_PFX_PASSWORD."""
    pw_file = os.getenv("A1_PFX_PASSWORD_FILE")
    if pw_file:
        try:
            return Path(pw_file).read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as exc:
            raise A1Error(f"não foi possível ler A1_PFX_PASSWORD_FILE ({pw_file}): {exc.strerror}") from None
    pw = os.getenv("A1_PFX_PASSWORD")
    if pw is None:
        raise A1Error("defina A1_PFX_PASSWORD ou A1_PFX_PASSWORD_FILE")
    return pw


def fetch_pfx(url: str, dest_dir: PathLike = WORK_DIR, retries: int = 3, timeout: int = 30) -> Path:
    """Baixa o .pfx para ``dest_dir`` (permissão 600). Tenta ``retries`` vezes."""
    import requests

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(dest_dir, 0o700)
    dest = dest_dir / "a1.pfx"
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            if not resp.content:
                raise A1Error("arquivo vazio")
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(resp.content)
            log.info("certificado baixado (%d bytes)", len(resp.content))
            return dest
        except Exception as exc:  # noqa: BLE001 - mensagem vai para o usuário
            last_error = str(exc)
            log.warning("download do certificado falhou (tentativa %d/%d): %s", attempt, retries, last_error)
            if attempt < retries:
                time.sleep(2 * attempt)
    raise A1Error(f"não foi possível baixar A1_PFX_URL: {last_error}")


def _pbe_description(data: bytes, password: str) -> str:
    """Algoritmos de cifra do .pfx, via openssl (informativo)."""
    with tempfile.TemporaryDirectory() as tmp:
        pfx, pw = Path(tmp) / "c.pfx", Path(tmp) / "pw"
        pfx.write_bytes(data)
        _write_secret(pw, password)
        try:
            out = subprocess.run(
                ["openssl", "pkcs12", "-in", str(pfx), "-info", "-noout", "-passin", f"file:{pw}", "-legacy"],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
    found = re.findall(r"(?:Encrypted data|Shrouded Keybag): (\S+)", out.stdout + out.stderr)
    return ", ".join(dict.fromkeys(f.rstrip(",") for f in found))


def load_pfx(path: PathLike, password: str) -> A1Certificate:
    """Abre o .pfx com a senha. Formatos modernos (AES) e legados (3DES/RC2)."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise A1Error(f"não foi possível ler {path}: {exc.strerror}") from None
    try:
        bundle = pkcs12.load_pkcs12(data, password.encode("utf-8"))
    except ValueError:
        raise A1Error("senha incorreta ou arquivo .pfx inválido") from None
    if bundle.key is None or bundle.cert is None:
        raise A1Error("o .pfx não contém chave privada e certificado")
    return A1Certificate(
        path=path,
        password=password,
        certificate=bundle.cert.certificate,
        private_key=bundle.key,
        chain=[c.certificate for c in bundle.additional_certs],
        pbe=_pbe_description(data, password),
    )


def load_from_env(dest_dir: PathLike = WORK_DIR) -> A1Certificate:
    """Carrega de A1_PFX_PATH ou A1_PFX_URL, com a senha das variáveis de ambiente."""
    password = password_from_env()
    if os.getenv("A1_PFX_PATH"):
        return load_pfx(os.environ["A1_PFX_PATH"], password)
    if os.getenv("A1_PFX_URL"):
        return load_pfx(fetch_pfx(os.environ["A1_PFX_URL"], dest_dir), password)
    raise A1Error("defina A1_PFX_URL ou A1_PFX_PATH")


# --- NSS (Chrome e Firefox) ----------------------------------------------------

def _write_secret(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def _run(cmd: Sequence[str], what: str) -> str:
    result = subprocess.run(list(cmd), capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise A1Error(f"{what} falhou: {(result.stderr or result.stdout).strip()[-400:]}")
    return result.stdout


def ensure_nss_db(db_dir: PathLike) -> Path:
    """Cria o banco NSS (sql:) vazio se ainda não existir."""
    db_dir = Path(db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(db_dir, 0o700)
    if not (db_dir / "cert9.db").exists():
        _run(["certutil", "-N", "-d", f"sql:{db_dir}", "--empty-password"], "certutil -N")
    return db_dir


def nss_nicknames(db_dir: PathLike) -> list:
    """Apelidos dos certificados no banco NSS."""
    out = subprocess.run(["certutil", "-L", "-d", f"sql:{db_dir}"], capture_output=True, text=True).stdout
    names = []
    for line in out.splitlines()[4:]:
        match = re.match(r"^(.*?)\s+[a-zA-Z]*,[a-zA-Z]*,[a-zA-Z]*\s*$", line)
        if match:
            names.append(match.group(1).strip())
    return names


def nss_has_private_key(db_dir: PathLike, nickname: str) -> bool:
    out = subprocess.run(
        ["certutil", "-K", "-d", f"sql:{db_dir}", "-f", "/dev/null"], capture_output=True, text=True
    ).stdout
    return any(line.rstrip().endswith(nickname) for line in out.splitlines())


def install_nss(cert: A1Certificate, db_dir: PathLike) -> str:
    """Importa chave + certificado (+ cadeia) no banco NSS. Devolve o apelido."""
    db_dir = ensure_nss_db(db_dir)
    remove_nss(cert, db_dir)
    tmp_pw = secrets.token_urlsafe(24)
    # Reexporta com apelido conhecido e cifra moderna: o NSS recebe sempre o mesmo formato.
    blob = pkcs12.serialize_key_and_certificates(
        name=cert.nickname.encode(),
        key=cert.private_key,
        cert=cert.certificate,
        cas=[pkcs12.PKCS12Certificate(c, f"{cert.nickname}-ca{i}".encode()) for i, c in enumerate(cert.chain)]
        or None,
        encryption_algorithm=serialization.BestAvailableEncryption(tmp_pw.encode()),
    )
    with tempfile.TemporaryDirectory(dir=_tmp_root()) as tmp:
        pfx, pw = Path(tmp) / "c.p12", Path(tmp) / "pw"
        pfx.write_bytes(blob)
        os.chmod(pfx, 0o600)
        _write_secret(pw, tmp_pw)
        _run(["pk12util", "-i", str(pfx), "-d", f"sql:{db_dir}", "-w", str(pw), "-k", "/dev/null"], "pk12util")
    if not nss_has_private_key(db_dir, cert.nickname):
        raise A1Error(f"chave privada não ficou no NSS ({db_dir})")
    log.info("certificado importado no NSS %s como %s", db_dir, cert.nickname)
    return cert.nickname


def remove_nss(cert: A1Certificate, db_dir: PathLike) -> None:
    """Remove chave, certificado e a cadeia importada (silencioso se não existir).

    Certificados da cadeia que já estavam no NSS com outro apelido (ex.: raízes
    ICP-Brasil instaladas pelo seu script) não são tocados.
    """
    if not (Path(db_dir) / "cert9.db").exists():
        return
    ours = {cert.nickname} | {f"{cert.nickname}-ca{i}" for i in range(len(cert.chain))}
    for _ in range(3):
        present = ours.intersection(nss_nicknames(db_dir))
        if not present:
            break
        if cert.nickname in present:
            subprocess.run(["certutil", "-F", "-d", f"sql:{db_dir}", "-n", cert.nickname, "-f", "/dev/null"],
                           capture_output=True)
        for name in present:
            subprocess.run(["certutil", "-D", "-d", f"sql:{db_dir}", "-n", name], capture_output=True)


def _tmp_root() -> str:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(WORK_DIR, 0o700)
    return str(WORK_DIR)


# --- Chrome -------------------------------------------------------------------

def chrome_policy(cert: A1Certificate, url_patterns: Iterable[str] = ("*",)) -> dict:
    """Policy AutoSelectCertificateForUrls filtrando pelo emissor do certificado."""
    issuer = {"CN": cert.issuer_cn}
    rules = [json.dumps({"pattern": p, "filter": {"ISSUER": issuer}}, ensure_ascii=False) for p in url_patterns]
    return {"AutoSelectCertificateForUrls": rules}


def install_chrome(cert: A1Certificate, url_patterns: Iterable[str] = ("*",),
                   db_dir: PathLike = CHROME_NSS_DB, policy_dirs: Sequence[PathLike] = CHROME_POLICY_DIRS) -> list:
    """Importa no NSS do Chrome e grava a policy de seleção automática.

    Os padrões seguem a sintaxe de padrões de URL do Chrome
    (ex.: ``https://pje.tjrn.jus.br`` ou ``[*.]jus.br``). Devolve os arquivos de policy.
    """
    install_nss(cert, db_dir)
    policy = chrome_policy(cert, url_patterns)
    written = []
    for d in map(Path, policy_dirs):
        d.mkdir(parents=True, exist_ok=True)
        target = d / CHROME_POLICY_FILE
        target.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(target)
    log.info("policy do Chrome gravada em %s", ", ".join(map(str, written)))
    return written


def uninstall_chrome(cert: A1Certificate, db_dir: PathLike = CHROME_NSS_DB,
                     policy_dirs: Sequence[PathLike] = CHROME_POLICY_DIRS) -> None:
    remove_nss(cert, db_dir)
    for d in map(Path, policy_dirs):
        (d / CHROME_POLICY_FILE).unlink(missing_ok=True)


# --- Firefox ------------------------------------------------------------------

FIREFOX_PREF = 'user_pref("security.default_personal_cert", "Select Automatically");'


def install_firefox(cert: A1Certificate, profile_dir: PathLike = FIREFOX_PROFILE_DIR) -> str:
    """Importa no NSS do profile do Firefox e liga a seleção automática (user.js)."""
    profile_dir = Path(profile_dir)
    nickname = install_nss(cert, profile_dir)
    user_js = profile_dir / "user.js"
    current = user_js.read_text(encoding="utf-8") if user_js.exists() else ""
    if FIREFOX_PREF not in current:
        user_js.write_text(current + ("\n" if current and not current.endswith("\n") else "") + FIREFOX_PREF + "\n",
                           encoding="utf-8")
    return nickname


def uninstall_firefox(cert: A1Certificate, profile_dir: PathLike = FIREFOX_PROFILE_DIR) -> None:
    remove_nss(cert, profile_dir)


def uninstall(cert: A1Certificate, firefox_profile: PathLike = FIREFOX_PROFILE_DIR) -> None:
    """Remove o certificado do Chrome e do Firefox e apaga o .pfx baixado em WORK_DIR."""
    uninstall_chrome(cert)
    uninstall_firefox(cert, firefox_profile)
    try:
        if cert.path.resolve().is_relative_to(WORK_DIR.resolve()):
            cert.path.unlink(missing_ok=True)
    except OSError:
        pass


# --- Assinatura -----------------------------------------------------------------

def _cms_detached(cert: A1Certificate, data: bytes, hashalgo: str = "sha256") -> bytes:
    """CMS SignedData (CAdES-BES: signing-time, message-digest, signing-certificate-v2)."""
    from endesive import signer

    return signer.sign(data, cert.private_key, cert.certificate, cert.chain, hashalgo, attrs=True)


def sign_bytes_p7s(cert: A1Certificate, data: bytes, attached: bool = True, hashalgo: str = "sha256") -> bytes:
    """Assina ``data`` e devolve o .p7s em DER. ``attached=True`` embute o conteúdo."""
    from asn1crypto import cms

    der = _cms_detached(cert, data, hashalgo)
    if not attached:
        return der
    info = cms.ContentInfo.load(der)
    info["content"]["encap_content_info"] = cms.ContentInfo({"content_type": "data", "content": data})
    return info.dump(force=True)


def sign_p7s(cert: A1Certificate, src: PathLike, dest: Optional[PathLike] = None, attached: bool = True) -> Path:
    """Assina um arquivo (ex.: PDF) e grava ``<arquivo>.p7s``. Padrão: attached."""
    src = Path(src)
    dest = Path(dest) if dest else src.with_name(src.name + ".p7s")
    dest.write_bytes(sign_bytes_p7s(cert, src.read_bytes(), attached=attached))
    return dest


def p7s_content(p7s: PathLike) -> Optional[bytes]:
    """Conteúdo embutido num .p7s attached (None se for detached)."""
    from asn1crypto import cms

    info = cms.ContentInfo.load(Path(p7s).read_bytes())
    content = info["content"]["encap_content_info"]["content"]
    return None if content.native is None else bytes(content.native)


def verify_p7s(p7s: PathLike, content: Optional[PathLike] = None, ca_certs: Sequence[x509.Certificate] = (),
               trust_chain: bool = True) -> bytes:
    """Verifica o .p7s com ``openssl cms -verify`` e devolve o conteúdo assinado.

    Com ``ca_certs`` a cadeia é validada até esses certificados (aceita AC
    intermediária como âncora: ``-partial_chain``); sem eles só a
    assinatura é conferida (``-noverify``). ``content`` é obrigatório para detached.
    """
    p7s = Path(p7s)
    with tempfile.TemporaryDirectory(dir=_tmp_root()) as tmp:
        out = Path(tmp) / "content"
        cmd = ["openssl", "cms", "-verify", "-binary", "-inform", "DER", "-in", str(p7s),
               "-out", str(out), "-purpose", "any", "-partial_chain"]
        if content is not None:
            cmd += ["-content", str(content)]
        if ca_certs and trust_chain:
            ca_file = Path(tmp) / "ca.pem"
            ca_file.write_bytes(b"".join(c.public_bytes(serialization.Encoding.PEM) for c in ca_certs))
            cmd += ["-CAfile", str(ca_file)]
        else:
            cmd += ["-noverify"]
        _run(cmd, "verificação do .p7s (openssl cms)")
        return out.read_bytes()


def sign_pdf(cert: A1Certificate, src: PathLike, dest: PathLike, reason: str = "Assinatura digital",
             location: str = "Brasil", hashalgo: str = "sha256") -> Path:
    """Assina o PDF por dentro (PAdES básico, via endesive)."""
    from endesive.pdf import cms as pdf_cms

    data = Path(src).read_bytes()
    signing_date = _dt.datetime.now(_dt.timezone.utc).strftime("D:%Y%m%d%H%M%S+00'00'")
    dct = {
        "sigflags": 3,
        "contact": cert.subject_cn,
        "location": location,
        "signingdate": signing_date,
        "reason": reason,
    }
    signature = pdf_cms.sign(data, dct, cert.private_key, cert.certificate, cert.chain, hashalgo)
    Path(dest).write_bytes(data + signature)
    return Path(dest)


def verify_pdf(pdf: PathLike, ca_certs: Sequence[x509.Certificate] = ()) -> list:
    """Verifica as assinaturas do PDF. Devolve [(hash_ok, assinatura_ok, cadeia_ok), ...]."""
    import warnings

    from endesive import pdf as endesive_pdf

    pems = [c.public_bytes(serialization.Encoding.PEM) for c in ca_certs]
    with warnings.catch_warnings():
        # o endesive carrega o bundle do certifi, que tem uma raiz com serial negativo
        warnings.simplefilter("ignore")
        return [tuple(r) for r in endesive_pdf.verify(Path(pdf).read_bytes(), pems)]


def export_pfx(cert: A1Certificate, dest: PathLike, password: str, legacy: bool = False) -> Path:
    """Regrava o .pfx com outra senha (ex.: só ASCII, exigência do Java/PJeOffice).

    ``legacy=True`` usa 3DES/SHA1, para programas antigos que não abrem AES.
    """
    if legacy:
        encryption = (
            serialization.PrivateFormat.PKCS12.encryption_builder()
            .kdf_rounds(2048)
            .key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC)
            .hmac_hash(hashes.SHA1())
            .build(password.encode("utf-8"))
        )
    else:
        encryption = serialization.BestAvailableEncryption(password.encode("utf-8"))
    blob = pkcs12.serialize_key_and_certificates(
        cert.nickname.encode(), cert.private_key, cert.certificate, cert.chain or None, encryption
    )
    dest = Path(dest)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(blob)
    return dest


def java_password_problem(cert: A1Certificate) -> Optional[str]:
    """Motivo conhecido para o Java não abrir o .pfx (None se não houver)."""
    if not cert.password.isascii():
        return ("a senha tem caracteres fora do ASCII (acento, ç...) e o Java/PJeOffice não abre "
                ".pfx assim; regrave o arquivo com uma senha sem acentos (a1cert.export_pfx)")
    return None


def java_can_read(cert: A1Certificate) -> bool:
    """O Java (usado pelo PJeOffice) abre o .pfx com a senha?"""
    # O PJeOffice roda no Java que vem com ele (/opt/pjeoffice/jre, Java 8); o do sistema é o reserva
    bundled = Path("/opt/pjeoffice/jre/bin/keytool")
    keytool = str(bundled) if os.access(bundled, os.X_OK) else shutil.which("keytool")
    if not keytool:
        raise A1Error("keytool (Java) não encontrado")
    with tempfile.TemporaryDirectory(dir=_tmp_root()) as tmp:
        pw = Path(tmp) / "pw"
        _write_secret(pw, cert.password)
        result = subprocess.run(
            [keytool, "-list", "-keystore", str(cert.path), "-storetype", "PKCS12", "-storepass:file", str(pw)],
            capture_output=True, text=True, timeout=60,
        )
    return result.returncode == 0 and "PrivateKeyEntry" in result.stdout


def sha256_file(path: PathLike) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
