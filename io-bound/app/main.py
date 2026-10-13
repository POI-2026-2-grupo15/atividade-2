import os
import tempfile
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

DATA_DIR = Path(os.getenv("IO_DATA_DIR", tempfile.gettempdir())) / "io-bound-data"
MAX_SIZE_KB = 16 * 1024
CHUNK = 1024 * 1024
# Buffer aleatório fixo: gerar dados a cada requisição gastaria CPU e mascararia o I/O.
PAYLOAD = os.urandom(CHUNK)

app = FastAPI(title="io-bound", version="1.0.0")


class IORequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    size_kb: int = Field(ge=1, le=MAX_SIZE_KB)
    fsync: bool = True


class IOResult(BaseModel):
    size_kb: int
    fsync: bool
    write_ms: float
    read_ms: float
    total_ms: float
    verified: bool


def drop_page_cache(fd: int) -> None:
    # Linux: descarta as páginas do arquivo para a leitura ir ao disco (sem efeito no macOS).
    if hasattr(os, "posix_fadvise"):
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/io", response_model=IOResult)
def run_io(params: IORequest) -> IOResult:
    # Rota síncrona: roda no thread pool do FastAPI, então várias requisições
    # esperam o disco em paralelo sem bloquear o loop de eventos.
    size = params.size_kb * 1024
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{uuid4().hex}.bin"
    try:
        started = perf_counter()
        with open(path, "wb", buffering=0) as handle:
            written = 0
            while written < size:
                written += handle.write(PAYLOAD[:min(CHUNK, size - written)])
            if params.fsync:
                os.fsync(handle.fileno())
            drop_page_cache(handle.fileno())
        written_at = perf_counter()
        read = 0
        verified = True
        with open(path, "rb", buffering=0) as handle:
            while chunk := handle.read(CHUNK):
                verified = verified and chunk == PAYLOAD[:len(chunk)]
                read += len(chunk)
        finished = perf_counter()
    finally:
        path.unlink(missing_ok=True)
    return IOResult(
        size_kb=params.size_kb, fsync=params.fsync,
        write_ms=(written_at - started) * 1000, read_ms=(finished - written_at) * 1000,
        total_ms=(finished - started) * 1000, verified=verified and read == size,
    )
