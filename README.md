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

1. Start the viewer server and open **Add**.
2. Stage one or more RIS/BibTeX records, DOI/arXiv identifiers, and optional PDFs.
3. Review each draft page and confirm entries one at a time. Nothing is added before confirmation.
   The browser preserves the draft queue and selected PDFs across refreshes and server restarts.
4. If needed, sync codes and filenames from later title corrections:

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

On this laptop, add new references through the dedicated **Add** page.
The review queue accepts batches of RIS/BibTeX records and identifiers, enriches
them from Crossref/arXiv, and cautiously fills remaining blanks from selected PDFs.
Each draft must be confirmed explicitly. A confirmed PDF is copied into `PDFs/`,
checksummed, and recorded under the current computer's hostname.

`python3 CODE/bib.py scan` is now maintenance-only: it reconciles local PDFs with
entries that already exist and ignores unmatched files instead of creating entries.

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

- Filters on publication-date range, one or more catalog-defined types, title, keywords, my_keywords,
  abstract text, added-at date range, and read-date range.
- Sorting by `added_at` or publication date (`year`), ascending or descending, plus random discovery order.
- `star` and `unread` toggles persisted to `METADATA/metadata.csv`.
- An `annotated` status records PDFs with highlights, comments, ink, or text notes. Structured
  PDF annotations are detected conservatively during PDF inspection/attachment and by an
  automatic local scan every 15 seconds. Replacing a local PDF rechecks it immediately and
  promotes the status when markup is found; flattened markings still require the manual toggle.
- Local, Remote, and Not added badges and filtering. Local availability is checked live;
  Remote means another computer is recorded in `pdf_hosts`, while Not added means no PDF
  has been recorded anywhere yet.
- Dashboard totals for local, remote, and not-added PDFs.
- Edit and recoverable delete controls for every entry.
- Attach a PDF directly to an existing entry; duplicate titles and DOIs are detected.
- One-step Undo backed by automatic snapshots in `METADATA/backups/viewer_changes/`.
- `last_viewed` discovery history with Read from/Read to filters, plus a one-entry Surprise me action.
- Saved Filters restore their conditions into the form for review or modification before they are applied.
- Saved Filters can be renamed or deleted from Options, with both operations covered by Undo last change.
- Type rename/merge management; merging removes the unused old type from selectors.
- Duplicate-entry merge combines metadata, abstracts, and PDF files while remaining undoable.
- A review queue accepts multiple RIS/BibTeX records, DOI/arXiv identifiers, and PDFs;
  DOI metadata enriches matching drafts before each entry is manually confirmed.
- Per-entry citation copying and bulk downloads in formatted citation, BibTeX, and RIS formats.
- SHA-256 PDF auditing detects changed files and byte-identical duplicates.
- Options includes a Library checkpoint panel that shows pending catalog files and Git sync
  state, validates the catalog, creates a recoverable data backup, and displays commit commands.
- Per-paper notes editor persisted to `METADATA/metadata.csv` (`notes` column).
- An entry form that can fill editable metadata from citations, DOI/arXiv identifiers, or a cautious
  PDF scan and optionally copy an uploaded PDF into `PDFs/`; it also supports metadata-only references.
  Its publication month and day are optional (`YYYY`, `YYYY-MM`, or `YYYY-MM-DD`), and
  document types come from the catalog with an option to add a new type.
- Entry creation and editing live on `VIEWER/add.html`; maintenance tools such as
  duplicate merging and type management live on `VIEWER/manage.html`.
- Options includes a fixed-wallpaper selector shared by both pages, adjustable transparency,
  and JPEG/PNG/WebP uploads stored in `VIEWER/wallpapers/custom/`.
- Saved Filter support via `SAVED_LISTS/*.json`.
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

Metadata schema additions are migrated automatically before the viewer reads or writes the
catalog. A timestamped pre-migration copy is retained under `METADATA/backups/schema_migrations/`.
The same migration can be run explicitly with:

```bash
python3 CODE/bib.py migrate-metadata
```

Unknown columns cause the writer to stop instead of silently discarding data from a newer schema.

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
