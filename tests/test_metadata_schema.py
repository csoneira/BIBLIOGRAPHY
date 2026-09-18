import csv
import importlib.util
import re
import unittest
from datetime import date
from pathlib import Path


def load_bib(module_path: Path):
    spec = importlib.util.spec_from_file_location("bib", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMetadataSchema(unittest.TestCase):
    def test_metadata_schema(self):
        repo_root = Path(__file__).resolve().parents[1]
        bib_path = repo_root / "CODE" / "bib.py"
        bib = load_bib(bib_path)

        metadata_path = repo_root / "METADATA" / "metadata.csv"
        if not metadata_path.exists():
            self.skipTest("metadata.csv not found")

        with metadata_path.open(newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
        self.assertEqual(header, bib.FIELDS)

        pdf_dir = repo_root / "PDFs"
        local_pdf_codes = {path.stem for path in pdf_dir.glob("*.pdf")}

        metadata_codes = set()
        doi_prefix = re.compile(r"^https?://(dx\.)?doi\.org/", re.IGNORECASE)
        doi_prefix_alt = re.compile(r"^doi:\s*", re.IGNORECASE)

        with metadata_path.open(newline="") as handle:
            rows = csv.DictReader(handle)
            for row in rows:
                code = (row.get("code") or "").strip()
                if code:
                    metadata_codes.add(code)

                year = (row.get("year") or "").strip()
                if year:
                    self.assertRegex(year, r"^\d{4}$")

                publication_date = (row.get("publication_date") or "").strip()
                if publication_date:
                    self.assertRegex(
                        publication_date,
                        r"^\d{4}(?:-(0[1-9]|1[0-2])(?:-(0[1-9]|[12]\d|3[01]))?)?$",
                    )
                    if len(publication_date) == 10:
                        date.fromisoformat(publication_date)
                    self.assertEqual(publication_date[:4], year)

                doi = (row.get("doi") or "").strip()
                if doi:
                    normalized = doi_prefix_alt.sub("", doi_prefix.sub("", doi))
                    self.assertTrue(bib.DOI_FULL_RE.match(normalized))

                if code:
                    pdf_rel = bib.code_to_rel_pdf_path(code)
                    self.assertTrue(pdf_rel.lower().endswith(".pdf"))

                pdf_hosts = (row.get("pdf_hosts") or "").strip()
                if code in local_pdf_codes:
                    self.assertTrue(pdf_hosts, f"local PDF has no recorded host: {code}")

                star = (row.get("star") or "").strip()
                if star:
                    self.assertIn(star, {"1"})

                unread = (row.get("unread") or "").strip()
                if unread:
                    self.assertIn(unread, {"1"})

                annotated = (row.get("annotated") or "").strip()
                if annotated:
                    self.assertIn(annotated, {"1"})

                added_at = (row.get("added_at") or "").strip()
                if added_at:
                    self.assertRegex(added_at, r"^\d{4}-\d{2}-\d{2}$")

                last_viewed = (row.get("last_viewed") or "").strip()
                if last_viewed:
                    self.assertRegex(last_viewed, r"^\d{4}-\d{2}-\d{2}$")

        self.assertTrue(local_pdf_codes.issubset(metadata_codes))

        abstracts_path = repo_root / "METADATA" / "abstracts.csv"
        self.assertTrue(abstracts_path.exists(), "abstracts.csv not found")

        with abstracts_path.open(newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
        self.assertEqual(header, bib.ABSTRACT_FIELDS)

        with abstracts_path.open(newline="") as handle:
            rows = csv.DictReader(handle)
            for row in rows:
                code = (row.get("code") or "").strip()
                self.assertTrue(code, "abstracts.csv has an empty code")
                self.assertIn(code, metadata_codes)


if __name__ == "__main__":
    unittest.main()
