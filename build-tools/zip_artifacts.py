from __future__ import annotations

import os
import pathlib
import platform
import sys
import tarfile
import zipfile

from comictaggerlib.ctversion import __version__


def addToZip(zf: zipfile.ZipFile, path: str, zippath: str) -> None:
    if os.path.isfile(path):
        zf.write(path, zippath)
    elif os.path.isdir(path):
        if zippath:
            zf.write(path, zippath)
        for nm in sorted(os.listdir(path)):
            addToZip(zf, os.path.join(path, nm), os.path.join(zippath, nm))


def Zip(zip_file: pathlib.Path, path: pathlib.Path) -> None:
    with zipfile.ZipFile(f"{zip_file}.zip", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=8) as zf:
        addToZip(zf, str(path), archive_name(path))


def archive_name(path: pathlib.Path) -> str:
    name = os.path.basename(path) or os.path.basename(os.path.dirname(path))
    return "" if name in ("", os.curdir, os.pardir) else name


def Tar(tar_file: pathlib.Path, path: pathlib.Path) -> None:
    with tarfile.open(f"{tar_file}.tar.gz", "w:gz") as tf:
        name = archive_name(path)
        if name or not path.is_dir():
            tf.add(path, name)
        else:
            for child in sorted(path.iterdir()):
                tf.add(child, child.name)


if __name__ == "__main__":
    app = "ComicTagger"
    exe = app.casefold()
    final_name = f"{app}-{__version__}-{platform.system()}-{platform.machine()}"
    if platform.system() == "Windows":
        exe = f"{exe}.exe"
    elif platform.system() == "Darwin":
        exe = f"{app}.app"
        ver = platform.mac_ver()
        final_name = f"{app}-{__version__}-macOS-{ver[0]}-{ver[2]}"

    path = pathlib.Path(f"dist/{exe}")
    binary_path = pathlib.Path("dist/binary")
    binary_path.mkdir(parents=True, exist_ok=True)
    archive_destination = binary_path / final_name

    if platform.system() == "Darwin":
        from dmgbuild.__main__ import main as dmg_main

        sys.argv = [
            "zip_artifacts",
            "-s",
            str(pathlib.Path(__file__).parent / "dmgbuild.conf"),
            f"{app} {__version__}",
            f"{archive_destination}.dmg",
        ]
        dmg_main()
    elif platform.system() == "Windows":
        Zip(archive_destination, path)
    else:
        Tar(archive_destination, path)
