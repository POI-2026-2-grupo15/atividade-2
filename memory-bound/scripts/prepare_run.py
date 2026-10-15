import argparse
import json
import math
import os
import platform
from datetime import datetime, timezone
from pathlib import Path

from dataset import load_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--users", type=int, required=True)
    parser.add_argument("--spawn-rate", type=float, required=True)
    parser.add_argument("--duration", required=True)
    args = parser.parse_args()
    if args.users < 1 or not math.isfinite(args.spawn_rate) or args.spawn_rate <= 0:
        parser.error("users e spawn-rate devem ser positivos")
    manifest = load_dataset(args.dataset)
    args.output.mkdir(parents=True, exist_ok=False)
    config = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "host": args.host, "users": args.users, "spawn_rate": args.spawn_rate,
        "duration": args.duration, "dataset_dir": str(args.dataset.resolve()),
        "request_timeout": os.getenv("REQUEST_TIMEOUT", "120"),
        "scenario": os.getenv("SCENARIO", "não informado"),
        "repetition": os.getenv("REPETITION", "não informada"),
        "server_workers": os.getenv("SERVER_WORKERS", "não informado"),
        "python": platform.python_version(), "generator_platform": platform.platform(),
        "warmup_seconds": os.getenv("WARMUP_SECONDS"),
        "measurement_seconds": os.getenv("MEASUREMENT_SECONDS"),
    }
    if os.getenv("CONTAINER_CPUS"):
        config.update({
            "execution_environment": "docker",
            "container_cpus": float(os.environ["CONTAINER_CPUS"]),
            "container_ram_mib": int(os.environ["CONTAINER_RAM_MIB"]),
        })
    for name, data in (("config.json", config), ("dataset-manifest.json", manifest)):
        (args.output / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8")


if __name__ == "__main__":
    main()
