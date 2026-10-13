"""Read and audit the raw VirtualBox CPU-bound experiments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import pandas as pd


CPUS = (1, 2, 4, 6, 8)
SELECTED_REPS = {
    1: (1, 2, 3),
    2: (1, 2, 4),
    4: (1, 4, 5),
    6: (1, 2, 3),
    8: (2, 3, 4),
}
EXCLUSION_REASONS = {
    (2, 3): "Monitor terminou 7 s antes da carga",
    (4, 2): "Monitor terminou 5 s antes do fim da carga",
    (4, 3): "Sem sobreposição entre monitor e carga",
    (8, 1): "Sem sobreposição entre monitor e carga",
}
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
CASE_PATTERN = re.compile(r"^vbox-(\d+)cpu-")
LOG_TIME_PATTERN = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+)\]")
MONITOR_COLUMNS = {"timestamp_utc", "system_cpu_percent", "ram_used_bytes", "app_rss_bytes"}
HISTORY_COLUMNS = {"Timestamp", "Name", "Requests/s", "95%", "Total Request Count"}
MIN_SELECTED_SAMPLES = 57  # At least 95% of a 60-second, one-sample-per-second run.
EXPECTED_WORKLOAD = {
    "users": "32", "spawn_rate": "32", "duration": "60s",
    "data_size_mb": "10", "iterations": "100", "wait_seconds": "0",
}


@dataclass
class ExperimentData:
    runs: pd.DataFrame
    monitor: pd.DataFrame
    history: pd.DataFrame
    audit: pd.DataFrame


def _required_columns(frame: pd.DataFrame, columns: set[str], path: Path) -> None:
    missing = columns.difference(frame.columns)
    if missing:
        raise ValueError(f"Colunas ausentes em {path}: {', '.join(sorted(missing))}")


def _check_workload(path: Path) -> None:
    settings = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            settings[key] = value
    for key, expected in EXPECTED_WORKLOAD.items():
        if settings.get(key) != expected:
            raise ValueError(f"Carga incompatível em {path}: {key}={settings.get(key)!r}, esperado {expected!r}")


def _log_window(lines: list[str], path: Path) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = end = None
    for line in lines:
        if "locust.main: Starting Locust" in line:
            match = LOG_TIME_PATTERN.match(line)
            if match:
                start = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S,%f")
        if "locust.main: Shutting down" in line:
            match = LOG_TIME_PATTERN.match(line)
            if match:
                end = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S,%f")
    if start is None or end is None or end <= start:
        raise ValueError(f"Janela de carga ausente ou inválida em {path}")
    return (pd.Timestamp(start.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)),
            pd.Timestamp(end.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)))


def parse_locust_log(path: Path) -> dict[str, float | int | pd.Timestamp]:
    """Return final HTTP metrics; periodic Locust CSVs are not final totals."""
    lines = path.read_text().splitlines()
    start, end = _log_window(lines, path)
    percentile_at = next((i for i, line in enumerate(lines)
                          if "Response time percentiles (approximated)" in line), None)
    if percentile_at is None:
        raise ValueError(f"Tabela de percentis/p95 ausente em {path}")
    summary_rows = [line for line in lines[:percentile_at]
                    if line.lstrip().startswith("POST") and "/benchmark" in line]
    percentile_rows = [line for line in lines[percentile_at + 1:]
                       if line.lstrip().startswith("POST") and "/benchmark" in line]
    if not summary_rows or not percentile_rows:
        raise ValueError(f"Resumo final ou p95 ausente em {path}")
    try:
        left, latency, rates = (part.split() for part in summary_rows[-1].split("|"))
        percentiles = percentile_rows[-1].split()
        if left[:2] != ["POST", "/benchmark"] or percentiles[:2] != ["POST", "/benchmark"]:
            raise ValueError("endpoint inesperado")
        count = int(left[2])
        if int(percentiles[-1]) != count:
            raise ValueError("contagens divergentes no log final")
        values = {
            "request_count": count,
            "failure_count": int(left[3].split("(")[0]),
            "average_latency_ms": int(latency[0]),
            "min_latency_ms": int(latency[1]),
            "max_latency_ms": int(latency[2]),
            "median_latency_ms": int(latency[3]),
            "requests_per_second": float(rates[0]),
            "p95_latency_ms": int(percentiles[7]),
            "window_start_utc": start,
            "window_end_utc": end,
        }
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"Resumo final inválido em {path}: {exc}") from exc
    if count < 0 or values["failure_count"] < 0 or values["failure_count"] > count:
        raise ValueError(f"Contagens inválidas em {path}")
    return values


def _vmstat_metrics(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {"swap_max_kib": 0, "swap_in_kib": 0, "swap_out_kib": 0}
    numeric = [line.split() for line in path.read_text().splitlines()
               if re.match(r"^\s*\d+\s+\d+\s+\d+", line)]
    # vmstat's first numeric row is an average since boot, not an interval.
    samples = numeric[1:]
    if not samples:
        return {"swap_max_kib": 0, "swap_in_kib": 0, "swap_out_kib": 0}
    if any(len(row) < 8 for row in samples):
        raise ValueError(f"Linhas incompletas em {path}")
    return {
        "swap_max_kib": max(int(row[2]) for row in samples),
        "swap_in_kib": sum(int(row[6]) for row in samples),
        "swap_out_kib": sum(int(row[7]) for row in samples),
    }


def _load_monitor(path: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    frame = pd.read_csv(path)
    _required_columns(frame, MONITOR_COLUMNS, path)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    if frame["timestamp_utc"].isna().any():
        raise ValueError(f"Horário inválido em {path}")
    for column in ("system_cpu_percent", "ram_used_bytes", "app_rss_bytes"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any() or (frame[column] < 0).any():
            raise ValueError(f"Métrica inválida {column} em {path}")
    frame = frame.loc[frame.timestamp_utc.between(start, end)].copy()
    frame["window_start_utc"] = start
    frame["window_end_utc"] = end
    frame["seconds_from_start"] = (frame.timestamp_utc - start).dt.total_seconds()
    frame["ram_used_mib"] = frame.ram_used_bytes / 2**20
    frame["app_rss_mib"] = frame.app_rss_bytes / 2**20
    return frame


def _load_history(path: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    frame = pd.read_csv(path)
    _required_columns(frame, HISTORY_COLUMNS, path)
    frame = frame.loc[frame.Name.eq("Aggregated")].copy()
    frame["Timestamp"] = pd.to_numeric(frame["Timestamp"], errors="coerce")
    frame["requests_per_second"] = pd.to_numeric(frame["Requests/s"], errors="coerce")
    frame["p95_latency_ms"] = pd.to_numeric(frame["95%"], errors="coerce")
    frame["request_count"] = pd.to_numeric(frame["Total Request Count"], errors="coerce")
    frame = frame.dropna(subset=["Timestamp", "requests_per_second", "request_count"])
    frame["timestamp_utc"] = pd.to_datetime(frame.Timestamp, unit="s", utc=True)
    frame = frame.loc[frame.timestamp_utc.between(start, end)]
    frame = frame.sort_values("Timestamp").drop_duplicates("Timestamp", keep="last").copy()
    if frame.empty or (frame.requests_per_second < 0).any() or (frame.request_count < 0).any():
        raise ValueError(f"Histórico válido ausente ou com valores negativos em {path}")
    frame["seconds_from_start"] = (frame.timestamp_utc - start).dt.total_seconds()
    return frame


def load_experiments(root: Path) -> ExperimentData:
    """Discover the five VirtualBox cases and preserve selected/excluded runs."""
    root = Path(root)
    cases: dict[int, Path] = {}
    for case in root.glob("vbox-*cpu-*"):
        match = CASE_PATTERN.match(case.name)
        if case.is_dir() and match:
            cpu = int(match.group(1))
            if cpu in cases:
                raise ValueError(f"Mais de um diretório para {cpu} vCPUs")
            cases[cpu] = case
    if set(cases) != set(CPUS):
        raise ValueError(f"São necessários os casos {CPUS}; encontrados {sorted(cases)} em {root}")

    runs, monitors, histories, audits = [], [], [], []
    for cpu in CPUS:
        case = cases[cpu]
        reps = sorted((path for path in case.glob("rep[0-9]*") if path.is_dir()),
                      key=lambda path: int(path.name[3:]))
        found = {int(path.name[3:]) for path in reps}
        if not set(SELECTED_REPS[cpu]).issubset(found):
            raise FileNotFoundError(f"Repetição selecionada ausente em {case}")
        for rep_dir in reps:
            rep = int(rep_dir.name[3:])
            selected = rep in SELECTED_REPS[cpu]
            log = rep_dir / "locust.log"
            monitor = case / f"rep{rep}-monitor.csv"
            vmstat = case / f"rep{rep}-vmstat.txt"
            history = rep_dir / "locust_stats_history.csv"
            config = rep_dir / "config.txt"
            if selected:
                for required in (log, monitor, vmstat, history, config):
                    if not required.is_file():
                        raise FileNotFoundError(required)
                _check_workload(config)
            metrics = parse_locust_log(log) if log.is_file() else {}
            overlap = pd.DataFrame()
            monitor_error = ""
            if monitor.is_file() and metrics:
                try:
                    overlap = _load_monitor(monitor, metrics["window_start_utc"], metrics["window_end_utc"])
                except ValueError as exc:
                    if selected:
                        raise
                    monitor_error = str(exc)
            if selected and overlap.empty:
                raise ValueError(f"Sem sobreposição entre monitor e carga: {monitor}")
            if selected and len(overlap) < MIN_SELECTED_SAMPLES:
                raise ValueError(f"Cobertura insuficiente do monitor ({len(overlap)} amostras): {monitor}")
            swap = _vmstat_metrics(vmstat)
            common = {"cpu": cpu, "rep": rep, "selected": selected, "source": str(case),
                      "overlap_samples": len(overlap)}
            run = {**common, **metrics, **swap,
                   "cpu_percent": float(overlap.system_cpu_percent.mean()) if not overlap.empty else float("nan"),
                   "ram_max_mib": float(overlap.ram_used_mib.max()) if not overlap.empty else float("nan"),
                   "app_rss_max_mib": float(overlap.app_rss_mib.max()) if not overlap.empty else float("nan")}
            runs.append(run)
            audits.append({**common, **swap, "has_log": log.is_file(), "has_monitor": monitor.is_file(),
                           "has_vmstat": vmstat.is_file(), "has_history": history.is_file(),
                           "has_config": config.is_file(), "monitor_error": monitor_error,
                           "reason": "" if selected else EXCLUSION_REASONS.get((cpu, rep), "Não selecionada")})
            if selected:
                overlap["cpu"] = cpu
                overlap["rep"] = rep
                monitors.append(overlap)
                temporal = _load_history(history, metrics["window_start_utc"], metrics["window_end_utc"])
                temporal["cpu"] = cpu
                temporal["rep"] = rep
                histories.append(temporal)
    return ExperimentData(pd.DataFrame(runs), pd.concat(monitors, ignore_index=True),
                          pd.concat(histories, ignore_index=True), pd.DataFrame(audits))


def summarize_selected(runs: pd.DataFrame) -> pd.DataFrame:
    """Compute one median per vCPU from the selected repetitions only."""
    chosen = runs.loc[runs.selected].copy()
    if chosen.empty:
        raise ValueError("Nenhuma repetição selecionada")
    metrics = ["requests_per_second", "average_latency_ms", "p95_latency_ms",
               "cpu_percent", "ram_max_mib", "request_count", "failure_count"]
    _required_columns(chosen, set(metrics) | {"cpu"}, Path("runs"))
    summary = chosen.groupby("cpu", as_index=False)[metrics].median().sort_values("cpu")
    totals = chosen.groupby("cpu", as_index=False).agg(requests_total=("request_count", "sum"),
                                                       failures_total=("failure_count", "sum"))
    return summary.merge(totals, on="cpu")
