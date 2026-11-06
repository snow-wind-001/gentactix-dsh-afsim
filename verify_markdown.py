"""Safe rendering of actual structured analysis, including narrow-screen tables."""
from pathlib import Path
import subprocess
import unittest


class MarkdownTests(unittest.TestCase):
    def test_data_tables_and_untrusted_text(self):
        result=subprocess.run(['node','tools/qa/markdown.mjs'],cwd=Path(__file__).resolve().parent,
            capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
