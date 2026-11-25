"""Testes rápidos (host) do image/app/worker_events.py: status.json, ping, telas e envio do log.

O envio de verdade (container terminando, docker stop, telas do Xvfb) roda no portão
(cenários de fim do container no scripts/test-image.sh)."""

import json
import os
import time

import pytest
import requests

import worker_events as we


class Calls(list):
    """Requisições feitas; ``status`` = respostas (código ou exceção) das próximas."""

    status: list


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code


@pytest.fixture
def calls(monkeypatch):
    """Requisições feitas (nenhuma sai do host)."""
    made = Calls()

    def fake(method):
        def call(url, **kwargs):
            made.append({"method": method, "url": url, **kwargs})
            status = made_status.pop(0) if made_status else 200
            if isinstance(status, Exception):
                raise status
            return FakeResponse(status)
        return call

    made_status = []
    monkeypatch.setattr(requests, "get", fake("GET"))
    monkeypatch.setattr(requests, "post", fake("POST"))
    monkeypatch.setattr(we.time, "sleep", lambda _s: None)
    made.status = made_status
    return made


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("LOG_POST_URL", "LOG_POST_URL_FILE", "PING_URL", "PING_URL_FILE", "EGRESS_PROXY_URL",
                 "EGRESS_PROXY_URL_FILE", "HTTPS_PROXY", "https_proxy", "LOG_POST_FULL", "LOG_POST_LINES",
                 "SCREENSHOT_ON_FAIL", "WORKER_STATUS", "SCRIPT_URL", "WORKER_ID"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# --- status ---------------------------------------------------------------------

def test_apply_updates_sets_increments_and_removes():
    status = {"contadores": {"ok": 1}, "execucao": {"inicio": "x"}}
    we.apply_updates(status, ["fase=executando", "iteracao=3", "ultima.duracao_s=12.5", "+contadores.ok",
                              "+contadores.falha", "~execucao", "partida.xvfb_s=0.3", "nome=job.py"])
    assert status["fase"] == "executando" and "desde" in status and "atualizado_em" in status
    assert status["iteracao"] == 3 and status["ultima"]["duracao_s"] == 12.5
    assert status["contadores"] == {"ok": 2, "falha": 1}
    assert "execucao" not in status
    assert status["partida"]["xvfb_s"] == 0.3 and status["nome"] == "job.py"


def test_phase_since_only_changes_with_the_phase():
    status = we.apply_updates({}, ["fase=esperando"])
    since = status["desde"]
    status["desde"] = "antes"
    we.apply_updates(status, ["fase=esperando", "iteracao=2"])
    assert status["desde"] == "antes"
    we.apply_updates(status, ["fase=executando"])
    assert status["desde"] != "antes" and since


def test_parse_value_times():
    assert we.parse_value("@now")[:4].isdigit()
    later = we.parse_value("@in:120")
    assert later > we.parse_value("@now")
    assert we.parse_value("abc") == "abc" and we.parse_value("-3") == -3


def test_status_command_writes_atomically(tmp_path, clean_env):
    path = tmp_path / "status.json"
    clean_env.setattr(we, "STATUS_FILE", path)
    clean_env.setenv("SCRIPT_URL", "https://u:SEGREDO@example.com/a/job.py?token=SEGREDO")
    assert we.main(["status", "--init", "modo=loop", "fase=iniciando"]) == 0
    assert we.main(["status", "+contadores.ok", "fase=pronto"]) == 0
    data = json.loads(path.read_text())
    assert data["modo"] == "loop" and data["fase"] == "pronto" and data["script"] == "job.py"
    assert data["contadores"] == {"ok": 1, "falha": 0, "tempo_esgotado": 0, "sem_trabalho": 0}
    assert "SEGREDO" not in path.read_text()
    assert not list(tmp_path.glob(".*tmp"))


# --- ping -----------------------------------------------------------------------

@pytest.mark.parametrize("base, event, code, expected", [
    ("https://hc-ping.com/abc", "start", None, "https://hc-ping.com/abc/start"),
    ("https://hc-ping.com/abc/", "ok", 0, "https://hc-ping.com/abc/0"),
    ("https://hc-ping.com/abc", "fail", 3, "https://hc-ping.com/abc/3"),
    ("https://kuma/api/push/T?status={status}&msg={evento}", "fail", 3, "https://kuma/api/push/T?status=down&msg=fail"),
    ("https://kuma/api/push/T?status={status}&msg={evento}", "start", None, "https://kuma/api/push/T?status=up&msg=start"),
    ("https://x/p?state={evento}&code={exit_code}", "ok", 0, "https://x/p?state=ok&code=0"),
])
def test_ping_url(base, event, code, expected):
    assert we.ping_url(base, event, code) == expected


def test_ping_sends_start_and_end(clean_env, calls):
    clean_env.setenv("PING_URL", "https://hc-ping.com/abc")
    we.main(["ping", "start"])
    we.main(["ping", "end", "--exit-code", "0"])
    we.main(["ping", "end", "--exit-code", "137"])
    assert [c["url"] for c in calls] == ["https://hc-ping.com/abc/start", "https://hc-ping.com/abc/0",
                                         "https://hc-ping.com/abc/137"]


def test_ping_file_wins_and_failures_only_warn(tmp_path, clean_env, calls, capsys):
    url_file = tmp_path / "ping"
    url_file.write_text("https://hc-ping.com/SEGREDO-TOKEN?k=SEGREDO\n")
    clean_env.setenv("PING_URL_FILE", str(url_file))
    clean_env.setenv("PING_URL", "https://other")
    calls.status.append(requests.ConnectionError("falhou https://hc-ping.com/SEGREDO-TOKEN/start?k=SEGREDO"))
    assert we.main(["ping", "start"]) == 0
    assert calls[0]["url"].startswith("https://hc-ping.com/SEGREDO-TOKEN")
    out = capsys.readouterr().out
    assert "PING_URL falhou" in out and "SEGREDO" not in out


def test_nothing_leaves_directly_when_the_relay_is_not_up(tmp_path, clean_env, calls, capsys):
    clean_env.setenv("PING_URL", "https://hc-ping.com/abc")
    clean_env.setenv("LOG_POST_URL", "https://logs.example.com/in")
    clean_env.setenv("EGRESS_PROXY_URL_FILE", "/run/secrets/relay")
    clean_env.setattr(we, "WORKER_LOG", tmp_path / "worker.log")
    we.main(["ping", "start"])
    we.main(["post", "--exit-code", "1"])
    assert calls == []
    assert "não sai direto" in capsys.readouterr().out
    clean_env.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")  # relay ligado pelo entrypoint
    we.main(["ping", "start"])
    assert len(calls) == 1


def test_disabled_without_urls(clean_env, calls):
    assert we.main(["ping", "start"]) == 0
    assert we.main(["post", "--exit-code", "0"]) == 0
    assert calls == []


# --- envio do log -----------------------------------------------------------------

@pytest.fixture
def worker_log(tmp_path, clean_env):
    log = tmp_path / "worker.log"
    lines = [f"[t] linha {i}" for i in range(1, 301)]
    summary = {"rotulo": "job.py", "exit_code": 3, "memoria": {"pico_mb": 512}}
    lines.insert(250, "RESOURCE_SUMMARY " + json.dumps(summary))
    log.write_text("\n".join(lines) + "\n")
    clean_env.setattr(we, "WORKER_LOG", log)
    clean_env.setattr(we, "FAILURES_DIR", tmp_path / "falhas")
    clean_env.setenv("LOG_POST_URL", "https://rpa:SEGREDO-USER@logs.example.com/in?token=SEGREDO-Q")
    clean_env.setenv("SCRIPT_URL", "https://example.com/jobs/job.py?token=SEGREDO-S")
    return log


def test_post_sends_last_lines_as_json(worker_log, calls, capsys):
    assert we.main(["post", "--exit-code", "3", "--mode", "script", "--started-at", str(time.time() - 65)]) == 0
    (call,) = calls
    report = call["json"]
    assert call["method"] == "POST" and "files" not in call
    assert report["evento"] == "fim_do_container" and report["motivo"] == "falha" and report["exit_code"] == 3
    assert report["modo"] == "script" and report["script"] == "job.py"
    assert 60 <= report["duracao_s"] <= 70
    assert report["linhas"] == 100 and report["log"].splitlines()[-1] == "[t] linha 300"
    assert report["recursos"]["memoria"]["pico_mb"] == 512
    assert "status" not in report
    out = capsys.readouterr().out
    assert "📤 Log enviado" in out and "100 linhas" in out and "SEGREDO" not in out


def test_post_with_full_log_is_multipart(worker_log, calls, clean_env):
    clean_env.setenv("LOG_POST_FULL", "1")
    clean_env.setenv("LOG_POST_LINES", "5")
    we.main(["post", "--exit-code", "0"])
    (call,) = calls
    report = json.loads(call["data"]["dados"])
    assert report["motivo"] == "concluido" and report["linhas"] == 5
    name, content, ctype = call["files"]["log"]
    assert name == "worker.txt" and content == worker_log.read_bytes() and ctype.startswith("text/plain")


def test_post_reports_docker_stop(worker_log, calls):
    we.main(["post", "--exit-code", "0", "--stopped"])
    assert calls[0]["json"]["motivo"] == "parado"


def test_post_attaches_this_run_failure_screens(worker_log, calls, clean_env, tmp_path):
    clean_env.setenv("SCREENSHOT_ON_FAIL", "1")
    old = tmp_path / "falhas" / "20200101-000000"
    old.mkdir(parents=True)
    (old / "tela-velha.jpg").write_bytes(b"velha")
    os.utime(old, (1, 1))
    started = time.time() - 5
    new = tmp_path / "falhas" / "20990101-000000"
    new.mkdir()
    (new / "tela-1.jpg").write_bytes(b"jpg1")
    (new / "tela-2-fim.jpg").write_bytes(b"jpg2")
    we.main(["post", "--exit-code", "3", "--started-at", str(started)])
    (call,) = calls
    assert sorted(call["files"]) == ["tela_1", "tela_2"]
    assert json.loads(call["data"]["dados"])["telas"] == ["tela-1.jpg", "tela-2-fim.jpg"]
    assert all(f[1] != b"velha" for f in call["files"].values())


def test_post_includes_status_when_enabled(worker_log, calls, clean_env, tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"fase": "encerrado", "contadores": {"ok": 2}}))
    clean_env.setattr(we, "STATUS_FILE", path)
    clean_env.setenv("WORKER_STATUS", "1")
    we.main(["post", "--exit-code", "0"])
    assert calls[0]["json"]["status"]["contadores"] == {"ok": 2}


def test_post_retries_then_gives_up_without_failing(worker_log, calls, capsys):
    calls.status.extend([500, requests.ConnectionError("x https://logs.example.com/in?token=SEGREDO-Q"), 503])
    assert we.main(["post", "--exit-code", "1", "--timeout", "30"]) == 0
    assert len(calls) == 3
    out = capsys.readouterr().out
    assert "Não foi possível enviar o log" in out and "HTTP 503" in out and "SEGREDO" not in out


def test_post_retry_succeeds(worker_log, calls):
    calls.status.extend([502, 200])
    we.main(["post", "--exit-code", "1", "--timeout", "30"])
    assert len(calls) == 2


def test_tail_lines(tmp_path):
    log = tmp_path / "x.log"
    log.write_text("".join(f"{i}\n" for i in range(50000)))
    assert we.tail_lines(log, 3) == ["49997", "49998", "49999"]
    assert we.tail_lines(tmp_path / "nao-existe", 3) == []


# --- telas ------------------------------------------------------------------------

def test_screens_keep_moves_frames_and_prunes(tmp_path, monkeypatch):
    def fake_grab(target, _display):
        target.write_bytes(b"jpg")
        return True

    monkeypatch.setattr(we, "grab_screen", fake_grab)
    to = tmp_path / "falhas"
    for i in range(4):
        (to / f"2020010{i}-000000").mkdir(parents=True)
    frames = tmp_path / "telas"
    frames.mkdir()
    (frames / "tela-20260101-000001.jpg").write_bytes(b"a")
    assert we.main(["screens", "keep", "--dir", str(frames), "--to", str(to), "--keep", "3"]) == 0
    kept = sorted(p.name for p in to.iterdir())
    assert len(kept) == 3 and "20200100-000000" not in kept
    newest = to / kept[-1]
    assert len(list(newest.glob("tela-*.jpg"))) == 2  # a da execução + a do fim
    assert not frames.exists()


def test_screens_keep_without_display_only_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(we, "grab_screen", lambda *_: False)
    assert we.main(["screens", "keep", "--dir", str(tmp_path / "t"), "--to", str(tmp_path / "f")]) == 0
    assert "não foi possível capturar" in capsys.readouterr().out
    assert not (tmp_path / "f").exists()


@pytest.mark.parametrize("url", [
    "https://hc-ping.com/0f1e2d3c-SEGREDO",
    "https://n8n.example.com/webhook/SEGREDO-ID?token=SEGREDO-Q",
    "https://rpa:SEGREDO-PASS@logs.example.com:8443/in",
])
def test_hide_url_and_errors_never_show_secrets(url):
    assert "SEGREDO" not in we.hide_url(url) and we.hide_url(url).endswith("/***")
    path = url.split("/", 3)[-1]
    message = (f"HTTPSConnectionPool(host='x', port=443): Max retries exceeded with url: /{path} "
               f"(Caused by ...) for url: {url}")
    assert "SEGREDO" not in we.hide_text(message, url)
