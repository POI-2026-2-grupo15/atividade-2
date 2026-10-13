"""Carga fixa por requisição; execute no hospedeiro."""

import math
import os

from locust import HttpUser, constant, task


SIZE_KB = int(os.getenv("SIZE_KB", "1024"))
FSYNC = os.getenv("FSYNC", "1") == "1"
WAIT_SECONDS = float(os.getenv("WAIT_SECONDS", "0"))
if not 1 <= SIZE_KB <= 16 * 1024:
    raise ValueError("SIZE_KB deve estar entre 1 e 16384")
if not math.isfinite(WAIT_SECONDS) or WAIT_SECONDS < 0:
    raise ValueError("WAIT_SECONDS deve ser finito e >= 0")


class IOUser(HttpUser):
    wait_time = constant(WAIT_SECONDS)

    @task
    def io(self):
        with self.client.post(
            "/io", json={"size_kb": SIZE_KB, "fsync": FSYNC},
            name="/io", timeout=120, catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
                return
            try:
                result = response.json()
                if not (result["verified"] and result["size_kb"] == SIZE_KB):
                    response.failure("Resposta de I/O inconsistente")
            except (ValueError, KeyError, TypeError):
                response.failure("Resposta de I/O inválida")
