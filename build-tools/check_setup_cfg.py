"""Check setup.cfg formatting without changing the working tree."""

from __future__ import annotations

import difflib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    source = Path("setup.cfg")
    with tempfile.TemporaryDirectory() as temporary_directory:
        candidate = Path(temporary_directory) / source.name
        shutil.copy2(source, candidate)
        result = subprocess.run(
            [sys.executable, "-m", "setup_cfg_fmt", str(candidate)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode

        if candidate.read_text(encoding="utf-8") == source.read_text(encoding="utf-8"):
            return 0

        diff = difflib.unified_diff(
            source.read_text(encoding="utf-8").splitlines(keepends=True),
            candidate.read_text(encoding="utf-8").splitlines(keepends=True),
            fromfile=str(source),
            tofile="formatted setup.cfg",
        )
        sys.stdout.writelines(diff)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
