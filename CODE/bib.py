#!/usr/bin/env python3
import argparse
import csv
import html
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

top = Path(__file__).resolve().parent.parent
PDF_DIR = top / "PDFs"
LIB_DIR = PDF_DIR
METADATA_DIR = top / "METADATA"
METADATA_FILE = METADATA_DIR / "metadata.csv"
ABSTRACTS_FILE = METADATA_DIR / "abstracts.csv"
COLLECTIONS_FILE = METADATA_DIR / "collections.json"
CONFIG_FILE = top / "CONFIGS" / "config.json"

FIELDS = [
    "code",
    "type",
    "title",
    "journal",
    "year",
    "doi",
    "author",
    "keywords",
    "my_keywords",
    "star",
    "unread",
    "added_at",
    "notes",
]

DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
DOI_FULL_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
YEAR_RE = re.compile(r"^\d{4}$")
ADDED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ARXIV_RE = re.compile(r"(?<!\d)(\d{2})(\d{2})\.\d{4,5}(?:v\d+)?(?!\d)")
ARXIV_TEXT_RE = re.compile(r"arxiv:\s*(\d{4})\.(\d{4,5})", re.IGNORECASE)
BAD_TITLE_RE = re.compile(
    r"^(?:untitled|pdf download|powerpoint presentation)$"
    r"|^(?:doi:|pii:|arxiv:)"
    r"|^(?:journal of|proceedings of)"
    r"|\\.(?:pdf|dvi|tif|djvu|doc)$",
    re.IGNORECASE,
)
TITLE_NOISE_RE = re.compile(
    r"\b(?:volume|vol\.?|number|issn|pii|afcrl|indd|confidential|submitted|draft version|research article)\b",
    re.IGNORECASE,
)
TITLE_SECTION_RE = re.compile(
    r"^(?:abstract|summary|keywords?|index terms?|introduction|references|acknowledg(?:e)?ments?)\b",
    re.IGNORECASE,
)
TITLE_AFFILIATION_RE = re.compile(
    r"\b(?:university|department|division|institute|laboratory|school|college|faculty|center|centre|campus|email)\b",
    re.IGNORECASE,
)
TITLE_EXTRA_NOISE_RE = re.compile(
    r"\b(?:submission|manuscript|file reference|proof|draft|confidential|not for distribution|temp|view|export|online citation)\b",
    re.IGNORECASE,
)
ABSTRACT_SECTION_RE = re.compile(
    r"^(?:keywords?|index terms?|key points?|introduction|1[.)]\s|i[.)]\s|references?)\b",
    re.IGNORECASE,
)
ABSTRACT_NOISE_RE = re.compile(
    r"\b(?:copyright|all rights reserved|creative commons|received|accepted|issn|doi:)\b",
    re.IGNORECASE,
)

REQUIRED_FIELDS = ["code", "type", "title", "year"]
ABSTRACT_FIELDS = ["code", "abstract"]


def code_to_rel_pdf_path(code: str) -> str:
    code = (code or "").strip()
    if not code:
        return ""
    return f"PDFs/{code}.pdf"


def row_pdf_path(row: dict) -> Path:
    rel = code_to_rel_pdf_path(row.get("code", ""))
    if not rel:
        return top / "__missing__.pdf"
    return top / rel


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
            timeout=30,
        )
        return result.stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
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
            timeout=25,
        )
        return result.stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def slugify(value: str, max_len: int = 60) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        return "untitled"
    return value[:max_len].rstrip("_")


def build_code(year: str, doc_type: str, title: str) -> str:
    safe_year = (year or "").strip()
    if not YEAR_RE.match(safe_year):
        safe_year = "0000"
    safe_type = slugify((doc_type or "").strip() or "article", max_len=20)
    return f"{safe_year}_{safe_type}_{slugify(title or 'untitled')}"


def score_title_candidate(text: str) -> int:
    candidate = (text or "").strip()
    if not candidate:
        return -100

    lower = candidate.lower()
    words = candidate.split()
    alnum = sum(1 for ch in candidate if ch.isalnum())
    letters = sum(1 for ch in candidate if ch.isalpha())
    digits = sum(1 for ch in candidate if ch.isdigit())

    score = 0
    if 4 <= len(words) <= 24:
        score += 3
    if 24 <= len(candidate) <= 180:
        score += 3
    if TITLE_NOISE_RE.search(lower):
        score -= 6
    if TITLE_SECTION_RE.search(lower):
        score -= 6
    if TITLE_EXTRA_NOISE_RE.search(lower):
        score -= 6
    if TITLE_AFFILIATION_RE.search(lower):
        score -= 4
    if BAD_TITLE_RE.search(lower):
        score -= 6
    if re.match(r"^\d{4}\b", lower):
        score -= 4
    if lower.startswith("article "):
        score -= 4
    if lower.count(",") >= 2:
        score -= 2
    if lower.count(",") >= 2 and digits:
        score -= 6
    if candidate.count(";") >= 2:
        score -= 8
    if len(re.findall(r"\b[A-Z]\.", candidate)) >= 2:
        score -= 6
    if re.search(r"[A-Za-z]\d", candidate):
        score -= 4
    alpha_words = [word for word in re.findall(r"[A-Za-z]+", candidate)]
    if alpha_words:
        upper_words = sum(1 for word in alpha_words if word.isupper())
        if upper_words / len(alpha_words) > 0.75 and len(alpha_words) >= 4:
            score -= 4
    if re.search(r"\b(?:v\d+|version)\b", lower):
        score -= 2
    if re.search(r"\b(?:of|the|and|for|with|within|to|in|on|at|from|by|a|an)\b$", lower):
        score -= 4
    if "_" in candidate:
        score -= 4
    if candidate.endswith("."):
        score -= 1
    if alnum:
        score -= 4 if digits / alnum > 0.24 else 0
        score -= 3 if letters / alnum < 0.6 else 0
    if candidate.isupper():
        score -= 1
    return score


def is_low_quality_title(title: str) -> bool:
    candidate = normalize_title_text(title or "")
    if not candidate:
        return True
    return score_title_candidate(candidate) <= 0


def needs_title_refresh(title: str) -> bool:
    candidate = normalize_title_text(title or "")
    if not candidate:
        return True

    lower = candidate.lower()
    if BAD_TITLE_RE.search(lower):
        return True
    if TITLE_NOISE_RE.search(lower):
        return True
    if "_" in candidate:
        return True
    if re.search(r"\b(?:vol\.?|volume|number|issn|pii)\b", lower):
        return True

    words = candidate.split()
    digits = sum(1 for ch in candidate if ch.isdigit())
    alnum = sum(1 for ch in candidate if ch.isalnum())
    if digits >= 6 and len(words) <= 14 and alnum and (digits / alnum) > 0.2:
        return True
    return False


def split_text_blocks(text: str, max_blocks: int = 20) -> list:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = []
    current = []
    for raw_line in normalized.split("\n"):
        line = re.sub(r"\s+", " ", html.unescape(raw_line)).strip()
        if line:
            current.append(line)
            continue
        if current:
            blocks.append(current)
            if len(blocks) >= max_blocks:
                break
            current = []
    if current and len(blocks) < max_blocks:
        blocks.append(current)
    return blocks


def guess_title_from_first_page(text: str) -> str:
    blocks = split_text_blocks(text, max_blocks=12)
    candidates = []

    for block in blocks:
        if not block:
            continue
        if TITLE_SECTION_RE.match(block[0]):
            break
        for take in (1, 2, 3):
            if len(block) < take:
                continue
            candidate = " ".join(block[:take]).strip()
            if candidate:
                candidates.append(candidate)

    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for raw_line in normalized.split("\n"):
        clean = re.sub(r"\s+", " ", html.unescape(raw_line)).strip()
        if not clean:
            continue
        if TITLE_SECTION_RE.match(clean):
            break
        lines.append(clean)
        if len(lines) >= 60:
            break
    for idx in range(min(len(lines), 25)):
        candidates.append(lines[idx])
        if idx + 1 < len(lines):
            candidates.append(f"{lines[idx]} {lines[idx + 1]}")

    best = ""
    best_score = -100
    seen = set()
    for raw in candidates:
        candidate = normalize_title_text(raw).strip(" .:;-|")
        key = candidate.lower()
        if not candidate or key in seen:
            continue
        seen.add(key)
        score = score_title_candidate(candidate)
        if score > best_score:
            best = candidate
            best_score = score

    if best_score > 0:
        return best
    return ""


def ensure_available_code(base_code: str, current_path: Path) -> tuple:
    candidate = base_code
    suffix = 2
    while True:
        path = LIB_DIR / f"{candidate}.pdf"
        if (not path.exists()) or path.resolve() == current_path.resolve():
            return candidate, path
        candidate = f"{base_code}_{suffix}"
        suffix += 1


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
    info_title = normalize_title_text(info.get("Title", "").strip())
    guessed = normalize_title_text(guess_title_from_first_page(text))

    if info_title and not needs_title_refresh(info_title):
        return info_title
    if guessed and not needs_title_refresh(guessed):
        return guessed
    if info_title:
        return info_title
    if guessed:
        return guessed
    return normalize_title_text(Path(filename).stem.replace("_", " "))


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
            key = (row.get("code") or "").strip()
            if key:
                data[key] = row
        return data


def save_metadata(rows: list) -> None:
    with METADATA_FILE.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def ensure_abstracts_file() -> None:
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    if ABSTRACTS_FILE.exists():
        return
    with ABSTRACTS_FILE.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ABSTRACT_FIELDS)
        writer.writeheader()


def load_abstracts() -> dict:
    if not ABSTRACTS_FILE.exists():
        return {}
    with ABSTRACTS_FILE.open("r", newline="") as handle:
        reader = csv.DictReader(handle)
        data = {}
        for row in reader:
            code = (row.get("code") or "").strip()
            if not code:
                continue
            data[code] = row.get("abstract", "")
        return data


def save_abstracts(mapping: dict) -> None:
    ensure_abstracts_file()
    with ABSTRACTS_FILE.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ABSTRACT_FIELDS)
        writer.writeheader()
        for raw_code in sorted(mapping.keys()):
            code = (raw_code or "").strip()
            if not code:
                continue
            writer.writerow(
                {
                    "code": code,
                    "abstract": mapping.get(raw_code) or "",
                }
            )


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def clean_abstract_text(text: str) -> str:
    candidate = collapse_whitespace(html.unescape(text or ""))
    if not candidate:
        return ""
    candidate = re.sub(
        r"\b(?:copyright|all rights reserved)\b[^.]*\.?",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+", " ", candidate).strip(" :;-")
    return candidate


def is_low_quality_abstract(text: str) -> bool:
    candidate = clean_abstract_text(text)
    if len(candidate) < 80:
        return True
    lower = candidate.lower()
    if ABSTRACT_NOISE_RE.search(lower):
        return True
    if lower.startswith(("volume ", "issn ", "doi:", "journal ")):
        return True
    return False


def extract_first_text_block(text: str) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return ""

    lines = [collapse_whitespace(html.unescape(line.strip())) for line in normalized.split("\n")]
    lines = [line for line in lines if line or line == ""]
    for idx, line in enumerate(lines):
        if not re.match(r"^abstract\b", line, flags=re.IGNORECASE):
            continue
        inline = re.sub(r"^abstract\b[:\s-]*", "", line, flags=re.IGNORECASE)
        block_lines = [inline] if inline.strip() else []
        for next_line in lines[idx + 1 :]:
            stripped = next_line.strip()
            if not stripped:
                if block_lines:
                    break
                continue
            if ABSTRACT_SECTION_RE.match(stripped):
                break
            if ABSTRACT_NOISE_RE.search(stripped):
                continue
            if block_lines and stripped.isupper() and len(stripped.split()) <= 8:
                break
            block_lines.append(stripped)
            if len(" ".join(block_lines)) > 4000:
                break
        candidate = clean_abstract_text(" ".join(block_lines))
        lower = candidate.lower()
        if candidate and not ABSTRACT_NOISE_RE.search(lower) and not lower.startswith(
            ("volume ", "issn ", "doi:", "journal ")
        ):
            return candidate

    for block in split_text_blocks(normalized, max_blocks=40):
        candidate = clean_abstract_text(" ".join(block))
        if is_low_quality_abstract(candidate):
            continue
        if len(candidate) >= 80:
            return candidate
    return ""


def guess_abstract_for_row(row: dict, from_pdfs: bool = False) -> str:
    if from_pdfs:
        path = row_pdf_path(row)
        if path.exists():
            text = run_pdftotext_full(path)
            candidate = extract_first_text_block(text)
            if candidate:
                return candidate
    notes = clean_abstract_text(row.get("notes", ""))
    if notes:
        return notes
    title = normalize_title_text(row.get("title", ""))
    doc_type = (row.get("type") or "").strip().lower()
    if title and doc_type in {"book", "thesis", "slides", "poster"}:
        return f"{doc_type.capitalize()} focused on {title}."
    return ""


def rebuild_abstracts(from_pdfs: bool = False, force: bool = False) -> int:
    ensure_abstracts_file()
    rows = load_rows()
    existing = load_abstracts()
    rebuilt = {}
    updated = 0
    preserved = 0

    for row in rows:
        code = (row.get("code") or "").strip()
        if not code or code in rebuilt:
            continue

        current = existing.get(code, "")
        if current and not force:
            rebuilt[code] = current
            preserved += 1
            continue

        guessed = guess_abstract_for_row(row, from_pdfs=from_pdfs)
        rebuilt[code] = guessed
        if guessed != current:
            updated += 1

    save_abstracts(rebuilt)
    print(f"Abstract entries: {len(rebuilt)}")
    print(f"Updated abstracts: {updated}")
    if preserved:
        print(f"Preserved existing abstracts: {preserved}")
    return updated


def scan_pdfs(dry_run: bool = False) -> list:
    LIB_DIR.mkdir(parents=True, exist_ok=True)

    config = load_config()
    existing = load_metadata()
    rows = []

    for path in sorted(LIB_DIR.glob("*.pdf")):
        old_code = path.stem
        info = run_pdfinfo(path)
        text = run_pdftotext_first_page(path)
        title = extract_title(info, text, path.name)
        year = infer_year(path.name, info, text)
        doc_type = infer_type(path.name, info, title)
        author = extract_author(info)
        doi = extract_doi(text)

        base_code = build_code(year, doc_type, title)
        code, new_path = ensure_available_code(base_code, path)

        if not dry_run and (path.resolve() != new_path.resolve()):
            path.rename(new_path)
        else:
            new_path = path

        code = new_path.stem

        prev = existing.get(old_code, {})
        auto_tags = ""
        if not prev.get("my_keywords"):
            auto_tags = suggest_my_keywords(f"{title}\n{prev.get('keywords', '')}", config)
        row = {
            "code": code,
            "type": prev.get("type", doc_type),
            "title": prev.get("title", title),
            "journal": prev.get("journal", ""),
            "year": prev.get("year", year),
            "doi": prev.get("doi", doi),
            "author": prev.get("author", author),
            "keywords": prev.get("keywords", ""),
            "my_keywords": prev.get("my_keywords", auto_tags),
            "star": prev.get("star", ""),
            "unread": prev.get("unread", ""),
            "added_at": prev.get("added_at", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
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


def parse_ymd_date(value: str):
    value = (value or "").strip()
    if not value:
        return None
    if not ADDED_AT_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def sort_rows_by_added(rows: list, descending: bool = False) -> list:
    dated = []
    missing = []
    for row in rows:
        parsed = parse_ymd_date(row.get("added_at", ""))
        if parsed is None:
            missing.append(row)
            continue
        dated.append((parsed, row))

    dated.sort(key=lambda item: item[0], reverse=descending)
    return [row for _, row in dated] + missing


def filter_rows(
    rows,
    year_from=None,
    year_to=None,
    journal=None,
    keyword=None,
    my_keyword=None,
    added_from=None,
    added_to=None,
    unread_only: bool = False,
):
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

    def match_added(row):
        added_at = parse_ymd_date(row.get("added_at", ""))
        if added_at is None:
            return False
        if added_from is not None and added_at < added_from:
            return False
        if added_to is not None and added_at > added_to:
            return False
        return True

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
        if added_from or added_to:
            if not match_added(row):
                continue
        if unread_only and (row.get("unread") or "").strip() != "1":
            continue
        filtered.append(row)
    return filtered


def load_rows() -> list:
    if not METADATA_FILE.exists():
        return []
    with METADATA_FILE.open("r", newline="") as handle:
        return list(csv.DictReader(handle))


def read_csv_header(path: Path) -> list:
    if not path.exists():
        return []
    with path.open("r", newline="") as handle:
        return next(csv.reader(handle), [])


def find_bad_titles(rows: list) -> list:
    bad = []
    for row in rows:
        title = (row.get("title") or "").strip()
        if needs_title_refresh(title):
            bad.append(row)
    return bad


def verify_integrity() -> int:
    issues = 0
    if not METADATA_FILE.exists():
        issues += 1
        print(f"Missing metadata file: {METADATA_FILE.relative_to(top)}")

    metadata_header = read_csv_header(METADATA_FILE)
    if metadata_header and metadata_header != FIELDS:
        issues += 1
        print(f"Metadata header mismatch: expected {FIELDS}, got {metadata_header}")

    pdfs = sorted([str(p.relative_to(top)) for p in LIB_DIR.glob("*.pdf")])
    rows = load_rows()
    meta_files = [code_to_rel_pdf_path(row.get("code", "")) for row in rows if row.get("code")]
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
            print(f"  - {row.get('title', '')} :: {row.get('code', '')}")
    if duplicate_codes:
        issues += 1
        print(f"Duplicate codes: {len(duplicate_codes)}")
        for code in duplicate_codes[:20]:
            print(f"  - {code}")

    if not ABSTRACTS_FILE.exists():
        issues += 1
        print(f"Missing abstracts file: {ABSTRACTS_FILE.relative_to(top)}")
    else:
        header = read_csv_header(ABSTRACTS_FILE)
        if header != ABSTRACT_FIELDS:
            issues += 1
            print(f"Abstracts header mismatch: expected {ABSTRACT_FIELDS}, got {header}")

        with ABSTRACTS_FILE.open("r", newline="") as handle:
            reader = csv.DictReader(handle)
            unknown_codes = []
            seen = set()
            metadata_codes = set(code_counts.keys())
            for row in reader:
                code = (row.get("code") or "").strip()
                if not code or code in seen:
                    continue
                seen.add(code)
                if code not in metadata_codes:
                    unknown_codes.append(code)

            if unknown_codes:
                issues += 1
                print(f"Abstract codes not in metadata: {len(unknown_codes)}")
                for code in unknown_codes[:20]:
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


def cleanup_titles(
    rename_files: bool = False,
    dry_run: bool = False,
    from_pdfs: bool = False,
    force_titles: bool = False,
) -> int:
    rows = load_rows()
    updated = 0
    refreshed_from_pdf = 0
    code_updates = 0
    renames = []
    for row in rows:
        original_title = row.get("title", "")
        normalized = normalize_title_text(original_title)

        if from_pdfs and (force_titles or needs_title_refresh(normalized)):
            path = row_pdf_path(row)
            if path.exists():
                info = run_pdfinfo(path)
                text = run_pdftotext_first_page(path)
                extracted = normalize_title_text(extract_title(info, text, path.name))
                current_score = score_title_candidate(normalized)
                extracted_score = score_title_candidate(extracted)
                if extracted and (
                    (force_titles and extracted_score > 0)
                    or (
                        extracted_score > current_score
                        and extracted_score > 0
                        and not needs_title_refresh(extracted)
                    )
                ):
                    normalized = extracted
                    refreshed_from_pdf += 1

        if normalized and normalized != original_title:
            row["title"] = normalized
            updated += 1

        if not rename_files:
            continue

        current_code = (row.get("code") or "").strip()
        year = (row.get("year") or "").strip() or "0000"
        doc_type = (row.get("type") or "").strip() or "article"
        title_for_code = row.get("title") or current_code or "untitled"
        base_code = build_code(year, doc_type, title_for_code)

        old_path = row_pdf_path(row)
        code, new_path = ensure_available_code(base_code, old_path)
        if old_path.exists() and old_path.resolve() != new_path.resolve():
            if not dry_run:
                old_path.rename(new_path)
            renames.append((str(old_path.relative_to(top)), str(new_path.relative_to(top))))

        if code != current_code:
            row["code"] = code
            code_updates += 1

    if (updated or code_updates or renames) and not dry_run:
        save_metadata(rows)

    if updated:
        print(f"Normalized titles: {updated}")
    if refreshed_from_pdf:
        print(f"Retitled from PDFs: {refreshed_from_pdf}")
    if code_updates:
        print(f"Updated codes: {code_updates}")
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
                print(f"      {row.get('code', '')}")

    if dup_title:
        duplicates += len(dup_title)
        print(f"Duplicate titles: {len(dup_title)}")
        for title, items in list(dup_title.items())[:20]:
            print(f"  - {title}")
            for row in items[:5]:
                print(f"      {row.get('code', '')}")

    if duplicates == 0:
        print("Dedupe check: OK")
    return duplicates


def validate_metadata(rows: list) -> int:
    missing_required = []
    bad_years = []
    bad_dois = []
    bad_unread = []
    bad_added_dates = []
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

        unread = (row.get("unread") or "").strip()
        if unread and unread != "1":
            bad_unread.append((row, unread))

        added_at = (row.get("added_at") or "").strip()
        if added_at and parse_ymd_date(added_at) is None:
            bad_added_dates.append((row, added_at))

        code = (row.get("code") or "").strip()
        file_rel = code_to_rel_pdf_path(code)
        if code and not (top / file_rel).exists():
            missing_files.append((row, file_rel))

    issues = 0
    if missing_required:
        issues += 1
        print(f"Missing required fields: {len(missing_required)}")
        for row, fields in missing_required[:20]:
            print(f"  - {row.get('code', '')} :: {', '.join(fields)}")
    if bad_years:
        issues += 1
        print(f"Bad year format: {len(bad_years)}")
        for row, year in bad_years[:20]:
            print(f"  - {row.get('code', '')} :: {year}")
    if bad_dois:
        issues += 1
        print(f"Bad DOI format: {len(bad_dois)}")
        for row, doi in bad_dois[:20]:
            print(f"  - {row.get('code', '')} :: {doi}")
    if bad_unread:
        issues += 1
        print(f"Bad unread format: {len(bad_unread)}")
        for row, unread in bad_unread[:20]:
            print(f"  - {row.get('code', '')} :: {unread}")
    if bad_added_dates:
        issues += 1
        print(f"Bad added_at format: {len(bad_added_dates)}")
        for row, added_at in bad_added_dates[:20]:
            print(f"  - {row.get('code', '')} :: {added_at}")
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


def parse_cli_ymd_date(value: str, flag: str, parser) -> date:
    parsed = parse_ymd_date(value)
    if parsed is None:
        parser.error(f"{flag} must be in YYYY-MM-DD format")
    return parsed


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
    find.add_argument("--added-from", help="Filter by added_at >= YYYY-MM-DD")
    find.add_argument("--added-to", help="Filter by added_at <= YYYY-MM-DD")
    find.add_argument("--sort-added", choices=["asc", "desc"], help="Sort by added_at")
    find.add_argument("--unread-only", action="store_true", help="Only include unread entries")

    save = sub.add_parser("save-collection", help="Save filtered results under a name")
    save.add_argument("--name", required=True)
    save.add_argument("--from-year", type=int)
    save.add_argument("--to-year", type=int)
    save.add_argument("--journal")
    save.add_argument("--keyword")
    save.add_argument("--my-keyword")
    save.add_argument("--added-from", help="Filter by added_at >= YYYY-MM-DD")
    save.add_argument("--added-to", help="Filter by added_at <= YYYY-MM-DD")
    save.add_argument("--sort-added", choices=["asc", "desc"], help="Sort by added_at")
    save.add_argument("--unread-only", action="store_true", help="Only include unread entries")

    list_c = sub.add_parser("list-collections", help="List saved collections")
    tag = sub.add_parser("tag", help="Auto-tag my_keywords using config.json")
    tag.add_argument("--force", action="store_true", help="Overwrite existing my_keywords")

    verify = sub.add_parser("verify", help="Check metadata integrity")
    abstracts = sub.add_parser("abstracts", help="Build or refresh abstracts metadata")
    abstracts.add_argument(
        "--from-pdfs",
        "--scan",
        dest="from_pdfs",
        action="store_true",
        help="Extract abstract text from PDFs via pdftotext",
    )
    abstracts.add_argument(
        "--force",
        action="store_true",
        help="Regenerate all abstracts even when already present",
    )
    cleanup = sub.add_parser("cleanup", help="Normalize titles in metadata")
    cleanup.add_argument("--rename", action="store_true", help="Rename files and codes to match")
    cleanup.add_argument(
        "--from-pdfs",
        action="store_true",
        help="Refresh weak titles from first-page PDF text",
    )
    cleanup.add_argument(
        "--force-titles",
        action="store_true",
        help="Refresh titles from PDFs even if current title looks valid",
    )
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
    export.add_argument("--added-from", help="Filter by added_at >= YYYY-MM-DD")
    export.add_argument("--added-to", help="Filter by added_at <= YYYY-MM-DD")
    export.add_argument("--sort-added", choices=["asc", "desc"], help="Sort by added_at")
    export.add_argument("--unread-only", action="store_true", help="Only include unread entries")

    args = parser.parse_args()

    if args.command == "scan":
        scan_pdfs(dry_run=args.dry_run)
        return
    if args.command == "abstracts":
        rebuild_abstracts(from_pdfs=args.from_pdfs, force=args.force)
        return

    rows = load_rows()

    added_from = None
    added_to = None
    if hasattr(args, "added_from") and args.added_from:
        added_from = parse_cli_ymd_date(args.added_from, "--added-from", parser)
    if hasattr(args, "added_to") and args.added_to:
        added_to = parse_cli_ymd_date(args.added_to, "--added-to", parser)
    if added_from and added_to and added_from > added_to:
        parser.error("--added-from cannot be after --added-to")

    if args.command == "find":
        filtered = filter_rows(
            rows,
            year_from=args.from_year,
            year_to=args.to_year,
            journal=args.journal,
            keyword=args.keyword,
            my_keyword=args.my_keyword,
            added_from=added_from,
            added_to=added_to,
            unread_only=args.unread_only,
        )
        if args.sort_added:
            filtered = sort_rows_by_added(filtered, descending=args.sort_added == "desc")
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
            added_from=added_from,
            added_to=added_to,
            unread_only=args.unread_only,
        )
        if args.sort_added:
            filtered = sort_rows_by_added(filtered, descending=args.sort_added == "desc")
        data = load_collections()
        data[args.name] = {
            "codes": [row.get("code", "") for row in filtered if row.get("code")],
            "filters": {
                "from_year": args.from_year,
                "to_year": args.to_year,
                "journal": args.journal,
                "keyword": args.keyword,
                "my_keyword": args.my_keyword,
                "added_from": args.added_from,
                "added_to": args.added_to,
                "sort_added": args.sort_added,
                "unread_only": args.unread_only,
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
            path = row_pdf_path(row)
            if not path.exists():
                continue
            text = run_pdftotext_full(path)
            basis = "\n".join(
                [row.get("title", ""), row.get("keywords", ""), text]
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
        cleanup_titles(
            rename_files=args.rename,
            dry_run=args.dry_run,
            from_pdfs=args.from_pdfs,
            force_titles=args.force_titles,
        )
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
            added_from=added_from,
            added_to=added_to,
            unread_only=args.unread_only,
        )
        if args.sort_added:
            filtered = sort_rows_by_added(filtered, descending=args.sort_added == "desc")
        export_metadata(filtered, args.format, args.output, pretty=args.pretty)
        return


if __name__ == "__main__":
    main()
