"""Plano determinístico e resumo de recursos na janela HTTP."""

import csv
from datetime import datetime
import statistics


def make_plan(rams, users, repetitions):
    plan = []
    for repetition in range(1, repetitions + 1):
        offset = (repetition - 1) % len(users)
        demand_order = users[offset:] + users[:offset]
        for index, demand in enumerate(demand_order):
            shift = (repetition - 1 + index) % len(rams)
            ram_order = rams[shift:] + rams[:shift]
            if repetition % 2 == 0:
                ram_order.reverse()
            plan.extend({"repetition": repetition, "ram_mib": ram, "users": demand} for ram in ram_order)
    return plan


def window_samples(path, start, end):
    if not path.exists() or start is None:
        return []
    with path.open() as handle:
        return [row for row in csv.DictReader(handle)
                if start <= datetime.fromisoformat(row["timestamp_utc"]).timestamp() <= end]


def peak(rows, key):
    values = [float(row[key]) for row in rows if row.get(key) not in (None, "")]
    return max(values) if values else None


def summarize_resources(point, window, cpus, interval):
    rows = window_samples(point / "monitor.csv", window["start_epoch"], window["end_epoch"])
    generator = window_samples(point / "generator-monitor.csv", window["start_epoch"], window["end_epoch"])
    cpu = None
    if len(rows) >= 2:
        elapsed = float(rows[-1]["elapsed_seconds"]) - float(rows[0]["elapsed_seconds"])
        cpu = (int(rows[-1]["container_cpu_usage_usec"]) - int(rows[0]["container_cpu_usage_usec"])) / elapsed / (cpus * 10000)
    generator_cpu = [float(row["app_cpu_percent"]) for row in generator if row["app_cpu_percent"]]
    start_gap = end_gap = None
    if rows:
        start_gap = datetime.fromisoformat(rows[0]["timestamp_utc"]).timestamp() - window["start_epoch"]
        end_gap = window["end_epoch"] - datetime.fromisoformat(rows[-1]["timestamp_utc"]).timestamp()
    timestamps = [datetime.fromisoformat(row["timestamp_utc"]).timestamp() for row in rows]
    max_gap = max((right - left for left, right in zip(timestamps, timestamps[1:])), default=None)
    memory = peak(rows, "container_memory_bytes")
    rss = peak(rows, "app_rss_bytes")
    return {
        "cpu_percent_of_limit": cpu,
        "memory_peak_mib": memory / 2**20 if memory is not None else None,
        "app_rss_peak_mib": rss / 2**20 if rss is not None else None,
        "generator_cpu_percent_of_one_core": statistics.mean(generator_cpu) if generator_cpu else None,
        "resource_samples": len(rows), "resource_start_gap_seconds": start_gap,
        "resource_end_gap_seconds": end_gap,
        "resource_max_gap_seconds": max_gap,
        "resource_window_covered": bool(len(rows) >= 2 and max(start_gap, end_gap, max_gap) <= interval * 2),
        "sampled_oom_kill_total": int(rows[-1]["container_oom_kill"]) if rows and rows[-1]["container_oom_kill"] else None,
        "sampled_oom_kill_delta": int(rows[-1]["container_oom_kill"]) - int(rows[0]["container_oom_kill"])
        if rows and rows[-1]["container_oom_kill"] and rows[0]["container_oom_kill"] else None,
    }
