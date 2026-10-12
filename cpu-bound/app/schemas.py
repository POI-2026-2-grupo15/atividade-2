from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MIB = 1024 * 1024
MAX_UPLOAD_BYTES = 16 * MIB
MAX_DATA_SIZE_MB = 32
MAX_ITERATIONS = 1000
MAX_TOTAL_MB = 8192
SHA256Hex = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$", min_length=64, max_length=64)]


class BenchmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    data_size_mb: int = Field(ge=1, le=MAX_DATA_SIZE_MB)
    iterations: int = Field(ge=1, le=MAX_ITERATIONS)

    @model_validator(mode="after")
    def limit_total_work(self) -> "BenchmarkRequest":
        if self.data_size_mb * self.iterations > MAX_TOTAL_MB:
            raise ValueError(f"Trabalho total deve ser <= {MAX_TOTAL_MB} MiB")
        return self


class HashResult(BaseModel):
    filename: str
    size_bytes: int
    algorithm: Literal["sha256"] = "sha256"
    digest: str
    execution_time_ms: float


class VerifyResult(BaseModel):
    filename: str
    size_bytes: int
    algorithm: Literal["sha256"] = "sha256"
    expected_hash: str
    calculated_hash: str
    matches: bool
    execution_time_ms: float


class BenchmarkResult(BaseModel):
    algorithm: Literal["sha256"] = "sha256"
    data_size_mb: int
    iterations: int
    total_processed_mb: int
    preparation_time_ms: float
    execution_time_ms: float
    digest: str
