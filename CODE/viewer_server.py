#!/usr/bin/env python3
import csv
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
from datetime import date, datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
SAVED_LISTS_DIR = ROOT / "SAVED_LISTS"
ABSTRACTS_FILE = ROOT / "METADATA" / "abstracts.csv"
METADATA_FILE = ROOT / "METADATA" / "metadata.csv"
CHANGE_BACKUP_DIR = ROOT / "METADATA" / "backups" / "viewer_changes"
_ABSTRACT_CACHE = {"mtime_ns": None, "data": {}}
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
    "added_at",
    "pdf_hosts",
    "last_viewed",
    "notes",
]


class DuplicateEntryError(ValueError):
    def __init__(self, matches: list):
        super().__init__("A matching entry already exists")
        self.matches = matches


def load_metadata_rows() -> list:
    if not METADATA_FILE.exists():
        return []
    with METADATA_FILE.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_metadata_rows(rows: list) -> None:
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
        snapshot.rename(snapshot.with_name(f"{snapshot.name}.restored"))


def list_change_snapshots() -> list:
    if not CHANGE_BACKUP_DIR.exists():
        return []
    return sorted(
        path
        for path in CHANGE_BACKUP_DIR.glob("change-*")
        if path.is_dir() and not path.name.endswith(".restored")
    )


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
    moved_pdf = manifest.get("moved_pdf") or {}
    moved_from = ROOT / moved_pdf.get("from", "") if moved_pdf else None
    moved_to = ROOT / moved_pdf.get("to", "") if moved_pdf else None
    if moved_from and moved_to and moved_to.exists() and not moved_from.exists():
        moved_to.replace(moved_from)

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
    value = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    value = re.sub(r"_+", "_", value).strip("_")
    return (value or "untitled")[:max_len].rstrip("_")


def create_metadata_entry(payload: dict) -> dict:
    title = str(payload.get("title") or "").strip()
    publication_date = str(payload.get("publication_date") or "").strip()
    doc_type = slugify(str(payload.get("type") or "article"), max_len=20)

    if not title:
        raise ValueError("Title is required")
    publication_pattern = r"\d{4}-(0[1-9]|1[0-2])(?:-(0[1-9]|[12]\d|3[01]))?"
    if publication_date and not re.fullmatch(publication_pattern, publication_date):
        raise ValueError("Publication date must use YYYY-MM or YYYY-MM-DD")
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
            "journal": str(payload.get("journal") or "").strip(),
            "year": year,
            "publication_date": publication_date,
            "doi": doi,
            "author": str(payload.get("author") or "").strip(),
            "keywords": str(payload.get("keywords") or "").strip(),
            "my_keywords": str(payload.get("my_keywords") or "").strip(),
            "star": "1" if payload.get("star") in (True, "1", 1) else "",
            "unread": "1" if payload.get("unread") in (True, "1", 1) else "",
            "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            # Metadata-only entries deliberately have no recorded PDF host.
            "pdf_hosts": "",
            "last_viewed": "",
            "notes": str(payload.get("notes") or "").strip(),
        }
    )
    rows.append(row)

    write_metadata_rows(rows)
    return row


def validate_publication_date(value: str) -> str:
    value = str(value or "").strip()
    pattern = r"\d{4}-(0[1-9]|1[0-2])(?:-(0[1-9]|[12]\d|3[01]))?"
    if value and not re.fullmatch(pattern, value):
        raise ValueError("Publication date must use YYYY-MM or YYYY-MM-DD")
    if value and len(value) == 10:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Publication date is not a valid calendar date") from exc
    return value


def update_metadata_entry(payload: dict) -> dict:
    code = str(payload.get("code") or "").strip()
    title = str(payload.get("title") or "").strip()
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

    updated = None
    for row in rows:
        if (row.get("code") or "").strip() != code:
            continue
        row.update(
            {
                "type": doc_type,
                "title": title,
                "journal": str(payload.get("journal") or "").strip(),
                "year": publication_date[:4] if publication_date else str(payload.get("year") or "").strip(),
                "publication_date": publication_date,
                "doi": str(payload.get("doi") or "").strip(),
                "author": str(payload.get("author") or "").strip(),
                "keywords": str(payload.get("keywords") or "").strip(),
                "my_keywords": str(payload.get("my_keywords") or "").strip(),
                "star": "1" if payload.get("star") in (True, "1", 1) else "",
                "unread": "1" if payload.get("unread") in (True, "1", 1) else "",
                "notes": str(payload.get("notes") or "").strip(),
            }
        )
        if "pdf_hosts" in payload:
            row["pdf_hosts"] = "; ".join(normalize_hosts(payload.get("pdf_hosts", "")))
        updated = dict(row)
        break
    if updated is None:
        raise LookupError("Entry not found")
    write_metadata_rows(rows)
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
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _disable_cache_for_request(self) -> bool:
        parsed = urlparse(self.path)
        path = parsed.path
        return (
            path.startswith("/VIEWER/")
            or path == "/METADATA/metadata.csv"
            or path == "/METADATA/abstracts.csv"
            or path in {
                "/saved-lists",
                "/abstracts",
                "/abstract",
                "/pdf-status",
                "/save-list",
                "/save-notes",
                "/create-entry",
                "/update-entry",
                "/delete-entry",
                "/attach-pdf",
                "/set-pdf-hosts",
                "/mark-viewed",
                "/manage-type",
                "/undo-last-change",
                "/toggle-star",
                "/toggle-unread",
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
        if parsed.path == "/saved-lists":
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
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path != "/save-list":
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
            if path == "/undo-last-change":
                self._handle_undo_last_change()
                return
            if path == "/toggle-star":
                self._handle_toggle_star()
                return
            if path == "/toggle-unread":
                self._handle_toggle_unread()
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

        if not name:
            self.send_error(400, "Missing name")
            return

        safe_name = "".join(ch for ch in name if ch.isalnum() or ch in ("-", "_", " ")).strip()
        if not safe_name:
            self.send_error(400, "Invalid name")
            return

        with _WRITE_LOCK:
            create_change_snapshot("save list")
            SAVED_LISTS_DIR.mkdir(parents=True, exist_ok=True)
            path = SAVED_LISTS_DIR / f"{safe_name}.json"

            data = {
                "name": name,
                "filters": filters,
                "codes": codes,
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
                row = update_metadata_entry(payload)
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
        code = (parse_qs(query).get("code", [""])[0] or "").strip()
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
            if target.exists():
                self.send_error(409, "A local PDF already exists")
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            snapshot = create_change_snapshot("attach PDF")
            with tempfile.NamedTemporaryFile(
                "wb", dir=target.parent, prefix=".upload-", suffix=".pdf", delete=False
            ) as handle:
                temp_path = Path(handle.name)
                remaining = content_length
                first = True
                valid_pdf = False
                while remaining:
                    chunk = self.rfile.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    if first:
                        valid_pdf = chunk.lstrip().startswith(b"%PDF-")
                        first = False
                    handle.write(chunk)
                    remaining -= len(chunk)
            if remaining or not valid_pdf:
                temp_path.unlink(missing_ok=True)
                discard_snapshot(snapshot)
                self.send_error(400, "The uploaded file is not a valid PDF")
                return
            temp_path.replace(target)
            hosts = [host.strip() for host in (row.get("pdf_hosts") or "").split(";")]
            update_entry_hosts(code, hosts + [socket.gethostname()])
            update_snapshot_manifest(snapshot, created_pdf=str(target.relative_to(ROOT)))
        self._send_json({"code": code, "hostname": socket.gethostname()})

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
        pdf_dir = ROOT / "PDFs"
        local_codes = sorted(path.stem for path in pdf_dir.glob("*.pdf"))
        self._send_json({"hostname": socket.gethostname(), "local_codes": local_codes})

    def _handle_toggle_star(self):
        self._handle_toggle_flag("star")

    def _handle_toggle_unread(self):
        self._handle_toggle_flag("unread")

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
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


if __name__ == "__main__":
    os.chdir(ROOT)
    # This server exposes endpoints that modify local metadata and open PDFs.
    # Keep it available only to this computer; it is not an authenticated web app.
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Serving on http://localhost:8000/VIEWER/viewer.html")
    server.serve_forever()
