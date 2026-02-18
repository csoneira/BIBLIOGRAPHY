import csv
import importlib.util
import re
import unittest
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

        doi_prefix = re.compile(r"^https?://(dx\.)?doi\.org/", re.IGNORECASE)
        doi_prefix_alt = re.compile(r"^doi:\s*", re.IGNORECASE)

        with metadata_path.open(newline="") as handle:
            rows = csv.DictReader(handle)
            for row in rows:
                year = (row.get("year") or "").strip()
                if year:
                    self.assertRegex(year, r"^\d{4}$")

                doi = (row.get("doi") or "").strip()
                if doi:
                    normalized = doi_prefix_alt.sub("", doi_prefix.sub("", doi))
                    self.assertTrue(bib.DOI_FULL_RE.match(normalized))

                file_val = (row.get("file") or "").strip()
                if file_val:
                    self.assertTrue(file_val.lower().endswith(".pdf"))

                star = (row.get("star") or "").strip()
                if star:
                    self.assertIn(star, {"1"})

                unread = (row.get("unread") or "").strip()
                if unread:
                    self.assertIn(unread, {"1"})

                added_at = (row.get("added_at") or "").strip()
                if added_at:
                    self.assertRegex(added_at, r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
