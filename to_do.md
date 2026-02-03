# TODO

- [x] Replace deprecated `datetime.utcnow()` calls in `CODE/bib.py` with timezone-aware UTC.
- [x] Add a simple integrity check command or script (e.g., verify PDFs <-> metadata rows, missing files, bad titles).
- [x] Add a small regression test for `CODE/bib.py scan` (rename + metadata update).
- [x] Review and refine `CONFIGS/config.json` keyword terms to reduce false-positive tagging.
- [x] Decide whether to keep `METADATA/metadata.csv` changes in this working tree and commit them.

# Additional tasks

- [x] Add a `make verify` or `scripts/verify.sh` shortcut for `python3 CODE/bib.py verify`.
- [x] Add `python3 -m unittest` to a simple CI workflow (GitHub Actions) to run on pushes.
- [x] Add a `CODE/bib.py cleanup` command to normalize titles (fix hyphenation, OCR artifacts).
- [x] Add a `CODE/bib.py dedupe` command to detect duplicate titles/DOIs across metadata.
- [x] Add a `CODE/bib.py import-bibtex` helper to ingest metadata from a `.bib` file.
- [x] Add `CODE/bib.py validate` to check required fields, year format, DOI format, and missing files.
- [x] Add `CODE/bib.py stats` to summarize counts by year/type/tag and list most-missing fields.
- [x] Add `CODE/bib.py export` to write filtered results to JSON/CSV for sharing or analysis.
- [x] Add a lightweight metadata schema test (CSV headers/order + basic field constraints) in `tests/`.
- [x] Add a `scripts/backup_metadata.sh` to timestamp-copy `METADATA/metadata.csv` and `collections.json`.
- [ ] Add `CODE/bib.py normalize` to standardize DOI casing/prefixes, trim whitespace, and normalize author separators.
- [ ] Add `CODE/bib.py find --missing FIELD` and `--has FIELD` to surface incomplete entries.
- [ ] Add `CODE/bib.py export --format bibtex|csljson` for sharing with Zotero/Overleaf.
- [ ] Add `CODE/bib.py import-ris` or `import-csljson` to complement BibTeX import.
- [ ] Add a `scripts/format_metadata.py` to sort rows, enforce header order, and keep separators consistent (wire into CI).
- [ ] Add VIEWER filters for missing fields and a "needs review" toggle.
- [ ] Add persistent viewer filters in the URL for shareable views.
- [ ] Add keyboard navigation (j/k) and open-PDF-in-new-tab in VIEWER.
- [ ] Add a text cache for `pdftotext` output to avoid reprocessing unchanged PDFs.
- [ ] Add tests for `cleanup`, `dedupe`, and `import-bibtex`.
