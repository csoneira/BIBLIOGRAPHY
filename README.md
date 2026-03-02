# Bibliography Repository

Local, git-friendly bibliography management with one canonical identifier per paper.

## Canonical Model

- `METADATA/metadata.csv` is the primary table.
- `code` is the canonical ID.
- PDF location is always derived, never stored: `PDFs/{code}.pdf`.
- `metadata.csv` has no `file` column.
- `code` and PDF filename stem must match exactly.
- Codes/filenames are underscore-only slugs (`a_z_0_9_`), never `-`.
- Abstracts live in sidecar `METADATA/abstracts.csv` with exactly:

```csv
code,abstract
```

## Essential Files

- `CODE/bib.py`: CLI (scan, cleanup, abstracts, verify, validate).
- `CODE/viewer_server.py`: local server + metadata toggle endpoints.
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

8. Open the viewer:

```bash
python3 CODE/viewer_server.py
```

Then open `http://localhost:8000/VIEWER/viewer.html`.

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
- Every metadata code must map to an existing PDF.
- Every abstract code must exist in metadata.
- `year` is `YYYY` when present.
- `added_at` is `YYYY-MM-DD` when present.
- `star`/`unread` are empty or `1`.

## Scripts

- `scripts/verify.sh` runs:
  - `python3 CODE/bib.py verify`
  - `python3 CODE/bib.py validate`
  - `python3 -m unittest discover -s tests`
- `scripts/backup_metadata.sh` snapshots `metadata.csv`, `abstracts.csv`, and `collections.json` into `METADATA/backups/`.

## Optional

- `python3 CODE/bib.py find ...`
- `python3 CODE/bib.py dedupe`
- `python3 CODE/bib.py export ...`
- `python3 CODE/bib.py save-collection ...`
- `python3 CODE/bib.py list-collections`
