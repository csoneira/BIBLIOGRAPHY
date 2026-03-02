import csv
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


def load_bib(module_path: Path):
    spec = importlib.util.spec_from_file_location("bib", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure_paths(bib, root: Path):
    bib.top = root
    bib.PDF_DIR = root / "PDFs"
    bib.LIB_DIR = bib.PDF_DIR
    bib.METADATA_DIR = root / "METADATA"
    bib.METADATA_FILE = bib.METADATA_DIR / "metadata.csv"
    bib.ABSTRACTS_FILE = bib.METADATA_DIR / "abstracts.csv"
    bib.COLLECTIONS_FILE = bib.METADATA_DIR / "collections.json"
    bib.CONFIG_FILE = root / "CONFIGS" / "config.json"


def write_metadata(path: Path, fields: list, rows: list):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            merged = {field: "" for field in fields}
            merged.update(row)
            writer.writerow(merged)


class TestAbstracts(unittest.TestCase):
    def test_load_save_abstracts_roundtrip(self):
        repo_root = Path(__file__).resolve().parents[1]
        bib = load_bib(repo_root / "CODE" / "bib.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            (tmp_root / "METADATA").mkdir()
            configure_paths(bib, tmp_root)

            bib.save_abstracts({"b_code": "Second abstract", "a_code": "First abstract"})
            loaded = bib.load_abstracts()
            self.assertEqual(
                loaded,
                {"a_code": "First abstract", "b_code": "Second abstract"},
            )

            with bib.ABSTRACTS_FILE.open(newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0], bib.ABSTRACT_FIELDS)
            self.assertEqual(rows[1][0], "a_code")
            self.assertEqual(rows[2][0], "b_code")

    def test_cli_abstracts_preserves_existing_without_force(self):
        repo_root = Path(__file__).resolve().parents[1]
        bib = load_bib(repo_root / "CODE" / "bib.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            (tmp_root / "PDFs").mkdir()
            (tmp_root / "METADATA").mkdir()
            (tmp_root / "CONFIGS").mkdir()
            (tmp_root / "CONFIGS" / "config.json").write_text("{}")
            configure_paths(bib, tmp_root)

            write_metadata(
                bib.METADATA_FILE,
                bib.FIELDS,
                [
                    {"code": "alpha", "title": "Alpha title", "year": "2025"},
                    {
                        "code": "beta",
                        "title": "Beta title",
                        "year": "2024",
                        "notes": "Beta abstract from notes.",
                    },
                ],
            )
            bib.save_abstracts(
                {
                    "alpha": "Existing alpha abstract.",
                    "orphan": "Should be dropped because code is missing in metadata.",
                }
            )

            argv_backup = sys.argv[:]
            try:
                sys.argv = ["bib.py", "abstracts"]
                bib.main()
            finally:
                sys.argv = argv_backup

            abstracts = bib.load_abstracts()
            self.assertEqual(abstracts["alpha"], "Existing alpha abstract.")
            self.assertEqual(abstracts["beta"], "Beta abstract from notes.")
            self.assertNotIn("orphan", abstracts)

    def test_cli_abstracts_from_pdfs_force(self):
        repo_root = Path(__file__).resolve().parents[1]
        bib = load_bib(repo_root / "CODE" / "bib.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            (tmp_root / "PDFs").mkdir()
            (tmp_root / "METADATA").mkdir()
            (tmp_root / "CONFIGS").mkdir()
            (tmp_root / "CONFIGS" / "config.json").write_text("{}")
            configure_paths(bib, tmp_root)

            pdf_path = tmp_root / "PDFs" / "alpha.pdf"
            pdf_path.write_text("dummy")
            write_metadata(
                bib.METADATA_FILE,
                bib.FIELDS,
                [
                    {
                        "code": "alpha",
                        "title": "Alpha title",
                        "year": "2025",
                        "notes": "Old note abstract.",
                    }
                ],
            )
            bib.save_abstracts({"alpha": "Old abstract."})

            original_pdftotext = bib.run_pdftotext_full
            try:
                bib.run_pdftotext_full = (
                    lambda _: "Title line\n\nABSTRACT\nThis is the PDF abstract text.\n\nIntroduction\nBody."
                )
                argv_backup = sys.argv[:]
                try:
                    sys.argv = ["bib.py", "abstracts", "--from-pdfs", "--force"]
                    bib.main()
                finally:
                    sys.argv = argv_backup
            finally:
                bib.run_pdftotext_full = original_pdftotext

            abstracts = bib.load_abstracts()
            self.assertEqual(abstracts["alpha"], "This is the PDF abstract text.")

    def test_verify_integrity_warns_on_header_and_unknown_codes(self):
        repo_root = Path(__file__).resolve().parents[1]
        bib = load_bib(repo_root / "CODE" / "bib.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            (tmp_root / "PDFs").mkdir()
            (tmp_root / "METADATA").mkdir()
            configure_paths(bib, tmp_root)

            (tmp_root / "PDFs" / "alpha.pdf").write_text("dummy")
            write_metadata(
                bib.METADATA_FILE,
                bib.FIELDS,
                [
                    {
                        "code": "alpha",
                        "title": "Alpha title",
                        "year": "2025",
                    }
                ],
            )

            bib.ABSTRACTS_FILE.write_text("code,abstract\norphan,Some orphan abstract.\n")
            output = io.StringIO()
            with redirect_stdout(output):
                issues = bib.verify_integrity()
            self.assertGreaterEqual(issues, 1)
            self.assertIn("Abstract codes not in metadata", output.getvalue())

            bib.ABSTRACTS_FILE.write_text("bad_header,abstract\nalpha,Some text\n")
            output = io.StringIO()
            with redirect_stdout(output):
                issues = bib.verify_integrity()
            self.assertGreaterEqual(issues, 1)
            self.assertIn("Abstracts header mismatch", output.getvalue())

            bib.METADATA_FILE.write_text("bad_header,title\nalpha,Alpha title\n")
            output = io.StringIO()
            with redirect_stdout(output):
                issues = bib.verify_integrity()
            self.assertGreaterEqual(issues, 1)
            self.assertIn("Metadata header mismatch", output.getvalue())


if __name__ == "__main__":
    unittest.main()
