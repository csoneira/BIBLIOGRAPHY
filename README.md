# Bibliography Repository

Lightweight, git-friendly bibliography tracker. PDFs stay in `PDFs/` (gitignored), while metadata and tools live in the repo.

## Layout

- `PDFs/`: all PDFs live here.
- `METADATA/metadata.csv`: extracted metadata + your additions.
- `METADATA/collections.json`: saved filters (named lists of bib codes).
- `CODE/bib.py`: scan, rename, and query.
- `CONFIGS/config.json`: personal tag config for `my_keywords`.
- `VIEWER/`: lightweight browser viewer.

## Quick start

1. Add PDFs to `PDFs/`.
2. Run `python3 CODE/bib.py scan` for preliminary naming.
3. Use Codex to read PDFs via `pdftotext` and complete metadata.
4. Optionally run auto-tagging with your personal keywords (see below).

## Find papers

List codes by filters:

```
python3 CODE/bib.py find --from-year 2022 --to-year 2025 --keyword muon
```

Save a named collection:

```
python3 CODE/bib.py save-collection --name "Recent muon detector development" --from-year 2022 --keyword muon
```

List saved collections:

```
python3 CODE/bib.py list-collections
```

## Updating

Add new PDFs to `PDFs/` and rerun:

```
python3 CODE/bib.py scan
```

The script renames PDFs in place using:

```
YYYY_TYPE_NAME.pdf
```

`TYPE` is inferred (article, preprint, thesis, poster, book, slides, proceedings) and can be edited in `METADATA/metadata.csv`.

## Personal keyword tagging

Edit `CONFIGS/config.json` with your personal tags. Then run:

```
python3 CODE/bib.py tag
```

Use `--force` to overwrite existing `my_keywords`.

## Lightweight GUI finder

Serve the repo locally and open the viewer:

```
python3 CODE/viewer_server.py
```

Then visit `http://localhost:8000/VIEWER/viewer.html` and filter on year, journal, keywords, or starred items.

Use the **Save list** button to write a JSON file into `SAVED_LISTS/`.
Click the star next to a title to toggle `star` in `METADATA/metadata.csv`.
