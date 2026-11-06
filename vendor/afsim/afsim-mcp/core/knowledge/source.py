"""Reading AFSIM source files.

AFSIM demo files are Windows-authored, so a trailing carriage return defeats
every end-of-line anchor used in this package and silently drops declarations.
Every read goes through here.
"""

from pathlib import Path


def read_normalized(path):
    """Read a demo file with line endings normalised to \\n."""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    return text.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))


def iter_demo_files(demos_root):
    if not demos_root:
        return []
    root = Path(demos_root)
    if not root.is_dir():
        return []
    return sorted(root.rglob("*.txt"))
