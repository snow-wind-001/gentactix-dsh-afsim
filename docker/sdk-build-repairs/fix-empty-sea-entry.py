"""Apply the local pkg6.21 SEA empty-file bound repair in a build checkout."""
from pathlib import Path
import os
pkg = next(Path("node_modules/.pnpm").glob("@yao-pkg+pkg@6.21.0*/node_modules/@yao-pkg/pkg"))
for relative in ("prelude/sea-vfs-setup.js", "prelude/sea-bootstrap.bundle.js"):
    path = pkg / relative
    source = path.read_text()
    if "? Math.max(1, meta.size)" in source:
        continue
    assert source.count("? meta.size") in (1, 2), "Packaging prelude changed; review before applying"
    temporary = path.with_name(path.name + ".gentactix-new")
    temporary.write_text(source.replace("? meta.size", "? Math.max(1, meta.size)"))
    os.replace(temporary, path)  # Copy-on-write: never modify pnpm's shared hardlink.
