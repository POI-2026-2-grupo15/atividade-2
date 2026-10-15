"""Executor Docker: plano, coleta por janela e preservação das falhas."""

import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import requests

from dataset import load_dataset
from experiment_metrics import make_plan, summarize_resources

PROJECT = Path(__file__).resolve().parents[1]
PROTOCOL = json.loads((PROJECT / "experiments/protocol.json").read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def docker(*args):
    return subprocess.check_output(["docker", *map(str, args)], text=True, stderr=subprocess.STDOUT, timeout=60).strip()


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    for name, default in (("rams", PROTOCOL["ram_mib"]), ("users", PROTOCOL["users"])):
        parser.add_argument(f"--{name}", nargs="+", type=int, default=default)
    for name, key in (("cpus", "cpus"), ("workers", "workers"), ("repetitions", "repetitions"),
                      ("duration", "measurement_seconds"), ("warmup", "warmup_seconds"),
                      ("pause", "pause_seconds")):
        parser.add_argument(f"--{name}", type=float if name == "cpus" else int, default=PROTOCOL[key])
    parser.add_argument("--dataset", type=Path, default=PROJECT / PROTOCOL["dataset"])
    parser.add_argument("--image", default=PROTOCOL["image"])
    parser.add_argument("--plan", action="store_true", help="Exibe o plano sem acessar Docker ou executar carga")
    parser.add_argument("--label", default="experiments", help="Use validation para coletas curtas de verificação")
    args = parser.parse_args()
    if not math.isfinite(args.cpus) or args.cpus <= 0 or min(args.workers, args.repetitions, args.duration) < 1:
        parser.error("CPU, workers, repetições e duração devem ser positivos")
    if min(args.warmup, args.pause) < 0 or any(min(values) < 1 or len(values) != len(set(values)) for values in (args.rams, args.users)):
        parser.error("Aquecimento/pausa não negativos; RAM e demandas positivas e sem duplicatas")
    if not args.label.replace("-", "").isalnum():
        parser.error("Use apenas letras, números e hífen no label")
    return args


def validate_api(host, point):
    deadline = time.monotonic() + 30
    while True:
        try:
            requests.get(host + "/openapi.json", timeout=1).raise_for_status()
            break
        except requests.RequestException:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)
    valid = requests.post(host + "/memory-test", files={
        "files": ("valid.csv", b"id,name,email,description\n1,A,a@x,old\n1,B,b@x,new\n")}, timeout=5)
    valid.raise_for_status()
    expected = {"files_processed": 1, "records_received": 2, "unique_records": 1, "replaced_occurrences": 1}
    if any(valid.json().get(k) != v for k, v in expected.items()):
        raise ValueError("Contrato HTTP diverge do esperado")
    write_json(point / "validation.json", {"valid_response": valid.json()})


def stop_process(process, group=False):
    if process.poll() is None:
        if group:
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if group:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=5)


@contextmanager
def container(args, run, point, name):
    docker("run", "-d", "--name", name, "--cpus", args.cpus,
           "--memory", f"{run['ram_mib']}m", "--memory-swap", f"{run['ram_mib']}m",
           "--pids-limit", "256", "-p", "127.0.0.1::8000", "-v", f"{point}:/results",
           args.image, "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
           "--port", "8000", "--workers", args.workers, "--no-access-log")
    try:
        yield
    finally:
        try:
            write_json(point / "container.json", json.loads(docker("inspect", name))[0])
            (point / "api.log").write_text(docker("logs", name) + "\n")
        finally:
            docker("rm", "-f", name)


def monitor_container(name, point, stack):
    log = stack.enter_context((point / "monitor.log").open("w"))
    process = subprocess.Popen(["docker", "exec", name, "python", "scripts/monitor.py",
                               "--pid", "1", "--interval", "0.5", "--pid-file", "/results/monitor.pid",
                               "--output", "/results/monitor.csv"], stdout=log, stderr=subprocess.STDOUT)

    def stop():
        state = json.loads(docker("inspect", name))[0]["State"]
        if state["Running"] and (point / "monitor.pid").exists():
            try:
                docker("exec", name, "python", "-c", "import os,signal; from pathlib import Path; "
                       "pid=int(Path('/results/monitor.pid').read_text()); "
                       "cmd=Path(f'/proc/{pid}/cmdline'); "
                       "os.kill(pid, signal.SIGTERM) if cmd.exists() and b'scripts/monitor.py' in cmd.read_bytes() else None")
            except subprocess.CalledProcessError:
                if json.loads(docker("inspect", name))[0]["State"]["Running"]:
                    raise
        process.wait(timeout=10)
    stack.callback(stop)
    deadline = time.monotonic() + 10
    while not (point / "monitor.csv").exists():
        if process.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError("Monitor do container não iniciou")
        time.sleep(0.1)


def collect_load(args, run, point, host, name):
    watchdog = args.warmup + args.duration + PROTOCOL["request_timeout_seconds"] + 20
    env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
               DATASET_DIR=str(args.dataset.resolve()), USERS=str(run["users"]), SPAWN_RATE=str(run["users"]),
               DURATION=f"{watchdog}s", REQUEST_TIMEOUT=str(PROTOCOL["request_timeout_seconds"]), HOST=host,
               OUTPUT_DIR=str(point / "load"), SCENARIO=f"docker-cpu{args.cpus:g}-ram{run['ram_mib']}",
               REPETITION=str(run["repetition"]), SERVER_WORKERS=str(args.workers),
               CONTAINER_CPUS=str(args.cpus), CONTAINER_RAM_MIB=str(run["ram_mib"]),
               WARMUP_SECONDS=str(args.warmup), MEASUREMENT_SECONDS=str(args.duration))
    with ExitStack() as stack:
        monitor_container(name, point, stack)
        log = stack.enter_context((point / "runner.log").open("w"))
        load = subprocess.Popen(["bash", str(PROJECT / "scripts/run_load_test.sh")], env=env,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        stack.callback(stop_process, load, True)
        generator_log = stack.enter_context((point / "generator-monitor.log").open("w"))
        monitor = subprocess.Popen([sys.executable, str(PROJECT / "scripts/monitor.py"), "--pid", str(load.pid),
                                    "--interval", "0.5", "--output", str(point / "generator-monitor.csv")],
                                   stdout=generator_log, stderr=subprocess.STDOUT)
        stack.callback(stop_process, monitor)
        code = load.wait(timeout=watchdog + 30)
        time.sleep(0.6)  # uma amostra posterior à janela, antes de encerrar os monitores
    return code


def oom_evidence(name):
    state = json.loads(docker("inspect", name))[0]["State"]
    events = None
    if state["Running"]:
        try:
            raw = docker("exec", name, "python", "-c",
                         "from pathlib import Path; print(Path('/sys/fs/cgroup/memory.events').read_text())")
            events = {key: int(value) for key, value in (line.split() for line in raw.splitlines())}
        except subprocess.CalledProcessError:
            pass
    return {"container_oom_killed": state["OOMKilled"], "memory_events_final": events}


def run_point(args, run, point, name):
    result = dict(run, cpus=args.cpus, workers=args.workers, status="not_started")
    with container(args, run, point, name):
        try:
            host = "http://127.0.0.1:" + docker("port", name, "8000/tcp").rsplit(":", 1)[1]
            validate_api(host, point)
            (point / "server-dependencies.txt").write_text(docker("exec", name, "python", "-m", "pip", "freeze") + "\n")
            result["locust_exit_code"] = collect_load(args, run, point, host, name)
            window_path = point / "load/measurement.json"
            if not window_path.exists():
                raise RuntimeError("Locust não produziu a janela de medição")
            window = json.loads(window_path.read_text())
            result.update(window)
            result.update(summarize_resources(point, window, args.cpus, PROTOCOL["monitor_interval_seconds"]))
            result["status"] = "completed" if window["complete"] else "incomplete_window"
        except (requests.RequestException, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            evidence = oom_evidence(name)
            if not evidence["container_oom_killed"] and not (evidence["memory_events_final"] or {}).get("oom_kill"):
                raise
            result.update(status="resource_failure_before_window", error=str(exc))
        result.update(oom_evidence(name))
        if result["status"] == "completed" and (result["container_oom_killed"] or
                (result["memory_events_final"] or {}).get("oom_kill")):
            result["status"] = "completed_with_oom"
    return result


def main():
    args = arguments()
    plan = make_plan(args.rams, args.users, args.repetitions)
    if args.plan:
        print(json.dumps({"configuration": vars(args) | {"dataset": str(args.dataset)},
                          "total_runs": len(plan), "runs": plan}, indent=2))
        return
    manifest = load_dataset(args.dataset)
    image = json.loads(docker("image", "inspect", args.image))[0]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = PROJECT / "results" / f"docker-{args.label}-{stamp}"
    output.mkdir(parents=True, exist_ok=False)
    configuration = vars(args) | {"dataset": str(args.dataset.resolve())}
    write_json(output / "plan.json", {"configuration": configuration, "runs": plan})
    write_json(output / "environment.json", {"image": image, "docker_version": docker("version"),
               "docker_info": json.loads(docker("info", "--format", "{{json .}}")), "protocol": PROTOCOL,
               "dataset_manifest": manifest, "configuration": configuration,
               "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
               "git_status": subprocess.check_output(["git", "status", "--short"], text=True)})
    snapshot = output / "source"
    snapshot.mkdir()
    for directory in ("scripts", "load_tests", "app", "experiments"):
        shutil.copytree(PROJECT / directory, snapshot / directory, ignore=shutil.ignore_patterns("__pycache__"))
    for filename in ("Dockerfile", "requirements.txt", "requirements-analysis.txt"):
        shutil.copy2(PROJECT / filename, snapshot / filename)
    results = []
    print(f"Resultados: {output}", flush=True)
    for index, run in enumerate(plan):
        point = output / f"rep{run['repetition']}-ram{run['ram_mib']}-u{run['users']}"
        point.mkdir()
        write_json(point / "configuration.json", configuration | run)
        name = f"memory-exp-{stamp.lower()}-{index}"
        try:
            result = run_point(args, run, point, name)
        except Exception as exc:
            write_json(point / "error.json", {"type": type(exc).__name__, "error": str(exc)})
            raise
        write_json(point / "summary.json", result)
        results.append(result)
        write_json(output / "summary.json", results)
        print(json.dumps(result), flush=True)
        if index + 1 < len(plan):
            time.sleep(args.pause)
    print(f"Concluídas {len(results)}/{len(plan)} execuções. Resultados: {output}", flush=True)
    if any(row["status"] == "incomplete_window" for row in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
