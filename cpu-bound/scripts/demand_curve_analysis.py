"""Read demand runs and align HTTP and guest metrics in one steady window."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re

import pandas as pd

from scripts.virtualbox_analysis import _vmstat_metrics, parse_locust_log


CPUS = (1, 2, 4, 6, 8)
BASE_USERS = (1, 2, 4, 8, 16)
CASE_PATTERN = re.compile(r"^demand-vbox-(\d+)cpu-")
METRICS = ("cpu_percent", "app_cpu_percent", "requests_per_second",
           "average_latency_ms", "p95_latency_ms", "ram_mean_mib",
           "ram_available_mean_mib", "ram_max_mib")


def _required(frame: pd.DataFrame, columns: set[str], path: Path) -> None:
    missing = columns.difference(frame.columns)
    if missing:
        raise ValueError(f"Colunas ausentes em {path}: {', '.join(sorted(missing))}")


def _config(path: Path, manifest: dict, users: int) -> None:
    settings = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    expected = {
        "users": users, "spawn_rate": manifest["spawn_rate"],
        "duration": f'{manifest["duration_seconds"]}s',
        "data_size_mb": manifest["data_size_mb"], "iterations": manifest["iterations"],
        "wait_seconds": 0,
    }
    for key, value in expected.items():
        if settings.get(key) != str(value):
            raise ValueError(f"Configuração incompatível em {path}: {key}")


def analyse_run(run_dir: Path, manifest: dict) -> dict:
    """Use completions for throughput and fully contained successes for latency."""
    run_dir = Path(run_dir)
    users = int(run_dir.parent.name.removeprefix("u"))
    rep = int(run_dir.name.removeprefix("rep"))
    status = json.loads((run_dir / "run-status.json").read_text())
    if status.get("locust_exit_code") != 0 or status.get("error"):
        raise ValueError(f"Execução falhou: {run_dir}: {status.get('error')}")
    _config(run_dir / "config.txt", manifest, users)

    history_path = run_dir / "locust_stats_history.csv"
    history = pd.read_csv(history_path)
    _required(history, {"Timestamp", "User Count", "Name"}, history_path)
    history = history.loc[history.Name.eq("Aggregated")].copy()
    history["Timestamp"] = pd.to_numeric(history["Timestamp"], errors="coerce")
    history["User Count"] = pd.to_numeric(history["User Count"], errors="coerce")
    history = history.dropna(subset=["Timestamp", "User Count"])
    full = history.loc[history["User Count"].eq(users)].sort_values("Timestamp")
    if full.empty:
        raise ValueError(f"Número completo de usuários ausente em {history_path}")
    start_full = float(full.Timestamp.iloc[0])
    end_full = float(full.Timestamp.iloc[-1])
    if (history.loc[history.Timestamp.between(start_full, end_full), "User Count"] < users).any():
        raise ValueError(f"Usuários diminuíram durante a carga: {history_path}")
    start = pd.to_datetime(start_full + manifest["warmup_seconds"], unit="s", utc=True)
    end = pd.to_datetime(end_full - manifest["cooldown_seconds"], unit="s", utc=True)
    seconds = (end - start).total_seconds()
    if seconds < 60:
        raise ValueError(f"Janela estável curta ({seconds:.0f} s): {run_dir}")

    monitor_path = run_dir / "monitor.csv"
    monitor = pd.read_csv(monitor_path)
    _required(monitor, {"timestamp_utc", "system_cpu_percent", "app_cpu_percent",
                        "ram_used_bytes", "ram_available_bytes"}, monitor_path)
    monitor["timestamp_utc"] = pd.to_datetime(monitor.timestamp_utc, utc=True, errors="coerce")
    for field in ("system_cpu_percent", "app_cpu_percent", "ram_used_bytes", "ram_available_bytes"):
        monitor[field] = pd.to_numeric(monitor[field], errors="coerce")
    monitor = monitor.loc[monitor.timestamp_utc.between(start, end)].copy()
    if len(monitor) < math.ceil(seconds * 0.95):
        raise ValueError(f"Cobertura insuficiente do monitor ({len(monitor)} amostras): {monitor_path}")
    if monitor[["system_cpu_percent", "app_cpu_percent", "ram_used_bytes", "ram_available_bytes"]].isna().any().any():
        raise ValueError(f"Amostra inválida no monitor: {monitor_path}")
    if (monitor[["system_cpu_percent", "app_cpu_percent", "ram_used_bytes", "ram_available_bytes"]] < 0).any().any():
        raise ValueError(f"Métrica negativa no monitor: {monitor_path}")

    requests_path = run_dir / "requests.csv"
    requests = pd.read_csv(requests_path)
    _required(requests, {"timestamp_utc", "started_utc", "method", "name",
                         "response_time_ms", "failed"}, requests_path)
    requests["timestamp_utc"] = pd.to_datetime(requests.timestamp_utc, utc=True, errors="coerce", format="ISO8601")
    requests["started_utc"] = pd.to_datetime(requests.started_utc, utc=True, errors="coerce", format="ISO8601")
    requests["response_time_ms"] = pd.to_numeric(requests.response_time_ms, errors="coerce")
    requests["failed"] = pd.to_numeric(requests.failed, errors="coerce")
    if requests[["timestamp_utc", "started_utc", "response_time_ms", "failed"]].isna().any().any():
        raise ValueError(f"Resposta inválida em {requests_path}")
    if (requests.response_time_ms < 0).any() or not requests.failed.isin((0, 1)).all():
        raise ValueError(f"Tempo ou falha inválidos em {requests_path}")
    if not requests.method.eq("POST").all() or not requests.name.eq("/benchmark").all():
        raise ValueError(f"Endpoint inesperado em {requests_path}")
    completed = requests.loc[requests.timestamp_utc.between(start, end)]
    completed_ok = completed.loc[completed.failed.eq(0)]
    latency = completed_ok.loc[completed_ok.started_utc.ge(start), "response_time_ms"]
    if latency.empty:
        raise ValueError(f"Nenhuma resposta válida inteiramente na janela: {requests_path}")
    swap = _vmstat_metrics(run_dir / "vmstat.txt")
    return {
        "vcpus": int(manifest["vcpus"]), "users": users, "rep": rep,
        "window_start_utc": start.isoformat(), "window_end_utc": end.isoformat(),
        "window_seconds": seconds, "monitor_samples": len(monitor),
        "request_count": len(completed), "failure_count": int(completed.failed.sum()),
        "requests_per_second": len(completed_ok) / seconds,
        "average_latency_ms": float(latency.mean()), "p95_latency_ms": float(latency.quantile(0.95)),
        "cpu_percent": float(monitor.system_cpu_percent.mean()),
        "app_cpu_percent": float(monitor.app_cpu_percent.mean()),
        "ram_mean_mib": float(monitor.ram_used_bytes.mean() / 2**20),
        "ram_max_mib": float(monitor.ram_used_bytes.max() / 2**20),
        "ram_available_mean_mib": float(monitor.ram_available_bytes.mean() / 2**20),
        **swap,
    }


def summarize_runs(runs: pd.DataFrame) -> pd.DataFrame:
    """Median and interquartile range across the three repetitions of each point."""
    if runs.empty:
        raise ValueError("Nenhuma execução válida")
    grouped = runs.groupby(["vcpus", "users"], sort=True)
    rows = []
    for (cpu, users), case in grouped:
        row = {"vcpus": cpu, "users": users, "repetitions": len(case),
               "requests_total": int(case.request_count.sum()),
               "failures_total": int(case.failure_count.sum())}
        for metric in METRICS:
            row[metric] = float(case[metric].median())
            row[metric + "_q25"] = float(case[metric].quantile(0.25))
            row[metric + "_q75"] = float(case[metric].quantile(0.75))
        rows.append(row)
    return pd.DataFrame(rows)


def collect_runs(case_dirs: list[Path], *, require_complete: bool = True) -> pd.DataFrame:
    """Validate one real, comparable run per vCPU scenario before aggregation."""
    if not case_dirs:
        raise ValueError("Nenhuma pasta de experimentos de demanda encontrada")
    manifests: list[tuple[Path, dict]] = []
    seen_cpu: set[int] = set()
    for case in map(Path, case_dirs):
        match = CASE_PATTERN.match(case.name)
        if match is None:
            raise ValueError(f"Pasta não é uma bateria definitiva de demanda: {case}")
        manifest = json.loads((case / "manifest.json").read_text())
        cpu = int(manifest["vcpus"])
        if manifest.get("smoke"):
            raise ValueError(f"Não incluir smoke como medição definitiva: {case}")
        if cpu != int(match.group(1)) or cpu not in CPUS or cpu in seen_cpu:
            raise ValueError(f"Cenário duplicado ou incoerente: {case}")
        if int(manifest["repetitions"]) < 3:
            raise ValueError(f"São necessárias três repetições: {case}")
        if int(manifest["workers"]) != 8 or int(manifest["ram_mib"]) != 1024:
            raise ValueError(f"Workers ou RAM incompatíveis: {case}")
        if not set(BASE_USERS).issubset(set(map(int, manifest["users"]))):
            raise ValueError(f"Níveis básicos de demanda incompletos: {case}")
        provenance = "separate-1cpu-vm" if cpu == 1 else "2-to-8cpu-snapshot-chain"
        if manifest.get("vm_provenance") != provenance:
            raise ValueError(f"Proveniência da VM não documentada: {case}")
        seen_cpu.add(cpu)
        manifests.append((case, manifest))
    if require_complete and seen_cpu != set(CPUS):
        raise ValueError(f"Cenários de vCPU ausentes: {sorted(set(CPUS) - seen_cpu)}")
    comparison_fields = ("duration_seconds", "data_size_mb", "iterations", "spawn_rate",
                         "wait_seconds", "workers", "ram_mib", "warmup_seconds", "cooldown_seconds")
    reference = {key: manifests[0][1][key] for key in comparison_fields}
    for case, manifest in manifests[1:]:
        if any(manifest[key] != value for key, value in reference.items()):
            raise ValueError(f"Parâmetros não comparáveis: {case}")
    rows = []
    for case, manifest in manifests:
        for users in sorted(map(int, manifest["users"])):
            for rep in range(1, int(manifest["repetitions"]) + 1):
                run_dir = case / f"u{users}" / f"rep{rep}"
                if not run_dir.is_dir():
                    raise ValueError(f"Execução ausente: {run_dir}")
                final = parse_locust_log(run_dir / "locust.log")
                requests = pd.read_csv(run_dir / "requests.csv", usecols=["failed"])
                if len(requests) != final["request_count"] or int(requests.failed.sum()) != final["failure_count"]:
                    raise ValueError(f"Contagens de respostas divergem do log final: {run_dir}")
                row = analyse_run(run_dir, manifest)
                row["case_dir"] = str(case)
                rows.append(row)
    return pd.DataFrame(rows).sort_values(["vcpus", "users", "rep"]).reset_index(drop=True)
