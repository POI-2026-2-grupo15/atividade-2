"""Execute uma bateria de demanda no hospedeiro e monitore a VM por SSH."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import posixpath
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_USERS = (1, 2, 4, 8, 16)
CHAIN_PROJECT = "/home/osboxes/atividade-2/cpu-bound"
ONE_CPU_PROJECT = "/home/osboxes/atividade-2-git/cpu-bound"


def _positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Informe um inteiro positivo")
    return number


def _users(value: str) -> tuple[int, ...]:
    try:
        levels = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use usuários separados por vírgulas") from exc
    if not levels or any(level <= 0 for level in levels) or len(levels) != len(set(levels)):
        raise argparse.ArgumentTypeError("Níveis de usuários devem ser positivos e distintos")
    return levels


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vcpus", type=int, choices=(1, 2, 4, 6, 8), required=True)
    parser.add_argument("--vm-name", help="Nome da VM no VirtualBox (ou CPU_BOUND_VM_NAME)")
    parser.add_argument("--remote-project", help="Caminho absoluto do projeto dentro da VM (ou CPU_BOUND_REMOTE_PROJECT)")
    parser.add_argument("--ssh-target", default="osboxes@127.0.0.1")
    parser.add_argument("--ssh-port", type=_positive, default=2222)
    parser.add_argument("--host", default="http://127.0.0.1:8000")
    parser.add_argument("--users", type=_users, default=DEFAULT_USERS)
    parser.add_argument("--repetitions", type=_positive, default=3)
    parser.add_argument("--duration-seconds", type=_positive, default=120)
    parser.add_argument("--data-size-mb", type=_positive, default=10)
    parser.add_argument("--iterations", type=_positive, default=100)
    parser.add_argument("--spawn-rate", type=_positive, default=32)
    parser.add_argument("--generator-cpu", type=int, default=0,
                        help="CPU lógica do hospedeiro para o Locust; -1 desativa afinidade")
    parser.add_argument("--output-root", type=Path, help="Pasta inédita dos resultados")
    parser.add_argument("--smoke", action="store_true", help="1 usuário, 1 repetição, 8 s e 1 MiB × 1")
    args = parser.parse_args(argv)
    args.vm_name = args.vm_name or os.getenv("CPU_BOUND_VM_NAME") or ("cpu_Bound" if args.vcpus == 1 else "cpu__bound_2cpu")
    args.remote_project = args.remote_project or os.getenv("CPU_BOUND_REMOTE_PROJECT") or (ONE_CPU_PROJECT if args.vcpus == 1 else CHAIN_PROJECT)
    if not args.remote_project.startswith("/"):
        parser.error("--remote-project deve ser absoluto")
    if args.data_size_mb > 32 or args.iterations > 1000 or args.data_size_mb * args.iterations > 8192:
        parser.error("Benchmark fora dos limites da API")
    if args.smoke:
        args.users = (1,)
        args.repetitions = 1
        args.duration_seconds = 8
        args.data_size_mb = 1
        args.iterations = 1
        args.spawn_rate = 1
    return args


def planned_runs(args: argparse.Namespace) -> list[tuple[int, int]]:
    return [(users, rep) for users in args.users for rep in range(1, args.repetitions + 1)]


def check_vm_info(info: str, expected_vcpus: int) -> None:
    settings = dict(line.split("=", 1) for line in info.splitlines() if "=" in line)
    settings = {key: value.strip('"') for key, value in settings.items()}
    if settings.get("VMState") != "running":
        raise ValueError("A VM selecionada precisa estar ligada")
    actual = int(settings.get("cpus", "0"))
    if actual != expected_vcpus:
        raise ValueError(f"A VM possui {actual} vCPUs; {expected_vcpus} esperadas. Restaure/inicie o cenário correto.")
    if int(settings.get("memory", "0")) != 1024:
        raise ValueError("A VM precisa ter 1.024 MiB de RAM para a matriz comparável")
    if settings.get("nic1") != "nat":
        raise ValueError("O adaptador 1 precisa estar em NAT")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ssh_args(args: argparse.Namespace, socket: Path) -> list[str]:
    return ["ssh", "-S", str(socket), "-o", "BatchMode=yes", "-p", str(args.ssh_port), args.ssh_target]


def _remote(args: argparse.Namespace, socket: Path, script: str, *, binary: bool = False):
    command = [*_ssh_args(args, socket), "bash -lc " + shlex.quote(script)]
    return subprocess.run(command, check=True, capture_output=True, text=not binary)


def _remote_preflight(args: argparse.Namespace, socket: Path) -> tuple[int, str]:
    project = shlex.quote(args.remote_project)
    script = f"""set -euo pipefail
cd {project}
test -x .venv/bin/python
test -f scripts/monitor.py
command -v vmstat >/dev/null
vcpus=$(nproc)
test "$vcpus" -eq {args.vcpus}
pids=$(pgrep -f '^.venv/bin/python -m uvicorn app.main:app .*--workers 8' || true)
set -- $pids
test "$#" -eq 1 || {{ echo 'Esperado um mestre Uvicorn com 8 workers' >&2; exit 2; }}
kill -0 "$1"
printf 'vcpus=%s\\napi_pid=%s\\n' "$vcpus" "$1"
.venv/bin/python --version
free -m
"""
    inventory = _remote(args, socket, script).stdout
    pid_line = next((line for line in inventory.splitlines() if line.startswith("api_pid=")), None)
    if pid_line is None:
        raise ValueError("PID mestre não retornado pelo convidado")
    return int(pid_line.split("=", 1)[1]), inventory


def _start_monitor(args: argparse.Namespace, socket: Path, remote_dir: str, api_pid: int) -> None:
    q = shlex.quote
    parent = posixpath.dirname(remote_dir)
    script = f"""set -euo pipefail
mkdir -p {q(parent)}
mkdir {q(remote_dir)}
cd {q(args.remote_project)}
nohup .venv/bin/python scripts/monitor.py --pid {api_pid} --interval 1 --output {q(remote_dir + '/monitor.csv')} > {q(remote_dir + '/monitor.log')} 2>&1 < /dev/null &
printf '%s\\n' "$!" > {q(remote_dir + '/monitor.pid')}
nohup vmstat -n 1 > {q(remote_dir + '/vmstat.txt')} 2>&1 < /dev/null &
printf '%s\\n' "$!" > {q(remote_dir + '/vmstat.pid')}
"""
    _remote(args, socket, script)
    time.sleep(2)
    _remote(args, socket, f"test -s {q(remote_dir + '/monitor.csv')} && test -s {q(remote_dir + '/vmstat.txt')}")


def _stop_monitor(args: argparse.Namespace, socket: Path, remote_dir: str) -> None:
    q = shlex.quote
    script = f"""for file in {q(remote_dir + '/monitor.pid')} {q(remote_dir + '/vmstat.pid')}; do
  if test -f "$file"; then kill -TERM "$(cat "$file")" 2>/dev/null || true; fi
done
sleep 2
"""
    _remote(args, socket, script)


def _copy_remote_files(args: argparse.Namespace, socket: Path, remote_dir: str, local_dir: Path) -> None:
    for name in ("monitor.csv", "vmstat.txt", "monitor.log"):
        content = _remote(args, socket, "cat " + shlex.quote(remote_dir + "/" + name), binary=True).stdout
        (local_dir / name).write_bytes(content)


def _run_locust(args: argparse.Namespace, local_dir: Path) -> int:
    env = os.environ.copy()
    env.update({
        "PATH": str(ROOT / ".venv/bin") + os.pathsep + env.get("PATH", ""),
        "USERS": str(local_dir.parent.name[1:]), "SPAWN_RATE": str(args.spawn_rate),
        "DURATION": f"{args.duration_seconds}s", "HOST": args.host,
        "DATA_SIZE_MB": str(args.data_size_mb), "ITERATIONS": str(args.iterations),
        "WAIT_SECONDS": "0", "OUTPUT_DIR": str(local_dir),
    })
    command = ["bash", str(ROOT / "scripts/run_load_test.sh")]
    if args.generator_cpu >= 0:
        command = ["taskset", "-c", str(args.generator_cpu), *command]
    return subprocess.run(command, env=env, check=False).returncode


def _host_inventory() -> str:
    parts = []
    for command in (["uname", "-a"], ["lscpu"], ["free", "-m"], ["VBoxManage", "--version"]):
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        parts.append("$ " + shlex.join(command) + "\n" + result.stdout)
    return "\n".join(parts)


def _check_health(host: str) -> None:
    with urlopen(host.rstrip("/") + "/health", timeout=5) as response:
        if response.status != 200 or json.load(response) != {"status": "ok"}:
            raise ValueError("/health não retornou status ok")


def _write_summary(output: Path, rows: list[dict]) -> None:
    with (output / "execution-summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("vcpus", "users", "rep", "locust_exit_code", "error", "directory"))
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> Path:
    if not (ROOT / ".venv/bin/python").is_file():
        raise FileNotFoundError("Crie a .venv do hospedeiro e instale requirements.txt")
    if args.generator_cpu >= 0 and shutil.which("taskset") is None:
        raise FileNotFoundError("taskset não encontrado no hospedeiro")
    vm_info = subprocess.check_output(["VBoxManage", "showvminfo", args.vm_name, "--machinereadable"], text=True)
    check_vm_info(vm_info, args.vcpus)
    _check_health(args.host)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = "demand-smoke-vbox" if args.smoke else "demand-vbox"
    output = (args.output_root or ROOT / "results" / f"{prefix}-{args.vcpus}cpu-{stamp}-{os.getpid()}").resolve()
    if output.exists():
        raise FileExistsError(f"Pasta de resultados já existe: {output}")
    with tempfile.TemporaryDirectory(prefix="cpu-bound-ssh-") as temporary:
        socket = Path(temporary) / "control"
        subprocess.run(["ssh", "-M", "-fN", "-S", str(socket), "-p", str(args.ssh_port), args.ssh_target], check=True)
        try:
            api_pid, guest_inventory = _remote_preflight(args, socket)
            output.mkdir(parents=True, exist_ok=False)
            (output / "virtualbox-info.txt").write_text(vm_info, encoding="utf-8")
            (output / "host-inventory.txt").write_text(_host_inventory(), encoding="utf-8")
            (output / "guest-inventory.txt").write_text(guest_inventory, encoding="utf-8")
            (output / "manifest.json").write_text(json.dumps({
                "created_utc": _utc(), "vm_name": args.vm_name, "vcpus": args.vcpus,
                "vm_provenance": "separate-1cpu-vm" if args.vcpus == 1 else "2-to-8cpu-snapshot-chain",
                "remote_project": args.remote_project, "users": args.users,
                "repetitions": args.repetitions, "duration_seconds": args.duration_seconds,
                "data_size_mb": args.data_size_mb, "iterations": args.iterations,
                "spawn_rate": args.spawn_rate, "wait_seconds": 0, "workers": 8,
                "ram_mib": 1024, "warmup_seconds": 30, "cooldown_seconds": 5,
                "smoke": args.smoke, "host": args.host,
            }, indent=2), encoding="utf-8")
            rows: list[dict] = []
            try:
                for users, rep in planned_runs(args):
                    local_dir = output / f"u{users}" / f"rep{rep}"
                    local_dir.parent.mkdir(parents=True, exist_ok=True)
                    remote_dir = posixpath.join(args.remote_project, "results", output.name, f"u{users}", f"rep{rep}")
                    error = ""
                    exit_code = None
                    print(f"[{_utc()}] {args.vcpus} vCPUs, {users} usuários, rep{rep}", flush=True)
                    try:
                        _check_health(args.host)
                        _start_monitor(args, socket, remote_dir, api_pid)
                        exit_code = _run_locust(args, local_dir)
                        if exit_code != 0:
                            error = f"Locust terminou com código {exit_code}"
                    except Exception as exc:
                        error = str(exc)
                    finally:
                        local_dir.mkdir(parents=True, exist_ok=True)
                        try:
                            _stop_monitor(args, socket, remote_dir)
                            _copy_remote_files(args, socket, remote_dir, local_dir)
                        except Exception as exc:
                            error = (error + "; " if error else "") + f"Coleta remota: {exc}"
                        (local_dir / "run-status.json").write_text(json.dumps({
                            "finished_utc": _utc(), "locust_exit_code": exit_code,
                            "error": error, "remote_dir": remote_dir,
                        }, indent=2), encoding="utf-8")
                        rows.append({"vcpus": args.vcpus, "users": users, "rep": rep,
                                     "locust_exit_code": exit_code, "error": error,
                                     "directory": str(local_dir.relative_to(output))})
                    if error:
                        raise RuntimeError(f"Execução interrompida em {users} usuários/rep{rep}: {error}")
            finally:
                _write_summary(output, rows)
        finally:
            subprocess.run(["ssh", "-S", str(socket), "-O", "exit", "-p", str(args.ssh_port), args.ssh_target],
                           check=False, capture_output=True)
    return output


def main() -> None:
    try:
        output = run(parse_args())
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Bateria preservada em {output}")


if __name__ == "__main__":
    main()
