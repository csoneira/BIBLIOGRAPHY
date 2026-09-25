"""Library manifest, initialization, and compatibility helpers."""

import csv
import json
import os
import tempfile
from pathlib import Path


FORMAT_VERSION = 1
MANIFEST_NAME = "library.json"
SELECTION_CONFIG_NAME = "config.json"


def selection_config_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return base / "bibliography" / SELECTION_CONFIG_NAME


def resolve_library_selection(application_root: Path) -> dict:
    application_root = application_root.resolve()
    environment_root = os.environ.get("BIBLIOGRAPHY_LIBRARY")
    if environment_root:
        return {
            "root": Path(environment_root).expanduser().resolve(),
            "source": "environment",
            "error": None,
        }
    config_path = selection_config_path()
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            configured_root = config.get("library_root") if isinstance(config, dict) else None
            if not isinstance(configured_root, str) or not configured_root.strip():
                raise ValueError("library_root must be a non-empty string")
            return {
                "root": Path(configured_root).expanduser().resolve(),
                "source": "user_config",
                "error": None,
            }
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return {
                "root": application_root,
                "source": "default",
                "error": f"Invalid {config_path}: {exc}",
            }
    return {"root": application_root, "source": "default", "error": None}


def save_library_selection(root: Path) -> Path:
    root = root.expanduser().resolve()
    description = describe_library(root)
    if not description["valid"]:
        raise ValueError(description["error"] or "Invalid bibliography library")
    config_path = selection_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=config_path.parent, prefix=".config.", suffix=".tmp",
        delete=False, encoding="utf-8",
    ) as handle:
        temp_path = Path(handle.name)
        json.dump({"library_root": str(root)}, handle, indent=2)
        handle.write("\n")
    os.replace(temp_path, config_path)
    return config_path


def clear_library_selection() -> bool:
    config_path = selection_config_path()
    if not config_path.exists():
        return False
    config_path.unlink()
    return True


def read_library_manifest(root: Path) -> dict:
    manifest_path = root / MANIFEST_NAME
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError("library.json must contain a JSON object")
    unknown = set(manifest) - {"format_version", "name", "pdf_archive"}
    if unknown:
        raise ValueError("Unknown library.json fields: " + ", ".join(sorted(unknown)))
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError(
            f"Unsupported library format_version: {manifest.get('format_version')!r}"
        )
    if not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
        raise ValueError("library.json must contain a non-empty name")
    archive = manifest.get("pdf_archive")
    if archive is not None:
        if not isinstance(archive, dict):
            raise ValueError("pdf_archive must be null or a JSON object")
        unknown_archive = set(archive) - {"backend", "remote", "path"}
        if unknown_archive:
            raise ValueError(
                "Unknown pdf_archive fields: " + ", ".join(sorted(unknown_archive))
            )
        backend = archive.get("backend")
        if not isinstance(backend, str) or not backend.strip():
            raise ValueError("pdf_archive.backend must be a non-empty string")
        for field in ("remote", "path"):
            value = archive.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"pdf_archive.{field} must be a string")
    return manifest


def describe_library(root: Path) -> dict:
    root = root.expanduser().resolve()
    manifest_path = root / MANIFEST_NAME
    metadata_path = root / "METADATA" / "metadata.csv"
    result = {
        "root": str(root),
        "exists": root.is_dir(),
        "initialized": manifest_path.is_file(),
        "legacy": False,
        "valid": False,
        "manifest": None,
        "error": None,
    }
    if not root.is_dir():
        result["error"] = "Library directory does not exist"
        return result
    if manifest_path.is_file():
        try:
            result["manifest"] = read_library_manifest(root)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            result["error"] = str(exc)
            return result
        if not metadata_path.is_file():
            result["error"] = "METADATA/metadata.csv is missing"
            return result
        result["valid"] = True
        return result
    if metadata_path.is_file():
        result["legacy"] = True
        result["valid"] = True
        return result
    result["error"] = "Directory is not an initialized bibliography library"
    return result


def _write_json_exclusive(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
        delete=False, encoding="utf-8",
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    try:
        os.link(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _write_csv_header_if_missing(path: Path, fields: list[str]) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerow(fields)
    return True


def initialize_library(
    root: Path,
    name: str,
    metadata_fields: list[str],
    abstract_fields: list[str],
) -> dict:
    root = root.expanduser().resolve()
    name = name.strip()
    if not name:
        raise ValueError("Library name cannot be empty")
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / MANIFEST_NAME
    manifest_created = False
    if manifest_path.exists():
        manifest = read_library_manifest(root)
    else:
        manifest = {
            "format_version": FORMAT_VERSION,
            "name": name,
            "pdf_archive": None,
        }
        _write_json_exclusive(manifest_path, manifest)
        manifest_created = True

    created = [MANIFEST_NAME] if manifest_created else []
    for directory in ("METADATA", "SAVED_LISTS", "CONFIGS", "PDFs"):
        path = root / directory
        if not path.exists():
            path.mkdir(parents=True)
            created.append(f"{directory}/")
    if _write_csv_header_if_missing(root / "METADATA" / "metadata.csv", metadata_fields):
        created.append("METADATA/metadata.csv")
    if _write_csv_header_if_missing(root / "METADATA" / "abstracts.csv", abstract_fields):
        created.append("METADATA/abstracts.csv")

    config_path = root / "CONFIGS" / "config.json"
    if not config_path.exists():
        config_path.write_text('{\n  "my_keywords": []\n}\n', encoding="utf-8")
        created.append("CONFIGS/config.json")
    gitignore_path = root / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(
            "PDFs/\nMETADATA/backups/\nMETADATA/title_audit_cache.json\n*.tmp\n",
            encoding="utf-8",
        )
        created.append(".gitignore")
    result = describe_library(root)
    result.update({"created": created, "manifest": manifest})
    return result
