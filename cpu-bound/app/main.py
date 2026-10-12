import hmac
from time import perf_counter
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app.hashing import UploadTooLarge, benchmark, hash_stream
from app.limits import ResourceLimits
from app.schemas import BenchmarkRequest, BenchmarkResult, HashResult, SHA256Hex, VerifyResult

app = FastAPI(title="cpu-bound", version="1.0.0")
app.add_middleware(ResourceLimits)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def calculate_upload(file: UploadFile) -> tuple[str, int, float]:
    started = perf_counter()
    try:
        digest, size = hash_stream(file.file)
    except UploadTooLarge as exc:
        raise HTTPException(413, str(exc)) from exc
    return digest, size, (perf_counter() - started) * 1000


@app.post("/hash", response_model=HashResult)
def hash_file(file: Annotated[UploadFile, File()]) -> HashResult:
    digest, size, duration = calculate_upload(file)
    return HashResult(filename=file.filename or "", size_bytes=size, digest=digest, execution_time_ms=duration)


@app.post("/verify", response_model=VerifyResult)
def verify_file(file: Annotated[UploadFile, File()], expected_hash: Annotated[SHA256Hex, Form()]) -> VerifyResult:
    digest, size, duration = calculate_upload(file)
    expected_hash = expected_hash.lower()
    return VerifyResult(
        filename=file.filename or "", size_bytes=size, expected_hash=expected_hash,
        calculated_hash=digest, matches=hmac.compare_digest(expected_hash, digest),
        execution_time_ms=duration,
    )


@app.post("/benchmark", response_model=BenchmarkResult)
async def run_benchmark(params: BenchmarkRequest) -> BenchmarkResult:
    return benchmark(params)
