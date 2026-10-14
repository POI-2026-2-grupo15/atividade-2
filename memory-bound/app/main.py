from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile

from app.consolidation import CSVSource, InvalidCSV, consolidate
from app.schemas import MemoryResult

app = FastAPI(title="memory-bound")


@app.post("/memory-test", response_model=MemoryResult)
def consolidate_files(files: Annotated[list[UploadFile], File()]) -> MemoryResult:
    try:
        sources = (CSVSource(file.filename or "unnamed-file", file.file) for file in files)
        return consolidate(sources)
    except InvalidCSV as exc:
        raise HTTPException(
            status_code=422,
            detail={"file": exc.filename, "line": exc.line, "reason": exc.reason},
        ) from exc
    finally:
        for file in files:
            file.file.close()
