from pydantic import BaseModel, Field


class MemoryResult(BaseModel):
    files_processed: int = Field(ge=0)
    records_received: int = Field(ge=0)
    unique_records: int = Field(ge=0)
    replaced_occurrences: int = Field(ge=0)
    processing_time_ms: float = Field(ge=0)
