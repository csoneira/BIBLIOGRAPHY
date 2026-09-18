import csv
import importlib.util
import json
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
                    "annotated": True,
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
            self.assertEqual(first["annotated"], "1")
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

    def test_allows_year_only_publication_date(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            server.METADATA_FILE = Path(tmp_dir) / "METADATA" / "metadata.csv"
            row = server.create_metadata_entry(
                {"title": "Year-only Crossref Paper", "publication_date": "2024"}
            )
            self.assertEqual(row["publication_date"], "2024")
            self.assertEqual(row["year"], "2024")

    def test_migrates_missing_metadata_columns_without_losing_values(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            server.METADATA_FILE = root / "METADATA" / "metadata.csv"
            server.METADATA_FILE.parent.mkdir(parents=True)
            server.METADATA_FILE.write_text(
                "code,type,title\nold,article,Preserved title\n", encoding="utf-8"
            )
            rows = server.load_metadata_rows()
            self.assertEqual(rows[0]["title"], "Preserved title")
            self.assertEqual(rows[0]["annotated"], "")
            with server.METADATA_FILE.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(next(csv.reader(handle)), server.METADATA_FIELDS)
            backups = root / "METADATA" / "backups" / "schema_migrations"
            self.assertEqual(len(list(backups.glob("metadata-before-*.csv"))), 1)

    def test_refuses_unknown_metadata_columns(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            server.METADATA_FILE = Path(tmp_dir) / "metadata.csv"
            server.METADATA_FILE.write_text(
                "code,type,title,future_field\none,article,One,keep me\n", encoding="utf-8"
            )
            with self.assertRaises(RuntimeError):
                server.load_metadata_rows()

    def test_normalizes_latex_accents_before_saving(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            server.METADATA_FILE = Path(tmp_dir) / "METADATA" / "metadata.csv"
            row = server.create_metadata_entry(
                {
                    "title": r"Regulamento de matr\'icula",
                    "author": r"Jos\'e Garc\'ia",
                    "type": "book",
                }
            )
            self.assertEqual(row["title"], "Regulamento de matrícula")
            self.assertEqual(row["author"], "José García")
            self.assertEqual(row["code"], "undated_book_regulamento_de_matricula")

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

    def test_general_edit_does_not_erase_annotated_status(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            server.METADATA_FILE = Path(tmp_dir) / "METADATA" / "metadata.csv"
            row = server.create_metadata_entry(
                {"title": "Annotated paper", "type": "article", "annotated": True}
            )
            updated = server.update_metadata_entry(
                {**row, "title": "Corrected annotated paper", "annotated": False}
            )
            self.assertEqual(updated["annotated"], "1")

    def test_manage_my_keywords_renames_merges_and_deletes(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            server.ROOT = root
            server.METADATA_FILE = root / "METADATA" / "metadata.csv"
            config_file = root / "CONFIGS" / "config.json"
            config_file.parent.mkdir(parents=True)
            config_file.write_text(
                '{"my_keywords": ['
                '{"tag": "rpc", "terms": ["resistive plate chamber"]},'
                '{"tag": "detectors", "terms": ["instrumentation"]}'
                ']}',
                encoding="utf-8",
            )
            server.create_metadata_entry(
                {"title": "One", "type": "article", "my_keywords": "rpc, detectors"}
            )
            server.create_metadata_entry(
                {"title": "Two", "type": "article", "my_keywords": "RPC; cosmic-rays"}
            )

            self.assertEqual(server.manage_my_keyword("merge", "rpc", "detectors"), 2)
            rows = server.load_metadata_rows()
            self.assertEqual(rows[0]["my_keywords"], "detectors")
            self.assertEqual(rows[1]["my_keywords"], "detectors, cosmic-rays")
            config = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual([item["tag"] for item in config["my_keywords"]], ["detectors"])
            self.assertEqual(
                config["my_keywords"][0]["terms"],
                ["instrumentation", "resistive plate chamber"],
            )

            self.assertEqual(server.manage_my_keyword("delete", "detectors"), 2)
            self.assertEqual(server.load_metadata_rows()[0]["my_keywords"], "")
            self.assertEqual(
                json.loads(config_file.read_text(encoding="utf-8"))["my_keywords"], []
            )

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
            config_file = root / "CONFIGS" / "config.json"
            config_file.parent.mkdir(parents=True)
            config_file.write_text('{"my_keywords": [{"tag": "original"}]}', encoding="utf-8")
            server.create_change_snapshot("test edit")
            server.update_metadata_entry({**original, "title": "Changed"})
            config_file.write_text('{"my_keywords": []}', encoding="utf-8")
            history = server.change_history()
            self.assertEqual(history[0]["action"], "test edit")
            self.assertEqual(history[0]["status"], "applied")
            self.assertTrue(history[0]["undoable"])
            result = server.undo_last_change()
            self.assertEqual(result["action"], "test edit")
            self.assertEqual(server.load_metadata_rows()[0]["title"], "Original")
            self.assertEqual(
                json.loads(config_file.read_text(encoding="utf-8"))["my_keywords"][0]["tag"],
                "original",
            )
            history = server.change_history()
            self.assertEqual(history[0]["status"], "undone")
            self.assertFalse(history[0]["undoable"])

    def test_library_checkpoint_copies_catalog_files(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            server.ROOT = root
            server.METADATA_FILE = root / "METADATA" / "metadata.csv"
            server.ABSTRACTS_FILE = root / "METADATA" / "abstracts.csv"
            server.SAVED_LISTS_DIR = root / "SAVED_LISTS"
            server.CHECKPOINT_BACKUP_DIR = root / "METADATA" / "backups" / "checkpoints"
            server.create_metadata_entry({"title": "Checkpoint paper", "type": "article"})
            server.ABSTRACTS_FILE.write_text("code,abstract\n", encoding="utf-8")
            server.SAVED_LISTS_DIR.mkdir()
            (server.SAVED_LISTS_DIR / "Mine.json").write_text("{}\n", encoding="utf-8")

            result = server.create_library_checkpoint()
            checkpoint = root / result["path"]
            self.assertTrue((checkpoint / "METADATA" / "metadata.csv").exists())
            self.assertTrue((checkpoint / "METADATA" / "abstracts.csv").exists())
            self.assertTrue((checkpoint / "SAVED_LISTS" / "Mine.json").exists())
            self.assertTrue((checkpoint / "manifest.json").exists())

    def test_change_history_keeps_only_ten_movements(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            server.ROOT = root
            server.METADATA_FILE = root / "METADATA" / "metadata.csv"
            server.ABSTRACTS_FILE = root / "METADATA" / "abstracts.csv"
            server.SAVED_LISTS_DIR = root / "SAVED_LISTS"
            server.CHANGE_BACKUP_DIR = root / "METADATA" / "backups" / "viewer_changes"
            for index in range(12):
                server.create_change_snapshot(f"movement {index}")
            discarded = server.create_change_snapshot("failed movement")
            server.discard_snapshot(discarded)

            history = server.change_history()

            self.assertEqual(len(history), 10)
            self.assertEqual(history[0]["action"], "movement 11")
            self.assertEqual(history[-1]["action"], "movement 2")
            self.assertEqual(len(list(server.CHANGE_BACKUP_DIR.iterdir())), 10)

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

    def test_crossref_and_arxiv_metadata_parsing(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")
        crossref = server.parse_crossref_message(
            {
                "title": ["A <i>useful</i> paper"],
                "author": [{"given": "Ada", "family": "Lovelace"}],
                "container-title": ["Journal"],
                "published-online": {"date-parts": [[2025, 4, 3]]},
                "DOI": "10.1234/example",
                "type": "journal-article",
                "abstract": "<jats:p>An abstract.</jats:p>",
            }
        )
        self.assertEqual(crossref["title"], "A useful paper")
        self.assertEqual(crossref["publication_date"], "2025-04-03")
        self.assertEqual(crossref["type"], "article")

        arxiv = server.parse_arxiv_feed(
            b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"
            xmlns:arxiv="http://arxiv.org/schemas/atom"><entry>
            <id>http://arxiv.org/abs/2401.12345v2</id><title>Example title</title>
            <published>2024-01-20T00:00:00Z</published><summary>Summary text</summary>
            <author><name>First Author</name></author><arxiv:doi>10.1/test</arxiv:doi>
            </entry></feed>'''
        )
        self.assertEqual(arxiv["arxiv"], "2401.12345v2")
        self.assertEqual(arxiv["publication_date"], "2024-01-20")
        self.assertEqual(arxiv["type"], "preprint")

    def test_detects_structured_pdf_annotations(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")
        try:
            from PyPDF2 import PdfWriter
        except ImportError:
            self.skipTest("PyPDF2 is not installed")

        with tempfile.TemporaryDirectory() as tmp_dir:
            plain = Path(tmp_dir) / "plain.pdf"
            annotated = Path(tmp_dir) / "annotated.pdf"
            writer = PdfWriter()
            writer.add_blank_page(100, 100)
            with plain.open("wb") as handle:
                writer.write(handle)
            self.assertFalse(server.pdf_has_annotations(plain))

            writer = PdfWriter()
            writer.add_blank_page(100, 100)
            writer.add_annotation(0, {
                "/Type": "/Annot", "/Subtype": "/Text", "/Rect": [0, 0, 10, 10],
                "/Contents": "A note",
            })
            with annotated.open("wb") as handle:
                writer.write(handle)
            self.assertTrue(server.pdf_has_annotations(annotated))

    def test_rechecks_replaced_pdf_and_promotes_annotated_status(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")
        try:
            from PyPDF2 import PdfWriter
        except ImportError:
            self.skipTest("PyPDF2 is not installed")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "PDFs").mkdir()
            server.ROOT = root
            server.METADATA_FILE = root / "METADATA" / "metadata.csv"
            server.ABSTRACTS_FILE = root / "METADATA" / "abstracts.csv"
            server.SAVED_LISTS_DIR = root / "SAVED_LISTS"
            server.CHANGE_BACKUP_DIR = root / "METADATA" / "backups" / "viewer_changes"
            server._ANNOTATION_SCAN_CACHE = {}
            row = server.create_metadata_entry({"title": "Replace me", "type": "article"})
            pdf = root / "PDFs" / f"{row['code']}.pdf"

            writer = PdfWriter()
            writer.add_blank_page(100, 100)
            with pdf.open("wb") as handle:
                writer.write(handle)
            first = server.reconcile_local_pdf_annotations()
            self.assertEqual(first["updated"], 0)

            writer = PdfWriter()
            writer.add_blank_page(100, 100)
            writer.add_annotation(0, {
                "/Type": "/Annot", "/Subtype": "/Highlight", "/Rect": [0, 0, 10, 10],
                "/Contents": "new highlight",
            })
            with pdf.open("wb") as handle:
                writer.write(handle)
            second = server.reconcile_local_pdf_annotations()
            self.assertEqual(second["updated"], 1)
            self.assertEqual(server.load_metadata_rows()[0]["annotated"], "1")

    def test_parses_multiple_bibtex_and_ris_records(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")

        bibtex = server.parse_citation_records(
            """@article{one, title={First {RPC} paper}, author={Ada A and Bob B},
            doi={10.1234/one}, year={2024}, journal={Detector Journal},
            abstract={Citation-only abstract}}
            @book{two, title={Second reference}, author={Carol C}, year={2020}}"""
        )
        self.assertEqual(len(bibtex), 2)
        self.assertEqual(bibtex[0]["title"], "First RPC paper")
        self.assertEqual(bibtex[0]["author"], "Ada A; Bob B")
        self.assertEqual(bibtex[0]["abstract"], "Citation-only abstract")
        self.assertEqual(bibtex[1]["type"], "book")

        accents = server.parse_citation_records(
            r"""@book{accented,
            title={Regulamento de matr\'icula e informa\c{c}\~ao},
            author={Jos\'e Garc\'ia and Fran\c{c}ois M\"uller}}"""
        )[0]
        self.assertEqual(accents["title"], "Regulamento de matrícula e informação")
        self.assertEqual(accents["author"], "José García; François Müller")

        ris = server.parse_citation_records(
            """TY  - JOUR
TI  - A RIS article
AU  - First Author
AU  - Second Author
DO  - https://doi.org/10.5678/ris
PY  - 2023/05/02
AB  - Preserved abstract
ER  -
TY  - RPRT
TI  - A report
ER  -"""
        )
        self.assertEqual(len(ris), 2)
        self.assertEqual(ris[0]["doi"], "10.5678/ris")
        self.assertEqual(ris[0]["publication_date"], "2023-05-02")
        self.assertEqual(ris[1]["type"], "report")

    def test_merge_entries_combines_metadata_pdf_and_undoes(self):
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
            server._ABSTRACT_CACHE = {"mtime_ns": None, "data": {}}
            source = server.create_metadata_entry(
                {"title": "Duplicate", "type": "article", "keywords": "detector", "notes": "source note"}
            )
            target = server.create_metadata_entry(
                {"title": "Preferred", "type": "article", "keywords": "physics"}
            )
            source_pdf = root / "PDFs" / f"{source['code']}.pdf"
            source_pdf.write_bytes(b"%PDF-source")
            server.set_abstract(source["code"], "Source abstract")
            snapshot = server.create_change_snapshot("merge duplicate entries")
            server.merge_metadata_entries(source["code"], target["code"], snapshot)

            rows = server.load_metadata_rows()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["keywords"], "physics; detector")
            self.assertIn("source note", rows[0]["notes"])
            self.assertTrue((root / "PDFs" / f"{target['code']}.pdf").exists())
            self.assertEqual(server.load_abstracts_map()[target["code"]], "Source abstract")

            server.undo_last_change()
            self.assertEqual(len(server.load_metadata_rows()), 2)
            self.assertTrue(source_pdf.exists())

    def test_saved_filters_can_be_renamed_deleted_and_undone(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            server.ROOT = root
            server.METADATA_FILE = root / "METADATA" / "metadata.csv"
            server.ABSTRACTS_FILE = root / "METADATA" / "abstracts.csv"
            server.SAVED_LISTS_DIR = root / "SAVED_LISTS"
            server.CHANGE_BACKUP_DIR = root / "METADATA" / "backups" / "viewer_changes"
            server.SAVED_LISTS_DIR.mkdir()
            original = server.SAVED_LISTS_DIR / "Books.json"
            original.write_text(
                '{"name":"Books","filters":{"types":["book"]},"codes":[],"dynamic":true}',
                encoding="utf-8",
            )

            server.create_change_snapshot("manage saved filter")
            renamed = server.manage_saved_filter("rename", "Books.json", "Reference books")
            self.assertEqual(renamed["filename"], "Reference books.json")
            self.assertFalse(original.exists())
            self.assertTrue((server.SAVED_LISTS_DIR / "Reference books.json").exists())
            server.undo_last_change()
            self.assertTrue(original.exists())

            server.create_change_snapshot("manage saved filter")
            server.manage_saved_filter("delete", "Books.json")
            self.assertFalse(original.exists())
            server.undo_last_change()
            self.assertTrue(original.exists())

    def test_wallpaper_image_validation(self):
        repo_root = Path(__file__).resolve().parents[1]
        server = load_server(repo_root / "CODE" / "viewer_server.py")
        self.assertEqual(server.detect_image_extension(b"\xff\xd8\xfftest"), ".jpg")
        self.assertEqual(server.detect_image_extension(b"\x89PNG\r\n\x1a\ntest"), ".png")
        self.assertEqual(server.detect_image_extension(b"RIFF1234WEBPtest"), ".webp")
        self.assertEqual(server.safe_wallpaper_stem("My Nice Picture.PNG"), "my_nice_picture")
        with self.assertRaises(ValueError):
            server.detect_image_extension(b"not-an-image")


if __name__ == "__main__":
    unittest.main()
