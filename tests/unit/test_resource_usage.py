"""Testes rápidos (host) do image/app/resource_usage.py com um cgroup falso.

A medida no cgroup real do Docker roda no portão (cenário de limites do scripts/test-image.sh)."""

import itertools
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


def test_short_run_is_flagged():
    summary = {"rotulo": "x.py", "exit_code": 0, "duracao_s": 0.4, "fonte": "cgroup v2", "amostras": 1,
               "cpu": {"media_nucleos": 1.1, "p95_nucleos": 1.1, "pico_nucleos": 1.1},
               "memoria": {"inicio_mb": 20, "media_mb": 20, "pico_mb": 20}, "limites": {}}
    assert "execução curta" in "\n".join(ru.human_lines(summary))
    summary["duracao_s"] = 60
    assert "execução curta" not in "\n".join(ru.human_lines(summary))


# --- divisão por processo (/proc falso) ---------------------------------------------

@pytest.mark.parametrize("exe, comm, cmdline, in_script, group", [
    ("/opt/chrome/chrome", "chrome", "/opt/chrome/chrome --type=renderer", True, "chrome"),
    ("/opt/chrome/chrome_crashpad_handler", "chrome_crashpad", "", False, "chrome"),
    ("/opt/firefox/firefox-bin", "Isolated Web Co", "", True, "firefox"),
    ("/usr/local/bin/chromedriver", "chromedriver", "", True, "drivers"),
    ("/opt/venv/lib/python3.13/site-packages/seleniumbase/drivers/uc_driver (deleted)", "uc_driver", "", True,
     "drivers"),
    ("/opt/pjeoffice/jre/bin/java", "java", "java -jar /opt/pjeoffice/pjeoffice-pro.jar", False, "pjeoffice"),
    ("/usr/bin/bash", "pjeoffice-pro.s", "/bin/bash /opt/pjeoffice/pjeoffice-pro.sh", False, "pjeoffice"),
    ("/usr/bin/Xvfb", "Xvfb", "Xvfb :99", False, "tela"),
    ("/usr/bin/python3.13", "python", "python /usr/local/bin/websockify --web /opt/novnc", False, "tela"),
    ("/usr/bin/python3.13", "python", "python /tmp/tarefa.py", True, "script"),
    ("/usr/bin/bash", "bash", "/bin/bash /app/entrypoint.sh", False, "outros"),
    ("", "kworker", "", False, "outros"),  # exe ilegível
])
def test_classify(exe, comm, cmdline, in_script, group):
    assert ru.classify(exe, comm, cmdline, in_script) == group


class FakeProc:
    """Um /proc mínimo: stat (comm, ppid, utime+stime, starttime), exe, cmdline, smaps_rollup."""

    def __init__(self, root):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def add(self, pid, comm, ppid, ticks, exe="", cmdline="", pss_kb=0, start=100):
        d = self.root / str(pid)
        d.mkdir(exist_ok=True)
        fields = ["S", str(ppid)] + ["0"] * 9 + [str(ticks), "0"] + ["0"] * 6 + [str(start)] + ["0"] * 10
        (d / "stat").write_text(f"{pid} ({comm}) " + " ".join(fields) + "\n")
        (d / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode())
        (d / "smaps_rollup").write_text(f"Rss: {pss_kb * 2} kB\nPss: {pss_kb} kB\n")
        if exe and not (d / "exe").is_symlink():
            (d / "exe").symlink_to(exe)

    def remove(self, pid):
        import shutil
        shutil.rmtree(self.root / str(pid))


def test_process_table_groups_cpu_and_memory(tmp_path):
    proc = FakeProc(tmp_path / "proc")
    proc.add(1, "bash", 0, 50, "/usr/bin/bash", "/bin/bash /app/entrypoint.sh", 3_000)
    proc.add(20, "java", 1, 900, "/opt/pjeoffice/jre/bin/java", "java -jar /opt/pjeoffice/pjeoffice-pro.jar", 200_000)
    proc.add(30, "Xvfb", 1, 400, "/usr/bin/Xvfb", "Xvfb :99", 40_000)
    table = ru.ProcessTable(proc.root)
    table.ticks = 100
    proc.add(40, "python", 1, 10, "/usr/bin/python3.13", "python /tmp/tarefa.py", 50_000)
    table.script_pid = 40
    proc.add(41, "chromedriver", 40, 5, "/usr/local/bin/chromedriver", "chromedriver --port=1", 10_000)
    proc.add(42, "chrome", 41, 150, "/opt/chrome/chrome", "/opt/chrome/chrome", 300_000)
    proc.add(43, "chrome", 42, 50, "/opt/chrome/chrome", "/opt/chrome/chrome --type=renderer", 100_000)
    proc.add(44, "sh", 40, 2, "/usr/bin/dash", "sh -c true", 500)  # filho do script que não é browser
    proc.add(20, "java", 1, 920, pss_kb=210_000)  # PJeOffice: +20 ticks
    sample = table.sample()
    assert sample["chrome"][0] == pytest.approx(2.0)  # processos novos: todo o tempo deles conta
    assert sample["chrome"][1] == 400_000 * 1024
    assert sample["pjeoffice"][0] == pytest.approx(0.2)  # só o que gastou desde a base
    assert sample["tela"][0] == 0 and sample["tela"][1] == 40_000 * 1024
    assert sample["drivers"][0] == pytest.approx(0.05)
    assert sample["script"][0] == pytest.approx(0.12)  # python + o sh filho dele
    assert sample["outros"][0] == 0

    # o script terminou: o Chrome que ficou órfão (ppid 1) continua contando como Chrome
    proc.remove(40)
    proc.remove(44)
    proc.add(42, "chrome", 1, 250, pss_kb=300_000)
    sample = table.sample()
    assert sample["chrome"][0] == pytest.approx(1.0) and "script" not in sample


def test_process_table_pid_reused_counts_from_zero(tmp_path):
    proc = FakeProc(tmp_path / "proc")
    proc.add(50, "python", 1, 500, "/usr/bin/python3.13", "python /tmp/a.py", start=100)
    table = ru.ProcessTable(proc.root)
    table.ticks, table.script_pid = 100, 50
    proc.remove(50)
    proc.add(50, "chrome", 1, 30, "/opt/chrome/chrome", start=900)  # mesmo pid, outro processo
    assert table.sample()["chrome"][0] == pytest.approx(0.3)


def test_process_table_skips_other_cgroups(tmp_path):
    proc = FakeProc(tmp_path / "proc")
    (proc.root / "self").mkdir()
    (proc.root / "self" / "cgroup").write_text("0::/docker/abc\n")
    proc.add(10, "chrome", 1, 0, "/opt/chrome/chrome", pss_kb=1_000)
    proc.add(11, "chrome", 1, 0, "/opt/chrome/chrome", pss_kb=9_000)
    (proc.root / "10" / "cgroup").write_text("0::/docker/abc\n")
    (proc.root / "11" / "cgroup").write_text("0::/user.slice\n")  # outro container/host
    assert ru.ProcessTable(proc.root).sample()["chrome"][1] == 1_000 * 1024


def test_sampler_reports_processes_and_peak_times(tmp_path, monkeypatch):
    root = _cgroup_v2(tmp_path / "cg", current=200 * MB, inactive=0, usage_usec=0)
    proc = FakeProc(tmp_path / "proc")
    proc.add(20, "java", 1, 0, "/opt/pjeoffice/jre/bin/java", "java /opt/pjeoffice/x.jar", 100 * 1024)
    monkeypatch.setattr(ru, "PSS_REFRESH_SECS", 0)  # PSS relida a cada amostra
    table = ru.ProcessTable(proc.root)
    table.ticks, table.script_pid, table.clock, table._pss_at = 100, 40, lambda: 0.0, float("-inf")
    clock = itertools.chain([0.0, 10.0, 20.0, 30.0], itertools.repeat(40.0))
    monkeypatch.setattr(ru.time, "monotonic", lambda: next(clock))
    sampler = ru.Sampler(ru.Cgroup.detect(root), interval=60, processes=table)  # started = 0
    steps = [(400, 2_000_000, 100), (900, 12_000_000, 900), (500, 14_000_000, 950)]
    for mem, usec, chrome_ticks in steps:
        _cgroup_v2(root, current=mem * MB, inactive=0, usage_usec=usec)
        proc.add(42, "chrome", 1, chrome_ticks, "/opt/chrome/chrome", pss_kb=mem * 1024 // 2)
        sampler._sample()  # t = 10, 20, 30
    sampler._stop_event.set()
    result = sampler.stop()  # última amostra em t = 40 (sem mudança)
    assert result["memoria"]["pico_em_s"] == 20 and result["cpu"]["pico_em_s"] == 20
    chrome, pje = result["processos"]["chrome"], result["processos"]["pjeoffice"]
    assert list(result["processos"]) == ["chrome", "pjeoffice"]  # maior CPU primeiro
    assert chrome["cpu_media_nucleos"] == round(9.5 / 40, 2) and chrome["cpu_pct"] == round(9.5 / 14 * 100)
    assert chrome["memoria_pico_mb"] == 450
    assert pje["memoria_media_mb"] == 100 and pje["cpu_media_nucleos"] == 0

    summary = ru.build_summary("x.py", 0, result, ru.Cgroup.detect(root), "agora", 40)
    text = "\n".join(ru.human_lines(summary))
    assert "picos: memória aos 20s · CPU aos 20s" in text
    assert "por processo" in text and "Chrome" in text and "PJeOffice (Java)" in text
    assert text.index("Chrome") < text.index("PJeOffice (Java)")


def test_run_breaks_down_by_process(fake_cgroup, capsys, tmp_path, monkeypatch):
    """Com o /proc real do host: o script medido aparece no grupo "script"."""
    monkeypatch.setenv("RESOURCE_PROCESSES", "1")
    rc = ru.main(["run", "--interval", "0.1", "--", sys.executable, "-c",
                  "import time\nt = time.time()\nwhile time.time() - t < 0.5: pass"])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out.split("RESOURCE_SUMMARY ", 1)[1].splitlines()[0])
    assert summary["processos"]["script"]["cpu_media_nucleos"] > 0


def test_run_without_process_breakdown(fake_cgroup, capsys, monkeypatch):
    monkeypatch.setenv("RESOURCE_PROCESSES", "0")
    assert ru.main(["run", "--", sys.executable, "-c", "pass"]) == 0
    out = capsys.readouterr().out
    assert "por processo" not in out and '"processos"' not in out


def test_report_aggregates_processes(tmp_path, capsys):
    log = tmp_path / "r.jsonl"
    runs = [{"rotulo": "pje.py", "exit_code": 0, "duracao_s": 60,
             "cpu": {"media_nucleos": 0.4, "p95_nucleos": 0.9, "pico_nucleos": 1.0},
             "memoria": {"media_mb": 500, "pico_mb": 800},
             "processos": {"chrome": {"cpu_media_nucleos": c, "cpu_pct": 60, "memoria_media_mb": 300,
                                      "memoria_pico_mb": p},
                           "pjeoffice": {"cpu_media_nucleos": 0.05, "cpu_pct": 10, "memoria_media_mb": 200,
                                         "memoria_pico_mb": 220}}}
            for c, p in ((0.2, 400), (0.3, 600))]
    log.write_text("\n".join(json.dumps(r) for r in runs) + "\n")
    assert ru.main(["report", str(log)]) == 0
    out = capsys.readouterr().out
    procs = json.loads(out.split("RESOURCE_REPORT ", 1)[1])["pje.py"]["processos"]
    assert procs["chrome"] == {"cpu_media_nucleos": 0.25, "cpu_pct": 60, "memoria_media_mb": 300,
                               "memoria_pico_max_mb": 600}
    assert list(procs) == ["chrome", "pjeoffice"]
    assert "por processo" in out and "600 MB" in out


def test_pss_is_reread_only_every_few_seconds(tmp_path, monkeypatch):
    """A PSS é cara (smaps_rollup): relida a cada PSS_REFRESH_SECS; processo novo é lido na hora."""
    monkeypatch.setattr(ru, "PSS_REFRESH_SECS", 5)
    proc = FakeProc(tmp_path / "proc")
    proc.add(42, "chrome", 1, 0, "/opt/chrome/chrome", pss_kb=1_000)
    now = [0.0]
    table = ru.ProcessTable(proc.root)
    table.clock = lambda: now[0]
    table._pss_at = 0.0
    proc.add(42, "chrome", 1, 0, pss_kb=5_000)
    proc.add(43, "chrome", 42, 0, "/opt/chrome/chrome", pss_kb=2_000)
    now[0] = 1.0
    assert table.sample()["chrome"][1] == (1_000 + 2_000) * 1024  # 42 do cache, 43 novo
    now[0] = 5.0
    assert table.sample()["chrome"][1] == (5_000 + 2_000) * 1024  # releitura
