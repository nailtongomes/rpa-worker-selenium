#!/usr/bin/env python3

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


CHROMEDRIVER = Path("/usr/local/bin/chromedriver")

PATTERN = re.compile(rb"cdc_.{22}")
REPLACEMENT = b"akl_roepstdlwoeproslP0wngs"


def patch_chromedriver(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"ChromeDriver não encontrado: {path}")

    if len(REPLACEMENT) != 26:
        raise ValueError(
            f"Replacement deve possuir 26 bytes, mas possui "
            f"{len(REPLACEMENT)}"
        )

    original_stat = path.stat()
    original_data = path.read_bytes()

    matches = list(PATTERN.finditer(original_data))

    if not matches:
        raise RuntimeError(
            "Assinatura cdc_ não encontrada. "
            "O ChromeDriver pode já estar alterado ou ter outro formato."
        )

    # Conservador: evita alterar um binário com estrutura inesperada.
    if len(matches) != 1:
        raise RuntimeError(
            f"Esperada exatamente uma ocorrência de cdc_; "
            f"encontradas: {len(matches)}"
        )

    patched_data, replacements = PATTERN.subn(
        REPLACEMENT,
        original_data,
        count=1,
    )

    if replacements != 1:
        raise RuntimeError(
            f"Número inesperado de substituições: {replacements}"
        )

    if len(patched_data) != len(original_data):
        raise RuntimeError(
            "O patch alterou o tamanho do binário. Operação cancelada."
        )

    if PATTERN.search(patched_data):
        raise RuntimeError(
            "A assinatura original ainda está presente após o patch."
        )

    if REPLACEMENT not in patched_data:
        raise RuntimeError(
            "A assinatura substituta não foi encontrada após o patch."
        )

    fd, temporary_name = tempfile.mkstemp(
        prefix=".chromedriver-patch-",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(fd, "wb") as temporary_file:
            temporary_file.write(patched_data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        # Preserva as permissões originais.
        original_mode = stat.S_IMODE(original_stat.st_mode)
        os.chmod(temporary_path, original_mode)

        if temporary_path.stat().st_size != original_stat.st_size:
            raise RuntimeError(
                "O arquivo temporário possui tamanho diferente do original."
            )

        # Teste inicial antes de substituir o binário oficial.
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

        # Substituição atômica. Não fica uma cópia permanente.
        os.replace(temporary_path, path)

        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

        print(f"ChromeDriver alterado: {path}")
        print(version_result.stdout.strip())

    finally:
        temporary_path.unlink(missing_ok=True)


def smoke_test_chromedriver(path: Path) -> None:
    process = subprocess.Popen(
        [
            str(path),
            "--port=9515",
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
                    "http://127.0.0.1:9515/status",
                    timeout=1,
                ) as response:
                    body = response.read().decode("utf-8")

                if response.status != 200:
                    raise RuntimeError(
                        f"Endpoint /status retornou HTTP {response.status}"
                    )

                if '"ready":true' not in body.replace(" ", ""):
                    raise RuntimeError(
                        f"Resposta inesperada do ChromeDriver: {body}"
                    )

                print("Smoke test concluído: endpoint /status respondeu.")
                return

            except Exception as exc:
                last_error = exc
                time.sleep(0.25)

        raise RuntimeError(
            f"ChromeDriver não respondeu em 10 segundos: {last_error}"
        )

    finally:
        process.terminate()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def main() -> None:
    patch_chromedriver(CHROMEDRIVER)
    smoke_test_chromedriver(CHROMEDRIVER)


if __name__ == "__main__":
    main()
