#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
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
DOI_FULL_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
YEAR_RE = re.compile(r"^\d{4}$")
ARXIV_RE = re.compile(r"(?<!\d)(\d{2})(\d{2})\.\d{4,5}(?:v\d+)?(?!\d)")
ARXIV_TEXT_RE = re.compile(r"arxiv:\s*(\d{4})\.(\d{4,5})", re.IGNORECASE)
BAD_TITLE_RE = re.compile(
    r"^(?:untitled|pdf download|powerpoint presentation)$"
    r"|^(?:doi:|pii:|arxiv:)"
    r"|^(?:journal of|proceedings of)"
    r"|\\.(?:pdf|dvi|tif|djvu|doc)$",
    re.IGNORECASE,
)

REQUIRED_FIELDS = ["code", "file", "type", "title", "year"]


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


def split_tags(value: str) -> list:
    if not value:
        return []
    parts = re.split(r"[;,]", value)
    return [part.strip() for part in parts if part.strip()]


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
                ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
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
            "added_at": prev.get("added_at", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
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


def find_bad_titles(rows: list) -> list:
    bad = []
    for row in rows:
        title = (row.get("title") or "").strip()
        if not title or BAD_TITLE_RE.search(title):
            bad.append(row)
    return bad


def verify_integrity() -> int:
    pdfs = sorted([str(p.relative_to(top)) for p in LIB_DIR.glob("*.pdf")])
    rows = load_rows()
    meta_files = [row.get("file", "") for row in rows if row.get("file")]
    missing_in_meta = [p for p in pdfs if p not in meta_files]
    missing_pdfs = [f for f in meta_files if f.endswith(".pdf") and not (top / f).exists()]

    code_counts = {}
    for row in rows:
        code = (row.get("code") or "").strip()
        if not code:
            continue
        code_counts[code] = code_counts.get(code, 0) + 1
    duplicate_codes = sorted([code for code, count in code_counts.items() if count > 1])

    bad_titles = find_bad_titles(rows)

    issues = 0
    if missing_in_meta:
        issues += 1
        print(f"Missing in metadata: {len(missing_in_meta)}")
        for item in missing_in_meta[:20]:
            print(f"  - {item}")
    if missing_pdfs:
        issues += 1
        print(f"Missing PDF files: {len(missing_pdfs)}")
        for item in missing_pdfs[:20]:
            print(f"  - {item}")
    if bad_titles:
        issues += 1
        print(f"Bad titles: {len(bad_titles)}")
        for row in bad_titles[:20]:
            print(f"  - {row.get('title', '')} :: {row.get('file', '')}")
    if duplicate_codes:
        issues += 1
        print(f"Duplicate codes: {len(duplicate_codes)}")
        for code in duplicate_codes[:20]:
            print(f"  - {code}")

    if issues == 0:
        print("Integrity check: OK")
    return issues


def normalize_title_text(title: str) -> str:
    if not title:
        return title
    replacements = {
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\u2010": "-",
        "\u2011": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": "\"",
        "\u201d": "\"",
        "\u00a0": " ",
    }
    for src, dst in replacements.items():
        title = title.replace(src, dst)
    title = re.sub(r"([A-Za-z])-\s+([A-Za-z])", r"\1-\2", title)
    title = re.sub(r"Tele-\s*scope", "Telescope", title, flags=re.IGNORECASE)
    title = title.replace("?HE ", "THE ")
    title = re.sub(r"\s+", " ", title).strip()
    return title.strip(" -")


def cleanup_titles(rename_files: bool = False, dry_run: bool = False) -> int:
    rows = load_rows()
    updated = 0
    renames = []
    for row in rows:
        title = row.get("title", "")
        normalized = normalize_title_text(title)
        if not normalized or normalized == title:
            continue
        row["title"] = normalized
        updated += 1

        if not rename_files:
            continue
        year = row.get("year", "0000")
        doc_type = row.get("type", "article")
        slug = slugify(normalized)
        code = f"{year}_{doc_type}_{slug}"
        new_name = f"{code}.pdf"
        old_path = top / row.get("file", "")
        new_path = LIB_DIR / new_name
        if old_path.exists() and old_path.resolve() != new_path.resolve():
            if new_path.exists():
                ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                new_path = LIB_DIR / f"{code}-{ts}.pdf"
                code = new_path.stem
            if not dry_run:
                old_path.rename(new_path)
            row["file"] = str(new_path.relative_to(top))
            row["code"] = code
            renames.append((str(old_path.relative_to(top)), row["file"]))

    if updated and not dry_run:
        save_metadata(rows)

    if updated:
        print(f"Normalized titles: {updated}")
    if renames:
        print(f"Renamed files: {len(renames)}")
        for old, new in renames[:20]:
            print(f"  - {old} -> {new}")
    return updated


def dedupe_metadata() -> int:
    rows = load_rows()
    doi_map = {}
    title_map = {}
    for row in rows:
        doi = (row.get("doi") or "").strip().lower()
        if doi:
            doi_map.setdefault(doi, []).append(row)
        title = normalize_title_text(row.get("title", "")).lower()
        if title:
            title_map.setdefault(title, []).append(row)

    duplicates = 0
    dup_doi = {k: v for k, v in doi_map.items() if len(v) > 1}
    dup_title = {k: v for k, v in title_map.items() if len(v) > 1}

    if dup_doi:
        duplicates += len(dup_doi)
        print(f"Duplicate DOIs: {len(dup_doi)}")
        for doi, items in list(dup_doi.items())[:20]:
            print(f"  - {doi}")
            for row in items[:5]:
                print(f"      {row.get('code', '')} :: {row.get('file', '')}")

    if dup_title:
        duplicates += len(dup_title)
        print(f"Duplicate titles: {len(dup_title)}")
        for title, items in list(dup_title.items())[:20]:
            print(f"  - {title}")
            for row in items[:5]:
                print(f"      {row.get('code', '')} :: {row.get('file', '')}")

    if duplicates == 0:
        print("Dedupe check: OK")
    return duplicates


def validate_metadata(rows: list) -> int:
    missing_required = []
    bad_years = []
    bad_dois = []
    missing_files = []

    for row in rows:
        missing = [field for field in REQUIRED_FIELDS if not (row.get(field) or "").strip()]
        if missing:
            missing_required.append((row, missing))

        year = (row.get("year") or "").strip()
        if year and not YEAR_RE.match(year):
            bad_years.append((row, year))

        doi = (row.get("doi") or "").strip()
        if doi and not DOI_FULL_RE.match(doi):
            bad_dois.append((row, doi))

        file_rel = (row.get("file") or "").strip()
        if file_rel and file_rel.endswith(".pdf") and not (top / file_rel).exists():
            missing_files.append((row, file_rel))

    issues = 0
    if missing_required:
        issues += 1
        print(f"Missing required fields: {len(missing_required)}")
        for row, fields in missing_required[:20]:
            print(f"  - {row.get('file', '')} :: {', '.join(fields)}")
    if bad_years:
        issues += 1
        print(f"Bad year format: {len(bad_years)}")
        for row, year in bad_years[:20]:
            print(f"  - {row.get('file', '')} :: {year}")
    if bad_dois:
        issues += 1
        print(f"Bad DOI format: {len(bad_dois)}")
        for row, doi in bad_dois[:20]:
            print(f"  - {row.get('file', '')} :: {doi}")
    if missing_files:
        issues += 1
        print(f"Missing PDF files: {len(missing_files)}")
        for _, file_rel in missing_files[:20]:
            print(f"  - {file_rel}")

    if issues == 0:
        print("Validation: OK")
    return issues


def stats_metadata(rows: list) -> None:
    year_counts = {}
    type_counts = {}
    tag_counts = {}
    missing_counts = {field: 0 for field in FIELDS}

    for row in rows:
        year = (row.get("year") or "").strip() or "unknown"
        year_counts[year] = year_counts.get(year, 0) + 1

        doc_type = (row.get("type") or "").strip() or "unknown"
        type_counts[doc_type] = type_counts.get(doc_type, 0) + 1

        for tag in split_tags(row.get("my_keywords", "")):
            key = tag.lower()
            tag_counts[key] = tag_counts.get(key, 0) + 1

        for field in FIELDS:
            if not (row.get(field) or "").strip():
                missing_counts[field] += 1

    print(f"Total entries: {len(rows)}")

    print("By year:")
    for year in sorted(year_counts.keys(), key=lambda y: (not y.isdigit(), int(y) if y.isdigit() else 0)):
        print(f"  {year}: {year_counts[year]}")

    print("By type:")
    for doc_type, count in sorted(type_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {doc_type}: {count}")

    if tag_counts:
        print("Top my_keywords:")
        for tag, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:20]:
            print(f"  {tag}: {count}")

    missing_sorted = [(field, count) for field, count in missing_counts.items() if count]
    if missing_sorted:
        print("Most-missing fields:")
        for field, count in sorted(missing_sorted, key=lambda item: (-item[1], item[0]))[:10]:
            print(f"  {field}: {count}")


def export_metadata(rows: list, fmt: str, output=None, pretty: bool = False) -> None:
    if fmt == "json":
        indent = 2 if pretty else None
        if output:
            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w") as handle:
                json.dump(rows, handle, indent=indent)
                handle.write("\n")
            return
        json.dump(rows, sys.stdout, indent=indent)
        sys.stdout.write("\n")
        return

    if fmt == "csv":
        if output:
            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
            return
        writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return

    raise ValueError(f"Unsupported export format: {fmt}")


def parse_bibtex_entries(text: str) -> list:
    entries = []
    i = 0
    while i < len(text):
        if text[i] != "@":
            i += 1
            continue
        brace = text.find("{", i)
        if brace == -1:
            break
        depth = 0
        j = brace
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= len(text):
            break
        body = text[brace + 1 : j]
        comma = body.find(",")
        if comma == -1:
            i = j + 1
            continue
        key = body[:comma].strip()
        fields = body[comma + 1 :]
        entry = {"_key": key}

        k = 0
        while k < len(fields):
            while k < len(fields) and fields[k] in " \t\r\n,":
                k += 1
            if k >= len(fields):
                break
            name_start = k
            while k < len(fields) and fields[k] not in "=\n":
                k += 1
            name = fields[name_start:k].strip().lower()
            if not name:
                break
            while k < len(fields) and fields[k] != "=":
                k += 1
            if k >= len(fields):
                break
            k += 1
            while k < len(fields) and fields[k] in " \t\r\n":
                k += 1
            if k >= len(fields):
                break
            if fields[k] == "{":
                depth = 0
                val_start = k + 1
                while k < len(fields):
                    if fields[k] == "{":
                        depth += 1
                    elif fields[k] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                value = fields[val_start:k].strip()
                k += 1
            elif fields[k] == "\"":
                k += 1
                val_start = k
                while k < len(fields) and fields[k] != "\"":
                    k += 1
                value = fields[val_start:k].strip()
                k += 1
            else:
                val_start = k
                while k < len(fields) and fields[k] not in ",\n":
                    k += 1
                value = fields[val_start:k].strip()
            if name:
                entry[name] = re.sub(r"\s+", " ", value)
        entries.append(entry)
        i = j + 1
    return entries


def import_bibtex(path: Path, force: bool = False) -> int:
    if not path.exists():
        print(f"BibTeX file not found: {path}")
        return 0
    text = path.read_text(errors="ignore")
    entries = parse_bibtex_entries(text)
    if not entries:
        print("No BibTeX entries found.")
        return 0

    rows = load_rows()
    doi_index = {}
    title_index = {}
    for row in rows:
        doi = (row.get("doi") or "").strip().lower()
        if doi:
            doi_index[doi] = row
        title = normalize_title_text(row.get("title", "")).lower()
        if title:
            title_index[title] = row

    updated = 0
    unmatched = 0
    for entry in entries:
        title = normalize_title_text(entry.get("title", ""))
        doi = (entry.get("doi") or "").strip().lower()
        row = None
        if doi and doi in doi_index:
            row = doi_index[doi]
        elif title and title.lower() in title_index:
            row = title_index[title.lower()]
        if row is None:
            unmatched += 1
            continue

        def set_field(field, value):
            if not value:
                return False
            if force or not (row.get(field) or "").strip():
                row[field] = value
                return True
            return False

        changed = False
        changed |= set_field("title", title)
        changed |= set_field("year", entry.get("year", ""))
        changed |= set_field("doi", entry.get("doi", ""))
        changed |= set_field("author", entry.get("author", ""))
        changed |= set_field("journal", entry.get("journal", ""))
        if changed:
            updated += 1

    if updated:
        save_metadata(rows)
    print(f"Updated entries: {updated}")
    print(f"Unmatched entries: {unmatched}")
    return updated


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

    verify = sub.add_parser("verify", help="Check metadata integrity")
    cleanup = sub.add_parser("cleanup", help="Normalize titles in metadata")
    cleanup.add_argument("--rename", action="store_true", help="Rename files and codes to match")
    cleanup.add_argument("--dry-run", action="store_true", help="Preview changes without writing")

    dedupe = sub.add_parser("dedupe", help="Report duplicate titles or DOIs")

    bibtex = sub.add_parser("import-bibtex", help="Update metadata from a BibTeX file")
    bibtex.add_argument("path", help="Path to .bib file")
    bibtex.add_argument("--force", action="store_true", help="Overwrite existing fields")

    validate = sub.add_parser("validate", help="Validate required fields and formats")
    stats = sub.add_parser("stats", help="Summarize metadata counts")

    export = sub.add_parser("export", help="Export filtered metadata to JSON or CSV")
    export.add_argument("--format", choices=["json", "csv"], default="json")
    export.add_argument("--output", help="Write to file instead of stdout")
    export.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    export.add_argument("--from-year", type=int)
    export.add_argument("--to-year", type=int)
    export.add_argument("--journal")
    export.add_argument("--keyword")
    export.add_argument("--my-keyword")

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

    if args.command == "verify":
        issues = verify_integrity()
        if issues:
            raise SystemExit(1)
        return

    if args.command == "cleanup":
        cleanup_titles(rename_files=args.rename, dry_run=args.dry_run)
        return

    if args.command == "dedupe":
        duplicates = dedupe_metadata()
        if duplicates:
            raise SystemExit(1)
        return

    if args.command == "import-bibtex":
        updated = import_bibtex(Path(args.path), force=args.force)
        if updated:
            print("BibTeX import complete.")
        return

    if args.command == "validate":
        issues = validate_metadata(rows)
        if issues:
            raise SystemExit(1)
        return

    if args.command == "stats":
        stats_metadata(rows)
        return

    if args.command == "export":
        filtered = filter_rows(
            rows,
            year_from=args.from_year,
            year_to=args.to_year,
            journal=args.journal,
            keyword=args.keyword,
            my_keyword=args.my_keyword,
        )
        export_metadata(filtered, args.format, args.output, pretty=args.pretty)
        return


if __name__ == "__main__":
    main()
