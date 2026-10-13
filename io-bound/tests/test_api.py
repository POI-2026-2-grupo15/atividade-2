import pytest
from fastapi.testclient import TestClient

from app.main import DATA_DIR, MAX_SIZE_KB, app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("size_kb, fsync", [(1, True), (1500, True), (64, False)])
def test_io_roundtrip(size_kb, fsync):
    response = client.post("/io", json={"size_kb": size_kb, "fsync": fsync})
    assert response.status_code == 200
    result = response.json()
    assert result["verified"] is True
    assert result["size_kb"] == size_kb and result["fsync"] is fsync
    assert result["total_ms"] >= result["write_ms"] >= 0
    assert not list(DATA_DIR.glob("*.bin"))


@pytest.mark.parametrize("body", [
    {"size_kb": 0}, {"size_kb": MAX_SIZE_KB + 1}, {"size_kb": "10"},
    {"size_kb": 1.5}, {"size_kb": 10, "fsync": "yes"}, {"size_kb": 10, "extra": 1}, {},
])
def test_io_validation(body):
    assert client.post("/io", json=body).status_code == 422
