import argparse
import csv
import json
import math
import platform
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

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
    if args.pid is not None and args.pid <= 0:
        parser.error("PID deve ser positivo")
    metadata_path = args.output.with_suffix(args.output.suffix + ".metadata.json")
    if args.output.exists() or metadata_path.exists():
        parser.error("Arquivo de saída ou metadados já existe")
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "python": platform.python_version(),
        "cpu_logical_count": psutil.cpu_count(),
        "ram_total_bytes": psutil.virtual_memory().total,
        "swap_total_bytes": psutil.swap_memory().total,
        "root_pid": args.pid, "interval_seconds": args.interval,
        "duration_seconds": args.duration,
    }
    if root:
        try:
            metadata["root_command"] = root.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            metadata["root_command"] = None
    with metadata_path.open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)
        handle.write("\n")
    fields = ["timestamp_utc", "elapsed_seconds", "sample_interval_seconds", "system_cpu_percent",
              "system_cpu_per_core_percent", "ram_used_bytes", "ram_available_bytes",
              "app_process_count", "app_rss_bytes", "app_cpu_percent", "app_cpu_sampled_process_count",
              "swap_used_bytes", "swap_total_bytes", "swap_in_bytes_per_s", "swap_out_bytes_per_s"]
    tracked: dict[int, psutil.Process] = {}
    for proc in process_tree(root):
        try:
            proc.cpu_percent()
            tracked[proc.pid] = proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    psutil.cpu_percent()
    psutil.cpu_percent(percpu=True)
    swap_before = psutil.swap_memory()
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
            swap = psutil.swap_memory()
            sample_interval = now - previous
            swap_rates = sys.platform.startswith("linux") and sample_interval > 0
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
                "swap_used_bytes": swap.used, "swap_total_bytes": swap.total,
                "swap_in_bytes_per_s": max(0, swap.sin - swap_before.sin) / sample_interval if swap_rates else "",
                "swap_out_bytes_per_s": max(0, swap.sout - swap_before.sout) / sample_interval if swap_rates else "",
            })
            swap_before = swap
            handle.flush()
            previous = now
            if stop.is_set():
                break


if __name__ == "__main__":
    main()
