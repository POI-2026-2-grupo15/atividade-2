import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import signal
import threading
import time

import psutil


def positive_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("Informe um número finito > 0")
    return result


def process_tree(root: psutil.Process | None) -> list[psutil.Process]:
    if root is None:
        return []
    try:
        if not root.is_running():
            return []
        return [root, *root.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/monitor.csv"))
    parser.add_argument("--interval", type=positive_float, default=1.0)
    parser.add_argument("--duration", type=positive_float, help="Segundos; padrão: até Ctrl+C/SIGTERM")
    parser.add_argument("--pid", type=int, help="PID mestre do Uvicorn; inclui descendentes")
    args = parser.parse_args()
    try:
        root = psutil.Process(args.pid) if args.pid is not None else None
    except (psutil.NoSuchProcess, ValueError) as exc:
        parser.error(str(exc))
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["timestamp_utc", "elapsed_seconds", "sample_interval_seconds", "system_cpu_percent",
              "system_cpu_per_core_percent", "ram_used_bytes", "ram_available_bytes",
              "app_process_count", "app_rss_bytes", "app_cpu_percent", "app_cpu_sampled_process_count"]
    tracked: dict[int, psutil.Process] = {}
    for proc in process_tree(root):
        try:
            proc.cpu_percent()
            tracked[proc.pid] = proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    psutil.cpu_percent()
    psutil.cpu_percent(percpu=True)
    start = previous = time.monotonic()
    deadline = start + args.duration if args.duration else math.inf
    with args.output.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        handle.flush()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            stop.wait(min(args.interval, remaining))
            now = time.monotonic()
            cpu = psutil.cpu_percent()
            cores = psutil.cpu_percent(percpu=True)
            memory = psutil.virtual_memory()
            current: dict[int, psutil.Process] = {}
            rss = cpu_app = sampled = 0
            for discovered in process_tree(root):
                try:
                    old = tracked.get(discovered.pid)
                    proc = old if old is not None and old == discovered else discovered
                    rss += proc.memory_info().rss
                    usage = proc.cpu_percent()
                    if proc is old:
                        cpu_app += usage
                        sampled += 1
                    current[proc.pid] = proc
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            tracked = current
            writer.writerow({
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(now - start, 6),
                "sample_interval_seconds": round(now - previous, 6),
                "system_cpu_percent": cpu, "system_cpu_per_core_percent": json.dumps(cores),
                "ram_used_bytes": memory.used, "ram_available_bytes": memory.available,
                "app_process_count": len(current) if root else "",
                "app_rss_bytes": rss if current else "",
                "app_cpu_percent": round(cpu_app, 2) if sampled else "",
                "app_cpu_sampled_process_count": sampled if root else "",
            })
            handle.flush()
            previous = now
            if stop.is_set():
                break


if __name__ == "__main__":
    main()
