#!/usr/bin/env python3
"""
Atualiza (ou confere) as ACs da ICP-Brasil empacotadas na imagem (image/icp-brasil/).

Fonte oficial: repositório do ITI (https://acraiz.icpbrasil.gov.br/).

    scripts/update-icp-brasil.py           # baixa, valida e regrava image/icp-brasil/
    scripts/update-icp-brasil.py --check   # só compara com o ITI (exit 1 se mudou)

Validações, nesta ordem (qualquer falha aborta sem gravar nada):
  1. ACcompactado.zip confere com o SHA-512 publicado pelo ITI (hashsha512.txt);
  2. cada raiz baixada tem o fingerprint SHA-256 fixado em PINNED_ROOTS abaixo
     (uma raiz nova exige conferir o fingerprint no site do ITI e acrescentá-lo aqui);
  3. cada AC do zip fecha cadeia até uma dessas raízes (``openssl verify``);
     AC vencida ou que não fecha cadeia fica de fora.

Só usa a biblioteca padrão e o ``openssl`` da linha de comando.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://acraiz.icpbrasil.gov.br/credenciadas"
ZIP_URL = f"{BASE}/CertificadosAC-ICP-Brasil/ACcompactado.zip"
ZIP_SHA512_URL = f"{BASE}/CertificadosAC-ICP-Brasil/hashsha512.txt"
ROOT_URL = BASE + "/RAIZ/ICP-Brasilv{v}.crt"

# AC Raiz Brasileira vN -> SHA-256 do certificado (DER).
# Fora: v1 e v2 (vencidas) e v7 (algoritmo pós-quântico experimental que o OpenSSL não lê).
PINNED_ROOTS = {
    5: "CAA53FC6091C6951887C976E378F6EF89AA6377C55D97B6475422B71ED7E9B17",
    6: "3BDB9B509352F1D3D71C2BF64D9A38A4E6CEBDA27809D77F7AC476CBDE6E314A",
    8: "CD5406F61A8D5D08A3797DA044BE669C555C2D8B821D67577F0A2CE3A1A277E1",
    9: "CDD1149DCFC137C4C34FA844CF592CFBFEA05CB13B770AD5E1F0C7FC8C9C43BF",
    10: "6E0BFF069A26994C15DE2C4888CC54AF84882E5495B7FBF66BE9CCFFEC7489F6",
    11: "1406710058180FA4081AAB3F246F1702429C552A11FA3143B84C88CB3AB8E5E7",
    12: "D8478E37CE19C690CF657381E68FE600E4E1A042536830F06847E03E554C4B01",
    13: "2B07D0BC02C4A6E0478ED22D0D99E8F97E1827B269097696A7FEB6AAD30C3AC8",
}

OUT_DIR = Path(__file__).resolve().parent.parent / "image" / "icp-brasil"
PEM_RE = re.compile(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", re.S)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "rpa-worker-selenium/update-icp-brasil"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - URL fixa do ITI
        return resp.read()


def to_der(data: bytes) -> bytes:
    """Aceita PEM ou DER (o ITI publica os dois) e devolve DER."""
    if b"-----BEGIN CERTIFICATE-----" in data:
        out = subprocess.run(["openssl", "x509", "-outform", "DER"], input=data, capture_output=True, check=True)
        return out.stdout
    return data


def der_to_pem(der: bytes) -> bytes:
    return subprocess.run(["openssl", "x509", "-inform", "DER"], input=der, capture_output=True, check=True).stdout


def openssl_field(pem: bytes, *args: str) -> str:
    out = subprocess.run(["openssl", "x509", "-noout", "-nameopt", "RFC2253", *args],
                         input=pem, capture_output=True, check=True, text=False)
    return out.stdout.decode().strip().split("=", 1)[-1]


def build(workdir: Path) -> dict:
    # 1) zip com todas as ACs, conferido com o SHA-512 publicado
    data = fetch(ZIP_URL)
    published = fetch(ZIP_SHA512_URL).decode().split()[0].lower()
    got = hashlib.sha512(data).hexdigest()
    if got != published:
        raise SystemExit(f"ACcompactado.zip: SHA-512 {got} difere do publicado pelo ITI ({published})")

    # 2) raízes com fingerprint fixado
    roots = {}
    for v, pin in PINNED_ROOTS.items():
        der = to_der(fetch(ROOT_URL.format(v=v)))
        fp = hashlib.sha256(der).hexdigest().upper()
        if fp != pin:
            raise SystemExit(f"raiz v{v}: fingerprint {fp} difere do fixado ({pin})")
        roots[v] = der_to_pem(der)
    roots_file = workdir / "raizes.pem"
    roots_file.write_bytes(b"".join(roots[v] for v in sorted(roots)))

    # 3) ACs do zip que fecham cadeia até as raízes
    candidates = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in sorted(zf.namelist()):
            for block in PEM_RE.findall(zf.read(name)) or [der_to_pem(zf.read(name))]:
                der = to_der(block)
                candidates.setdefault(hashlib.sha256(der).hexdigest(), (name, der_to_pem(der)))
    pinned = {p.lower() for p in PINNED_ROOTS.values()}
    untrusted = workdir / "todas.pem"
    untrusted.write_bytes(b"".join(pem for _, pem in candidates.values()))
    kept, skipped = [], []
    for fp, (name, pem) in sorted(candidates.items(), key=lambda kv: kv[1][0].lower()):
        if fp in pinned:
            continue  # raiz já incluída
        if openssl_field(pem, "-subject") == openssl_field(pem, "-issuer"):
            skipped.append(f"{name}: raiz não fixada")
            continue
        leaf = workdir / "ac.pem"
        leaf.write_bytes(pem)
        res = subprocess.run(["openssl", "verify", "-CAfile", str(roots_file), "-untrusted", str(untrusted),
                              "-purpose", "any", str(leaf)], capture_output=True, text=True)
        if res.returncode != 0:
            skipped.append(f"{name}: {res.stdout.strip().splitlines()[-1:] or res.stderr.strip()}")
            continue
        kept.append((name, pem))

    def label(pem: bytes) -> bytes:
        return f"# {openssl_field(pem, '-subject')}\n".encode()

    return {
        "raizes.pem": b"".join(label(roots[v]) + roots[v] for v in sorted(roots)),
        "acs.pem": b"".join(label(pem) + pem for _, pem in kept),
        "skipped": skipped,
        "zip_sha512": got,
        "count": len(kept),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="só compara com o ITI; exit 1 se mudou")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        result = build(Path(tmp))

    for line in result["skipped"]:
        print(f"ignorada: {line}")
    changed = [n for n in ("raizes.pem", "acs.pem")
               if not (args.out / n).exists() or (args.out / n).read_bytes() != result[n]]
    if args.check:
        if changed:
            print(f"ICP-Brasil mudou no ITI ({', '.join(changed)}): rode scripts/update-icp-brasil.py")
            return 1
        print(f"ICP-Brasil em dia: {len(PINNED_ROOTS)} raízes, {result['count']} ACs")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    for name in ("raizes.pem", "acs.pem"):
        (args.out / name).write_bytes(result[name])
    (args.out / "manifest.json").write_text(json.dumps({
        "fonte": BASE,
        "atualizado_em": dt.date.today().isoformat(),
        "acs_zip_sha512": result["zip_sha512"],
        "raizes": {f"v{v}": fp for v, fp in sorted(PINNED_ROOTS.items())},
        "acs": result["count"],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"gravado em {args.out}: {len(PINNED_ROOTS)} raízes, {result['count']} ACs"
          + (f" (mudou: {', '.join(changed)})" if changed else " (sem mudanças)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
