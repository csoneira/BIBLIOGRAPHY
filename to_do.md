# TODO

- [x] Replace deprecated `datetime.utcnow()` calls in `CODE/bib.py` with timezone-aware UTC.
- [x] Add a simple integrity check command or script (e.g., verify PDFs <-> metadata rows, missing files, bad titles).
- [x] Add a small regression test for `CODE/bib.py scan` (rename + metadata update).
- [x] Review and refine `CONFIGS/config.json` keyword terms to reduce false-positive tagging.
- [x] Decide whether to keep `METADATA/metadata.csv` changes in this working tree and commit them.
