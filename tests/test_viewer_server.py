import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


def load_server(module_path: Path):
    spec = importlib.util.spec_from_file_location("viewer_server", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCreateMetadataEntry(unittest.TestCase):
    def test_creates_metadata_only_entry_with_unique_code(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            server.METADATA_FILE = Path(tmp_dir) / "METADATA" / "metadata.csv"
            first = server.create_metadata_entry(
                {
                    "title": "A Printed Paper",
                    "publication_date": "2024-07-16",
                    "type": "article",
                    "author": "Example Author",
                    "unread": True,
                }
            )
            second = server.create_metadata_entry(
                {
                    "title": "A Printed Paper",
                    "publication_date": "2024-07-16",
                    "type": "article",
                    "allow_duplicate": True,
                }
            )

            self.assertEqual(first["code"], "2024_article_a_printed_paper")
            self.assertEqual(second["code"], "2024_article_a_printed_paper_2")
            self.assertEqual(first["publication_date"], "2024-07-16")
            self.assertEqual(first["year"], "2024")
            self.assertEqual(first["pdf_hosts"], "")
            self.assertEqual(first["unread"], "1")
            with server.METADATA_FILE.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)

    def test_rejects_missing_title_and_invalid_year(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            server.METADATA_FILE = Path(tmp_dir) / "METADATA" / "metadata.csv"
            with self.assertRaises(ValueError):
                server.create_metadata_entry({"title": "", "publication_date": "2024-07"})
            with self.assertRaises(ValueError):
                server.create_metadata_entry({"title": "Paper", "publication_date": "2024-13"})
            with self.assertRaises(ValueError):
                server.create_metadata_entry({"title": "Paper", "publication_date": "2024-02-30"})

    def test_allows_entry_without_publication_date(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            server.METADATA_FILE = Path(tmp_dir) / "METADATA" / "metadata.csv"
            row = server.create_metadata_entry({"title": "Undated Print", "type": "notes"})
            self.assertEqual(row["code"], "undated_notes_undated_print")
            self.assertEqual(row["publication_date"], "")
            self.assertEqual(row["year"], "")

    def test_duplicate_detection_editing_locations_and_types(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            server.METADATA_FILE = Path(tmp_dir) / "METADATA" / "metadata.csv"
            first = server.create_metadata_entry(
                {"title": "Unique Paper", "publication_date": "2025-03", "type": "article"}
            )
            with self.assertRaises(server.DuplicateEntryError):
                server.create_metadata_entry(
                    {"title": "Unique Paper", "publication_date": "2025-03", "type": "article"}
                )

            updated = server.update_metadata_entry(
                {
                    **first,
                    "title": "Corrected Paper",
                    "type": "report",
                    "pdf_hosts": "naranjito; manzanita",
                }
            )
            self.assertEqual(updated["title"], "Corrected Paper")
            self.assertEqual(updated["pdf_hosts"], "naranjito; manzanita")
            self.assertEqual(server.manage_type("merge", "report", "article"), 1)
            rows = server.load_metadata_rows()
            self.assertEqual(rows[0]["type"], "article")

    def test_snapshot_undo_restores_metadata(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            server.ROOT = root
            server.METADATA_FILE = root / "METADATA" / "metadata.csv"
            server.ABSTRACTS_FILE = root / "METADATA" / "abstracts.csv"
            server.SAVED_LISTS_DIR = root / "SAVED_LISTS"
            server.CHANGE_BACKUP_DIR = root / "METADATA" / "backups" / "viewer_changes"
            original = server.create_metadata_entry(
                {"title": "Original", "publication_date": "2024-01", "type": "article"}
            )
            server.create_change_snapshot("test edit")
            server.update_metadata_entry({**original, "title": "Changed"})
            result = server.undo_last_change()
            self.assertEqual(result["action"], "test edit")
            self.assertEqual(server.load_metadata_rows()[0]["title"], "Original")

    def test_undo_reverses_created_and_trashed_pdf_moves(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "PDFs").mkdir()
            server.ROOT = root
            server.METADATA_FILE = root / "METADATA" / "metadata.csv"
            server.ABSTRACTS_FILE = root / "METADATA" / "abstracts.csv"
            server.SAVED_LISTS_DIR = root / "SAVED_LISTS"
            server.CHANGE_BACKUP_DIR = root / "METADATA" / "backups" / "viewer_changes"
            server.create_metadata_entry({"title": "Paper", "type": "article"})

            attached = root / "PDFs" / "undated_article_paper.pdf"
            attach_snapshot = server.create_change_snapshot("attach PDF")
            attached.write_bytes(b"%PDF-test")
            server.update_snapshot_manifest(
                attach_snapshot, created_pdf="PDFs/undated_article_paper.pdf"
            )
            server.undo_last_change()
            self.assertFalse(attached.exists())
            self.assertTrue(any((root / "PDFs" / ".trash").iterdir()))

            attached.write_bytes(b"%PDF-test")
            delete_snapshot = server.create_change_snapshot("delete entry")
            trash = root / "PDFs" / ".trash" / "deleted.pdf"
            attached.replace(trash)
            server.update_snapshot_manifest(
                delete_snapshot,
                moved_pdf={
                    "from": "PDFs/undated_article_paper.pdf",
                    "to": "PDFs/.trash/deleted.pdf",
                },
            )
            server.undo_last_change()
            self.assertTrue(attached.exists())
            self.assertFalse(trash.exists())


if __name__ == "__main__":
    unittest.main()
