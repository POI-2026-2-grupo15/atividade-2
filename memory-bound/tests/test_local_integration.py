"""Validação local com HTTP, Locust e monitor reais; não é experimento de desempenho."""

from contextlib import ExitStack
import csv
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class LocalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        results = PROJECT_DIR / "results"
        results.mkdir(exist_ok=True)
        cls.output = Path(tempfile.mkdtemp(prefix="local-validation-", dir=results))
        cls.dataset = cls.output / "dataset"
        subprocess.run([
            sys.executable, "scripts/generate_dataset.py", "--output", str(cls.dataset),
            "--unique-records", "6", "--duplicates", "2", "--description-bytes", "64",
            "--files", "2",
        ], cwd=PROJECT_DIR, check=True, stdout=subprocess.DEVNULL)
        cls.api_log = (cls.output / "api.log").open("w")
        cls.addClassCleanup(cls.api_log.close)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        cls.host = f"http://127.0.0.1:{port}"
        cls.server = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
            "--port", str(port), "--workers", "2", "--no-access-log",
        ], cwd=PROJECT_DIR, stdout=cls.api_log, stderr=subprocess.STDOUT)
        cls.addClassCleanup(stop_process, cls.server)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if cls.server.poll() is not None:
                raise RuntimeError(f"API encerrou; consulte {cls.output / 'api.log'}")
            try:
                response = requests.get(cls.host + "/openapi.json", timeout=1)
                if response.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("API não iniciou dentro de 20 segundos")
        print(f"\nArtefatos da validação: {cls.output}")

    def send_example(self):
        dataset = self.dataset
        manifest = json.loads((dataset / "manifest.json").read_text())
        with ExitStack() as stack:
            files = [("files", (item["name"], stack.enter_context(
                (dataset / item["name"]).open("rb")), "text/csv")) for item in manifest["files"]]
            response = requests.post(self.host + "/memory-test", files=files, timeout=10)
        return response, manifest["expected"]

    def test_example_upload_matches_manifest_and_requests_are_independent(self):
        for _ in range(2):
            response, expected = self.send_example()
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual({key: result[key] for key in expected}, expected)
            self.assertGreaterEqual(result["processing_time_ms"], 0)

    def test_invalid_upload_returns_422_and_server_recovers(self):
        response = requests.post(self.host + "/memory-test", files=[
            ("files", ("invalid.csv", io.BytesIO(b"wrong,header\n"), "text/csv")),
        ], timeout=10)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["file"], "invalid.csv")
        response, _ = self.send_example()
        self.assertEqual(response.status_code, 200, response.text)

    def test_missing_files_returns_422(self):
        response = requests.post(self.host + "/memory-test", timeout=10)
        self.assertEqual(response.status_code, 422)

    def test_locust_scripts_and_monitor_produce_consistent_artifacts(self):
        monitor_path = self.output / "monitor.csv"
        with (self.output / "monitor.log").open("w") as monitor_log:
            monitor = subprocess.Popen([
                sys.executable, "scripts/monitor.py", "--pid", str(self.server.pid),
                "--interval", "0.2", "--output", str(monitor_path),
            ], cwd=PROJECT_DIR, stdout=monitor_log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 5
                while not monitor_path.exists() and time.monotonic() < deadline:
                    if monitor.poll() is not None:
                        self.fail("Monitor encerrou antes de iniciar a coleta")
                    time.sleep(0.1)
                self.assertTrue(monitor_path.exists())
                env = os.environ.copy()
                env.update({
                    "PATH": str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", ""),
                    "HOST": self.host, "DATASET_DIR": str(self.dataset),
                    "SCENARIO": "local-functional-validation", "REPETITION": "1",
                    "SERVER_WORKERS": "2", "USERS_LIST": "1 2", "SPAWN_RATE": "2",
                    "DURATION": "3s", "REQUEST_TIMEOUT": "10", "PAUSE_SECONDS": "0",
                    "OUTPUT_ROOT": str(self.output / "curve"),
                })
                # Esta integração funcional não usa as fases da matriz Docker.
                for name in ("WARMUP_SECONDS", "MEASUREMENT_SECONDS", "CONTAINER_CPUS", "CONTAINER_RAM_MIB"):
                    env.pop(name, None)
                with (self.output / "curve.log").open("w") as log:
                    completed = subprocess.run(
                        ["bash", "scripts/run_demand_curve.sh"], cwd=PROJECT_DIR, env=env,
                        stdout=log, stderr=subprocess.STDOUT, timeout=60,
                    )
                self.assertEqual(completed.returncode, 0, f"Consulte {self.output / 'curve.log'}")
                for users in (1, 2):
                    point = self.output / "curve" / f"u{users}"
                    with (point / "locust_stats.csv").open() as handle:
                        total = next(row for row in csv.DictReader(handle) if row["Name"] == "Aggregated")
                    self.assertGreater(int(total["Request Count"]), 0)
                    self.assertEqual(int(total["Failure Count"]), 0)
                    config = json.loads((point / "config.json").read_text())
                    self.assertEqual(config["users"], users)
                    self.assertTrue((point / "dataset-manifest.json").exists())
                    self.assertTrue((point / "dependencies.txt").exists())
            finally:
                if monitor.poll() is None:
                    monitor.send_signal(signal.SIGINT)
                try:
                    monitor.wait(timeout=10)
                finally:
                    stop_process(monitor)
            self.assertEqual(monitor.returncode, 0)
        with monitor_path.open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertGreater(len(rows), 0)
        self.assertTrue(any(int(row["app_process_count"]) > 1 for row in rows))
        self.assertTrue(any(float(row["app_rss_bytes"] or 0) > 0 for row in rows))
        self.assertTrue(all(float(row["sample_interval_seconds"]) > 0 for row in rows))
        metadata = json.loads(monitor_path.with_suffix(".csv.metadata.json").read_text())
        self.assertEqual(metadata["root_pid"], self.server.pid)
        self.assertGreater(metadata["ram_total_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
