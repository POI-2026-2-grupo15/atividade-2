"""Cálculos locais; nenhuma dependência de HTTP ou acesso externo."""

import hashlib
from time import perf_counter
from typing import BinaryIO

from app.schemas import BenchmarkRequest, BenchmarkResult, MAX_UPLOAD_BYTES, MIB

CHUNK_SIZE = 64 * 1024


class UploadTooLarge(ValueError):
    pass


def hash_stream(stream: BinaryIO, max_bytes: int = MAX_UPLOAD_BYTES) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(CHUNK_SIZE):
        size += len(chunk)
        if size > max_bytes:
            raise UploadTooLarge("Arquivo excede o limite de upload")
        digest.update(chunk)
    return digest.hexdigest(), size


def benchmark(params: BenchmarkRequest) -> BenchmarkResult:
    started = perf_counter()
    data = bytes(range(256)) * (params.data_size_mb * MIB // 256)
    preparation_time_ms = (perf_counter() - started) * 1000

    started = perf_counter()
    aggregate = hashlib.sha256()
    for _ in range(params.iterations):
        # Recalcular efetivamente: nenhum cache, cópia ou reconstrução de data.
        aggregate.update(hashlib.sha256(data).digest())
    digest = aggregate.hexdigest()
    execution_time_ms = (perf_counter() - started) * 1000
    return BenchmarkResult(
        data_size_mb=params.data_size_mb,
        iterations=params.iterations,
        total_processed_mb=params.data_size_mb * params.iterations,
        preparation_time_ms=preparation_time_ms,
        execution_time_ms=execution_time_ms,
        digest=digest,
    )
