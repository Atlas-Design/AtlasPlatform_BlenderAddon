"""Create a portable zip archive with POSIX-style entry names.

PowerShell's Compress-Archive can produce archives that preserve Windows path
separators in some environments. Blender installs add-ons more reliably when
zip entries use forward slashes, so the release batch file delegates archive
creation here.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path, PurePosixPath


def to_zip_name(path: Path, root_parent: Path) -> str:
    """Return a portable archive name relative to root_parent."""
    relative = path.relative_to(root_parent)
    return PurePosixPath(*relative.parts).as_posix()


def create_zip(source_dir: Path, zip_path: Path) -> None:
    """Zip source_dir into zip_path using forward-slash archive paths."""
    source_dir = source_dir.resolve()
    zip_path = zip_path.resolve()
    root_parent = source_dir.parent

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(source_dir.rglob("*")):
            if not file_path.is_file():
                continue
            archive.write(file_path, to_zip_name(file_path, root_parent))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: create_portable_zip.py <source_dir> <zip_path>", file=sys.stderr)
        return 2

    source_dir = Path(argv[1])
    zip_path = Path(argv[2])

    if not source_dir.is_dir():
        print(f"ERROR: Source directory does not exist: {source_dir}", file=sys.stderr)
        return 1

    create_zip(source_dir, zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
