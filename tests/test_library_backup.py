import importlib.util
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_bib():
    spec = importlib.util.spec_from_file_location(
        "bib_library_backup", REPO_ROOT / "CODE" / "bib.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_test_library(bib, root: Path):
    bib.initialize_library(
        root, "Backup test", bib.FIELDS, bib.ABSTRACT_FIELDS
    )
    manifest_path = root / "library.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["metadata_backup"] = {
        "backend": "rclone",
        "remote": "gdrive",
        "path": "BIBLIOGRAPHY_BACKUPS",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (root / "SAVED_LISTS" / "Reading.json").write_text("{}\n", encoding="utf-8")
    (root / "PDFs" / "private.pdf").write_bytes(b"not in metadata backup")
    backups = root / "METADATA" / "backups"
    backups.mkdir()
    (backups / "old.csv").write_text("not recursive\n", encoding="utf-8")


class TestLibraryBackup(unittest.TestCase):
    def test_snapshot_contains_only_expected_library_text_state(self):
        bib = load_bib()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "library"
            create_test_library(bib, root)
            archive_path = Path(tmp_dir) / "snapshot.tar.gz"

            files = bib.create_library_snapshot(root, archive_path)

            self.assertIn("library.json", files)
            self.assertIn("METADATA/metadata.csv", files)
            self.assertIn("METADATA/abstracts.csv", files)
            self.assertIn("SAVED_LISTS/Reading.json", files)
            with tarfile.open(archive_path, "r:gz") as archive:
                members = set(archive.getnames())
            self.assertEqual(members, set(files))
            self.assertFalse(any(name.startswith("PDFs/") for name in members))
            self.assertFalse(any("backups" in name for name in members))

    def test_dry_run_builds_snapshot_without_calling_rclone(self):
        bib = load_bib()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "library"
            create_test_library(bib, root)
            bib.LIBRARY_ROOT = root
            with patch.object(bib.shutil, "which", return_value="/usr/bin/rclone"), patch.object(
                bib.subprocess, "run"
            ) as run:
                result = bib.backup_library(dry_run=True)

            self.assertFalse(result["uploaded"])
            self.assertEqual(result["remote"], "gdrive:BIBLIOGRAPHY_BACKUPS")
            self.assertGreater(result["bytes"], 0)
            self.assertEqual(len(result["sha256"]), 64)
            run.assert_not_called()

    def test_uploads_archive_and_checksum_then_verifies(self):
        bib = load_bib()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "library"
            create_test_library(bib, root)
            bib.LIBRARY_ROOT = root
            completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            with patch.object(bib.shutil, "which", return_value="/usr/bin/rclone"), patch.object(
                bib.subprocess, "run", return_value=completed
            ) as run:
                result = bib.backup_library()

            self.assertTrue(result["uploaded"])
            self.assertEqual(run.call_count, 3)
            self.assertEqual(run.call_args_list[0].args[0][0:2], ["rclone", "copyto"])
            self.assertEqual(run.call_args_list[1].args[0][0:2], ["rclone", "copyto"])
            self.assertEqual(run.call_args_list[2].args[0][0:2], ["rclone", "check"])


if __name__ == "__main__":
    unittest.main()
