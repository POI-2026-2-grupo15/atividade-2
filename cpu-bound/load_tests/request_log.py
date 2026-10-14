"""CSV de cada resposta HTTP observada pelo Locust no hospedeiro."""

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path


class RequestCsvLogger:
    FIELDS = ("timestamp_utc", "started_utc", "method", "name", "response_time_ms", "failed", "error")

    def __init__(self, path: Path):
        self.handle = Path(path).open("x", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.handle, fieldnames=self.FIELDS)
        self.writer.writeheader()
        self.handle.flush()

    def write(self, method: str, name: str, response_time_ms: float,
              exception: Exception | None, *, timestamp: datetime | None = None) -> None:
        moment = timestamp or datetime.now(timezone.utc)
        if moment.utcoffset() is None:
            raise ValueError("O timestamp precisa conter fuso horário")
        self.writer.writerow({
            "timestamp_utc": moment.astimezone(timezone.utc).isoformat(),
            "started_utc": (moment - timedelta(milliseconds=response_time_ms)).astimezone(timezone.utc).isoformat(),
            "method": method, "name": name, "response_time_ms": response_time_ms,
            "failed": int(exception is not None), "error": str(exception) if exception else "",
        })
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()
