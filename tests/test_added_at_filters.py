import importlib.util
import unittest
from datetime import date
from pathlib import Path


def load_bib(module_path: Path):
    spec = importlib.util.spec_from_file_location("bib", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAddedAtFilters(unittest.TestCase):
    def test_filter_rows_by_added_date_range(self):
        repo_root = Path(__file__).resolve().parents[1]
        bib = load_bib(repo_root / "CODE" / "bib.py")
        rows = [
            {"code": "a", "added_at": "2026-01-10"},
            {"code": "b", "added_at": "2026-01-12"},
            {"code": "c", "added_at": "2026-01-15"},
            {"code": "d", "added_at": ""},
        ]

        filtered = bib.filter_rows(
            rows,
            added_from=date(2026, 1, 11),
            added_to=date(2026, 1, 13),
        )
        self.assertEqual([row["code"] for row in filtered], ["b"])

    def test_sort_rows_by_added_places_missing_last(self):
        repo_root = Path(__file__).resolve().parents[1]
        bib = load_bib(repo_root / "CODE" / "bib.py")
        rows = [
            {"code": "old", "added_at": "2026-01-10"},
            {"code": "missing", "added_at": ""},
            {"code": "new", "added_at": "2026-01-20"},
        ]

        sorted_rows = bib.sort_rows_by_added(rows, descending=True)
        self.assertEqual([row["code"] for row in sorted_rows], ["new", "old", "missing"])

    def test_filter_rows_unread_only(self):
        repo_root = Path(__file__).resolve().parents[1]
        bib = load_bib(repo_root / "CODE" / "bib.py")
        rows = [
            {"code": "a", "unread": ""},
            {"code": "b", "unread": "1"},
            {"code": "c", "unread": "0"},
        ]

        filtered = bib.filter_rows(rows, unread_only=True)
        self.assertEqual([row["code"] for row in filtered], ["b"])


if __name__ == "__main__":
    unittest.main()
