import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestLibraryRoot(unittest.TestCase):
    def test_bib_defaults_to_application_root(self):
        with tempfile.TemporaryDirectory() as config_dir:
            with patch.dict(
                os.environ, {"XDG_CONFIG_HOME": config_dir}, clear=False
            ):
                os.environ.pop("BIBLIOGRAPHY_LIBRARY", None)
                bib = load_module("bib_default_root", REPO_ROOT / "CODE" / "bib.py")

        self.assertEqual(bib.APPLICATION_ROOT, REPO_ROOT)
        self.assertEqual(bib.LIBRARY_ROOT, REPO_ROOT)
        self.assertEqual(bib.METADATA_FILE, REPO_ROOT / "METADATA" / "metadata.csv")

    def test_modules_use_external_library_from_environment(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir).resolve()
            with patch.dict(
                os.environ,
                {
                    "BIBLIOGRAPHY_LIBRARY": str(library_root),
                    "XDG_CONFIG_HOME": str(library_root / "unused-config"),
                },
            ):
                bib = load_module("bib_external_root", REPO_ROOT / "CODE" / "bib.py")
                server = load_module(
                    "viewer_external_root", REPO_ROOT / "CODE" / "viewer_server.py"
                )

            self.assertEqual(bib.APPLICATION_ROOT, REPO_ROOT)
            self.assertEqual(bib.PDF_DIR, library_root / "PDFs")
            self.assertEqual(
                bib.METADATA_FILE, library_root / "METADATA" / "metadata.csv"
            )
            self.assertEqual(server.APPLICATION_ROOT, REPO_ROOT)
            self.assertEqual(server.ROOT, library_root)
            self.assertEqual(
                server.SAVED_LISTS_DIR, library_root / "SAVED_LISTS"
            )

            handler = object.__new__(server.Handler)
            handler.directory = str(server.APPLICATION_ROOT)
            self.assertEqual(
                Path(handler.translate_path("/METADATA/metadata.csv")),
                library_root / "METADATA" / "metadata.csv",
            )
            self.assertEqual(
                Path(handler.translate_path("/PDFs/example.pdf")),
                library_root / "PDFs" / "example.pdf",
            )
            self.assertEqual(
                Path(handler.translate_path("/VIEWER/viewer.html")),
                REPO_ROOT / "VIEWER" / "viewer.html",
            )


if __name__ == "__main__":
    unittest.main()
