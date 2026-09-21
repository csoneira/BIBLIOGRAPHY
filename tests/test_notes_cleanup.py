import json
import shutil
import subprocess
import unittest
from pathlib import Path


class TestNotesCleanup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("Node.js is not installed")
        cls.module_path = Path(__file__).resolve().parents[1] / "VIEWER" / "notes-cleanup.js"

    def clean(self, value):
        script = (
            f"const clean=require({json.dumps(str(self.module_path))}).cleanPastedNotes;"
            f"process.stdout.write(clean({json.dumps(value)}));"
        )
        result = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, check=True
        )
        return result.stdout

    def test_joins_wrapped_lines_and_preserves_list_items(self):
        source = (
            "- Interesting explanation of the\navalanche mechanism.\n\n"
            "- The author compares two\ndifferent gases.\n"
            "1. A numbered item\nwith a continuation"
        )
        self.assertEqual(
            self.clean(source),
            "- Interesting explanation of the avalanche mechanism.\n"
            "- The author compares two different gases.\n"
            "1. A numbered item with a continuation",
        )

    def test_repairs_split_words_but_preserves_real_hyphens(self):
        self.assertEqual(
            self.clean("- A detec-\ntor and a high-\nenergy event"),
            "- A detector and a high-energy event",
        )

    def test_removes_extra_blank_lines(self):
        self.assertEqual(
            self.clean("Introductory\ntext.\n\n\n• First point\ncontinued"),
            "Introductory text.\n• First point continued",
        )


if __name__ == "__main__":
    unittest.main()
