#!/usr/bin/env python3
"""Remove a assinatura `cdc_` do binário do ChromeDriver.

O ChromeDriver injeta variáveis globais com o prefixo `cdc_<22 chars>` na
página (cdc_..._Array, cdc_..._Promise, cdc_..._Symbol, ...). Esse prefixo é
constante entre builds oficiais e por isso é um sinal trivial de detecção via
JavaScript.

O binário contém a MESMA string de prefixo repetida N vezes (tipicamente entre
15 e 20, dependendo da versão). TODAS precisam ser substituídas pelo MESMO
token: o driver escreve e depois lê essas variáveis pelo nome, de modo que
tokens divergentes quebrariam a injeção.

O token substituto tem exatamente o mesmo tamanho do original, o que mantém
todos os offsets do binário intactos — nenhuma seção ELF precisa ser
recalculada.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
import string
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


CHROMEDRIVER = Path(os.environ.get("CHROMEDRIVER_PATH", "/usr/local/bin/chromedriver"))

# `cdc_` + 22 caracteres alfanuméricos = 26 bytes.
# Classe restrita em vez de `.` para evitar casar lixo binário adjacente.
PATTERN = re.compile(rb"cdc_[a-zA-Z0-9]{22}")
TOKEN_LENGTH = 26

# Limites de sanidade. Fora dessa faixa, o binário provavelmente não é o que
# esperamos e é mais seguro abortar do que gravar algo imprevisível.
MIN_EXPECTED_MATCHES = 1
MAX_EXPECTED_MATCHES = 64

SMOKE_TEST_PORT = int(os.environ.get("CHROMEDRIVER_SMOKE_PORT", "9515"))


def generate_token() -> bytes:
    """Gera um identificador JavaScript válido de 26 bytes.

    Um token aleatório por build é preferível a uma constante: strings fixas
    que circulam em gists públicos podem, elas próprias, virar assinatura.

    Pode ser fixado via CHROMEDRIVER_PATCH_TOKEN para builds reproduzíveis.
    """
    override = os.environ.get("CHROMEDRIVER_PATCH_TOKEN")

    if override is not None:
        token = override.encode("ascii")

        if len(token) != TOKEN_LENGTH:
            raise ValueError(
                f"CHROMEDRIVER_PATCH_TOKEN deve ter {TOKEN_LENGTH} bytes, "
                f"mas tem {len(token)}"
            )

        if not re.fullmatch(rb"[a-zA-Z_][a-zA-Z0-9_]*", token):
            raise ValueError(
                "CHROMEDRIVER_PATCH_TOKEN não é um identificador JS válido"
            )

        if PATTERN.search(token):
            raise ValueError("CHROMEDRIVER_PATCH_TOKEN ainda contém a assinatura cdc_")

        return token

    # Primeiro caractere deve ser letra: identificador JS não inicia com dígito.
    first = secrets.choice(string.ascii_lowercase)
    rest = "".join(
        secrets.choice(string.ascii_letters + string.digits)
        for _ in range(TOKEN_LENGTH - 1)
    )
    return (first + rest).encode("ascii")


def patch_chromedriver(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"ChromeDriver não encontrado: {path}")

    original_stat = path.stat()
    original_data = path.read_bytes()

    matches = PATTERN.findall(original_data)

    if not matches:
        raise RuntimeError(
            "Assinatura cdc_ não encontrada. O ChromeDriver pode já ter sido "
            "alterado ou usar outro formato."
        )

    if not (MIN_EXPECTED_MATCHES <= len(matches) <= MAX_EXPECTED_MATCHES):
        raise RuntimeError(
            f"Número de ocorrências fora do esperado: {len(matches)} "
            f"(faixa aceita: {MIN_EXPECTED_MATCHES}-{MAX_EXPECTED_MATCHES}). "
            f"Binário inesperado; operação cancelada."
        )

    # Verificação crítica: o binário deve conter uma única string distinta,
    # repetida. Prefixos divergentes indicariam um layout que este script não
    # sabe tratar com segurança.
    distinct = set(matches)

    if len(distinct) != 1:
        raise RuntimeError(
            f"Esperado um único prefixo cdc_ repetido, encontrados "
            f"{len(distinct)} distintos: "
            f"{sorted(s.decode('ascii', 'replace') for s in distinct)}"
        )

    signature = distinct.pop()
    token = generate_token()

    if len(token) != len(signature):
        raise RuntimeError(
            f"Token ({len(token)} bytes) e assinatura ({len(signature)} bytes) "
            f"têm tamanhos diferentes."
        )

    print(f"Assinatura encontrada: {signature.decode('ascii')}")
    print(f"Ocorrências a substituir: {len(matches)}")

    # count=0 substitui todas as ocorrências.
    patched_data, replacements = PATTERN.subn(token, original_data)

    if replacements != len(matches):
        raise RuntimeError(
            f"Substituições ({replacements}) divergem das ocorrências "
            f"detectadas ({len(matches)})."
        )

    if len(patched_data) != len(original_data):
        raise RuntimeError("O patch alterou o tamanho do binário. Cancelado.")

    if PATTERN.search(patched_data):
        raise RuntimeError("A assinatura cdc_ ainda está presente após o patch.")

    if patched_data.count(token) != replacements:
        raise RuntimeError(
            f"Token substituto aparece {patched_data.count(token)} vezes; "
            f"esperado {replacements}."
        )

    _write_atomically(path, patched_data, original_stat)

    print(f"ChromeDriver alterado: {path}")
    print(f"Token aplicado: {token.decode('ascii')}")


def _write_atomically(path: Path, data: bytes, original_stat: os.stat_result) -> None:
    """Grava via arquivo temporário no mesmo diretório e faz rename atômico.

    Se qualquer verificação falhar, o binário original permanece intacto.
    """
    fd, temporary_name = tempfile.mkstemp(
        prefix=".chromedriver-patch-",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(fd, "wb") as temporary_file:
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.chmod(temporary_path, stat.S_IMODE(original_stat.st_mode))

        if temporary_path.stat().st_size != original_stat.st_size:
            raise RuntimeError("Arquivo temporário com tamanho diferente do original.")

        # Executa o binário alterado ANTES de sobrescrever o oficial.
        version_result = subprocess.run(
            [str(temporary_path), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if version_result.returncode != 0:
            raise RuntimeError(
                "O ChromeDriver alterado não executou corretamente.\n"
                f"stdout: {version_result.stdout}\n"
                f"stderr: {version_result.stderr}"
            )

        print(version_result.stdout.strip())

        os.replace(temporary_path, path)

        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    finally:
        temporary_path.unlink(missing_ok=True)


def smoke_test_chromedriver(path: Path) -> None:
    """Sobe o driver e confirma que o endpoint /status responde ready."""
    process = subprocess.Popen(
        [
            str(path),
            f"--port={SMOKE_TEST_PORT}",
            "--allowed-ips=127.0.0.1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        deadline = time.monotonic() + 10
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=2)
                raise RuntimeError(
                    "ChromeDriver encerrou durante o smoke test.\n"
                    f"Exit code: {process.returncode}\n"
                    f"stdout: {stdout}\n"
                    f"stderr: {stderr}"
                )

            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{SMOKE_TEST_PORT}/status",
                    timeout=1,
                ) as response:
                    body = response.read().decode("utf-8")

                if response.status != 200:
                    raise RuntimeError(
                        f"Endpoint /status retornou HTTP {response.status}"
                    )

                if '"ready":true' not in body.replace(" ", ""):
                    raise RuntimeError(f"Resposta inesperada: {body}")

                print("Smoke test concluído: endpoint /status respondeu ready.")
                return

            except Exception as exc:  # noqa: BLE001 - retry até o deadline
                last_error = exc
                time.sleep(0.25)

        raise RuntimeError(f"ChromeDriver não respondeu em 10 segundos: {last_error}")

    finally:
        process.terminate()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def main() -> int:
    try:
        patch_chromedriver(CHROMEDRIVER)
        smoke_test_chromedriver(CHROMEDRIVER)
    except Exception as exc:  # noqa: BLE001 - fronteira do processo
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
