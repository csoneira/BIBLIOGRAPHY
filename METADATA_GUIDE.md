# Metadata Guide

`METADATA/metadata.csv` is the single source of truth for your bibliography. The scanner fills what it can from PDFs; you complete the rest.

## Fields

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

## Tips

- Fill `my_keywords` with project names to group related work.
- Use consistent separators (comma or semicolon) in keyword fields.
- If a file is renamed or moved by `CODE/bib.py`, its `code` and `file` are updated automatically.
- Personal tags can be suggested from `CONFIGS/config.json` by running `python3 CODE/bib.py tag`.
