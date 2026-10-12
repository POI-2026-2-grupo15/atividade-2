import asyncio
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import MAX_UPLOAD_BYTES, BenchmarkRequest

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("data", [b"", b"abc", b"x" * (1024 * 1024 + 1)])
def test_hash(data):
    response = client.post("/hash", files={"file": ("sample.bin", data)})
    assert response.status_code == 200
    result = response.json()
    assert result["digest"] == hashlib.sha256(data).hexdigest()
    assert result["filename"] == "sample.bin"
    assert result["size_bytes"] == len(data)
    assert result["algorithm"] == "sha256"
    assert result["execution_time_ms"] >= 0


@pytest.mark.parametrize("expected, matches", [(hashlib.sha256(b"abc").hexdigest().upper(), True), ("0" * 64, False)])
def test_verify(expected, matches):
    response = client.post("/verify", files={"file": ("a", b"abc")}, data={"expected_hash": expected})
    assert response.status_code == 200
    assert response.json()["matches"] is matches
    assert response.json()["expected_hash"] == expected.lower()
    assert response.json()["calculated_hash"] == hashlib.sha256(b"abc").hexdigest()


@pytest.mark.parametrize("invalid", ["abc", "g" * 64, "a" * 65, "a" * 63, "a" * 64 + "\n"])
def test_invalid_hash(invalid):
    assert client.post("/verify", files={"file": ("a", b"abc")}, data={"expected_hash": invalid}).status_code == 422


def test_benchmark():
    response = client.post("/benchmark", json={"data_size_mb": 1, "iterations": 2})
    assert response.status_code == 200
    assert response.json()["total_processed_mb"] == 2
    assert len(response.json()["digest"]) == 64


@pytest.mark.parametrize("body", [
    {}, {"data_size_mb": 0, "iterations": 1}, {"data_size_mb": 33, "iterations": 1},
    {"data_size_mb": 1, "iterations": 0}, {"data_size_mb": 1, "iterations": 1001},
    {"data_size_mb": 32, "iterations": 257}, {"data_size_mb": True, "iterations": 1},
    {"data_size_mb": 1.5, "iterations": 1}, {"data_size_mb": "1", "iterations": 1},
    {"data_size_mb": 1, "iterations": 1, "extra": 1},
])
def test_invalid_benchmark(body):
    assert client.post("/benchmark", json=body).status_code == 422


def test_limit_boundaries_without_heavy_calculation():
    assert BenchmarkRequest(data_size_mb=32, iterations=256).iterations == 256
    assert BenchmarkRequest(data_size_mb=1, iterations=1000).iterations == 1000


@pytest.mark.parametrize("path", ["/hash", "/verify"])
def test_upload_size_limit(path):
    fields = {"expected_hash": "0" * 64} if path == "/verify" else {}
    assert client.post(path, files={"file": ("big", b"x" * (MAX_UPLOAD_BYTES + 1))}, data=fields).status_code == 413


def test_upload_exact_limit():
    assert client.post("/hash", files={"file": ("limit", b"x" * MAX_UPLOAD_BYTES)}).status_code == 200


def test_missing_file():
    assert client.post("/hash").status_code == 422


def test_streamed_body_limit():
    # A generator omits Content-Length; protection must count received bytes.
    response = client.post("/hash", content=iter([b"x" * 1024] * (17 * 1024 + 1)), headers={"content-type": "multipart/form-data; boundary=abc"})
    assert response.status_code == 413


def test_json_body_limit():
    assert client.post("/benchmark", content=b" " * 4097, headers={"content-type": "application/json"}).status_code == 413


def test_multipart_limit_across_asgi_messages():
    # Unlike TestClient's transport, deliver distinct ASGI receive messages.
    async def exercise():
        chunks = iter([
            b'--abc\r\nContent-Disposition: form-data; name="file"; filename="big"\r\n\r\n',
            *([b"x" * (1024 * 1024)] * 18),
            b"\r\n--abc--\r\n",
        ])
        sent = []

        async def receive():
            return {"type": "http.request", "body": next(chunks), "more_body": True}

        async def send(message):
            sent.append(message)

        await app({
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": "/hash", "raw_path": b"/hash",
            "query_string": b"", "root_path": "",
            "headers": [(b"content-type", b"multipart/form-data; boundary=abc")],
            "client": ("127.0.0.1", 1234), "server": ("localhost", 80),
        }, receive, send)
        assert sent[0]["status"] == 413

    asyncio.run(exercise())
