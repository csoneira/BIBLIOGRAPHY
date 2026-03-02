import csv
import importlib.util
import tempfile
from pathlib import Path
import unittest


def load_bib(module_path: Path):
    spec = importlib.util.spec_from_file_location("bib", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBibScan(unittest.TestCase):
    def test_scan_renames_and_writes_metadata(self):
        repo_root = Path(__file__).resolve().parents[1]
        bib_path = repo_root / "CODE" / "bib.py"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            (tmp_root / "PDFs").mkdir()
            (tmp_root / "METADATA").mkdir()
            (tmp_root / "CONFIGS").mkdir()
            (tmp_root / "CONFIGS" / "config.json").write_text("{}")

            # Dummy PDF: year in filename ensures deterministic year inference.
            (tmp_root / "PDFs" / "2020_mytest.pdf").write_text("dummy")

            bib = load_bib(bib_path)

            # Patch paths to point at the temp workspace.
            bib.top = tmp_root
            bib.PDF_DIR = tmp_root / "PDFs"
            bib.LIB_DIR = bib.PDF_DIR
            bib.METADATA_DIR = tmp_root / "METADATA"
            bib.METADATA_FILE = bib.METADATA_DIR / "metadata.csv"
            bib.COLLECTIONS_FILE = bib.METADATA_DIR / "collections.json"
            bib.CONFIG_FILE = tmp_root / "CONFIGS" / "config.json"

            bib.scan_pdfs(dry_run=False)

            pdfs = list((tmp_root / "PDFs").glob("*.pdf"))
            self.assertEqual(len(pdfs), 1)
            self.assertEqual(pdfs[0].name, "2020_article_2020_mytest.pdf")

            self.assertTrue(bib.METADATA_FILE.exists())
            with bib.METADATA_FILE.open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["code"], pdfs[0].stem)
            self.assertEqual(row["year"], "2020")
            self.assertEqual(row["type"], "article")
            self.assertEqual(row["unread"], "")
            self.assertRegex(row["added_at"], r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
