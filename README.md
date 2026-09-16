# Bibliography Repository

Local, git-friendly bibliography management with one canonical identifier per paper.

## Canonical Model

- `METADATA/metadata.csv` is the primary table.
- `code` is the canonical ID.
- PDF location is always derived, never stored: `PDFs/{code}.pdf`.
- `metadata.csv` has no `file` column.
- `pdf_hosts` records the computer or computers known to store the PDF, separated by semicolons.
- `pdf_sha256` records the PDF content checksum so copies can be verified across computers.
- `code` and PDF filename stem must match exactly.
- Codes/filenames are underscore-only slugs (`a_z_0_9_`), never `-`.
- Abstracts live in sidecar `METADATA/abstracts.csv` with exactly:

```csv
code,abstract
```

## Essential Files

- `CODE/bib.py`: CLI for scan/cleanup/abstracts plus find/export/collections, tagging, BibTeX import, and integrity checks.
- `CODE/viewer_server.py`: local viewer service for searching and safely editing the catalog.
- `VIEWER/viewer.html`, `VIEWER/viewer.js`: browser UI.
- `METADATA/metadata.csv`: curated bibliography metadata.
- `METADATA/abstracts.csv`: curated abstracts.
- `scripts/verify.sh`: full integrity gate.
- `scripts/backup_metadata.sh`: timestamped metadata backups.

## Minimal Workflow

1. Add PDFs to `PDFs/`.
2. Build initial metadata rows:

```bash
python3 CODE/bib.py scan
```

3. Curate titles/fields in `METADATA/metadata.csv`.
4. Sync codes and filenames from curated titles:

```bash
python3 CODE/bib.py cleanup --rename
```

5. Build/refresh abstracts:

```bash
python3 CODE/bib.py abstracts
```

6. If you need extraction from PDF text:

```bash
python3 CODE/bib.py abstracts --from-pdfs
```

7. Validate before commit:

```bash
scripts/verify.sh
```

8. Open the viewer server:

```bash
python3 CODE/viewer_server.py
```

Or launch from the desktop helper:

```bash
LAUNCHER/launch_viewer.sh
```

Then open `http://localhost:8000/VIEWER/viewer.html`.

## Working With Only Some PDFs

The metadata catalog is shared through Git, while `PDFs/` is intentionally ignored.
Each computer can therefore hold a different subset of the documents.

On this laptop:

1. Put new documents in `PDFs/`.
2. Run `python3 CODE/bib.py scan`. Existing catalog rows are preserved even when
   their PDFs are absent; new local PDFs are added to the catalog. Scanning also
   adds the current computer's hostname to `pdf_hosts` for every local PDF.
3. Curate the new rows, run `scripts/verify.sh`, then commit and push the metadata.

To update another computer, pull the Git changes there and copy the local PDFs
separately. For example, from this repository you can transfer only files the
destination does not already have:

```bash
rsync -av --ignore-existing PDFs/ USER@OTHER-COMPUTER:/path/to/BIBLIOGRAPHY/PDFs/
```

Normal `verify` and `validate` commands allow catalogued PDFs to be absent. On a
computer that should contain the complete library, use the strict checks:

```bash
python3 CODE/bib.py verify --require-pdfs
python3 CODE/bib.py validate --require-pdfs
```

If PDFs are copied without running a full scan, record the current computer for
all PDFs it actually contains with:

```bash
python3 CODE/bib.py mark-pdf-host
```

Record checksums for local PDFs and report byte-identical duplicates with:

```bash
python3 CODE/bib.py checksums
```

For a one-time migration where every catalogued PDF is known to be on one machine:

```bash
python3 CODE/bib.py mark-pdf-host --host COMPUTER-NAME --all
```

## Viewer Features (Current)

- Filters on publication-date range, one or more catalog-defined types, title, journal, keywords, my_keywords,
  abstract text, and added_at date range.
- Sorting by `added_at` or publication date (`year`), ascending or descending, plus random discovery order.
- `star` and `unread` toggles persisted to `METADATA/metadata.csv`.
- Local, Remote, and Not added badges and filtering. Local availability is checked live;
  Remote means another computer is recorded in `pdf_hosts`, while Not added means no PDF
  has been recorded anywhere yet.
- Dashboard totals for local, remote, not-added, and multi-computer PDFs.
- Edit and recoverable delete controls for every entry.
- Attach a PDF directly to an existing entry; duplicate titles and DOIs are detected.
- One-step Undo backed by automatic snapshots in `METADATA/backups/viewer_changes/`.
- `last_viewed` discovery history, a 30-day exclusion filter, and a one-entry Surprise me action.
- Saved lists restore their stored filter selections.
- Dynamic saved views re-run their filters against the latest catalog, so future matching entries appear automatically.
- Type rename/merge management; merging removes the unused old type from selectors.
- Duplicate-entry merge combines metadata, abstracts, saved-list membership, and PDF files while remaining undoable.
- DOI and arXiv lookup fills the entry form from Crossref or arXiv metadata.
- Per-entry and bulk citation tools copy or download formatted citations, BibTeX, and RIS.
- SHA-256 PDF auditing detects changed files and byte-identical duplicates.
- Per-paper notes editor persisted to `METADATA/metadata.csv` (`notes` column).
- A metadata-only entry form for printed papers or references without a local PDF.
  Its publication month is optional, an exact day can be included when known, and
  document types come from the catalog with an option to add a new type.
- Catalog-management tools (create/edit entries, merge duplicates, and manage types)
  live on the separate `VIEWER/manage.html` page, linked from the main finder.
- Save/load list support via `SAVED_LISTS/*.json`.
- Title click behavior:
  - Normal left-click opens the local `PDFs/{code}.pdf` file with `evince` (fallback `xdg-open`) through server endpoint `/open-pdf`.
  - Modified clicks (Ctrl/Cmd/Shift/Alt/middle-click) keep normal browser link behavior.

## Curation Commands

- Auto-refresh weak titles from first PDF page and then rename:

```bash
python3 CODE/bib.py cleanup --from-pdfs --rename
```

- Force title refresh even if current title looks valid:

```bash
python3 CODE/bib.py cleanup --from-pdfs --force-titles --rename
```

- Rebuild every abstract from PDFs:

```bash
python3 CODE/bib.py abstracts --from-pdfs --force
```

## Integrity Rules

- `metadata.csv` header must match `CODE/bib.py` `FIELDS`.
- `abstracts.csv` header must match `code,abstract`.
- Every local PDF must map to metadata; metadata may refer to a PDF stored on another computer.
- Every abstract code must exist in metadata.
- `year` is `YYYY` when present.
- `added_at` is `YYYY-MM-DD` when present.
- `star`/`unread` are empty or `1`.
- `notes` is optional free text.

## Scripts

- `scripts/verify.sh` runs:
  - `python3 CODE/bib.py verify`
  - `python3 CODE/bib.py validate`
  - `python3 -m unittest discover -s tests`
- `scripts/backup_metadata.sh` snapshots `metadata.csv`, `abstracts.csv`, and `collections.json` into `METADATA/backups/`.

## Optional

- `python3 CODE/bib.py find ...`
- `python3 CODE/bib.py save-collection ...`
- `python3 CODE/bib.py list-collections`
- `python3 CODE/bib.py export ...`
- `python3 CODE/bib.py tag [--force]`
- `python3 CODE/bib.py import-bibtex PATH [--force]`
- `python3 CODE/bib.py stats`
- `python3 CODE/bib.py dedupe`
