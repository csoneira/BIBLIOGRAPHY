import csv
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_library_state():
    path = REPO_ROOT / "CODE" / "library_state.py"
    spec = importlib.util.spec_from_file_location("test_library_state_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestLibraryState(unittest.TestCase):
    def test_cli_init_creates_empty_idempotent_library(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "My Library"
            command = [
                sys.executable,
                str(REPO_ROOT / "CODE" / "bib.py"),
                "init",
                str(root),
                "--name",
                "My Papers",
            ]
            environment = os.environ.copy()
            environment.pop("BIBLIOGRAPHY_LIBRARY", None)
            first = subprocess.run(
                command, cwd=REPO_ROOT, env=environment,
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("Library ready", first.stdout)

            manifest = json.loads((root / "library.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest,
                {"format_version": 1, "name": "My Papers", "pdf_archive": None},
            )
            with (root / "METADATA" / "metadata.csv").open(newline="") as handle:
                self.assertEqual(next(csv.reader(handle)), load_bib_fields())
                self.assertEqual(list(csv.reader(handle)), [])
            self.assertEqual(
                (root / "METADATA" / "abstracts.csv").read_text(encoding="utf-8"),
                "code,abstract\n",
            )
            self.assertTrue((root / "SAVED_LISTS").is_dir())
            self.assertTrue((root / "PDFs").is_dir())
            self.assertEqual(
                (root / ".gitignore").read_text(encoding="utf-8"),
                "PDFs/\nMETADATA/backups/\nMETADATA/title_audit_cache.json\n*.tmp\n",
            )

            second = subprocess.run(
                command, cwd=REPO_ROOT, env=environment,
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("No changes needed", second.stdout)

    def test_init_adopts_existing_metadata_without_overwriting_it(self):
        state = load_library_state()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            metadata = root / "METADATA" / "metadata.csv"
            metadata.parent.mkdir()
            original = "code,type,title\nkept,book,Keep me\n"
            metadata.write_text(original, encoding="utf-8")

            result = state.initialize_library(
                root, "Adopted", ["code", "type", "title"], ["code", "abstract"]
            )

            self.assertTrue(result["valid"])
            self.assertEqual(metadata.read_text(encoding="utf-8"), original)
            self.assertEqual(result["manifest"]["name"], "Adopted")

    def test_manifest_validation_reports_invalid_state(self):
        state = load_library_state()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "library.json").write_text(
                '{"format_version": 2, "name": "Future", "pdf_archive": null}\n',
                encoding="utf-8",
            )
            result = state.describe_library(root)
            self.assertFalse(result["valid"])
            self.assertIn("format_version", result["error"])

    def test_persistent_selection_uses_xdg_config_and_environment_wins(self):
        state = load_library_state()
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            library = base / "library"
            override = base / "override"
            state.initialize_library(
                library, "Selected", ["code", "type", "title"], ["code", "abstract"]
            )
            with patch.dict(
                os.environ, {"XDG_CONFIG_HOME": str(base / "config")}, clear=False
            ):
                os.environ.pop("BIBLIOGRAPHY_LIBRARY", None)
                config_path = state.save_library_selection(library)
                selected = state.resolve_library_selection(base / "application")
                self.assertEqual(selected["root"], library.resolve())
                self.assertEqual(selected["source"], "user_config")
                self.assertTrue(config_path.is_file())

                with patch.dict(
                    os.environ, {"BIBLIOGRAPHY_LIBRARY": str(override)}
                ):
                    selected = state.resolve_library_selection(base / "application")
                self.assertEqual(selected["root"], override.resolve())
                self.assertEqual(selected["source"], "environment")


def load_bib_fields():
    spec = importlib.util.spec_from_file_location(
        "bib_fields_for_init_test", REPO_ROOT / "CODE" / "bib.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FIELDS


if __name__ == "__main__":
    unittest.main()
