import hashlib
import io

import pytest

from app.hashing import benchmark, hash_stream, UploadTooLarge
from app.schemas import BenchmarkRequest


def test_known_hash_and_size():
    digest, size = hash_stream(io.BytesIO(b"abc"))
    assert digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert size == 3


def test_stream_limits():
    assert hash_stream(io.BytesIO(b"abcd"), max_bytes=4)[1] == 4
    with pytest.raises(UploadTooLarge):
        hash_stream(io.BytesIO(b"abcde"), max_bytes=4)


def test_benchmark_reference_and_determinism():
    params = BenchmarkRequest(data_size_mb=1, iterations=2)
    first = benchmark(params)
    second = benchmark(params)
    data = bytes(range(256)) * 4096
    expected = hashlib.sha256(hashlib.sha256(data).digest() * 2).hexdigest()
    assert first.digest == second.digest == expected
    assert first.total_processed_mb == 2
    assert first.execution_time_ms > 0
    assert first.preparation_time_ms > 0
    assert benchmark(BenchmarkRequest(data_size_mb=1, iterations=1)).digest != first.digest


def test_benchmark_hashes_entire_same_buffer_each_iteration(monkeypatch):
    # Spy delegates to real SHA-256; guards against replacing real work with a cache.
    real_sha256 = hashlib.sha256
    buffers = []

    def record_sha256(data=b""):
        if data:
            buffers.append(data)
        return real_sha256(data)

    monkeypatch.setattr("app.hashing.hashlib.sha256", record_sha256)
    benchmark(BenchmarkRequest(data_size_mb=1, iterations=3))
    assert len(buffers) == 3
    assert all(len(data) == 1024 * 1024 for data in buffers)
    assert all(data is buffers[0] for data in buffers)
