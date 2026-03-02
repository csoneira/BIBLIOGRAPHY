# To Do

- [x] Also it would be super nice to have abstracts saved too, maybe with a dedicated `METADATA/abstracts.csv` with `code,abstract`, so the main `metadata.csv` stays less crowded; and I would like to access abstracts in the HTML viewer as an expand menu.
- [x] Add `python3 CODE/bib.py abstracts` command(s) to create/update `METADATA/abstracts.csv` from existing metadata/PDF text.
- [x] Add viewer server endpoint(s) to read abstracts by `code` and return them fast (without loading full PDFs in the browser).
- [x] In `VIEWER/viewer.js`, add a per-card `Show abstract` / `Hide abstract` expandable section.
- [x] Add optional abstract text filter in the viewer (simple contains search), using the separate abstracts data source.
- [x] Include `METADATA/abstracts.csv` in `scripts/backup_metadata.sh` and in integrity checks/tests.

## General repo improvements

- [ ] Add a small `scripts/restart_viewer.sh` (or `scripts/viewer_status.sh`) to stop stale `viewer_server.py` processes and start a fresh one cleanly.
- [ ] Add `python3 CODE/bib.py migrate-metadata` to safely add new columns (like `unread`) without manual CSV edits.
- [ ] Add tests for viewer server toggle endpoints (`/toggle-star`, `/toggle-unread`) so metadata write behavior is covered.
- [ ] When loading a saved list in the viewer, optionally re-apply and show its stored filters (not only the stored codes).
- [x] Add a simple `scripts/verify.sh` check to ensure metadata header order matches `bib.py` fields before committing.

## Completed curation pass

- [x] Remove `file` as a metadata column and use `code` as the single source of truth for `PDFs/{code}.pdf`.
- [x] Rename mismatched PDFs/codes to underscore-only canonical slugs derived from curated titles.
- [x] Rebuild `METADATA/abstracts.csv` after code renames and fill remaining empty abstracts.
