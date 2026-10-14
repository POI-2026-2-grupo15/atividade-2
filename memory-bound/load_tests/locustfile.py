"""Envio em fluxo dos CSVs predefinidos; execute fora da VM."""

import math
import os
import sys
from contextlib import ExitStack
from pathlib import Path

from dataset import load_dataset
from locust import HttpUser, constant, task
from requests_toolbelt.multipart.encoder import MultipartEncoder

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

DATASET_DIR = Path(os.getenv("DATASET_DIR", str(PROJECT_DIR / "datasets/example"))).resolve()
MANIFEST = load_dataset(DATASET_DIR)
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "120"))
if not math.isfinite(REQUEST_TIMEOUT) or REQUEST_TIMEOUT <= 0:
    raise ValueError("REQUEST_TIMEOUT deve ser finito e > 0")


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
            with self.client.post(
                "/memory-test", data=body, headers={"Content-Type": body.content_type},
                name="/memory-test", timeout=REQUEST_TIMEOUT, catch_response=True,
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
