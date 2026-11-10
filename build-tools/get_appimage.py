from __future__ import annotations

import argparse
import os
import pathlib
import platform

import requests


def urlretrieve(url: str, dest: pathlib.Path) -> None:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to download {url}: HTTP {resp.status_code}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)


def main() -> None:
    arch = platform.machine()
    parser = argparse.ArgumentParser()
    parser.add_argument("APPIMAGETOOL", default=f"build/appimagetool-{arch}.AppImage", type=pathlib.Path, nargs="?")
    opts = parser.parse_args()
    destination = opts.APPIMAGETOOL.absolute()
    if destination.exists():
        return

    urlretrieve(
        f"https://github.com/AppImage/appimagetool/releases/latest/download/appimagetool-{arch}.AppImage",
        destination,
    )
    os.chmod(destination, 0o0700)


if __name__ == "__main__":
    main()
