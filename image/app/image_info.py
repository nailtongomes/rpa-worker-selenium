#!/usr/bin/env python3
"""
image_info — qual imagem está rodando neste worker (revisão, data do build, arquitetura,
versões dos browsers), sem `docker inspect` no host.

O build grava /app/image_info.json (`image_info.py write`, última camada do Dockerfile.trixie);
o entrypoint mostra a linha na primeira mensagem do log e o preflight inclui o JSON.

    python /app/image_info.py          # 🏷️  Imagem sha-4eda8ad (arm64) · build 20261124-153000 · Chrome ... · Firefox ...
    python /app/image_info.py --json   # o mesmo em JSON
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import subprocess
import sys
from pathlib import Path

INFO_FILE = Path(__file__).resolve().parent / "image_info.json"
REGISTRY = "ghcr.io/nailtongomes/rpa-worker-selenium"
DOCKER_ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}


def docker_arch(machine: str = "") -> str:
    machine = machine or platform.machine()
    return DOCKER_ARCH.get(machine.lower(), machine.lower() or "desconhecida")


def _version(cmd: list) -> str:
    """Só o número: "Google Chrome for Testing 158.0.8127.36" -> "158.0.8127.36"."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""
    words = out.splitlines()[0].split() if out else []
    return next((w for w in words if w[:1].isdigit()), "")


def _package(name: str) -> str:
    try:
        from importlib import metadata

        return metadata.version(name)
    except Exception:  # noqa: BLE001 - fora da imagem o pacote pode não existir
        return ""


def tag_for(revision: str, arch: str) -> str:
    """Tag publicada pelo release para esta revisão (sha-<7>, com -arm64 no ARM)."""
    if not revision or revision == "dev":
        return "dev"
    return f"sha-{revision[:7]}" + ("-arm64" if arch == "arm64" else "")


def collect(revision: str = "dev", created: str = "") -> dict:
    arch = docker_arch()
    return {
        "revisao": revision or "dev",
        "tag": tag_for(revision, arch),
        "criada_em": created or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S"),
        "arquitetura": arch,
        "chrome": _version(["chrome", "--version"]),
        "chromedriver": _version(["chromedriver", "--version"]),
        "firefox": _version(["firefox", "--version"]),
        "geckodriver": _version(["geckodriver", "--version"]),
        "selenium": _package("selenium"),
        "seleniumbase": _package("seleniumbase"),
        "python": platform.python_version(),
    }


def load(path: Path = INFO_FILE) -> dict:
    """O que o build gravou; fora da imagem (ou build antigo), o que dá para saber agora."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"revisao": "desconhecida", "tag": "desconhecida", "criada_em": "",
                "python": platform.python_version()}
    data.setdefault("arquitetura", docker_arch())
    data["imagem"] = f"{REGISTRY}:{data.get('tag') or 'desconhecida'}"
    return data


def summary_line(info: dict) -> str:
    parts = [f"Imagem {info.get('tag') or 'desconhecida'} ({info.get('arquitetura', '?')})"]
    if info.get("criada_em"):
        parts.append(f"build {info['criada_em']}")
    for key, name in (("chrome", "Chrome"), ("firefox", "Firefox"), ("seleniumbase", "SeleniumBase")):
        if info.get(key):
            parts.append(f"{name} {info[key]}")
    return " · ".join(parts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd")
    write = sub.add_parser("write", help="usado no build: grava image_info.json")
    write.add_argument("--revision", default="dev")
    write.add_argument("--created", default="")
    write.add_argument("--out", default=str(INFO_FILE))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "write":
        info = collect(args.revision, args.created)
        Path(args.out).write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(summary_line(info))
        return 0
    info = load()
    print(json.dumps(info, ensure_ascii=False, indent=2) if args.json else f"🏷️  {summary_line(info)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
