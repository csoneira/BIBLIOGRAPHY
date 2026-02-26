# Bibliography Repository

Local, git-friendly bibliography management.

- PDFs are stored in `PDFs/` and are intentionally gitignored.
- Metadata is stored as CSV in `METADATA/`.
- All operations are done through `CODE/bib.py` and the lightweight viewer.

## Essential layout

- `CODE/bib.py`: CLI for scan, search, validation, cleanup, export.
- `CODE/viewer_server.py`: local HTTP server for the viewer and toggle endpoints.
- `VIEWER/viewer.html` + `VIEWER/viewer.js`: browser UI.
- `METADATA/metadata.csv`: main bibliography table.
- `METADATA/abstracts.csv`: abstracts sidecar keyed by `code`.
- `scripts/verify.sh`: one-command integrity + tests.
- `scripts/backup_metadata.sh`: timestamped backup of metadata files.

## Dependencies

- Required: `python3`
- Optional but recommended: `pdftotext` (used for text extraction in `scan`, `tag`, and `abstracts --from-pdfs`)
- Optional: `pdfinfo` (improves metadata inference during `scan`)

## How it is supposed to work

1. Put PDFs in `PDFs/`.
2. Run initial scan:

```bash
python3 CODE/bib.py scan
```

3. Edit `METADATA/metadata.csv` to complete or correct fields.
4. Build/update abstracts sidecar:

```bash
python3 CODE/bib.py abstracts
```

5. If you want extraction from PDF text:

```bash
python3 CODE/bib.py abstracts --from-pdfs
```

6. Validate repository state before committing:

```bash
scripts/verify.sh
```

7. Open viewer:

```bash
python3 CODE/viewer_server.py
```

Then open: `http://localhost:8000/VIEWER/viewer.html`

## Data contracts

### `METADATA/metadata.csv`

- Header order must match `CODE/bib.py` constant `FIELDS`.
- `code` must be unique.
- `file` points to a relative PDF path.
- `code` and PDF stem must match exactly.
- Naming convention is underscore-only (`_`); do not use `-` in generated codes or PDF names.
- `year` must be `YYYY` when present.
- `star` and `unread` are empty or `1`.
- `added_at` is `YYYY-MM-DD` when present.

### `METADATA/abstracts.csv`

- Header is exactly:

```csv
code,abstract
```

- `code` must reference an existing metadata row.
- This file is independent from `metadata.csv` by design; `scan` does not modify it.
- `bib.py abstracts` is the explicit maintenance command.

## Core CLI commands

```bash
python3 CODE/bib.py scan
python3 CODE/bib.py abstracts [--from-pdfs|--scan] [--force]
python3 CODE/bib.py find --from-year 2022 --keyword detector
python3 CODE/bib.py verify
python3 CODE/bib.py validate
```

## Viewer behavior

- Reads `metadata.csv` and `abstracts.csv`.
- Supports filtering by title/journal/keywords/my keywords/abstract text/year/date/star/unread.
- Star/unread toggles write back into `METADATA/metadata.csv`.
- Abstract section is per-card expandable (`Show abstract` / `Hide abstract`).
- Viewer saved lists are stored as JSON files in `SAVED_LISTS/`.

Note: CLI collections (`save-collection`, `list-collections`) are separate and stored in `METADATA/collections.json`.

## Maintenance scripts

Run full checks:

```bash
scripts/verify.sh
```

This runs:

1. `python3 CODE/bib.py verify`
2. `python3 CODE/bib.py validate`
3. `python3 -m unittest discover -s tests`

Create timestamped metadata backups:

```bash
scripts/backup_metadata.sh
```

Backups are written to `METADATA/backups/`.

## Keep the repository essential

- Track only canonical metadata files (`metadata.csv`, `abstracts.csv`).
- Use `METADATA/backups/` for backups; generated backup variants are ignored by `.gitignore`.
- Prefer explicit commands (`scan`, `abstracts`, `verify`) over implicit side effects.

## Optional commands

These are available but not required for the core flow:

- `python3 CODE/bib.py tag`
- `python3 CODE/bib.py dedupe`
- `python3 CODE/bib.py cleanup`
- `python3 CODE/bib.py export`
- `python3 CODE/bib.py save-collection`
- `python3 CODE/bib.py list-collections`

## Desktop launcher (optional)

```bash
cp /home/csoneira/WORK/BIBLIOGRAPHY/BIBLIOGRAPHY.desktop ~/.local/share/applications/
chmod +x /home/csoneira/WORK/BIBLIOGRAPHY/LAUNCHER/launch_viewer.sh
```
