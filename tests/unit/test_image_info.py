"""Testes rápidos (host) do image/app/image_info.py. O arquivo gravado no build é conferido
na imagem (tests/image/test_contract.py)."""

import json

import pytest

import image_info


@pytest.mark.parametrize("revision, arch, tag", [
    ("4eda8ad0123456789", "amd64", "sha-4eda8ad"),
    ("4eda8ad0123456789", "arm64", "sha-4eda8ad-arm64"),
    ("dev", "amd64", "dev"),
    ("", "arm64", "dev"),
])
def test_tag_matches_release_tags(revision, arch, tag):
    assert image_info.tag_for(revision, arch) == tag


@pytest.mark.parametrize("machine, arch", [("x86_64", "amd64"), ("aarch64", "arm64"), ("riscv64", "riscv64")])
def test_docker_arch(machine, arch):
    assert image_info.docker_arch(machine) == arch


def test_write_and_load(tmp_path):
    out = tmp_path / "image_info.json"
    assert image_info.main(["write", "--revision", "abcdef1234567", "--created", "20261124-120000",
                            "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["revisao"] == "abcdef1234567" and data["criada_em"] == "20261124-120000"
    assert data["tag"].startswith("sha-abcdef1")
    loaded = image_info.load(out)
    assert loaded["imagem"] == f"{image_info.REGISTRY}:{data['tag']}"
    assert "selenium" in data and "seleniumbase" in data
    line = image_info.summary_line({**loaded, "chrome": "158.0.1", "firefox": "153.7.0esr",
                                    "seleniumbase": "4.59.0"})
    assert line.startswith(f"Imagem {data['tag']} (") and "build 20261124-120000" in line
    assert "Chrome 158.0.1" in line and "Firefox 153.7.0esr" in line and line.endswith("SeleniumBase 4.59.0")


def test_load_without_file(tmp_path):
    data = image_info.load(tmp_path / "nao-existe.json")
    assert data["tag"] == "desconhecida" and data["arquitetura"]
    assert image_info.summary_line(data).startswith("Imagem desconhecida (")
