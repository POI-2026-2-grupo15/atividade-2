"""Carga fixa por requisição; execute no hospedeiro."""

import math
import os

from locust import HttpUser, constant, task


DATA_SIZE_MB = int(os.getenv("DATA_SIZE_MB", "10"))
ITERATIONS = int(os.getenv("ITERATIONS", "100"))
WAIT_SECONDS = float(os.getenv("WAIT_SECONDS", "0"))
if not 1 <= DATA_SIZE_MB <= 32 or not 1 <= ITERATIONS <= 1000 or DATA_SIZE_MB * ITERATIONS > 8192:
    raise ValueError("Carga fora dos limites: 1–32 MiB, 1–1000 iterações, produto <= 8192")
if not math.isfinite(WAIT_SECONDS) or WAIT_SECONDS < 0:
    raise ValueError("WAIT_SECONDS deve ser finito e >= 0")


class BenchmarkUser(HttpUser):
    wait_time = constant(WAIT_SECONDS)

    @task
    def benchmark(self):
        with self.client.post(
            "/benchmark", json={"data_size_mb": DATA_SIZE_MB, "iterations": ITERATIONS},
            name="/benchmark", timeout=120, catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
                return
            try:
                result = response.json()
                valid = (
                    result["algorithm"] == "sha256"
                    and result["data_size_mb"] == DATA_SIZE_MB
                    and result["iterations"] == ITERATIONS
                    and result["total_processed_mb"] == DATA_SIZE_MB * ITERATIONS
                    and len(result["digest"]) == 64
                    and result["execution_time_ms"] > 0
                )
                if not valid:
                    response.failure("Resposta de benchmark inconsistente")
            except (ValueError, KeyError, TypeError):
                response.failure("Resposta de benchmark inválida")
