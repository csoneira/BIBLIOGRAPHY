import csv
import importlib.util
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch


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

            with patch("socket.gethostname", return_value="test-laptop"):
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
            self.assertEqual(row["pdf_hosts"], "test-laptop")
            self.assertRegex(row["added_at"], r"^\d{4}-\d{2}-\d{2}$")

    def test_scan_preserves_metadata_for_pdfs_not_stored_locally(self):
        repo_root = Path(__file__).resolve().parents[1]
        bib = load_bib(repo_root / "CODE" / "bib.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            (tmp_root / "PDFs").mkdir()
            (tmp_root / "METADATA").mkdir()
            (tmp_root / "CONFIGS").mkdir()
            (tmp_root / "CONFIGS" / "config.json").write_text("{}")

            bib.top = tmp_root
            bib.PDF_DIR = tmp_root / "PDFs"
            bib.LIB_DIR = bib.PDF_DIR
            bib.METADATA_DIR = tmp_root / "METADATA"
            bib.METADATA_FILE = bib.METADATA_DIR / "metadata.csv"
            bib.CONFIG_FILE = tmp_root / "CONFIGS" / "config.json"

            old_row = {field: "" for field in bib.FIELDS}
            old_row.update(
                {
                    "code": "2019_article_remote_only",
                    "type": "article",
                    "title": "Remote only",
                    "year": "2019",
                }
            )
            bib.save_metadata([old_row])
            (tmp_root / "PDFs" / "2025_new_local.pdf").write_text("dummy")

            with patch("socket.gethostname", return_value="manzanita"):
                rows = bib.scan_pdfs(dry_run=False)

            codes = {row["code"] for row in rows}
            self.assertIn("2019_article_remote_only", codes)
            self.assertEqual(len(rows), 2)
            local_row = next(row for row in rows if row["code"] != "2019_article_remote_only")
            self.assertEqual(local_row["pdf_hosts"], "manzanita")

    def test_scan_matches_existing_entry_by_title_instead_of_duplicating(self):
        repo_root = Path(__file__).resolve().parents[1]
        bib = load_bib(repo_root / "CODE" / "bib.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            (tmp_root / "PDFs").mkdir()
            (tmp_root / "METADATA").mkdir()
            (tmp_root / "CONFIGS").mkdir()
            (tmp_root / "CONFIGS" / "config.json").write_text("{}")
            bib.top = tmp_root
            bib.PDF_DIR = tmp_root / "PDFs"
            bib.LIB_DIR = bib.PDF_DIR
            bib.METADATA_DIR = tmp_root / "METADATA"
            bib.METADATA_FILE = bib.METADATA_DIR / "metadata.csv"
            bib.CONFIG_FILE = tmp_root / "CONFIGS" / "config.json"

            row = {field: "" for field in bib.FIELDS}
            row.update(
                {
                    "code": "2020_article_matching_title",
                    "type": "article",
                    "title": "Matching Title",
                    "year": "2020",
                    "pdf_hosts": "naranjito",
                }
            )
            bib.save_metadata([row])
            source = tmp_root / "PDFs" / "unhelpful_name.pdf"
            source.write_text("dummy")

            with patch.object(bib, "extract_title", return_value="Matching Title"), patch(
                "socket.gethostname", return_value="manzanita"
            ):
                rows = bib.scan_pdfs()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["code"], "2020_article_matching_title")
            self.assertEqual(rows[0]["pdf_hosts"], "naranjito; manzanita")
            self.assertTrue((tmp_root / "PDFs" / "2020_article_matching_title.pdf").exists())


if __name__ == "__main__":
    unittest.main()
