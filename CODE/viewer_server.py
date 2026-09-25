#!/usr/bin/env python3
import csv
import hashlib
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

APPLICATION_ROOT = Path(__file__).resolve().parent.parent
CODE_ROOT = Path(__file__).resolve().parent
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))
from library_state import describe_library, resolve_library_selection

LIBRARY_SELECTION = resolve_library_selection(APPLICATION_ROOT)
LIBRARY_ROOT = LIBRARY_SELECTION["root"]
ROOT = LIBRARY_ROOT  # Backward-compatible alias used by existing integrations.
SAVED_LISTS_DIR = LIBRARY_ROOT / "SAVED_LISTS"
ABSTRACTS_FILE = LIBRARY_ROOT / "METADATA" / "abstracts.csv"
METADATA_FILE = LIBRARY_ROOT / "METADATA" / "metadata.csv"
CHANGE_BACKUP_DIR = LIBRARY_ROOT / "METADATA" / "backups" / "viewer_changes"
CHECKPOINT_BACKUP_DIR = LIBRARY_ROOT / "METADATA" / "backups" / "checkpoints"
CHANGE_HISTORY_LIMIT = 10
CUSTOM_WALLPAPER_DIR = APPLICATION_ROOT / "VIEWER" / "wallpapers" / "custom"
_ABSTRACT_CACHE = {"mtime_ns": None, "data": {}}
_ANNOTATION_SCAN_CACHE = {}
_WRITE_LOCK = threading.Lock()
METADATA_FIELDS = [
    "code",
    "type",
    "title",
    "journal",
    "year",
    "publication_date",
    "doi",
    "author",
    "keywords",
    "my_keywords",
    "star",
    "unread",
    "annotated",
    "added_at",
    "pdf_hosts",
    "pdf_sha256",
    "last_viewed",
    "notes",
]


class DuplicateEntryError(ValueError):
    def __init__(self, matches: list):
        super().__init__("A matching entry already exists")
        self.matches = matches


def migrate_metadata_schema() -> list:
    """Add known missing columns without ever discarding unknown future columns."""
    if not METADATA_FILE.exists():
        return []
    with METADATA_FILE.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    unknown = [field for field in header if field not in METADATA_FIELDS]
    if unknown:
        raise RuntimeError(
            "metadata.csv contains columns this version does not understand: "
            + ", ".join(unknown)
        )
    missing = [field for field in METADATA_FIELDS if field not in header]
    if not missing:
        return []

    backup_dir = METADATA_FILE.parent / "backups" / "schema_migrations"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    shutil.copy2(METADATA_FILE, backup_dir / f"metadata-before-{stamp}.csv")
    write_metadata_rows(rows, migrate=False)
    return missing


def load_metadata_rows() -> list:
    if not METADATA_FILE.exists():
        return []
    migrate_metadata_schema()
    with METADATA_FILE.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_metadata_rows(rows: list, migrate: bool = True) -> None:
    if migrate:
        migrate_metadata_schema()
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        dir=METADATA_FILE.parent,
        prefix=".metadata-",
        suffix=".tmp",
        delete=False,
        newline="",
        encoding="utf-8",
    ) as handle:
        temp_path = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=METADATA_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in METADATA_FIELDS})
    os.replace(temp_path, METADATA_FILE)


def create_change_snapshot(action: str) -> Path:
    CHANGE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot = CHANGE_BACKUP_DIR / f"change-{stamp}"
    snapshot.mkdir()
    if METADATA_FILE.exists():
        shutil.copy2(METADATA_FILE, snapshot / "metadata.csv")
    if ABSTRACTS_FILE.exists():
        shutil.copy2(ABSTRACTS_FILE, snapshot / "abstracts.csv")
    if SAVED_LISTS_DIR.exists():
        shutil.copytree(SAVED_LISTS_DIR, snapshot / "saved_lists")
    keyword_config = ROOT / "CONFIGS" / "config.json"
    if keyword_config.exists():
        shutil.copy2(keyword_config, snapshot / "config.json")
    (snapshot / "manifest.json").write_text(
        json.dumps({"action": action, "created_at": stamp}, indent=2),
        encoding="utf-8",
    )
    return snapshot


def update_snapshot_manifest(snapshot: Path, **updates) -> None:
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(updates)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def discard_snapshot(snapshot: Path) -> None:
    if snapshot.exists():
        snapshot.rename(snapshot.with_name(f"{snapshot.name}.discarded"))


def list_change_snapshots() -> list:
    if not CHANGE_BACKUP_DIR.exists():
        return []
    return sorted(
        path
        for path in CHANGE_BACKUP_DIR.glob("change-*")
        if path.is_dir() and not path.name.endswith(".restored")
        and not path.name.endswith(".discarded")
    )


def prune_change_history(limit: int = CHANGE_HISTORY_LIMIT) -> int:
    if not CHANGE_BACKUP_DIR.exists():
        return 0
    discarded = sorted(
        path for path in CHANGE_BACKUP_DIR.glob("change-*.discarded") if path.is_dir()
    )
    movements = sorted(
        path
        for path in CHANGE_BACKUP_DIR.glob("change-*")
        if path.is_dir() and not path.name.endswith(".discarded")
    )
    obsolete = discarded + movements[:-limit] if limit else discarded + movements
    removed = 0
    for path in obsolete:
        try:
            shutil.rmtree(path)
            removed += 1
        except FileNotFoundError:
            pass
    return removed


def change_history(limit: int = CHANGE_HISTORY_LIMIT) -> list:
    if not CHANGE_BACKUP_DIR.exists():
        return []
    prune_change_history(limit)
    active = list_change_snapshots()
    latest = active[-1] if active else None
    history = []
    paths = sorted(
        (
            path for path in CHANGE_BACKUP_DIR.glob("change-*")
            if path.is_dir() and not path.name.endswith(".discarded")
        ),
        reverse=True,
    )
    for path in paths[:limit]:
        manifest_path = path / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        stamp = str(manifest.get("created_at") or "")
        try:
            created_at = datetime.strptime(stamp, "%Y%m%dT%H%M%S%fZ").replace(
                tzinfo=timezone.utc
            ).isoformat().replace("+00:00", "Z")
        except ValueError:
            created_at = stamp
        undone = path.name.endswith(".restored")
        history.append(
            {
                "action": str(manifest.get("action") or "Change"),
                "created_at": created_at,
                "status": "undone" if undone else "applied",
                "undoable": path == latest,
            }
        )
    return history


def undo_last_change() -> dict:
    snapshots = list_change_snapshots()
    if not snapshots:
        raise ValueError("There is no viewer change to undo")
    snapshot = snapshots[-1]
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if (snapshot / "metadata.csv").exists():
        shutil.copy2(snapshot / "metadata.csv", METADATA_FILE)
    if (snapshot / "abstracts.csv").exists():
        shutil.copy2(snapshot / "abstracts.csv", ABSTRACTS_FILE)
    if (snapshot / "config.json").exists():
        keyword_config = ROOT / "CONFIGS" / "config.json"
        keyword_config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot / "config.json", keyword_config)
    saved_backup = snapshot / "saved_lists"
    if saved_backup.exists():
        SAVED_LISTS_DIR.mkdir(parents=True, exist_ok=True)
        for path in SAVED_LISTS_DIR.glob("*.json"):
            path.unlink()
        for path in saved_backup.glob("*.json"):
            shutil.copy2(path, SAVED_LISTS_DIR / path.name)

    created_pdf = manifest.get("created_pdf")
    if created_pdf:
        created_path = ROOT / created_pdf
        if created_path.exists():
            trash_dir = ROOT / "PDFs" / ".trash"
            trash_dir.mkdir(parents=True, exist_ok=True)
            created_path.replace(trash_dir / f"undo-{snapshot.name}-{created_path.name}")
    replaced_pdf = manifest.get("replaced_pdf") or {}
    if replaced_pdf:
        replacement_target = ROOT / replaced_pdf.get("path", "")
        replacement_backup = snapshot / replaced_pdf.get("backup", "")
        if replacement_backup.exists():
            replacement_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(replacement_backup, replacement_target)
    moved_pdf = manifest.get("moved_pdf") or {}
    moved_from = ROOT / moved_pdf.get("from", "") if moved_pdf else None
    moved_to = ROOT / moved_pdf.get("to", "") if moved_pdf else None
    if moved_from and moved_to and moved_to.exists() and not moved_from.exists():
        moved_to.replace(moved_from)
    for movement in reversed(manifest.get("pdf_moves", [])):
        source = ROOT / movement.get("from", "")
        destination = ROOT / movement.get("to", "")
        if destination.exists() and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            destination.replace(source)

    restored = snapshot.with_name(f"{snapshot.name}.restored")
    snapshot.rename(restored)
    return {"action": manifest.get("action", "change"), "snapshot": restored.name}


def normalize_title_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def normalize_doi(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^doi:\s*", "", value, flags=re.IGNORECASE)
    return value.lower()


def duplicate_matches(rows: list, title: str, doi: str, exclude_code: str = "") -> list:
    title_key = normalize_title_key(title)
    doi_key = normalize_doi(doi)
    matches = []
    for row in rows:
        code = (row.get("code") or "").strip()
        if code == exclude_code:
            continue
        same_title = title_key and normalize_title_key(row.get("title")) == title_key
        same_doi = doi_key and normalize_doi(row.get("doi")) == doi_key
        if same_title or same_doi:
            matches.append({"code": code, "title": row.get("title", ""), "doi": row.get("doi", "")})
    return matches


def slugify(value: str, max_len: int = 60) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    value = re.sub(r"_+", "_", value).strip("_")
    return (value or "untitled")[:max_len].rstrip("_")


def create_metadata_entry(payload: dict) -> dict:
    title = _clean_citation_value(payload.get("title", ""))
    publication_date = str(payload.get("publication_date") or "").strip()
    doc_type = slugify(str(payload.get("type") or "article"), max_len=20)

    if not title:
        raise ValueError("Title is required")
    publication_pattern = r"\d{4}(?:-(0[1-9]|1[0-2])(?:-(0[1-9]|[12]\d|3[01]))?)?"
    if publication_date and not re.fullmatch(publication_pattern, publication_date):
        raise ValueError("Publication date must use YYYY, YYYY-MM, or YYYY-MM-DD")
    if publication_date and len(publication_date) == 10:
        try:
            date.fromisoformat(publication_date)
        except ValueError as exc:
            raise ValueError("Publication date is not a valid calendar date") from exc

    year = publication_date[:4] if publication_date else ""

    metadata_dir = METADATA_FILE.parent
    metadata_dir.mkdir(parents=True, exist_ok=True)
    rows = load_metadata_rows()
    doi = str(payload.get("doi") or "").strip()
    matches = duplicate_matches(rows, title, doi)
    if matches and not payload.get("allow_duplicate"):
        raise DuplicateEntryError(matches)

    existing_codes = {(row.get("code") or "").strip() for row in rows}
    base_code = f"{year or 'undated'}_{doc_type}_{slugify(title)}"
    code = base_code
    suffix = 2
    while code in existing_codes:
        code = f"{base_code}_{suffix}"
        suffix += 1

    row = {field: "" for field in METADATA_FIELDS}
    row.update(
        {
            "code": code,
            "type": doc_type,
            "title": title,
            "journal": _clean_citation_value(payload.get("journal", "")),
            "year": year,
            "publication_date": publication_date,
            "doi": doi,
            "author": _clean_citation_value(payload.get("author", "")),
            "keywords": str(payload.get("keywords") or "").strip(),
            "my_keywords": str(payload.get("my_keywords") or "").strip(),
            "star": "1" if payload.get("star") in (True, "1", 1) else "",
            "unread": "1" if payload.get("unread") in (True, "1", 1) else "",
            "annotated": "1" if payload.get("annotated") in (True, "1", 1) else "",
            "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            # Metadata-only entries deliberately have no recorded PDF host.
            "pdf_hosts": "",
            "pdf_sha256": "",
            "last_viewed": "",
            "notes": str(payload.get("notes") or "").strip(),
        }
    )
    rows.append(row)

    write_metadata_rows(rows)
    return row


def validate_publication_date(value: str) -> str:
    value = str(value or "").strip()
    pattern = r"\d{4}(?:-(0[1-9]|1[0-2])(?:-(0[1-9]|[12]\d|3[01]))?)?"
    if value and not re.fullmatch(pattern, value):
        raise ValueError("Publication date must use YYYY, YYYY-MM, or YYYY-MM-DD")
    if value and len(value) == 10:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Publication date is not a valid calendar date") from exc
    return value


def canonical_entry_code(rows: list, current_code: str, title: str, doc_type: str, year: str) -> str:
    base = f"{year or 'undated'}_{doc_type}_{slugify(title)}"
    occupied = {
        (row.get("code") or "").strip()
        for row in rows
        if (row.get("code") or "").strip() != current_code
    }
    candidate, suffix = base, 2
    while candidate in occupied or (
        candidate != current_code and (ROOT / "PDFs" / f"{candidate}.pdf").exists()
    ):
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def rename_entry_sidecars(old_code: str, new_code: str, snapshot: Path | None = None) -> None:
    if old_code == new_code:
        return
    movements = []
    old_pdf = ROOT / "PDFs" / f"{old_code}.pdf"
    new_pdf = ROOT / "PDFs" / f"{new_code}.pdf"
    if old_pdf.exists():
        new_pdf.parent.mkdir(parents=True, exist_ok=True)
        old_pdf.replace(new_pdf)
        movements.append({
            "from": str(old_pdf.relative_to(ROOT)),
            "to": str(new_pdf.relative_to(ROOT)),
        })

    abstracts = load_abstracts_map()
    if old_code in abstracts:
        if new_code not in abstracts:
            abstracts[new_code] = abstracts[old_code]
        abstracts.pop(old_code, None)
        write_abstracts_map(abstracts)

    for path in SAVED_LISTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        codes = data.get("codes", [])
        if old_code not in codes:
            continue
        data["codes"] = list(dict.fromkeys(new_code if code == old_code else code for code in codes))
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    cached_signature = _ANNOTATION_SCAN_CACHE.pop(old_code, None)
    if cached_signature is not None:
        _ANNOTATION_SCAN_CACHE[new_code] = cached_signature
    if snapshot and movements:
        update_snapshot_manifest(snapshot, pdf_moves=movements)


def update_metadata_entry(payload: dict, snapshot: Path | None = None) -> dict:
    code = str(payload.get("code") or "").strip()
    title = _clean_citation_value(payload.get("title", ""))
    publication_date = validate_publication_date(payload.get("publication_date"))
    doc_type = slugify(str(payload.get("type") or "article"), max_len=20)
    if not code:
        raise ValueError("Code is required")
    if not title:
        raise ValueError("Title is required")

    rows = load_metadata_rows()
    matches = duplicate_matches(rows, title, payload.get("doi", ""), exclude_code=code)
    if matches and not payload.get("allow_duplicate"):
        raise DuplicateEntryError(matches)

    publication_year = publication_date[:4] if publication_date else str(payload.get("year") or "").strip()
    new_code = canonical_entry_code(rows, code, title, doc_type, publication_year)
    updated = None
    for row in rows:
        if (row.get("code") or "").strip() != code:
            continue
        row.update(
            {
                "type": doc_type,
                "title": title,
                "journal": _clean_citation_value(payload.get("journal", "")),
                "year": publication_year,
                "publication_date": publication_date,
                "doi": str(payload.get("doi") or "").strip(),
                "author": _clean_citation_value(payload.get("author", "")),
                "keywords": str(payload.get("keywords") or "").strip(),
                "my_keywords": str(payload.get("my_keywords") or "").strip(),
                "star": "1" if payload.get("star") in (True, "1", 1) else "",
                "unread": "1" if payload.get("unread") in (True, "1", 1) else "",
                # General metadata edits must not erase a previously detected/manual mark.
                # The dedicated card toggle remains the explicit way to clear it.
                "annotated": "1" if (
                    row.get("annotated") == "1"
                    or payload.get("annotated") in (True, "1", 1)
                ) else "",
                "notes": str(payload.get("notes") or "").strip(),
            }
        )
        if "pdf_hosts" in payload:
            row["pdf_hosts"] = "; ".join(normalize_hosts(payload.get("pdf_hosts", "")))
        row["code"] = new_code
        updated = dict(row)
        break
    if updated is None:
        raise LookupError("Entry not found")
    rename_entry_sidecars(code, new_code, snapshot)
    write_metadata_rows(rows)
    updated["previous_code"] = code
    return updated


def normalize_hosts(hosts) -> list:
    if isinstance(hosts, str):
        hosts = re.split(r"[;,]", hosts)
    normalized = []
    for host in hosts:
        host = str(host or "").strip()
        if not host:
            continue
        if not re.fullmatch(r"[A-Za-z0-9._-]+", host):
            raise ValueError(f"Invalid computer name: {host}")
        if host not in normalized:
            normalized.append(host)
    return normalized


def update_entry_hosts(code: str, hosts: list) -> dict:
    normalized = normalize_hosts(hosts)
    rows = load_metadata_rows()
    for row in rows:
        if (row.get("code") or "").strip() == code:
            row["pdf_hosts"] = "; ".join(normalized)
            write_metadata_rows(rows)
            return dict(row)
    raise LookupError("Entry not found")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pdf_has_annotations(path: Path) -> bool:
    """Detect structured reader annotations; flattened page markings are not distinguishable."""
    try:
        from PyPDF2 import PdfReader

        annotation_types = {
            "/Text", "/FreeText", "/Highlight", "/Underline", "/Squiggly",
            "/StrikeOut", "/Ink", "/Stamp", "/Caret", "/Sound",
            "/FileAttachment", "/Redact",
        }
        reader = PdfReader(str(path), strict=False)
        for page in reader.pages:
            references = page.get("/Annots", []) or []
            if hasattr(references, "get_object"):
                references = references.get_object()
            for reference in references:
                annotation = reference.get_object()
                if str(annotation.get("/Subtype", "")) in annotation_types:
                    return True
    except Exception:
        return False
    return False


def reconcile_local_pdf_annotations() -> dict:
    """Promote entries when a new or replaced local PDF contains structured annotations."""
    rows = load_metadata_rows()
    by_code = {(row.get("code") or "").strip(): row for row in rows}
    checked = detected = updated = 0
    for path in sorted((ROOT / "PDFs").glob("*.pdf")):
        row = by_code.get(path.stem)
        if row is None:
            continue
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if _ANNOTATION_SCAN_CACHE.get(path.stem) == signature:
            continue
        checked += 1
        has_annotations = pdf_has_annotations(path)
        _ANNOTATION_SCAN_CACHE[path.stem] = signature
        if has_annotations:
            detected += 1
            if row.get("annotated") != "1":
                row["annotated"] = "1"
                updated += 1
    if updated:
        create_change_snapshot("automatic annotation scan")
        write_metadata_rows(rows)
    return {"checked": checked, "detected": detected, "updated": updated}


def annotation_scan_worker(stop_event: threading.Event) -> None:
    while not stop_event.wait(15):
        try:
            with _WRITE_LOCK:
                reconcile_local_pdf_annotations()
        except (OSError, RuntimeError):
            # Keep the local viewer alive if a PDF is temporarily being copied.
            continue


def write_abstracts_map(abstracts: dict) -> None:
    ABSTRACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=ABSTRACTS_FILE.parent, prefix=".abstracts-", suffix=".tmp",
        delete=False, newline="", encoding="utf-8",
    ) as handle:
        temp_path = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=["code", "abstract"], lineterminator="\n")
        writer.writeheader()
        for code in sorted(abstracts):
            value = str(abstracts[code] or "").strip()
            if value:
                writer.writerow({"code": code, "abstract": value})
    os.replace(temp_path, ABSTRACTS_FILE)
    _ABSTRACT_CACHE["mtime_ns"] = None


def set_abstract(code: str, value: str) -> None:
    abstracts = load_abstracts_map()
    value = str(value or "").strip()
    if value:
        abstracts[code] = value
    else:
        abstracts.pop(code, None)
    write_abstracts_map(abstracts)


def merge_delimited_values(*values) -> str:
    merged = []
    seen = set()
    for value in values:
        for item in re.split(r"[;,]", str(value or "")):
            item = item.strip()
            if item and item.casefold() not in seen:
                seen.add(item.casefold())
                merged.append(item)
    return "; ".join(merged)


def merge_metadata_entries(source_code: str, target_code: str, snapshot: Path | None = None) -> dict:
    source_code = str(source_code or "").strip()
    target_code = str(target_code or "").strip()
    if not source_code or not target_code or source_code == target_code:
        raise ValueError("Choose two different entries")
    rows = load_metadata_rows()
    source = next((row for row in rows if row.get("code", "").strip() == source_code), None)
    target = next((row for row in rows if row.get("code", "").strip() == target_code), None)
    if source is None or target is None:
        raise LookupError("Source or destination entry not found")

    special = {"code", "keywords", "my_keywords", "pdf_hosts", "star", "unread", "annotated", "notes", "added_at", "last_viewed"}
    for field in METADATA_FIELDS:
        if field not in special and not str(target.get(field) or "").strip() and str(source.get(field) or "").strip():
            target[field] = source[field]
    for field in ("keywords", "my_keywords", "pdf_hosts"):
        target[field] = merge_delimited_values(target.get(field), source.get(field))
    target["star"] = "1" if target.get("star") == "1" or source.get("star") == "1" else ""
    target["unread"] = "1" if target.get("unread") == "1" or source.get("unread") == "1" else ""
    target["annotated"] = "1" if target.get("annotated") == "1" or source.get("annotated") == "1" else ""
    target["added_at"] = min(filter(None, [target.get("added_at", ""), source.get("added_at", "")]), default="")
    target["last_viewed"] = max(target.get("last_viewed", ""), source.get("last_viewed", ""))
    source_notes = str(source.get("notes") or "").strip()
    target_notes = str(target.get("notes") or "").strip()
    if source_notes and source_notes not in target_notes:
        target["notes"] = "\n\n".join(filter(None, [target_notes, source_notes]))

    source_pdf = ROOT / "PDFs" / f"{source_code}.pdf"
    target_pdf = ROOT / "PDFs" / f"{target_code}.pdf"
    movements = []
    if source_pdf.exists():
        if not target_pdf.exists():
            source_pdf.replace(target_pdf)
            movements.append({"from": str(source_pdf.relative_to(ROOT)), "to": str(target_pdf.relative_to(ROOT))})
            target["pdf_sha256"] = sha256_file(target_pdf)
        else:
            duplicate_dir = ROOT / "PDFs" / ".duplicates"
            duplicate_dir.mkdir(parents=True, exist_ok=True)
            suffix = "same" if sha256_file(source_pdf) == sha256_file(target_pdf) else "different"
            duplicate_path = duplicate_dir / f"{snapshot.name if snapshot else 'merge'}-{suffix}-{source_pdf.name}"
            source_pdf.replace(duplicate_path)
            movements.append({"from": str(source_pdf.relative_to(ROOT)), "to": str(duplicate_path.relative_to(ROOT))})
            target["pdf_sha256"] = sha256_file(target_pdf)

    abstracts = load_abstracts_map()
    if not abstracts.get(target_code, "").strip() and abstracts.get(source_code, "").strip():
        abstracts[target_code] = abstracts[source_code]
    abstracts.pop(source_code, None)
    write_abstracts_map(abstracts)
    for path in SAVED_LISTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        replaced = [target_code if code == source_code else code for code in data.get("codes", [])]
        data["codes"] = list(dict.fromkeys(replaced))
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_metadata_rows([row for row in rows if row is not source])
    if snapshot and movements:
        update_snapshot_manifest(snapshot, pdf_moves=movements)
    return {"source": source_code, "target": target_code, "pdf_moves": len(movements)}


def clean_markup(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()


def date_parts_to_text(parts) -> str:
    if not parts:
        return ""
    parts = parts[0] if isinstance(parts[0], list) else parts
    return "-".join(str(value).zfill(2) if index else str(value) for index, value in enumerate(parts[:3]))


def parse_crossref_message(message: dict) -> dict:
    authors = []
    for author in message.get("author", []):
        name = " ".join(filter(None, [author.get("given", ""), author.get("family", "")])).strip()
        if name:
            authors.append(name)
    date_value = ""
    for key in ("published-print", "published-online", "issued"):
        date_value = date_parts_to_text(message.get(key, {}).get("date-parts", []))
        if date_value:
            break
    type_map = {
        "journal-article": "article", "book": "book", "book-chapter": "chapter",
        "proceedings-article": "conference", "posted-content": "preprint",
        "report": "report", "dissertation": "thesis",
    }
    return {
        "title": clean_markup((message.get("title") or [""])[0]),
        "author": "; ".join(authors),
        "journal": clean_markup((message.get("container-title") or [""])[0]),
        "publication_date": date_value, "doi": message.get("DOI", ""),
        "type": type_map.get(message.get("type", ""), "article"),
        "abstract": clean_markup(message.get("abstract", "")), "source": "Crossref",
    }


def parse_arxiv_feed(raw: bytes) -> dict:
    root = ET.fromstring(raw)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise LookupError("arXiv entry not found")

    def text_at(path):
        node = entry.find(path, ns)
        return clean_markup(node.text if node is not None else "")

    authors = [clean_markup(node.findtext("atom:name", default="", namespaces=ns)) for node in entry.findall("atom:author", ns)]
    return {
        "title": text_at("atom:title"), "author": "; ".join(filter(None, authors)),
        "journal": text_at("arxiv:journal_ref"), "publication_date": text_at("atom:published")[:10],
        "doi": text_at("arxiv:doi"), "type": "preprint", "abstract": text_at("atom:summary"),
        "arxiv": text_at("atom:id").rsplit("/abs/", 1)[-1], "source": "arXiv",
    }


def lookup_reference(identifier: str) -> dict:
    identifier = str(identifier or "").strip()
    if not identifier:
        raise ValueError("Enter a DOI or arXiv identifier")
    is_arxiv = "arxiv" in identifier.lower() or bool(re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", identifier))
    if is_arxiv:
        arxiv_id = re.sub(r"^.*?(?:arxiv:|/abs/|/pdf/)", "", identifier, flags=re.IGNORECASE).removesuffix(".pdf")
        url = "https://export.arxiv.org/api/query?" + urlencode({"id_list": arxiv_id, "max_results": 1})
        request = Request(url, headers={"User-Agent": "BIBLIOGRAPHY-workbench/1.0 (mailto:csoneira@ucm.es)"})
        with urlopen(request, timeout=20) as response:
            return parse_arxiv_feed(response.read())
    doi = normalize_doi(identifier)
    if not doi.startswith("10."):
        raise ValueError("This does not look like a DOI or arXiv identifier")
    request = Request(
        f"https://api.crossref.org/works/{quote(doi, safe='')}",
        headers={"Accept": "application/json", "User-Agent": "BIBLIOGRAPHY-workbench/1.0 (mailto:csoneira@ucm.es)"},
    )
    with urlopen(request, timeout=20) as response:
        return parse_crossref_message(json.loads(response.read().decode("utf-8"))["message"])


def decode_latex_text(value: str) -> str:
    accent_marks = {
        "'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308",
        "~": "\u0303", "=": "\u0304", ".": "\u0307", "u": "\u0306",
        "v": "\u030c", "H": "\u030b", "c": "\u0327", "k": "\u0328",
        "r": "\u030a", "b": "\u0331", "d": "\u0323",
    }
    special_letters = {
        "aa": "å", "AA": "Å", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ",
        "o": "ø", "O": "Ø", "l": "ł", "L": "Ł", "ss": "ß",
    }
    value = re.sub(r"\\([ij])\b", r"\1", value)

    def replace_accent(match):
        return unicodedata.normalize("NFC", match.group(2) + accent_marks[match.group(1)])

    value = re.sub(r"\\(['`^\"~=\.uvHckrbd])\s*\{?([A-Za-z])\}?", replace_accent, value)
    value = re.sub(
        r"\\(aa|AA|ae|AE|oe|OE|ss|[oOlL])\b",
        lambda match: special_letters[match.group(1)],
        value,
    )
    value = re.sub(r"\\([&%_#$])", r"\1", value)
    return value


def _clean_citation_value(value: str) -> str:
    value = str(value or "").strip()
    while len(value) >= 2 and ((value[0], value[-1]) in {("{", "}"), ('"', '"')}):
        value = value[1:-1].strip()
    value = value.replace("{", "").replace("}", "")
    value = decode_latex_text(value)
    return re.sub(r"\s+", " ", value).strip()


def parse_bibtex_records(text: str) -> list[dict]:
    records = []
    position = 0
    while True:
        match = re.search(r"@([A-Za-z]+)\s*\{", text[position:])
        if not match:
            break
        entry_type = match.group(1).lower()
        start = position + match.end()
        depth, quoted, escaped, end = 1, False, False, start
        while end < len(text) and depth:
            char = text[end]
            if char == '"' and not escaped:
                quoted = not quoted
            elif not quoted and char == "{":
                depth += 1
            elif not quoted and char == "}":
                depth -= 1
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
            end += 1
        body = text[start : end - 1]
        position = end
        comma = body.find(",")
        if comma < 0:
            continue
        fields, cursor = {}, comma + 1
        while cursor < len(body):
            field_match = re.search(r"([A-Za-z][\w-]*)\s*=\s*", body[cursor:])
            if not field_match:
                break
            name = field_match.group(1).lower()
            cursor += field_match.end()
            if cursor >= len(body):
                break
            if body[cursor] == "{":
                value_start, nested = cursor + 1, 1
                cursor += 1
                while cursor < len(body) and nested:
                    nested += (body[cursor] == "{") - (body[cursor] == "}")
                    cursor += 1
                value = body[value_start : cursor - 1]
            elif body[cursor] == '"':
                cursor += 1
                value_start = cursor
                while cursor < len(body) and body[cursor] != '"':
                    cursor += 2 if body[cursor] == "\\" else 1
                value = body[value_start:cursor]
                cursor += 1
            else:
                value_start = cursor
                while cursor < len(body) and body[cursor] not in ",\n":
                    cursor += 1
                value = body[value_start:cursor]
            fields[name] = _clean_citation_value(value)
        type_map = {
            "article": "article", "book": "book", "inbook": "book",
            "incollection": "book-chapter", "inproceedings": "proceedings",
            "conference": "proceedings", "phdthesis": "thesis",
            "mastersthesis": "thesis", "techreport": "report",
            "unpublished": "preprint",
        }
        date_match = re.search(r"\b((?:19|20)\d{2})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?", fields.get("date", ""))
        month_names = {name: index for index, name in enumerate(
            ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
        )}
        year_match = re.search(r"\b(19|20)\d{2}\b", fields.get("year", ""))
        month_value = fields.get("month", "").strip().lower()[:3]
        month_number = int(fields["month"]) if fields.get("month", "").isdigit() else month_names.get(month_value)
        publication_date = ""
        if date_match:
            publication_date = f"{date_match.group(1)}-{int(date_match.group(2)):02d}"
            if date_match.group(3):
                publication_date += f"-{int(date_match.group(3)):02d}"
        elif year_match and month_number and 1 <= month_number <= 12:
            publication_date = f"{year_match.group(0)}-{month_number:02d}"
        elif year_match:
            publication_date = year_match.group(0)
        records.append({
            "title": fields.get("title", ""),
            "author": re.sub(r"\s+and\s+", "; ", fields.get("author", ""), flags=re.I),
            "journal": fields.get("journal") or fields.get("booktitle") or fields.get("publisher", ""),
            "publication_date": publication_date,
            "doi": normalize_doi(fields.get("doi", "")),
            "type": type_map.get(entry_type, entry_type or "article"),
            "keywords": fields.get("keywords", ""),
            "abstract": fields.get("abstract", ""),
            "source": "BibTeX",
        })
    return records


def parse_ris_records(text: str) -> list[dict]:
    records, current = [], {}
    for raw_line in text.splitlines():
        match = re.match(r"^([A-Z0-9]{2})\s{0,2}-\s?(.*)$", raw_line.strip())
        if not match:
            continue
        tag, value = match.groups()
        if tag == "TY" and current:
            records.append(current)
            current = {}
        current.setdefault(tag, []).append(value.strip())
        if tag == "ER":
            records.append(current)
            current = {}
    if current:
        records.append(current)
    type_map = {
        "JOUR": "article", "JFULL": "article", "BOOK": "book", "CHAP": "book-chapter",
        "CONF": "proceedings", "CPAPER": "proceedings", "THES": "thesis",
        "RPRT": "report", "UNPB": "preprint", "ELEC": "web",
    }
    parsed = []
    for fields in records:
        first = lambda *tags: next((fields[tag][0] for tag in tags if fields.get(tag)), "")
        date_value = first("DA", "Y1", "PY")
        date_match = re.search(r"\b((?:19|20)\d{2})(?:[/.-](\d{1,2}))?(?:[/.-](\d{1,2}))?", date_value)
        publication_date = ""
        if date_match:
            publication_date = date_match.group(1)
            if date_match.group(2):
                publication_date += f"-{int(date_match.group(2)):02d}"
                if date_match.group(3):
                    publication_date += f"-{int(date_match.group(3)):02d}"
        parsed.append({
            "title": first("TI", "T1", "CT"),
            "author": "; ".join(fields.get("AU", []) + fields.get("A1", [])),
            "journal": first("JO", "JF", "T2", "PB"),
            "publication_date": publication_date,
            "doi": normalize_doi(first("DO")),
            "type": type_map.get(first("TY").upper(), first("TY").lower() or "article"),
            "keywords": "; ".join(fields.get("KW", [])),
            "abstract": first("AB", "N2"),
            "source": "RIS",
        })
    return [item for item in parsed if item["title"] or item["doi"]]


def parse_citation_records(text: str) -> list[dict]:
    text = str(text or "").strip()
    if not text:
        raise ValueError("Paste one or more RIS or BibTeX records")
    records = parse_bibtex_records(text) if re.search(r"@\w+\s*\{", text) else parse_ris_records(text)
    if not records:
        raise ValueError("No RIS or BibTeX records were recognized")
    return records


def inspect_pdf_file(path: Path, filename: str = "") -> dict:
    info = {}
    try:
        result = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=15)
        for line in result.stdout.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                info[key.strip().lower()] = value.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    text = ""
    try:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "2", str(path), "-"],
            capture_output=True, text=True, timeout=20,
        )
        text = result.stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    doi_match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, flags=re.I)
    title = _clean_citation_value(info.get("title", ""))
    if not title or title.lower() in {"untitled", Path(filename).stem.lower()}:
        title = next((
            re.sub(r"\s+", " ", line).strip()
            for line in text.splitlines()[:35]
            if 12 <= len(line.strip()) <= 240 and not re.match(r"^(doi|arxiv|http|www\.)", line.strip(), re.I)
        ), "")
    abstract = ""
    abstract_match = re.search(
        r"\babstract\b\s*[:.—-]?\s*(.{80,3000}?)(?=\n\s*(?:1\.?\s+)?(?:introduction|keywords?)\b)",
        text, flags=re.I | re.S,
    )
    if abstract_match:
        abstract = re.sub(r"\s+", " ", abstract_match.group(1)).strip()
    return {
        "title": title,
        "author": _clean_citation_value(info.get("author", "")),
        "doi": normalize_doi(doi_match.group(0).rstrip(".,;)") if doi_match else ""),
        "keywords": _clean_citation_value(info.get("keywords", "")),
        "abstract": abstract,
        "annotated": pdf_has_annotations(path),
        "source": "PDF scan",
    }


def audit_pdfs(update_missing: bool = False) -> dict:
    rows = load_metadata_rows()
    entries, groups = [], {}
    changed = False
    for row in rows:
        path = ROOT / "PDFs" / f"{row.get('code', '').strip()}.pdf"
        if not path.exists():
            continue
        actual = sha256_file(path)
        expected = (row.get("pdf_sha256") or "").strip()
        status = "ok" if expected == actual else ("unrecorded" if not expected else "mismatch")
        if update_missing and not expected:
            row["pdf_sha256"] = actual
            status, changed = "recorded", True
        entries.append({"code": row.get("code", ""), "status": status, "expected": expected, "actual": actual})
        groups.setdefault(actual, []).append(row.get("code", ""))
    if changed:
        write_metadata_rows(rows)
    return {
        "entries": entries, "duplicates": [codes for codes in groups.values() if len(codes) > 1],
        "summary": {"local": len(entries),
                    "ok": sum(item["status"] in {"ok", "recorded"} for item in entries),
                    "unrecorded": sum(item["status"] == "unrecorded" for item in entries),
                    "mismatch": sum(item["status"] == "mismatch" for item in entries)},
    }


def mark_entry_viewed(code: str) -> str:
    rows = load_metadata_rows()
    viewed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for row in rows:
        if (row.get("code") or "").strip() == code:
            row["last_viewed"] = viewed_at
            write_metadata_rows(rows)
            return viewed_at
    raise LookupError("Entry not found")


def manage_type(action: str, source: str, target: str = "") -> int:
    source = slugify(source, max_len=20)
    target = slugify(target, max_len=20) if target else ""
    rows = load_metadata_rows()
    affected = [row for row in rows if (row.get("type") or "").strip() == source]
    if action in {"rename", "merge"}:
        if not target:
            raise ValueError("A destination type is required")
        for row in affected:
            row["type"] = target
    elif action == "delete":
        if affected:
            raise ValueError("This type is still used; merge it into another type first")
    else:
        raise ValueError("Unknown type action")
    write_metadata_rows(rows)
    return len(affected)


def keyword_parts(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;,]", str(value or "")) if part.strip()]


def validate_keyword(value: str, field_name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{field_name} keyword is required")
    if len(value) > 80 or re.search(r"[;,\r\n]", value):
        raise ValueError("Keywords must be 80 characters or fewer and cannot contain separators")
    return value


def manage_my_keyword(action: str, source: str, target: str = "") -> int:
    source = validate_keyword(source, "A source")
    if action not in {"rename", "merge", "delete"}:
        raise ValueError("Unknown keyword action")
    target = validate_keyword(target, "A destination") if action in {"rename", "merge"} else ""
    source_key = source.casefold()
    target_key = target.casefold()
    rows = load_metadata_rows()
    updated = 0
    found = False

    for row in rows:
        parts = keyword_parts(row.get("my_keywords", ""))
        if not any(part.casefold() == source_key for part in parts):
            continue
        found = True
        replacement = []
        seen = set()
        for part in parts:
            if part.casefold() == source_key:
                if action == "delete":
                    continue
                part = target
            key = part.casefold()
            if key not in seen:
                seen.add(key)
                replacement.append(part)
        row["my_keywords"] = ", ".join(replacement)
        updated += 1

    config_path = ROOT / "CONFIGS" / "config.json"
    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("CONFIGS/config.json is not valid JSON") from exc
    entries = config.get("my_keywords", [])
    if not isinstance(entries, list):
        raise ValueError("The my_keywords configuration must be a list")

    source_entries = []
    target_entry = None
    for entry in entries:
        tag = entry if isinstance(entry, str) else entry.get("tag", "") if isinstance(entry, dict) else ""
        if str(tag).strip().casefold() == source_key:
            source_entries.append(entry)
            found = True
        elif action != "delete" and str(tag).strip().casefold() == target_key:
            target_entry = entry

    if not found:
        raise ValueError("Keyword not found")

    if source_entries:
        if action == "delete":
            entries = [entry for entry in entries if entry not in source_entries]
        elif target_entry is not None:
            target_terms = target_entry.setdefault("terms", []) if isinstance(target_entry, dict) else [target]
            merged_terms = list(target_terms)
            known_terms = {str(term).casefold() for term in merged_terms}
            for entry in source_entries:
                terms = entry.get("terms", []) if isinstance(entry, dict) else [entry]
                for term in terms:
                    if str(term).casefold() not in known_terms:
                        known_terms.add(str(term).casefold())
                        merged_terms.append(term)
            if isinstance(target_entry, dict):
                target_entry["terms"] = merged_terms
            entries = [entry for entry in entries if entry not in source_entries]
        else:
            primary = source_entries[0]
            if isinstance(primary, dict):
                primary["tag"] = target
            else:
                index = entries.index(primary)
                entries[index] = {"tag": target, "terms": [primary]}
            entries = [entry for entry in entries if entry is primary or entry not in source_entries]
        config["my_keywords"] = entries
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=config_path.parent, prefix=".config-", suffix=".tmp",
            delete=False, encoding="utf-8",
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
        os.replace(temp_path, config_path)

    write_metadata_rows(rows)
    return updated


def safe_saved_filter_name(name: str) -> str:
    name = str(name or "").strip()
    safe_name = "".join(ch for ch in name if ch.isalnum() or ch in ("-", "_", " ")).strip()
    if not safe_name:
        raise ValueError("A valid filter name is required")
    return safe_name


def detect_image_extension(header: bytes) -> str:
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    raise ValueError("Wallpaper must be a JPEG, PNG, or WebP image")


def safe_wallpaper_stem(filename: str) -> str:
    stem = Path(str(filename or "wallpaper")).stem
    return slugify(stem, max_len=80)


def list_custom_wallpapers() -> list:
    CUSTOM_WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(CUSTOM_WALLPAPER_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        items.append(
            {
                "id": f"custom/{path.name}",
                "name": path.stem.replace("_", " ").strip().title(),
                "url": f"wallpapers/custom/{quote(path.name)}",
            }
        )
    return items


def manage_saved_filter(action: str, filename: str, new_name: str = "") -> dict:
    filename = str(filename or "").strip()
    if not filename or Path(filename).name != filename or not filename.endswith(".json"):
        raise ValueError("Choose a valid saved filter")
    source = SAVED_LISTS_DIR / filename
    if not source.exists():
        raise LookupError("Saved filter not found")
    if action == "delete":
        source.unlink()
        return {"action": "delete", "filename": filename}
    if action != "rename":
        raise ValueError("Unknown saved-filter action")

    display_name = str(new_name or "").strip()
    destination = SAVED_LISTS_DIR / f"{safe_saved_filter_name(display_name)}.json"
    if destination != source and destination.exists():
        raise FileExistsError("A saved filter with that name already exists")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("The saved filter file is invalid") from exc
    data["name"] = display_name
    with tempfile.NamedTemporaryFile(
        "w", dir=SAVED_LISTS_DIR, prefix=".filter-", suffix=".tmp",
        delete=False, encoding="utf-8",
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(temp_path, destination)
    if destination != source:
        source.unlink()
    return {"action": "rename", "filename": destination.name, "name": display_name}


def library_git_status() -> dict:
    scope = [
        "METADATA/metadata.csv", "METADATA/abstracts.csv",
        "SAVED_LISTS", "CONFIGS/config.json",
    ]
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--", *scope],
        cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
    )
    changes = [line for line in result.stdout.splitlines() if line.strip()]
    sync = subprocess.run(
        ["git", "rev-list", "--left-right", "--count", "origin/main...HEAD"],
        cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
    )
    behind = ahead = None
    match = re.fullmatch(r"(\d+)\s+(\d+)", sync.stdout.strip())
    if match:
        behind, ahead = map(int, match.groups())
    return {
        "library": describe_library(ROOT),
        "clean": not changes,
        "changes": changes,
        "ahead": ahead,
        "behind": behind,
        "commands": [
            "scripts/verify.sh",
            "git add METADATA/metadata.csv METADATA/abstracts.csv SAVED_LISTS CONFIGS/config.json",
            'git commit -m "Update bibliography data"',
            "git push origin main",
        ],
    }


def validate_library() -> dict:
    checks = []
    for label, command in (
        ("Integrity", ["python3", str(APPLICATION_ROOT / "CODE" / "bib.py"), "verify"]),
        ("Metadata", ["python3", str(APPLICATION_ROOT / "CODE" / "bib.py"), "validate"]),
    ):
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, timeout=60, check=False,
        )
        checks.append({
            "label": label, "ok": result.returncode == 0,
            "output": (result.stdout + result.stderr).strip(),
        })
    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def create_library_checkpoint() -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    CHECKPOINT_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = CHECKPOINT_BACKUP_DIR / stamp
    suffix = 2
    while destination.exists():
        destination = CHECKPOINT_BACKUP_DIR / f"{stamp}-{suffix}"
        suffix += 1
    destination.mkdir()
    copied = []
    for source in (METADATA_FILE, ABSTRACTS_FILE, ROOT / "CONFIGS" / "config.json"):
        if source.exists():
            relative = source.relative_to(ROOT)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(str(relative))
    if SAVED_LISTS_DIR.exists():
        shutil.copytree(SAVED_LISTS_DIR, destination / "SAVED_LISTS")
        copied.extend(str(path.relative_to(ROOT)) for path in SAVED_LISTS_DIR.glob("*.json"))
    (destination / "manifest.json").write_text(
        json.dumps({"created_at": stamp, "files": copied}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"path": str(destination.relative_to(ROOT)), "files": len(copied)}


def load_abstracts_map() -> dict:
    if not ABSTRACTS_FILE.exists():
        _ABSTRACT_CACHE["mtime_ns"] = None
        _ABSTRACT_CACHE["data"] = {}
        return {}

    mtime_ns = ABSTRACTS_FILE.stat().st_mtime_ns
    if _ABSTRACT_CACHE["mtime_ns"] == mtime_ns:
        return dict(_ABSTRACT_CACHE["data"])

    data = {}
    with ABSTRACTS_FILE.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            code = (row.get("code") or "").strip()
            if not code:
                continue
            data[code] = row.get("abstract", "")

    _ABSTRACT_CACHE["mtime_ns"] = mtime_ns
    _ABSTRACT_CACHE["data"] = data
    return dict(data)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Let the standard handler normalize request paths and reject traversal.
        super().__init__(*args, directory=str(APPLICATION_ROOT), **kwargs)

    def translate_path(self, path):
        """Serve library data under the legacy URLs while UI assets stay in the app."""
        app_path = Path(super().translate_path(path))
        try:
            relative = app_path.relative_to(APPLICATION_ROOT)
        except ValueError:
            return str(app_path)
        if relative.parts and relative.parts[0] in {
            "CONFIGS", "METADATA", "PDFs", "SAVED_LISTS",
        }:
            return str(ROOT / relative)
        return str(app_path)

    def _disable_cache_for_request(self) -> bool:
        parsed = urlparse(self.path)
        path = parsed.path
        return (
            path.startswith("/VIEWER/")
            or path == "/METADATA/metadata.csv"
            or path == "/METADATA/abstracts.csv"
            or path in {
                "/saved-lists",
                "/saved-filters",
                "/abstracts",
                "/abstract",
                "/pdf-status",
                "/pdf-audit",
                "/change-history",
                "/library-status",
                "/library-info",
                "/validate-library",
                "/checkpoint-library",
                "/wallpapers",
                "/save-list",
                "/save-filter",
                "/manage-saved-filter",
                "/upload-wallpaper",
                "/save-notes",
                "/create-entry",
                "/update-entry",
                "/delete-entry",
                "/attach-pdf",
                "/set-pdf-hosts",
                "/mark-viewed",
                "/manage-type",
                "/manage-my-keyword",
                "/merge-entries",
                "/lookup-reference",
                "/parse-citations",
                "/inspect-pdf",
                "/undo-last-change",
                "/toggle-star",
                "/toggle-unread",
                "/toggle-annotated",
                "/open-pdf",
            }
        )

    def _is_pdf_request(self) -> bool:
        path = urlparse(self.path).path
        return path.startswith("/PDFs/") and path.lower().endswith(".pdf")

    def end_headers(self):
        if self._is_pdf_request():
            # Hint browsers to render PDFs inline instead of downloading by default.
            self.send_header("Content-Disposition", "inline")
        if self._disable_cache_for_request():
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in {"/saved-lists", "/saved-filters"}:
            self._handle_saved_lists()
            return
        if parsed.path == "/abstracts":
            self._handle_abstracts()
            return
        if parsed.path == "/abstract":
            self._handle_abstract(parsed.query)
            return
        if parsed.path == "/pdf-status":
            self._handle_pdf_status()
            return
        if parsed.path == "/pdf-audit":
            self._handle_pdf_audit()
            return
        if parsed.path == "/change-history":
            self._send_json({"history": change_history()})
            return
        if parsed.path == "/library-status":
            try:
                self._send_json(library_git_status())
            except (OSError, subprocess.SubprocessError) as exc:
                self.send_error(500, str(exc))
            return
        if parsed.path == "/library-info":
            self._send_json(describe_library(ROOT))
            return
        if parsed.path == "/wallpapers":
            self._send_json({"custom": list_custom_wallpapers()})
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        library = describe_library(ROOT)
        if not library["valid"]:
            self.send_error(409, library["error"] or "Library is not initialized")
            return

        if path not in {"/save-list", "/save-filter"}:
            if path == "/create-entry":
                self._handle_create_entry()
                return
            if path == "/update-entry":
                self._handle_update_entry()
                return
            if path == "/delete-entry":
                self._handle_delete_entry()
                return
            if path == "/attach-pdf":
                self._handle_attach_pdf(parsed.query)
                return
            if path == "/set-pdf-hosts":
                self._handle_set_pdf_hosts()
                return
            if path == "/mark-viewed":
                self._handle_mark_viewed()
                return
            if path == "/manage-type":
                self._handle_manage_type()
                return
            if path == "/manage-my-keyword":
                self._handle_manage_my_keyword()
                return
            if path == "/manage-saved-filter":
                self._handle_manage_saved_filter()
                return
            if path == "/upload-wallpaper":
                self._handle_upload_wallpaper(parsed.query)
                return
            if path == "/merge-entries":
                self._handle_merge_entries()
                return
            if path == "/lookup-reference":
                self._handle_lookup_reference()
                return
            if path == "/parse-citations":
                self._handle_parse_citations()
                return
            if path == "/inspect-pdf":
                self._handle_inspect_pdf(parsed.query)
                return
            if path == "/undo-last-change":
                self._handle_undo_last_change()
                return
            if path == "/toggle-star":
                self._handle_toggle_star()
                return
            if path == "/toggle-unread":
                self._handle_toggle_unread()
                return
            if path == "/toggle-annotated":
                self._handle_toggle_annotated()
                return
            if path == "/validate-library":
                try:
                    self._send_json(validate_library())
                except (OSError, subprocess.SubprocessError) as exc:
                    self.send_error(500, str(exc))
                return
            if path == "/checkpoint-library":
                try:
                    with _WRITE_LOCK:
                        result = create_library_checkpoint()
                    self._send_json(result)
                except OSError as exc:
                    self.send_error(500, str(exc))
                return
            if path == "/save-notes":
                self._handle_save_notes()
                return
            if path == "/open-pdf":
                self._handle_open_pdf()
                return
            self.send_error(404, "Not Found")
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        name = payload.get("name", "").strip()
        codes = payload.get("codes", [])
        filters = payload.get("filters", {})
        dynamic = bool(payload.get("dynamic"))

        if not name:
            self.send_error(400, "Missing name")
            return

        try:
            safe_name = safe_saved_filter_name(name)
        except ValueError:
            self.send_error(400, "Invalid name")
            return

        with _WRITE_LOCK:
            create_change_snapshot("save filter")
            SAVED_LISTS_DIR.mkdir(parents=True, exist_ok=True)
            path = SAVED_LISTS_DIR / f"{safe_name}.json"

            data = {
                "name": name,
                "filters": filters,
                "codes": codes,
                "dynamic": dynamic,
            }
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"path": str(path)}).encode("utf-8"))

    def _handle_create_entry(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > 1_000_000:
            self.send_error(413, "Entry is too large")
            return
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Entry must be a JSON object")
            with _WRITE_LOCK:
                snapshot = create_change_snapshot("create entry")
                row = create_metadata_entry(payload)
                if "abstract" in payload:
                    set_abstract(row["code"], payload.get("abstract", ""))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        except DuplicateEntryError as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self._send_json({"error": str(exc), "duplicates": exc.matches}, status=409)
            return
        except ValueError as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self.send_error(400, str(exc))
            return
        self._send_json(row)

    def _read_json_payload(self, max_length: int = 1_000_000) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > max_length:
            raise OverflowError("Request is too large")
        payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Request must be a JSON object")
        return payload

    def _handle_update_entry(self):
        try:
            payload = self._read_json_payload()
            with _WRITE_LOCK:
                snapshot = create_change_snapshot("update entry")
                row = update_metadata_entry(payload, snapshot=snapshot)
                if "abstract" in payload:
                    set_abstract(row["code"], payload.get("abstract", ""))
        except DuplicateEntryError as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self._send_json({"error": str(exc), "duplicates": exc.matches}, status=409)
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_error(400, str(exc))
            return
        except LookupError as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self.send_error(404, str(exc))
            return
        self._send_json(row)

    def _handle_delete_entry(self):
        try:
            payload = self._read_json_payload()
            code = str(payload.get("code") or "").strip()
            if not code:
                raise ValueError("Code is required")
            with _WRITE_LOCK:
                rows = load_metadata_rows()
                if not any((row.get("code") or "").strip() == code for row in rows):
                    raise LookupError("Entry not found")
                snapshot = create_change_snapshot("delete entry")
                pdf_path = ROOT / "PDFs" / f"{code}.pdf"
                moved_pdf = None
                if pdf_path.exists():
                    trash_dir = ROOT / "PDFs" / ".trash"
                    trash_dir.mkdir(parents=True, exist_ok=True)
                    trash_path = trash_dir / f"{snapshot.name}-{pdf_path.name}"
                    pdf_path.replace(trash_path)
                    moved_pdf = {
                        "from": str(pdf_path.relative_to(ROOT)),
                        "to": str(trash_path.relative_to(ROOT)),
                    }
                    update_snapshot_manifest(snapshot, moved_pdf=moved_pdf)
                write_metadata_rows(
                    [row for row in rows if (row.get("code") or "").strip() != code]
                )
                self._remove_code_from_sidecars(code)
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_error(400, str(exc))
            return
        except LookupError as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self.send_error(404, str(exc))
            return
        self._send_json({"code": code, "pdf_moved_to_trash": bool(moved_pdf)})

    def _remove_code_from_sidecars(self, code: str):
        if ABSTRACTS_FILE.exists():
            with ABSTRACTS_FILE.open(newline="", encoding="utf-8") as handle:
                rows = [
                    row
                    for row in csv.DictReader(handle)
                    if (row.get("code") or "").strip() != code
                ]
            with ABSTRACTS_FILE.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["code", "abstract"], lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
        for path in SAVED_LISTS_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            data["codes"] = [item for item in data.get("codes", []) if item != code]
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _handle_attach_pdf(self, query: str):
        params = parse_qs(query)
        code = (params.get("code", [""])[0] or "").strip()
        replace_existing = (params.get("replace", [""])[0] or "") == "1"
        content_length = int(self.headers.get("Content-Length", "0"))
        if not code:
            self.send_error(400, "Code is required")
            return
        if content_length <= 0 or content_length > 250 * 1024 * 1024:
            self.send_error(413, "PDF must be between 1 byte and 250 MB")
            return
        with _WRITE_LOCK:
            rows = load_metadata_rows()
            row = next((row for row in rows if (row.get("code") or "").strip() == code), None)
            if row is None:
                self.send_error(404, "Entry not found")
                return
            target = ROOT / "PDFs" / f"{code}.pdf"
            target_existed = target.exists()
            if target_existed and not replace_existing:
                self.send_error(409, "A local PDF already exists")
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            snapshot = create_change_snapshot("replace PDF" if target_existed else "attach PDF")
            if target_existed:
                shutil.copy2(target, snapshot / "previous.pdf")
            with tempfile.NamedTemporaryFile(
                "wb", dir=target.parent, prefix=".upload-", suffix=".pdf", delete=False
            ) as handle:
                temp_path = Path(handle.name)
                remaining = content_length
                first = True
                valid_pdf = False
                digest = hashlib.sha256()
                while remaining:
                    chunk = self.rfile.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    if first:
                        valid_pdf = chunk.lstrip().startswith(b"%PDF-")
                        first = False
                    handle.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            if remaining or not valid_pdf:
                temp_path.unlink(missing_ok=True)
                discard_snapshot(snapshot)
                self.send_error(400, "The uploaded file is not a valid PDF")
                return
            temp_path.replace(target)
            detected_annotations = pdf_has_annotations(target)
            stat = target.stat()
            _ANNOTATION_SCAN_CACHE[code] = (stat.st_mtime_ns, stat.st_size)
            hosts = [host.strip() for host in (row.get("pdf_hosts") or "").split(";")]
            update_entry_hosts(code, hosts + [socket.gethostname()])
            rows = load_metadata_rows()
            for candidate in rows:
                if candidate.get("code", "").strip() == code:
                    candidate["pdf_sha256"] = digest.hexdigest()
                    if detected_annotations:
                        candidate["annotated"] = "1"
            write_metadata_rows(rows)
            if target_existed:
                update_snapshot_manifest(
                    snapshot,
                    replaced_pdf={"path": str(target.relative_to(ROOT)), "backup": "previous.pdf"},
                )
            else:
                update_snapshot_manifest(snapshot, created_pdf=str(target.relative_to(ROOT)))
        self._send_json({
            "code": code, "hostname": socket.gethostname(), "sha256": digest.hexdigest(),
            "annotated": detected_annotations, "replaced": target_existed,
        })

    def _handle_set_pdf_hosts(self):
        try:
            payload = self._read_json_payload()
            code = str(payload.get("code") or "").strip()
            hosts = payload.get("hosts", [])
            if not code or not isinstance(hosts, list):
                raise ValueError("Code and a host list are required")
            with _WRITE_LOCK:
                snapshot = create_change_snapshot("update PDF locations")
                row = update_entry_hosts(code, hosts)
        except (json.JSONDecodeError, ValueError) as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self.send_error(400, str(exc))
            return
        except LookupError as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self.send_error(404, str(exc))
            return
        self._send_json(row)

    def _handle_mark_viewed(self):
        try:
            payload = self._read_json_payload()
            code = str(payload.get("code") or "").strip()
            if not code:
                raise ValueError("Code is required")
            with _WRITE_LOCK:
                viewed_at = mark_entry_viewed(code)
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_error(400, str(exc))
            return
        except LookupError as exc:
            self.send_error(404, str(exc))
            return
        self._send_json({"code": code, "last_viewed": viewed_at})

    def _handle_manage_type(self):
        try:
            payload = self._read_json_payload()
            with _WRITE_LOCK:
                snapshot = create_change_snapshot("manage types")
                count = manage_type(
                    str(payload.get("action") or ""),
                    str(payload.get("source") or ""),
                    str(payload.get("target") or ""),
                )
        except (json.JSONDecodeError, ValueError) as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self.send_error(400, str(exc))
            return
        self._send_json({"updated": count})

    def _handle_manage_my_keyword(self):
        try:
            payload = self._read_json_payload()
            with _WRITE_LOCK:
                snapshot = create_change_snapshot("manage my keywords")
                count = manage_my_keyword(
                    str(payload.get("action") or ""),
                    str(payload.get("source") or ""),
                    str(payload.get("target") or ""),
                )
        except (json.JSONDecodeError, ValueError) as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self.send_error(400, str(exc))
            return
        self._send_json({"updated": count})

    def _handle_manage_saved_filter(self):
        try:
            payload = self._read_json_payload()
            with _WRITE_LOCK:
                snapshot = create_change_snapshot("manage saved filter")
                result = manage_saved_filter(
                    str(payload.get("action") or ""),
                    str(payload.get("filename") or ""),
                    str(payload.get("new_name") or ""),
                )
        except (json.JSONDecodeError, ValueError) as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self.send_error(400, str(exc))
            return
        except FileExistsError as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self.send_error(409, str(exc))
            return
        except LookupError as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self.send_error(404, str(exc))
            return
        self._send_json(result)

    def _handle_upload_wallpaper(self, query: str):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > 25 * 1024 * 1024:
            self.send_error(413, "Wallpaper must be between 1 byte and 25 MB")
            return
        filename = (parse_qs(query).get("name", ["wallpaper"])[0] or "wallpaper").strip()
        raw = self.rfile.read(content_length)
        if len(raw) != content_length:
            self.send_error(400, "Wallpaper upload was incomplete")
            return
        try:
            extension = detect_image_extension(raw[:16])
            stem = safe_wallpaper_stem(filename)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        with _WRITE_LOCK:
            CUSTOM_WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)
            target = CUSTOM_WALLPAPER_DIR / f"{stem}{extension}"
            suffix = 2
            while target.exists():
                target = CUSTOM_WALLPAPER_DIR / f"{stem}_{suffix}{extension}"
                suffix += 1
            with tempfile.NamedTemporaryFile(
                "wb", dir=CUSTOM_WALLPAPER_DIR, prefix=".wallpaper-", suffix=".tmp", delete=False
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(raw)
            os.replace(temp_path, target)
        item = {
            "id": f"custom/{target.name}",
            "name": target.stem.replace("_", " ").strip().title(),
            "url": f"wallpapers/custom/{quote(target.name)}",
        }
        self._send_json(item)

    def _handle_merge_entries(self):
        try:
            payload = self._read_json_payload()
            with _WRITE_LOCK:
                snapshot = create_change_snapshot("merge duplicate entries")
                result = merge_metadata_entries(
                    payload.get("source", ""), payload.get("target", ""), snapshot
                )
        except (json.JSONDecodeError, ValueError) as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self.send_error(400, str(exc))
            return
        except LookupError as exc:
            if "snapshot" in locals():
                discard_snapshot(snapshot)
            self.send_error(404, str(exc))
            return
        self._send_json(result)

    def _handle_lookup_reference(self):
        try:
            payload = self._read_json_payload()
            result = lookup_reference(payload.get("identifier", ""))
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_error(400, str(exc))
            return
        except LookupError as exc:
            self.send_error(404, str(exc))
            return
        except HTTPError as exc:
            self.send_error(
                404 if exc.code == 404 else 502,
                "Reference service did not return this item",
            )
            return
        except (URLError, TimeoutError, ET.ParseError, KeyError):
            self.send_error(502, "Reference service is temporarily unavailable")
            return
        self._send_json(result)

    def _handle_parse_citations(self):
        try:
            payload = self._read_json_payload(max_length=5_000_000)
            records = parse_citation_records(payload.get("text", ""))
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_error(400, str(exc))
            return
        self._send_json({"entries": records})

    def _handle_inspect_pdf(self, query: str):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > 250 * 1024 * 1024:
            self.send_error(413, "PDF must be between 1 byte and 250 MB")
            return
        filename = (parse_qs(query).get("name", [""])[0] or "").strip()
        with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as handle:
            temp_path = Path(handle.name)
            remaining, first, valid_pdf = content_length, True, False
            while remaining:
                chunk = self.rfile.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                if first:
                    valid_pdf = chunk.lstrip().startswith(b"%PDF-")
                    first = False
                handle.write(chunk)
                remaining -= len(chunk)
        try:
            if remaining or not valid_pdf:
                self.send_error(400, "The uploaded file is not a valid PDF")
                return
            self._send_json(inspect_pdf_file(temp_path, filename))
        finally:
            temp_path.unlink(missing_ok=True)

    def _handle_undo_last_change(self):
        try:
            with _WRITE_LOCK:
                result = undo_last_change()
        except ValueError as exc:
            self.send_error(409, str(exc))
            return
        self._send_json(result)

    def _handle_saved_lists(self):
        SAVED_LISTS_DIR.mkdir(parents=True, exist_ok=True)
        items = []
        for path in sorted(SAVED_LISTS_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            items.append(
                {
                    "filename": path.name,
                    "name": data.get("name", path.stem),
                    "codes": data.get("codes", []),
                    "filters": data.get("filters", {}),
                    "dynamic": bool(data.get("dynamic")),
                }
            )

        self._send_json(items)

    def _handle_abstracts(self):
        data = load_abstracts_map()
        self._send_json({"abstracts": data})

    def _handle_abstract(self, query: str):
        params = parse_qs(query)
        code = (params.get("code", [""])[0] or "").strip()
        if not code:
            self.send_error(400, "Missing code")
            return

        abstracts = load_abstracts_map()
        self._send_json({"code": code, "abstract": abstracts.get(code, "")})

    def _handle_pdf_status(self):
        with _WRITE_LOCK:
            annotation_scan = reconcile_local_pdf_annotations()
        pdf_dir = ROOT / "PDFs"
        local_codes = sorted(path.stem for path in pdf_dir.glob("*.pdf"))
        self._send_json({
            "hostname": socket.gethostname(), "local_codes": local_codes,
            "annotation_scan": annotation_scan,
        })

    def _handle_pdf_audit(self):
        with _WRITE_LOCK:
            annotation_scan = reconcile_local_pdf_annotations()
            audit = audit_pdfs(update_missing=False)
        audit["annotation_scan"] = annotation_scan
        self._send_json(audit)

    def _handle_toggle_star(self):
        self._handle_toggle_flag("star")

    def _handle_toggle_unread(self):
        self._handle_toggle_flag("unread")

    def _handle_toggle_annotated(self):
        self._handle_toggle_flag("annotated")

    def _handle_save_notes(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        code = (payload.get("code") or "").strip()
        notes = payload.get("notes", "")
        if notes is None:
            notes = ""
        notes = str(notes)
        if not code:
            self.send_error(400, "Missing code")
            return

        if not METADATA_FILE.exists():
            self.send_error(500, "metadata.csv not found")
            return

        with _WRITE_LOCK:
            rows = load_metadata_rows()
            found = False
            for row in rows:
                if (row.get("code") or "").strip() == code:
                    row["notes"] = notes
                    found = True
            if not found:
                self.send_error(404, "Code not found")
                return
            create_change_snapshot("save notes")
            write_metadata_rows(rows)

        self._send_json({"code": code, "notes": notes})

    def _handle_open_pdf(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        code = (payload.get("code") or "").strip()
        if not code:
            self.send_error(400, "Missing code")
            return

        pdf_root = (ROOT / "PDFs").resolve()
        pdf_path = (pdf_root / f"{code}.pdf").resolve()
        if pdf_root not in pdf_path.parents:
            self.send_error(400, "Invalid code")
            return
        if not pdf_path.exists():
            self.send_error(404, "PDF not found")
            return

        try:
            opener = "evince" if shutil.which("evince") else "xdg-open"
            subprocess.Popen(
                [opener, str(pdf_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            self.send_error(500, "Failed to launch PDF viewer")
            return

        self._send_json({"code": code, "path": str(pdf_path)})

    def _handle_toggle_flag(self, field_name):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        code = (payload.get("code") or "").strip()
        file_path = (payload.get("file") or "").strip()
        if not code and file_path:
            code = Path(file_path).stem
        value = payload.get(field_name, "")
        if not code:
            self.send_error(400, "Missing code")
            return

        if not METADATA_FILE.exists():
            self.send_error(500, "metadata.csv not found")
            return

        with _WRITE_LOCK:
            rows = load_metadata_rows()
            found = False
            for row in rows:
                if (row.get("code") or "").strip() == code:
                    row[field_name] = "1" if value == "1" else ""
                    found = True
            if not found:
                self.send_error(404, "Code not found")
                return
            create_change_snapshot(f"toggle {field_name}")
            write_metadata_rows(rows)

        self._send_json({"code": code, field_name: value})

    def _send_json(self, payload, status=200):
        if status < 400:
            prune_change_history()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


if __name__ == "__main__":
    os.chdir(APPLICATION_ROOT)
    migrate_metadata_schema()
    # This server exposes endpoints that modify local metadata and open PDFs.
    # Keep it available only to this computer; it is not an authenticated web app.
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    annotation_stop = threading.Event()
    threading.Thread(
        target=annotation_scan_worker, args=(annotation_stop,), daemon=True,
        name="pdf-annotation-scan",
    ).start()
    print("Serving on http://localhost:8000/VIEWER/viewer.html")
    try:
        server.serve_forever()
    finally:
        annotation_stop.set()
