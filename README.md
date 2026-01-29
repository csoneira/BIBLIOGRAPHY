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

## Metadata (single source of truth)

`METADATA/metadata.csv` is the single source of truth for your bibliography. The scanner fills what it can from PDFs; you complete the rest.

### Fields

- `code`: bibliography code, matches filename without extension.
- `file`: relative path to the PDF.
- `type`: article | preprint | thesis | poster | book | slides | proceedings (edit as needed).
- `title`: paper title.
- `journal`: journal or venue.
- `year`: 4-digit year.
- `doi`: DOI string.
- `author`: author list.
- `keywords`: keywords from the paper or your tags.
- `my_keywords`: your project- or topic-specific tags.
- `star`: set to `1` when starred in the viewer.
- `added_at`: date added to the bibliography (YYYY-MM-DD).
- `abstract`: full abstract text.
- `notes`: any extra notes (optional).

### Tips

- Fill `my_keywords` with project names to group related work.
- Use consistent separators (comma or semicolon) in keyword fields.
- If a file is renamed or moved by `CODE/bib.py`, its `code` and `file` are updated automatically.
- Personal tags can be suggested from `CONFIGS/config.json` by running `python3 CODE/bib.py tag`.

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

## Desktop launcher

The repo ships a launcher in `BIBLIOGRAPHY.desktop`. To register it:

```
cp /home/csoneira/BIBLIOGRAPHY/BIBLIOGRAPHY.desktop ~/.local/share/applications/
```
