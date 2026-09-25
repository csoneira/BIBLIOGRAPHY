import csv
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_server():
    spec = importlib.util.spec_from_file_location(
        "viewer_server_pdf_archive", REPO_ROOT / "CODE" / "viewer_server.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure_archive(server, root: Path):
    server.ROOT = root
    server.METADATA_FILE = root / "METADATA" / "metadata.csv"
    (root / "METADATA").mkdir(parents=True)
    (root / "library.json").write_text(
        json.dumps({
            "format_version": 1,
            "name": "Archive test",
            "pdf_archive": {
                "backend": "rclone",
                "remote": "gdrive",
                "path": "BIBLIOGRAPHY_PDFS",
            },
        }),
        encoding="utf-8",
    )
    server._ARCHIVE_CACHE.update({"expires_at": 0.0, "codes": set(), "error": None})


class TestPdfArchive(unittest.TestCase):
    def test_lists_only_top_level_pdf_codes(self):
        server = load_server()
        with tempfile.TemporaryDirectory() as tmp_dir:
            configure_archive(server, Path(tmp_dir))
            result = subprocess.CompletedProcess(
                [], 0, stdout="alpha.pdf\nnested/ignored.pdf\nnotes.txt\n", stderr=""
            )
            with patch.object(server.shutil, "which", return_value="/usr/bin/rclone"), patch.object(
                server.subprocess, "run", return_value=result
            ):
                codes, error = server.archived_pdf_codes(force=True)
            self.assertEqual(codes, {"alpha"})
            self.assertIsNone(error)

    def test_downloads_and_checksum_verifies_missing_pdf(self):
        server = load_server()
        content = b"archived pdf bytes"
        checksum = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            configure_archive(server, root)
            with server.METADATA_FILE.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=server.METADATA_FIELDS)
                writer.writeheader()
                writer.writerow({
                    **{field: "" for field in server.METADATA_FIELDS},
                    "code": "alpha",
                    "type": "article",
                    "title": "Alpha",
                    "pdf_sha256": checksum,
                })

            def fake_copy(command, **kwargs):
                self.assertEqual(
                    command[2], "gdrive:BIBLIOGRAPHY_PDFS/alpha.pdf"
                )
                Path(command[3]).write_bytes(content)
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with patch.object(server.shutil, "which", return_value="/usr/bin/rclone"), patch.object(
                server.subprocess, "run", side_effect=fake_copy
            ):
                self.assertTrue(server.fetch_pdf_from_archive("alpha"))

            self.assertEqual((root / "PDFs" / "alpha.pdf").read_bytes(), content)
            self.assertEqual(list((root / "PDFs").glob("*.archive.tmp")), [])

    def test_rejects_archive_checksum_mismatch(self):
        server = load_server()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            configure_archive(server, root)
            with server.METADATA_FILE.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=server.METADATA_FIELDS)
                writer.writeheader()
                writer.writerow({
                    **{field: "" for field in server.METADATA_FIELDS},
                    "code": "alpha",
                    "type": "article",
                    "title": "Alpha",
                    "pdf_sha256": "0" * 64,
                })

            def fake_copy(command, **kwargs):
                Path(command[3]).write_bytes(b"wrong bytes")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with patch.object(server.shutil, "which", return_value="/usr/bin/rclone"), patch.object(
                server.subprocess, "run", side_effect=fake_copy
            ):
                with self.assertRaisesRegex(RuntimeError, "checksum"):
                    server.fetch_pdf_from_archive("alpha")
            self.assertFalse((root / "PDFs" / "alpha.pdf").exists())


if __name__ == "__main__":
    unittest.main()
