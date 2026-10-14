import csv
from codecs import getreader
from dataclasses import dataclass
from time import perf_counter
from typing import BinaryIO, Iterable

from app.schemas import MemoryResult

HEADER = ["id", "name", "email", "description"]


@dataclass(frozen=True)
class CSVSource:
    filename: str
    stream: BinaryIO


class InvalidCSV(ValueError):
    def __init__(self, filename: str, line: int, reason: str) -> None:
        self.filename = filename
        self.line = line
        self.reason = reason
        super().__init__(reason)


def read_into_catalog(source: CSVSource, catalog: dict[str, dict[str, str]]) -> int:
    text = getreader("utf-8-sig")(source.stream)
    reader = csv.reader(text, strict=True)
    received = 0
    try:
        header = next(reader, None)
        if header != HEADER:
            raise InvalidCSV(
                source.filename,
                reader.line_num or 1,
                "Cabeçalho esperado: id,name,email,description",
            )
        for row in reader:
            if not row:
                continue
            if len(row) != len(HEADER):
                raise InvalidCSV(
                    source.filename,
                    reader.line_num,
                    "Cada registro deve conter exatamente quatro campos",
                )
            if not row[0].strip():
                raise InvalidCSV(
                    source.filename, reader.line_num, "ID não pode estar vazio"
                )

            catalog[row[0]] = dict(zip(HEADER, row))
            received += 1
    except UnicodeError as exc:
        raise InvalidCSV(
            source.filename, reader.line_num or 1, "Arquivo deve usar codificação UTF-8"
        ) from exc
    except csv.Error as exc:
        raise InvalidCSV(
            source.filename,
            reader.line_num or 1,
            "CSV malformado ou campo incompatível com o parser",
        ) from exc
    return received


def consolidate(sources: Iterable[CSVSource]) -> MemoryResult:
    started = perf_counter()
    catalog: dict[str, dict[str, str]] = {}
    files_processed = records_received = 0
    try:
        for source in sources:
            records_received += read_into_catalog(source, catalog)
            files_processed += 1
        unique_records = len(catalog)
        return MemoryResult(
            files_processed=files_processed,
            records_received=records_received,
            unique_records=unique_records,
            replaced_occurrences=records_received - unique_records,
            processing_time_ms=(perf_counter() - started) * 1000,
        )
    finally:
        catalog.clear()
