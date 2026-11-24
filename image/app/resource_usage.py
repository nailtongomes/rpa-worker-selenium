#!/usr/bin/env python3
"""
resource_usage — quanto CPU e memória uma execução consumiu (média, p95 e pico), para
dimensionar o worker e reservar só o necessário.

O entrypoint já roda cada script assim (SCRIPT_URL, loop e standby; RESOURCE_SUMMARY=0
desliga). Ao fim de cada execução saem:
  - um resumo legível no log (📊), com uma sugestão de reserva;
  - uma linha `RESOURCE_SUMMARY {...}` em JSON, para o orquestrador;
  - a mesma linha em RESOURCE_LOG (padrão /app/logs/resources.jsonl), para juntar várias execuções.

Uso:
    python /app/resource_usage.py run [--label NOME] -- python meu_script.py
    python /app/resource_usage.py report [/app/logs/resources.jsonl]   # média e picos de todas
    python /app/resource_usage.py limits                               # limites do container

A medida é do container inteiro (cgroup): o script, os browsers que ele abre e os serviços
(Xvfb, PJeOffice, VNC...). É o que conta para a reserva do container. A memória é a mesma do
`docker stats` (uso menos o cache de arquivos que o kernel pode liberar). O exit code do
script é devolvido sem mudança.

Variáveis: RESOURCE_SAMPLE_SECS (intervalo das amostras, padrão 1), RESOURCE_LOG ("" não grava),
WORKER_ID (vai no JSON).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

CGROUP_ROOT = Path("/sys/fs/cgroup")
MB = 1024 * 1024
UNLIMITED = 1 << 60  # cgroup v1 usa ~2^63 para "sem limite"
MEMORY_HEADROOM = 1.25  # reserva sugerida = pico x 1,25
SHORT_RUN_SECS = 10  # abaixo disso a CPU medida é quase só a partida do interpretador


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _stat(path: Path) -> dict:
    out = {}
    for line in _read(path).splitlines():
        key, _, value = line.partition(" ")
        if value.strip().lstrip("-").isdigit():
            out[key] = int(value)
    return out


class Cgroup:
    """CPU e memória do container pelo cgroup (v2, ou v1 em hosts antigos)."""

    def __init__(self, root: Path, version: int) -> None:
        self.root = Path(root)
        self.version = version

    @classmethod
    def detect(cls, root: Optional[Path] = None) -> Optional["Cgroup"]:
        root = Path(root or CGROUP_ROOT)
        if (root / "memory.current").exists() and (root / "cpu.stat").exists():
            return cls(root, 2)
        if (root / "memory" / "memory.usage_in_bytes").exists():
            return cls(root, 1)
        return None

    @property
    def source(self) -> str:
        return f"cgroup v{self.version} (container inteiro)"

    def memory_bytes(self) -> Optional[int]:
        """Memória em uso sem o cache de arquivos inativo (mesma conta do `docker stats`)."""
        if self.version == 2:
            used, stat = _read(self.root / "memory.current"), _stat(self.root / "memory.stat")
            cache = stat.get("inactive_file", 0)
        else:
            used = _read(self.root / "memory" / "memory.usage_in_bytes")
            cache = _stat(self.root / "memory" / "memory.stat").get("total_inactive_file", 0)
        if not used.isdigit():
            return None
        return max(int(used) - cache, 0)

    def cpu_usec(self) -> Optional[int]:
        """Tempo de CPU acumulado do container, em microssegundos."""
        if self.version == 2:
            return _stat(self.root / "cpu.stat").get("usage_usec")
        for sub in ("cpuacct", "cpu,cpuacct"):
            value = _read(self.root / sub / "cpuacct.usage")
            if value.isdigit():
                return int(value) // 1000
        return None

    def throttled_usec(self) -> Optional[int]:
        """Tempo em que o container quis CPU e o limite (--cpus) segurou."""
        if self.version == 2:
            return _stat(self.root / "cpu.stat").get("throttled_usec")
        for sub in ("cpu", "cpu,cpuacct"):
            stat = _stat(self.root / sub / "cpu.stat")
            if "throttled_time" in stat:
                return stat["throttled_time"] // 1000
        return None

    def oom_kills(self) -> Optional[int]:
        if self.version == 2:
            return _stat(self.root / "memory.events").get("oom_kill")
        return _stat(self.root / "memory" / "memory.oom_control").get("oom_kill")

    def memory_limit(self) -> Optional[int]:
        if self.version == 2:
            value = _read(self.root / "memory.max")
        else:
            value = _read(self.root / "memory" / "memory.limit_in_bytes")
        if not value.isdigit() or int(value) >= UNLIMITED:
            return None
        return int(value)

    def cpu_limit(self) -> Optional[float]:
        """Núcleos permitidos por --cpus (cota/período); None = sem limite."""
        if self.version == 2:
            quota, _, period = _read(self.root / "cpu.max").partition(" ")
        else:
            quota = _read(self.root / "cpu" / "cpu.cfs_quota_us") or _read(self.root / "cpu,cpuacct" / "cpu.cfs_quota_us")
            period = _read(self.root / "cpu" / "cpu.cfs_period_us") or _read(self.root / "cpu,cpuacct" / "cpu.cfs_period_us")
        if not quota.isdigit() or not period.isdigit() or int(period) == 0:
            return None
        return int(quota) / int(period)


def host_memory_bytes() -> Optional[int]:
    for line in _read(Path("/proc/meminfo")).splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    return None


def host_cpus() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def limits(cg: Optional[Cgroup] = None) -> dict:
    """Limites efetivos do container (ou do host, se não houver limite)."""
    cg = cg if cg is not None else Cgroup.detect()
    mem = cg.memory_limit() if cg else None
    cpu = cg.cpu_limit() if cg else None
    return {
        "memoria_mb": round(mem / MB) if mem else None,
        "cpu_nucleos": round(cpu, 2) if cpu else None,
        "host_memoria_mb": round((host_memory_bytes() or 0) / MB) or None,
        "host_cpus": host_cpus(),
    }


def percentile(values: list, pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))]


def round_up(value: float, step: float) -> float:
    return math.ceil(value / step - 1e-9) * step if value > 0 else step


def suggestion(memory_peak_mb: float, cpu_p95: float) -> dict:
    """Reserva sugerida: memória = pico + 25% (múltiplos de 64 MB); CPU = p95 (múltiplos de 0,25)."""
    # 0,05 de folga: 1,03 núcleo medido é ruído de amostragem, não pede 1,25
    return {"memoria_mb": int(round_up(memory_peak_mb * MEMORY_HEADROOM, 64)),
            "cpu_nucleos": round(round_up(max(cpu_p95 - 0.05, 0), 0.25), 2)}


class Sampler(threading.Thread):
    """Amostra CPU e memória do cgroup a cada ``interval`` segundos até ``stop()``."""

    def __init__(self, cg: Cgroup, interval: float = 1.0) -> None:
        super().__init__(daemon=True)
        self.cg, self.interval = cg, max(float(interval), 0.1)
        self._stop_event = threading.Event()
        self.cpu, self.memory = [], []
        self.started = time.monotonic()
        self.cpu0, self.throttled0, self.oom0 = cg.cpu_usec(), cg.throttled_usec(), cg.oom_kills()
        self.memory0 = cg.memory_bytes()
        self._last = (self.started, self.cpu0)

    def _sample(self) -> None:
        now, cpu, mem = time.monotonic(), self.cg.cpu_usec(), self.cg.memory_bytes()
        last_t, last_cpu = self._last
        if cpu is not None and last_cpu is not None and now > last_t:
            self.cpu.append(max(cpu - last_cpu, 0) / 1e6 / (now - last_t))
        if mem is not None:
            self.memory.append(mem)
        self._last = (now, cpu)

    def run(self) -> None:
        while not self._stop_event.wait(self.interval):
            try:
                self._sample()
            except Exception:  # noqa: BLE001 - medir nunca pode derrubar o script
                pass

    def stop(self) -> dict:
        self._stop_event.set()
        if self.ident is not None:  # a thread pode nem ter começado
            self.join(timeout=5)
        try:
            self._sample()  # última amostra: execuções mais curtas que o intervalo também medem
        except Exception:  # noqa: BLE001
            pass
        duration = time.monotonic() - self.started
        cpu_now, throttled, oom = self.cg.cpu_usec(), self.cg.throttled_usec(), self.cg.oom_kills()
        cpu_total = (cpu_now - self.cpu0) / 1e6 if None not in (cpu_now, self.cpu0) else None
        mem_mb = [m / MB for m in self.memory]
        cpu = {
            "media_nucleos": round(cpu_total / duration, 2) if cpu_total is not None and duration > 0 else None,
            "p95_nucleos": round(percentile(self.cpu, 95), 2),
            "pico_nucleos": round(max(self.cpu, default=0.0), 2),
            "tempo_s": round(cpu_total, 1) if cpu_total is not None else None,
        }
        if None not in (throttled, self.throttled0) and duration > 0:
            cpu["limitada_pct"] = round(min(100.0, (throttled - self.throttled0) / 1e6 / duration * 100), 1)
        memory = {
            "inicio_mb": round(self.memory0 / MB) if self.memory0 is not None else None,
            "media_mb": round(sum(mem_mb) / len(mem_mb)) if mem_mb else None,
            "p95_mb": round(percentile(mem_mb, 95)) if mem_mb else None,
            "pico_mb": round(max(mem_mb)) if mem_mb else None,
        }
        if None not in (oom, self.oom0):
            memory["oom_kills"] = oom - self.oom0
        return {"duracao_s": round(duration, 1), "amostras": len(self.memory), "intervalo_s": self.interval,
                "cpu": cpu, "memoria": memory}


# --- formatação -----------------------------------------------------------------

def _num(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def fmt_mb(mb: Optional[float]) -> str:
    if mb is None:
        return "?"
    return f"{_num(mb / 1024)} GB" if mb >= 1024 else f"{round(mb)} MB"


def fmt_cores(value: Optional[float]) -> str:
    if value is None:
        return "?"
    return f"{_num(value)} núcleo" + ("s" if value >= 2 else "")


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _timestamp() -> str:
    return time.strftime("[%Y-%m-%d %H:%M:%S]")


def human_lines(summary: dict) -> list:
    """Resumo legível de uma execução (o mesmo dict gravado em RESOURCE_LOG)."""
    cpu, mem, lim = summary.get("cpu", {}), summary.get("memoria", {}), summary.get("limites", {})
    head = (f"📊 Recursos de {summary.get('rotulo', 'script')} "
            f"(exit {summary.get('exit_code')}, {fmt_duration(summary.get('duracao_s', 0))}; "
            f"{summary.get('fonte', '?')}, {summary.get('amostras', 0)} amostras)")
    if not summary.get("medido", True):
        return [head, f"   ⚠️  medição indisponível: {summary.get('motivo', '')}"]
    cpu_limit = f" (limite {fmt_cores(lim['cpu_nucleos'])})" if lim.get("cpu_nucleos") else " (sem limite)"
    lines = [head, f"   CPU: média {fmt_cores(cpu.get('media_nucleos'))} · p95 {fmt_cores(cpu.get('p95_nucleos'))}"
                   f" · pico {fmt_cores(cpu.get('pico_nucleos'))}{cpu_limit}"]
    mem_line = (f"   memória: início {fmt_mb(mem.get('inicio_mb'))} · média {fmt_mb(mem.get('media_mb'))}"
                f" · pico {fmt_mb(mem.get('pico_mb'))}")
    if lim.get("memoria_mb") and mem.get("pico_mb") is not None:
        mem_line += f" (limite {fmt_mb(lim['memoria_mb'])}, {round(mem['pico_mb'] / lim['memoria_mb'] * 100)}%)"
    else:
        mem_line += " (sem limite)"
    lines.append(mem_line)
    if summary.get("duracao_s", 0) < SHORT_RUN_SECS:
        lines.append(f"   ℹ️  execução curta ({fmt_duration(summary.get('duracao_s', 0))}): a CPU aqui é quase só a partida "
                     "do Python; para dimensionar, use execuções reais (resource_usage.py report)")
    if cpu.get("limitada_pct", 0) >= 10:
        lines.append(f"   ⚠️  a CPU bateu no limite em {_num(cpu['limitada_pct'], 0)}% do tempo: "
                     "a necessidade real pode ser maior que o medido")
    if mem.get("oom_kills"):
        lines.append(f"   ❌ o kernel matou {mem['oom_kills']} processo(s) por falta de memória (OOM): "
                     "aumente a memória do container")
    sug = summary.get("sugestao")
    if sug:
        lines.append(f"   💡 reserva sugerida: memória {fmt_mb(sug['memoria_mb'])} (pico + 25%) · "
                     f"CPU {fmt_cores(sug['cpu_nucleos'])} (p95)")
    return lines


# --- run --------------------------------------------------------------------------

def _exit_code(returncode: int) -> int:
    return 128 - returncode if returncode < 0 else returncode


def _record(summary: dict) -> None:
    path = os.getenv("RESOURCE_LOG", "/app/logs/resources.jsonl")
    if not path:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"{_timestamp()} ⚠️  não gravou o resumo de recursos em {path}: {exc}", flush=True)


def default_label(cmd: list) -> str:
    """Nome do script (o último argumento .py) ou do programa."""
    script = next((a for a in reversed(cmd) if a.endswith(".py")), "")
    return Path(script or cmd[0]).name


def build_summary(label: str, exit_code: int, measured: Optional[dict], cg: Optional[Cgroup],
                  started_at: str, duration: float) -> dict:
    summary = {"rotulo": label, "inicio": started_at, "exit_code": exit_code,
               "worker_id": os.getenv("WORKER_ID", ""), "fonte": cg.source if cg else "nenhuma"}
    if measured is None:
        summary.update({"medido": False, "duracao_s": round(duration, 1), "amostras": 0,
                        "motivo": "sem cgroup de CPU/memória legível neste ambiente"})
        return summary
    summary.update(measured)
    summary["limites"] = limits(cg)
    peak, p95 = measured["memoria"].get("pico_mb"), measured["cpu"].get("p95_nucleos")
    if peak is not None and p95 is not None:
        summary["sugestao"] = suggestion(peak, p95)
    return summary


def run(cmd: list, label: str, interval: float) -> int:
    """Roda ``cmd`` (stdin/stdout/stderr herdados), mede e devolve o exit code dele."""
    cg = Cgroup.detect()
    started_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    began = time.monotonic()
    sampler = None
    if cg is not None:
        try:
            sampler = Sampler(cg, interval)
            sampler.start()
        except Exception:  # noqa: BLE001
            sampler = None

    # Sob o entrypoint, sinais de parada (timeout do loop, Ctrl+C) chegam ao grupo de processos
    # inteiro, script incluído: aqui só esperamos ele terminar para escrever o resumo. Como PID 1
    # (`docker run imagem python /app/resource_usage.py run -- ...`), repassamos ao script.
    forward = os.getpid() == 1
    try:
        proc = subprocess.Popen(cmd)
    except OSError as exc:
        print(f"{_timestamp()} ❌ não executou {cmd[0]}: {exc}", flush=True)
        if sampler:
            sampler.stop()
        return 127

    def on_signal(signum, _frame):
        if forward and proc.poll() is None:
            proc.send_signal(signum)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(sig, on_signal)
        except (OSError, ValueError):
            pass
    returncode = proc.wait()
    code = _exit_code(returncode)

    try:
        measured = sampler.stop() if sampler else None
        summary = build_summary(label, code, measured, cg, started_at, time.monotonic() - began)
        ts = _timestamp()
        print("\n".join(f"{ts} {line}" if i == 0 else line for i, line in enumerate(human_lines(summary))), flush=True)
        print("RESOURCE_SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
        _record(summary)
    except Exception as exc:  # noqa: BLE001 - o resumo nunca muda o resultado do script
        print(f"{_timestamp()} ⚠️  resumo de recursos falhou: {exc}", flush=True)
    return code


# --- report -----------------------------------------------------------------------

def aggregate(summaries: list) -> dict:
    """Junta várias execuções (por rótulo): o que reservar para o pior caso visto."""
    measured = [s for s in summaries if s.get("medido", True) and s.get("memoria", {}).get("pico_mb") is not None]
    if not measured:
        return {"execucoes": len(summaries), "medidas": 0}
    peaks = [s["memoria"]["pico_mb"] for s in measured]
    means = [s["memoria"]["media_mb"] for s in measured if s["memoria"].get("media_mb") is not None]
    cpu_means = [s["cpu"]["media_nucleos"] for s in measured if s["cpu"].get("media_nucleos") is not None]
    cpu_p95 = [s["cpu"]["p95_nucleos"] for s in measured if s["cpu"].get("p95_nucleos") is not None]
    durations = [s.get("duracao_s", 0) for s in measured]
    return {
        "execucoes": len(summaries),
        "medidas": len(measured),
        "falhas": sum(1 for s in summaries if s.get("exit_code") not in (0, None)),
        "duracao_media_s": round(sum(durations) / len(durations), 1),
        "duracao_max_s": max(durations),
        "cpu_media_nucleos": round(sum(cpu_means) / len(cpu_means), 2) if cpu_means else None,
        "cpu_p95_nucleos": round(percentile(cpu_p95, 95), 2) if cpu_p95 else None,
        "cpu_pico_nucleos": max((s["cpu"].get("pico_nucleos") or 0 for s in measured), default=0),
        "memoria_media_mb": round(sum(means) / len(means)) if means else None,
        "memoria_pico_medio_mb": round(sum(peaks) / len(peaks)),
        "memoria_pico_max_mb": max(peaks),
        "oom_kills": sum(s["memoria"].get("oom_kills") or 0 for s in measured),
        "sugestao": suggestion(max(peaks), percentile(cpu_p95, 95) if cpu_p95 else 0),
    }


def report(path: Path) -> int:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"❌ não abriu {path}: {exc}")
        return 1
    summaries = []
    for line in lines:
        try:
            summaries.append(json.loads(line))
        except ValueError:
            continue
    if not summaries:
        print(f"nenhuma execução registrada em {path}")
        return 1
    groups: dict = {}
    for s in summaries:
        groups.setdefault(s.get("rotulo", "?"), []).append(s)
    out = {}
    for label, items in sorted(groups.items()):
        agg = out[label] = aggregate(items)
        print(f"📊 {label}: {agg['execucoes']} execução(ões), {agg.get('falhas', 0)} com erro")
        if not agg.get("medidas"):
            print("   medição indisponível")
            continue
        print(f"   duração: média {fmt_duration(agg['duracao_media_s'])} · máxima {fmt_duration(agg['duracao_max_s'])}")
        print(f"   CPU: média {fmt_cores(agg['cpu_media_nucleos'])} · p95 {fmt_cores(agg['cpu_p95_nucleos'])}"
              f" · pico {fmt_cores(agg['cpu_pico_nucleos'])}")
        print(f"   memória: média {fmt_mb(agg['memoria_media_mb'])} · pico médio {fmt_mb(agg['memoria_pico_medio_mb'])}"
              f" · pico máximo {fmt_mb(agg['memoria_pico_max_mb'])}")
        if agg["oom_kills"]:
            print(f"   ❌ {agg['oom_kills']} processo(s) mortos por falta de memória (OOM)")
        sug = agg["sugestao"]
        print(f"   💡 reserva sugerida: memória {fmt_mb(sug['memoria_mb'])} · CPU {fmt_cores(sug['cpu_nucleos'])}")
    print("RESOURCE_REPORT " + json.dumps(out, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="roda um comando e mede (use -- antes do comando)")
    p_run.add_argument("--label", default="")
    p_run.add_argument("--interval", type=float, default=float(os.getenv("RESOURCE_SAMPLE_SECS", "1") or 1))
    p_report = sub.add_parser("report", help="média e picos das execuções registradas")
    p_report.add_argument("path", nargs="?", default=os.getenv("RESOURCE_LOG") or "/app/logs/resources.jsonl")
    sub.add_parser("limits", help="limites de CPU/memória do container")

    cmd = []
    if "--" in argv:
        cut = argv.index("--")
        argv, cmd = argv[:cut], argv[cut + 1:]
    args = parser.parse_args(argv)
    if args.cmd == "run":
        if not cmd:
            parser.error("faltou o comando: resource_usage.py run -- python script.py")
        return run(cmd, args.label or default_label(cmd), args.interval)
    if args.cmd == "report":
        return report(Path(args.path))
    print(json.dumps(limits(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
