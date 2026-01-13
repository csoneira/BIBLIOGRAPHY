#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

top = Path(__file__).resolve().parent.parent
PDF_DIR = top / "PDFs"
LIB_DIR = PDF_DIR
METADATA_DIR = top / "METADATA"
METADATA_FILE = METADATA_DIR / "metadata.csv"
COLLECTIONS_FILE = METADATA_DIR / "collections.json"
CONFIG_FILE = top / "CONFIGS" / "config.json"

FIELDS = [
    "code",
    "file",
    "type",
    "title",
    "journal",
    "year",
    "doi",
    "author",
    "keywords",
    "my_keywords",
    "star",
    "added_at",
    "abstract",
    "notes",
]

DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
ARXIV_RE = re.compile(r"(?<!\d)(\d{2})(\d{2})\.\d{4,5}(?:v\d+)?(?!\d)")
ARXIV_TEXT_RE = re.compile(r"arxiv:\s*(\d{4})\.(\d{4,5})", re.IGNORECASE)


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        with CONFIG_FILE.open("r") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return {}


def normalize_keyword_config(config: dict) -> list:
    raw = config.get("my_keywords", [])
    normalized = []
    for entry in raw:
        if isinstance(entry, str):
            normalized.append({"tag": entry, "terms": [entry]})
            continue
        tag = entry.get("tag")
        terms = entry.get("terms", [])
        if tag and terms:
            normalized.append({"tag": tag, "terms": terms})
    return normalized


def suggest_my_keywords(text: str, config: dict) -> str:
    if not text:
        return ""
    text_lower = text.lower()
    matches = []
    for entry in normalize_keyword_config(config):
        if any(term.lower() in text_lower for term in entry["terms"]):
            matches.append(entry["tag"])
    return ", ".join(sorted(set(matches)))


def run_pdfinfo(path: Path) -> dict:
    try:
        result = subprocess.run(
            ["pdfinfo", str(path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return {}

    info = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        info[key.strip()] = value.strip()
    return info


def run_pdftotext_first_page(path: Path) -> str:
    if shutil.which("pdftotext") is None:
        return ""
    try:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "1", "-layout", str(path), "-"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout
    except (OSError, subprocess.CalledProcessError):
        return ""


def run_pdftotext_full(path: Path) -> str:
    if shutil.which("pdftotext") is None:
        return ""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout
    except (OSError, subprocess.CalledProcessError):
        return ""


def slugify(value: str, max_len: int = 60) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if not value:
        return "untitled"
    return value[:max_len].rstrip("-")


def infer_year(filename: str, info: dict, text: str) -> str:
    # 1) CreationDate from pdfinfo
    creation = info.get("CreationDate", "")
    match = re.search(r"(19|20)\d{2}", creation)
    if match:
        return match.group(0)

    # 2) arXiv-style yymm in filename
    match = ARXIV_RE.search(filename)
    if match:
        yy = int(match.group(1))
        return f"20{yy:02d}"

    # 3) arXiv id in the text
    match = ARXIV_TEXT_RE.search(text)
    if match:
        yy = int(match.group(1)[:2])
        return f"20{yy:02d}"

    # 4) 4-digit year in filename
    match = re.search(r"(19|20)\d{2}", filename)
    if match:
        return match.group(0)

    # 5) scan text for a plausible year, pick the latest
    years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", text)]
    if years:
        return str(max(years))

    return "0000"


def infer_type(filename: str, info: dict, title: str) -> str:
    haystack = " ".join([filename, title, info.get("Creator", "")]).lower()
    if "thesis" in haystack or "phd" in haystack:
        return "thesis"
    if "slides" in haystack or "presentation" in haystack:
        return "slides"
    if "poster" in haystack:
        return "poster"
    if "arxiv" in haystack:
        return "preprint"
    if "book" in haystack:
        return "book"
    return "article"


def extract_title(info: dict, text: str, filename: str) -> str:
    title = info.get("Title", "").strip()
    if title:
        return title

    # Heuristic: first non-empty line from first page
    for line in text.splitlines():
        line = line.strip()
        if len(line) >= 8:
            return line

    return Path(filename).stem


def extract_author(info: dict) -> str:
    return info.get("Author", "").strip()


def extract_doi(text: str) -> str:
    match = DOI_RE.search(text)
    if not match:
        return ""
    doi = match.group(0)
    return doi.rstrip(".)];,\"")


def load_metadata() -> dict:
    if not METADATA_FILE.exists():
        return {}
    with METADATA_FILE.open("r", newline="") as handle:
        reader = csv.DictReader(handle)
        data = {}
        for row in reader:
            key = row.get("file", "")
            if key:
                data[key] = row
        return data


def save_metadata(rows: list) -> None:
    with METADATA_FILE.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def scan_pdfs(dry_run: bool = False) -> list:
    LIB_DIR.mkdir(parents=True, exist_ok=True)

    config = load_config()
    existing = load_metadata()
    rows = []
    seen_files = set()

    for path in sorted(LIB_DIR.glob("*.pdf")):
        info = run_pdfinfo(path)
        text = run_pdftotext_first_page(path)
        title = extract_title(info, text, path.name)
        year = infer_year(path.name, info, text)
        doc_type = infer_type(path.name, info, title)
        author = extract_author(info)
        doi = extract_doi(text)

        slug = slugify(title)
        code = f"{year}_{doc_type}_{slug}"
        new_name = f"{code}.pdf"
        new_path = LIB_DIR / new_name

        if not dry_run and (path.resolve() != new_path.resolve()):
            if new_path.exists():
                # Avoid collisions by appending a suffix.
                ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                new_path = LIB_DIR / f"{code}-{ts}.pdf"
                code = new_path.stem
            path.rename(new_path)
        else:
            new_path = path

        rel_path = str(new_path.relative_to(top))
        seen_files.add(rel_path)

        prev = existing.get(rel_path, {})
        auto_tags = ""
        if not prev.get("my_keywords"):
            auto_tags = suggest_my_keywords(f"{title}\n{prev.get('keywords', '')}", config)
        row = {
            "code": prev.get("code", code),
            "file": rel_path,
            "type": prev.get("type", doc_type),
            "title": prev.get("title", title),
            "journal": prev.get("journal", ""),
            "year": prev.get("year", year),
            "doi": prev.get("doi", doi),
            "author": prev.get("author", author),
            "keywords": prev.get("keywords", ""),
            "my_keywords": prev.get("my_keywords", auto_tags),
            "star": prev.get("star", ""),
            "added_at": prev.get("added_at", datetime.utcnow().strftime("%Y-%m-%d")),
            "abstract": prev.get("abstract", ""),
            "notes": prev.get("notes", ""),
        }
        rows.append(row)

    save_metadata(rows)
    return rows


def load_collections() -> dict:
    if not COLLECTIONS_FILE.exists():
        return {}
    with COLLECTIONS_FILE.open("r") as handle:
        return json.load(handle)


def save_collections(data: dict) -> None:
    with COLLECTIONS_FILE.open("w") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def filter_rows(rows, year_from=None, year_to=None, journal=None, keyword=None, my_keyword=None):
    def match_year(row):
        try:
            year = int(row.get("year", "0"))
        except ValueError:
            return False
        if year_from is not None and year < year_from:
            return False
        if year_to is not None and year > year_to:
            return False
        return True

    def match_text(field, needle):
        if not needle:
            return True
        return needle.lower() in field.lower()

    filtered = []
    for row in rows:
        if year_from or year_to:
            if not match_year(row):
                continue
        if journal and not match_text(row.get("journal", ""), journal):
            continue
        if keyword and not match_text(row.get("keywords", ""), keyword):
            continue
        if my_keyword and not match_text(row.get("my_keywords", ""), my_keyword):
            continue
        filtered.append(row)
    return filtered


def load_rows() -> list:
    if not METADATA_FILE.exists():
        return []
    with METADATA_FILE.open("r", newline="") as handle:
        return list(csv.DictReader(handle))


def print_codes(rows: list) -> None:
    for row in rows:
        print(row.get("code", ""))


def main():
    parser = argparse.ArgumentParser(description="Bibliography helper")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan PDFs, rename, and update metadata")
    scan.add_argument("--dry-run", action="store_true", help="Preview without renaming")

    find = sub.add_parser("find", help="Filter metadata and list codes")
    find.add_argument("--from-year", type=int)
    find.add_argument("--to-year", type=int)
    find.add_argument("--journal")
    find.add_argument("--keyword")
    find.add_argument("--my-keyword")

    save = sub.add_parser("save-collection", help="Save filtered results under a name")
    save.add_argument("--name", required=True)
    save.add_argument("--from-year", type=int)
    save.add_argument("--to-year", type=int)
    save.add_argument("--journal")
    save.add_argument("--keyword")
    save.add_argument("--my-keyword")

    list_c = sub.add_parser("list-collections", help="List saved collections")
    tag = sub.add_parser("tag", help="Auto-tag my_keywords using config.json")
    tag.add_argument("--force", action="store_true", help="Overwrite existing my_keywords")

    args = parser.parse_args()

    if args.command == "scan":
        scan_pdfs(dry_run=args.dry_run)
        return

    rows = load_rows()

    if args.command == "find":
        filtered = filter_rows(
            rows,
            year_from=args.from_year,
            year_to=args.to_year,
            journal=args.journal,
            keyword=args.keyword,
            my_keyword=args.my_keyword,
        )
        print_codes(filtered)
        return

    if args.command == "save-collection":
        filtered = filter_rows(
            rows,
            year_from=args.from_year,
            year_to=args.to_year,
            journal=args.journal,
            keyword=args.keyword,
            my_keyword=args.my_keyword,
        )
        data = load_collections()
        data[args.name] = {
            "codes": [row.get("code", "") for row in filtered if row.get("code")],
            "filters": {
                "from_year": args.from_year,
                "to_year": args.to_year,
                "journal": args.journal,
                "keyword": args.keyword,
                "my_keyword": args.my_keyword,
            },
        }
        save_collections(data)
        print(f"Saved {len(data[args.name]['codes'])} entries to {args.name}")
        return

    if args.command == "list-collections":
        data = load_collections()
        for name in sorted(data.keys()):
            print(name)
        return

    if args.command == "tag":
        config = load_config()
        rows = load_rows()
        updated = 0
        for row in rows:
            if row.get("my_keywords") and not args.force:
                continue
            path = top / row.get("file", "")
            if not path.exists():
                continue
            text = run_pdftotext_full(path)
            basis = "\n".join(
                [row.get("title", ""), row.get("keywords", ""), row.get("abstract", ""), text]
            )
            tags = suggest_my_keywords(basis, config)
            if tags:
                row["my_keywords"] = tags
                updated += 1
        save_metadata(rows)
        print(f"Updated my_keywords for {updated} entries")
        return


if __name__ == "__main__":
    main()
