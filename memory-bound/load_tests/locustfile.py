"""Envio em fluxo no hospedeiro; janela experimental opcional após aquecimento."""

import math
import os
import sys
import time
from contextlib import ExitStack
from pathlib import Path

import gevent
from locust import HttpUser, constant, events, task
from requests_toolbelt.multipart.encoder import MultipartEncoder

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from dataset import load_dataset  # noqa: E402
from measurement import Measurement  # noqa: E402

DATASET_DIR = Path(os.getenv("DATASET_DIR", str(PROJECT_DIR / "datasets/pequeno"))).resolve()
MANIFEST = load_dataset(DATASET_DIR)
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "120"))
if not math.isfinite(REQUEST_TIMEOUT) or REQUEST_TIMEOUT <= 0:
    raise ValueError("REQUEST_TIMEOUT deve ser finito e > 0")

measurement = None
phase_started = False


@events.init.add_listener
def configure_window(environment, **kwargs):
    global measurement, active_environment
    active_environment = environment
    if os.getenv("MEASUREMENT_SECONDS"):
        duration = float(os.environ["MEASUREMENT_SECONDS"])
        warmup = float(os.getenv("WARMUP_SECONDS", "10"))
        if not math.isfinite(duration) or duration <= 0 or not math.isfinite(warmup) or warmup < 0:
            raise ValueError("Janela positiva e aquecimento não negativo são necessários")
        measurement = Measurement(Path(os.environ["OUTPUT_DIR"]), duration)


@events.spawning_complete.add_listener
def start_phases(user_count, **kwargs):
    global phase_started
    if measurement is None or phase_started:
        return
    phase_started = True

    def collect():
        gevent.sleep(float(os.getenv("WARMUP_SECONDS", "10")))
        measurement.begin()
        gevent.sleep(measurement.duration)
        measurement.save(True)
        active_environment.runner.quit()

    gevent.spawn(collect)


@events.request.add_listener
def record_window(response_time, start_time, exception, context, **kwargs):
    if measurement is not None:
        measurement.completed_request(context.get("started_epoch", start_time), time.time(),
                                      response_time, exception is not None)


@events.test_stop.add_listener
def close_window(environment, **kwargs):
    if measurement is not None:
        # Preservar janela incompleta quando o watchdog interrompe o Locust.
        if not measurement.finalized:
            measurement.save(False)
        measurement.close()


class MemoryUser(HttpUser):
    wait_time = constant(0)

    @task
    def consolidate(self):
        with ExitStack() as stack:
            fields = [
                ("files", (item["name"], stack.enter_context(
                    (DATASET_DIR / item["name"]).open("rb")), "text/csv"))
                for item in MANIFEST["files"]
            ]
            body = MultipartEncoder(fields=fields)
            started = time.time()
            if measurement is not None:
                measurement.started(started)
            with self.client.post(
                "/memory-test", data=body, headers={"Content-Type": body.content_type},
                name="/memory-test", timeout=REQUEST_TIMEOUT, catch_response=True,
                context={"started_epoch": started},
            ) as response:
                if response.status_code != 200:
                    response.failure(f"HTTP {response.status_code}")
                    return
                try:
                    result = response.json()
                    if not isinstance(result, dict) or any(
                        type(result.get(key)) is not int or result[key] != value
                        for key, value in MANIFEST["expected"].items()
                    ):
                        response.failure("Contagens de consolidação inconsistentes")
                except (ValueError, TypeError):
                    response.failure("Resposta JSON inválida")
