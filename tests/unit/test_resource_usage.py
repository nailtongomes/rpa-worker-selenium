"""Testes rápidos (host) do image/app/resource_usage.py com um cgroup falso.

A medida no cgroup real do Docker roda no portão (cenário de limites do scripts/test-image.sh)."""

import json
import sys

import pytest

import resource_usage as ru

MB = 1024 * 1024


def _cgroup_v2(root, *, current=300 * MB, inactive=50 * MB, usage_usec=0, throttled=0,
               mem_max="max", cpu_max="max 100000", oom=0):
    root.mkdir(parents=True, exist_ok=True)
    (root / "memory.current").write_text(f"{current}\n")
    (root / "memory.stat").write_text(f"anon 1\ninactive_file {inactive}\nactive_file 2\n")
    (root / "cpu.stat").write_text(f"usage_usec {usage_usec}\nuser_usec 1\nthrottled_usec {throttled}\n")
    (root / "memory.max").write_text(f"{mem_max}\n")
    (root / "cpu.max").write_text(f"{cpu_max}\n")
    (root / "memory.events").write_text(f"low 0\noom 0\noom_kill {oom}\n")
    return root


def test_reads_cgroup_v2_like_docker_stats(tmp_path):
    cg = ru.Cgroup.detect(_cgroup_v2(tmp_path, mem_max=str(2048 * MB), cpu_max="150000 100000",
                                     usage_usec=5_000_000, throttled=7))
    assert cg.version == 2
    assert cg.memory_bytes() == 250 * MB  # uso menos o cache inativo
    assert cg.cpu_usec() == 5_000_000 and cg.throttled_usec() == 7 and cg.oom_kills() == 0
    assert cg.memory_limit() == 2048 * MB and cg.cpu_limit() == 1.5
    assert ru.limits(cg)["memoria_mb"] == 2048 and ru.limits(cg)["cpu_nucleos"] == 1.5


def test_unlimited_container(tmp_path):
    cg = ru.Cgroup.detect(_cgroup_v2(tmp_path))
    assert cg.memory_limit() is None and cg.cpu_limit() is None
    lim = ru.limits(cg)
    assert lim["memoria_mb"] is None and lim["host_cpus"] >= 1


def test_reads_cgroup_v1(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "cpuacct").mkdir()
    (tmp_path / "cpu").mkdir()
    (tmp_path / "memory" / "memory.usage_in_bytes").write_text(str(500 * MB))
    (tmp_path / "memory" / "memory.stat").write_text(f"total_inactive_file {100 * MB}\n")
    (tmp_path / "memory" / "memory.limit_in_bytes").write_text("9223372036854771712")
    (tmp_path / "cpuacct" / "cpuacct.usage").write_text("3000000000")
    (tmp_path / "cpu" / "cpu.cfs_quota_us").write_text("50000")
    (tmp_path / "cpu" / "cpu.cfs_period_us").write_text("100000")
    cg = ru.Cgroup.detect(tmp_path)
    assert cg.version == 1
    assert cg.memory_bytes() == 400 * MB and cg.cpu_usec() == 3_000_000
    assert cg.memory_limit() is None and cg.cpu_limit() == 0.5


def test_no_cgroup(tmp_path):
    assert ru.Cgroup.detect(tmp_path) is None


@pytest.mark.parametrize("peak, p95, memory, cpu", [
    (1000, 0.62, 1280, 0.75),   # 1000 x 1,25 = 1250 -> múltiplo de 64
    (1130, 1.03, 1472, 1.0),    # 1,03 é ruído de amostragem: 1 núcleo basta
    (100, 0.0, 128, 0.25),      # mínimo de 1/4 de núcleo
    (2048, 1.9, 2560, 2.0),
])
def test_suggestion(peak, p95, memory, cpu):
    assert ru.suggestion(peak, p95) == {"memoria_mb": memory, "cpu_nucleos": cpu}


def test_percentile():
    values = list(range(1, 101))
    assert ru.percentile(values, 95) == 95
    assert ru.percentile([3.0], 95) == 3.0
    assert ru.percentile([], 95) == 0.0


def test_sampler_average_and_peak(tmp_path):
    root = _cgroup_v2(tmp_path, current=200 * MB, inactive=0, usage_usec=0)
    cg = ru.Cgroup.detect(root)
    sampler = ru.Sampler(cg, interval=60)  # sem thread: amostras manuais
    for mem, cpu in ((400, 500_000), (800, 1_000_000), (600, 1_500_000)):
        _cgroup_v2(root, current=mem * MB, inactive=0, usage_usec=cpu)
        sampler._sample()
    sampler._stop_event.set()
    result = sampler.stop()
    mem = result["memoria"]
    assert mem["inicio_mb"] == 200 and mem["pico_mb"] == 800
    assert mem["media_mb"] == round((400 + 800 + 600 + 600) / 4)  # stop() faz a última amostra
    assert result["cpu"]["tempo_s"] == 1.5 and result["cpu"]["pico_nucleos"] > 0
    assert mem["oom_kills"] == 0


@pytest.fixture
def fake_cgroup(tmp_path, monkeypatch):
    root = _cgroup_v2(tmp_path / "cg", mem_max=str(2048 * MB), cpu_max="100000 100000")
    monkeypatch.setattr(ru, "CGROUP_ROOT", root)
    log = tmp_path / "logs" / "resources.jsonl"
    monkeypatch.setenv("RESOURCE_LOG", str(log))
    monkeypatch.setenv("WORKER_ID", "w-01")
    return log


@pytest.mark.parametrize("code", [0, 3])
def test_run_keeps_exit_code_and_records(fake_cgroup, capsys, code):
    rc = ru.main(["run", "--interval", "0.1", "--", sys.executable, "-c", f"print('SAIDA'); raise SystemExit({code})"])
    assert rc == code
    out = capsys.readouterr().out
    assert "📊 Recursos de python" in out and "reserva sugerida" in out and "limite 2,00 GB" in out
    summary = json.loads(out.split("RESOURCE_SUMMARY ", 1)[1].splitlines()[0])
    assert summary["exit_code"] == code and summary["worker_id"] == "w-01"
    assert summary["limites"]["memoria_mb"] == 2048 and summary["limites"]["cpu_nucleos"] == 1.0
    assert json.loads(fake_cgroup.read_text().splitlines()[-1]) == summary


def test_run_reports_signal_like_the_shell(fake_cgroup):
    rc = ru.main(["run", "--label", "morto", "--", sys.executable, "-c",
                  "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"])
    assert rc == 128 + 9


def test_run_missing_program(fake_cgroup, capsys):
    assert ru.main(["run", "--", "/nao/existe"]) == 127


def test_run_without_cgroup_still_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ru, "CGROUP_ROOT", tmp_path / "nada")
    monkeypatch.setenv("RESOURCE_LOG", "")
    assert ru.main(["run", "--", sys.executable, "-c", "raise SystemExit(5)"]) == 5
    assert "medição indisponível" in capsys.readouterr().out


def test_default_label():
    assert ru.default_label(["python", "/tmp/tarefa.py"]) == "tarefa.py"
    assert ru.default_label(["/usr/bin/python3", "-c", "print(1)"]) == "python3"


def test_human_lines_flag_throttling_and_oom():
    summary = {"rotulo": "x.py", "exit_code": 0, "duracao_s": 75, "fonte": "cgroup v2", "amostras": 75,
               "cpu": {"media_nucleos": 0.9, "p95_nucleos": 1.0, "pico_nucleos": 1.0, "limitada_pct": 40.0},
               "memoria": {"inicio_mb": 400, "media_mb": 900, "pico_mb": 1900, "oom_kills": 2},
               "limites": {"memoria_mb": 2048, "cpu_nucleos": 1.0}, "sugestao": ru.suggestion(1900, 1.0)}
    text = "\n".join(ru.human_lines(summary))
    assert "1m15s" in text and "pico 1,86 GB (limite 2,00 GB, 93%)" in text
    assert "bateu no limite em 40% do tempo" in text and "OOM" in text


def test_report_aggregates_runs(tmp_path, capsys):
    log = tmp_path / "r.jsonl"
    runs = []
    for peak, p95, code in ((800, 0.5, 0), (1200, 0.9, 0), (1000, 0.7, 1)):
        runs.append({"rotulo": "pje.py", "exit_code": code, "duracao_s": 60,
                     "cpu": {"media_nucleos": 0.4, "p95_nucleos": p95, "pico_nucleos": 1.0},
                     "memoria": {"media_mb": peak - 200, "pico_mb": peak, "oom_kills": 0}})
    log.write_text("\n".join(json.dumps(r) for r in runs) + "\nlinha quebrada\n")
    assert ru.main(["report", str(log)]) == 0
    out = capsys.readouterr().out
    agg = json.loads(out.split("RESOURCE_REPORT ", 1)[1])["pje.py"]
    assert agg["execucoes"] == 3 and agg["falhas"] == 1
    assert agg["memoria_pico_max_mb"] == 1200 and agg["memoria_pico_medio_mb"] == 1000
    assert agg["sugestao"] == ru.suggestion(1200, 0.9)
    assert "pico máximo 1,17 GB" in out
