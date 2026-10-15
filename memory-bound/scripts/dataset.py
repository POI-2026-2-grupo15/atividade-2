import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(directory: Path) -> dict:
    directory = directory.resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["format_version"] != 1 or not manifest["files"]:
        raise ValueError("Manifesto sem arquivos ou com versão incompatível")
    names = set()
    for item in manifest["files"]:
        name = item["name"]
        if Path(name).name != name or name in names:
            raise ValueError("Nome de arquivo inválido ou repetido no manifesto")
        names.add(name)
        path = directory / name
        if path.stat().st_size != item["size_bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Dataset alterado: {name}")
    return manifest
