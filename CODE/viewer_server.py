#!/usr/bin/env python3
import csv
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
SAVED_LISTS_DIR = ROOT / "SAVED_LISTS"
ABSTRACTS_FILE = ROOT / "METADATA" / "abstracts.csv"
_ABSTRACT_CACHE = {"mtime_ns": None, "data": {}}


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
    def translate_path(self, path):
        # Serve files from repo root.
        rel = path.lstrip("/")
        return str(ROOT / rel)

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
        super().do_GET()

    def do_POST(self):
        if self.path != "/save-list":
            if self.path == "/toggle-star":
                self._handle_toggle_star()
                return
            if self.path == "/toggle-unread":
                self._handle_toggle_unread()
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

    def _handle_toggle_star(self):
        self._handle_toggle_flag("star")

    def _handle_toggle_unread(self):
        self._handle_toggle_flag("unread")

    def _handle_toggle_flag(self, field_name):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        file_path = payload.get("file", "").strip()
        value = payload.get(field_name, "")
        if not file_path:
            self.send_error(400, "Missing file")
            return

        metadata_path = ROOT / "METADATA" / "metadata.csv"
        if not metadata_path.exists():
            self.send_error(500, "metadata.csv not found")
            return

        rows = []
        with metadata_path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            for row in reader:
                if row.get("file") == file_path:
                    row[field_name] = "1" if value == "1" else ""
                rows.append(row)

        if field_name not in fieldnames:
            fieldnames.append(field_name)

        with metadata_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        self._send_json({"file": file_path, field_name: value})

    def _send_json(self, payload):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


if __name__ == "__main__":
    os.chdir(ROOT)
    server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    print("Serving on http://localhost:8000/VIEWER/viewer.html")
    server.serve_forever()
