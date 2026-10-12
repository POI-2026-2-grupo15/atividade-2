import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[1]


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def counters(path: Path) -> dict[str, int]:
    return {key: int(value) for key, value in (line.split() for line in path.read_text().splitlines())}


def snapshot(group: Path) -> dict[str, int]:
    cpu = counters(group / "cpu.stat")
    memory_events = counters(group / "memory.events")
    io = {"rbytes": 0, "wbytes": 0}
    for line in (group / "io.stat").read_text().splitlines():
        for item in line.split()[1:]:
            key, value = item.split("=")
            if key in io:
                io[key] += int(value)
    return {
        "cpu_usage_usec": cpu["usage_usec"],
        "throttled_usec": cpu.get("throttled_usec", 0),
        "memory_bytes": int((group / "memory.current").read_text()),
        "swap_bytes": int((group / "memory.swap.current").read_text()),
        "oom_kill": memory_events["oom_kill"],
        "disk_read_bytes": io["rbytes"], "disk_write_bytes": io["wbytes"],
    }


def save_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def wait_until_idle(group: Path, timeout: float = 120) -> float:
    """Aguardar cálculos remanescentes após o Locust encerrar conexões."""
    started = previous_time = time.monotonic()
    previous_usage = counters(group / "cpu.stat")["usage_usec"]
    quiet_intervals = 0
    while time.monotonic() - started < timeout:
        time.sleep(0.5)
        now = time.monotonic()
        usage = counters(group / "cpu.stat")["usage_usec"]
        consumed_cpus = (usage - previous_usage) / 1e6 / (now - previous_time)
        quiet_intervals = quiet_intervals + 1 if consumed_cpus < 0.05 else 0
        if quiet_intervals >= 2:
            return now - started
        previous_usage, previous_time = usage, now
    raise TimeoutError("Container não ficou ocioso entre os níveis de demanda")


def run_load(group: Path, url: str, output: Path, users: int, duration: int,
             generator_cpu: int, server_cpus: list[int], payload: dict[str, int],
             cpu_limit: int = 1, require_ac: bool = False) -> dict:
    output.mkdir()
    env = {**os.environ, "DATA_SIZE_MB": str(payload["data_size_mb"]),
           "ITERATIONS": str(payload["iterations"]), "WAIT_SECONDS": "0"}
    args = ["taskset", "--cpu-list", str(generator_cpu), sys.executable, "-m", "locust",
            "-f", str(ROOT / "load_tests/locustfile.py"), "--headless", "--host", url,
            "--users", str(users), "--spawn-rate", str(users), "--run-time", f"{duration}s",
            "--csv", str(output / "locust"), "--csv-full-history", "--only-summary",
            "--exit-code-on-error", "1"]
    save_json(output / "config.json", {"command": args, "payload": payload, "wait_seconds": 0})
    samples = []
    before = snapshot(group)
    previous = before
    start = previous_time = time.monotonic()
    psutil.cpu_percent(percpu=True)
    with (output / "locust.log").open("w") as log, (output / "resources.csv").open("w", newline="") as metrics:
        process = subprocess.Popen(args, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        generator = psutil.Process(process.pid)
        generator.cpu_percent()
        writer = None
        try:
            while process.poll() is None:
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                now = time.monotonic()
                current = snapshot(group)
                host_cores = psutil.cpu_percent(percpu=True)
                try:
                    generator_cpu_percent = generator.cpu_percent()
                except psutil.NoSuchProcess:
                    generator_cpu_percent = 0.0
                battery = psutil.sensors_battery()
                frequencies = psutil.cpu_freq(percpu=True)
                row = {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": now - start,
                    "interval_seconds": now - previous_time,
                    "container_cpu_percent": (current["cpu_usage_usec"] - previous["cpu_usage_usec"]) / (now - previous_time) / 10000,
                    "generator_cpu_percent": generator_cpu_percent,
                    "host_selected_cpu_percent": json.dumps({cpu: host_cores[cpu] for cpu in server_cpus}),
                    "host_selected_cpu_frequency_mhz": json.dumps({cpu: frequencies[cpu].current for cpu in server_cpus}) if frequencies else "",
                    "host_power_plugged": battery.power_plugged if battery is not None else "",
                    **current,
                }
                if writer is None:
                    writer = csv.DictWriter(metrics, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow(row)
                metrics.flush()
                samples.append(row)
                if require_ac and battery is not None and not battery.power_plugged:
                    raise RuntimeError("Alimentação mudou para bateria; medição interrompida e CSV preservado")
                previous, previous_time = current, now
                if now - start > duration + 30:
                    raise TimeoutError("Locust não encerrou dentro do prazo")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if process.returncode:
            raise RuntimeError(f"Locust falhou ({process.returncode}); consulte {output / 'locust.log'}")
    after = snapshot(group)
    # Descartar início/rampa e encerramento na análise de recursos.
    stable = [row for row in samples if 5 <= row["elapsed_seconds"] <= duration - 2]
    if not stable:
        raise RuntimeError("Janela estável insuficiente")
    with (output / "locust_stats.csv").open() as handle:
        aggregate = next(row for row in csv.DictReader(handle) if row["Name"] == "Aggregated")
    result = {
        "users": users,
        "cpu_limit": cpu_limit,
        "power_plugged_observations": sorted({str(row["host_power_plugged"]) for row in samples}),
        "cpu_window_elapsed_seconds": [5, duration - 2],
        "http_window": "Último snapshot cumulativo do Locust; inclui início/rampa",
        "requests_csv_snapshot": int(aggregate["Request Count"]),
        "failures": int(aggregate["Failure Count"]),
        "requests_per_second": float(aggregate["Requests/s"]),
        "average_latency_ms": float(aggregate["Average Response Time"]),
        "p95_latency_ms": float(aggregate["95%"]),
        "stable_samples": len(stable),
        "container_cpu_mean_percent": statistics.mean(row["container_cpu_percent"] for row in stable),
        "allocated_cpu_utilization_percent": statistics.mean(row["container_cpu_percent"] for row in stable) / cpu_limit,
        "generator_cpu_mean_percent": statistics.mean(row["generator_cpu_percent"] for row in stable),
        "memory_max_mib": max(row["memory_bytes"] for row in samples) / 2**20,
        "swap_max_bytes": max(row["swap_bytes"] for row in samples),
        "disk_read_bytes_delta": after["disk_read_bytes"] - before["disk_read_bytes"],
        "disk_write_bytes_delta": after["disk_write_bytes"] - before["disk_write_bytes"],
        "oom_kill_delta": after["oom_kill"] - before["oom_kill"],
        "throttled_seconds_delta": (after["throttled_usec"] - before["throttled_usec"]) / 1e6,
    }
    save_json(output / "summary.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="cpu-bound:experiment")
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--server-cpus", help="Lista de CPUs lógicas permitidas, ex.: 2,3,4,5; substitui --cpu")
    parser.add_argument("--cpu-limit", type=int, choices=(1, 2, 4, 6, 8), default=1)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--users", type=int, nargs="+", default=[1, 4, 8])
    parser.add_argument("--generator-cpu", type=int, default=0)
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--require-ac", action="store_true", help="Interromper se o sensor informar uso de bateria")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.duration < 15:
        parser.error("Use duração >= 15 segundos")
    battery = psutil.sensors_battery()
    if args.require_ac and battery is not None and not battery.power_plugged:
        parser.error("Conecte o hospedeiro à tomada para iniciar este experimento")
    available = os.sched_getaffinity(0)
    try:
        server_cpus = sorted(set(int(cpu) for cpu in args.server_cpus.split(","))) if args.server_cpus else [args.cpu]
    except ValueError:
        parser.error("--server-cpus deve ser uma lista de inteiros separados por vírgulas")
    if not set(server_cpus).issubset(available) or args.generator_cpu not in available or args.generator_cpu in server_cpus:
        parser.error("Escolha CPUs disponíveis e distintas para servidor e gerador")
    if len(server_cpus) < args.cpu_limit:
        parser.error("O conjunto de CPUs deve comportar a quota solicitada")
    if not 1 <= args.workers <= 8 or any(not 1 <= users <= 64 for users in args.users):
        parser.error("Use 1–8 workers e 1–64 usuários")
    if len(set(args.users)) != len(args.users):
        parser.error("Não repita níveis de usuários na mesma execução")
    output = (args.output or ROOT / "results" / datetime.now(timezone.utc).strftime("docker-%Y%m%dT%H%M%S")).resolve()
    output.mkdir(parents=True, exist_ok=False)
    name = f"cpu-bound-pilot-{os.getpid()}"
    created = False
    payload = {"data_size_mb": 10, "iterations": 100}
    try:
        command("docker", "run", "-d", "--name", name, f"--cpus={args.cpu_limit}",
                "--cpuset-cpus=" + ",".join(map(str, server_cpus)),
                "--memory=1g", "--memory-swap=1g", "--pids-limit=128",
                "-p", "127.0.0.1::8000", args.image,
                "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
                "--port", "8000", "--workers", str(args.workers), "--no-access-log")
        created = True
        info = json.loads(command("docker", "inspect", name))[0]
        binding = info["NetworkSettings"]["Ports"]["8000/tcp"][0]
        url = f"http://127.0.0.1:{binding['HostPort']}"
        pid = info["State"]["Pid"]
        relative = next(line[3:] for line in Path(f"/proc/{pid}/cgroup").read_text().splitlines() if line.startswith("0::"))
        group = Path("/sys/fs/cgroup") / relative.lstrip("/")
        snapshot(group)
        save_json(output / "environment.json", {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(), "container": name,
            "image_id": info["Image"], "url": url, "host_config": {
                key: info["HostConfig"][key] for key in ("NanoCpus", "CpusetCpus", "Memory", "MemorySwap")
            }, "cpu_max": (group / "cpu.max").read_text().strip(),
            "cpuset_effective": (group / "cpuset.cpus.effective").read_text().strip(),
            "memory_max": (group / "memory.max").read_text().strip(),
            "swap_max": (group / "memory.swap.max").read_text().strip(),
            "generator_cpu": args.generator_cpu, "workers": args.workers, "payload": payload,
            "cpu_limit": args.cpu_limit, "users": args.users,
            "duration_seconds": args.duration, "host_python": sys.version,
            "cpu_topology": command("lscpu", "-e=CPU,CORE,SOCKET"),
            "docker_version": command("docker", "version", "--format", "{{.Server.Version}}"),
        })
        (output / "container-dependencies.txt").write_text(command("docker", "exec", name, "python", "-m", "pip", "freeze") + "\n")
        (output / "host-dependencies.txt").write_text(command(sys.executable, "-m", "pip", "freeze") + "\n")
        with httpx.Client(base_url=url, timeout=30) as client:
            for attempt in range(100):
                try:
                    client.get("/health").raise_for_status()
                    break
                except httpx.HTTPError:
                    if attempt == 99:
                        raise
                    time.sleep(0.1)
            def warmup_request(_: int) -> dict:
                # Uma conexão por chamada permite distribuir aquecimento aos workers.
                response = httpx.post(url + "/benchmark", json=payload, timeout=60)
                response.raise_for_status()
                return response.json()

            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                warmup = list(pool.map(warmup_request, range(max(5, args.workers * 4))))
            save_json(output / "warmup.json", warmup)
        results = []
        for users in args.users:
            idle_wait_seconds = wait_until_idle(group)
            print(f"Quota {args.cpu_limit} CPU(s), {args.workers} workers, {users} usuário(s), {args.duration}s, saída: {output}", flush=True)
            result = run_load(group, url, output / f"users-{users}", users, args.duration,
                              args.generator_cpu, server_cpus, payload, args.cpu_limit, args.require_ac)
            result["workers"] = args.workers
            result["idle_wait_before_seconds"] = idle_wait_seconds
            save_json(output / f"users-{users}" / "summary.json", result)
            results.append(result)
            save_json(output / "summary.json", results)
            print(json.dumps(result), flush=True)
    finally:
        if created:
            try:
                (output / "container.log").write_text(subprocess.run(["docker", "logs", name], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout)
            finally:
                try:
                    subprocess.run(["docker", "stop", "--time", "10", name], check=True, stdout=subprocess.DEVNULL)
                finally:
                    subprocess.run(["docker", "rm", "--force", name], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
