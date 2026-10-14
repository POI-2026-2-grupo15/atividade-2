import argparse
import csv
import io
import json
from contextlib import ExitStack
from pathlib import Path

from dataset import sha256_file

MIB = 1024 * 1024
HEADER = ["id", "name", "email", "description"]
GENERATOR_VERSION = 1


def nonnegative(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("Informe inteiro >= 0")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--unique-records", type=nonnegative, default=88000)
    parser.add_argument("--duplicates", type=nonnegative, default=8000)
    parser.add_argument("--description-bytes", type=nonnegative, default=1024)
    parser.add_argument("--files", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.unique_records < 10**12 or args.files < 1:
        parser.error("Informe 1..999999999999 IDs únicos e pelo menos um arquivo")
    if args.description_bytes < 25 or args.description_bytes > 64000:
        parser.error("description-bytes deve estar entre 25 e 64000 (compatível com o parser CSV)")
    total = args.unique_records + args.duplicates
    if args.files > total or total // args.unique_records >= 10**6:
        parser.error("Distribuição inválida de arquivos ou versões dos registros")


    sample = io.StringIO(newline="")
    writer = csv.writer(sample, lineterminator="\n")
    writer.writerow(HEADER)
    header_bytes = len(sample.getvalue().encode("utf-8"))
    row_bytes = 12 + 19 + 24 + args.description_bytes + 4
    rows_per_file = (total + args.files - 1) // args.files
    if header_bytes + rows_per_file * row_bytes > 25 * MIB:
        parser.error("Configuração excede 25 MiB por CSV; aumente --files ou reduza registros/descrição")

    args.output.mkdir(parents=True, exist_ok=False)
    paths = [args.output / f"cadastro-{index + 1:02d}.csv" for index in range(args.files)]
    with ExitStack() as stack:
        writers = [csv.writer(stack.enter_context(path.open("w", encoding="utf-8", newline="")),
                              lineterminator="\n") for path in paths]
        for output in writers:
            output.writerow(HEADER)
        for position in range(total):
            record_id = f"{position % args.unique_records:012d}"
            version = position // args.unique_records
            prefix = f"id={record_id};v={version:06d};"
            description = prefix + "x" * (args.description_bytes - len(prefix))
            output_index = min(position // rows_per_file, args.files - 1)
            writers[output_index].writerow([
                record_id, f"person-{record_id}", f"{record_id}@example.com", description,
            ])
    manifest = {
        "format_version": 1,
        "generator_version": GENERATOR_VERSION,
        "parameters": {
            "unique_records": args.unique_records, "duplicates": args.duplicates,
            "description_bytes": args.description_bytes, "files": args.files,
        },
        "files": [{"name": path.name, "size_bytes": path.stat().st_size,
                   "sha256": sha256_file(path)} for path in paths],
        "expected": {"files_processed": args.files, "records_received": total,
                     "unique_records": args.unique_records, "replaced_occurrences": args.duplicates},
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for item in manifest["files"]:
        print(f"{item['name']}: {item['size_bytes'] / MIB:.2f} MiB")


if __name__ == "__main__":
    main()
