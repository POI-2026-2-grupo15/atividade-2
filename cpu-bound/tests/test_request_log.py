import csv
from datetime import datetime, timezone

from load_tests.request_log import RequestCsvLogger


def test_request_log_preserves_success_failure_and_utc_timestamp(tmp_path):
    path = tmp_path / "requests.csv"
    logger = RequestCsvLogger(path)
    logger.write("POST", "/benchmark", 1250.5, None,
                 timestamp=datetime(2026, 10, 13, 20, 0, tzinfo=timezone.utc))
    logger.write("POST", "/benchmark", 2000.0, ValueError("HTTP 503"),
                 timestamp=datetime(2026, 10, 13, 20, 0, 1, tzinfo=timezone.utc))
    logger.close()

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {"timestamp_utc": "2026-10-13T20:00:00+00:00", "started_utc": "2026-10-13T19:59:58.749500+00:00", "method": "POST",
         "name": "/benchmark", "response_time_ms": "1250.5", "failed": "0", "error": ""},
        {"timestamp_utc": "2026-10-13T20:00:01+00:00", "started_utc": "2026-10-13T19:59:59+00:00", "method": "POST",
         "name": "/benchmark", "response_time_ms": "2000.0", "failed": "1", "error": "HTTP 503"},
    ]
