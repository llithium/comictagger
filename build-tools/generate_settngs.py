from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

import settngs

import comicapi.comicarchive
import comictaggerlib.main
from comicapi.archivers.folder import FolderArchiver
from comicapi.archivers.rar import RarArchiver
from comicapi.archivers.sevenzip import SevenZipArchiver
from comicapi.archivers.zip import ZipArchiver
from comicapi.tags.comicrack import ComicRack
from comictaggerlib.ctversion import version
from comictalker.talkers.comicvine import ComicVineTalker


def generate() -> str:
    archivers = comicapi.comicarchive.archivers
    tags = comicapi.comicarchive.tags
    original_archivers = archivers.copy()
    original_tags = tags.copy()
    try:
        archivers[:] = [ZipArchiver, SevenZipArchiver, RarArchiver, FolderArchiver]
        tags.clear()
        tags[ComicRack.id] = ComicRack(version)
        with tempfile.TemporaryDirectory() as cache:
            app = comictaggerlib.main.App()
            talker = ComicVineTalker(version, pathlib.Path(cache))
            app.talkers = {talker.id: talker}
            app.register_settings(True)
            imports, types = settngs.generate_dict(app.manager.definitions)
            imports2, types2 = settngs.generate_ns(app.manager.definitions)
    finally:
        archivers[:] = original_archivers
        tags.clear()
        tags.update(original_tags)
    i = imports.splitlines()
    i.extend(sorted(set(imports2.splitlines()) - set(i)))
    return (os.linesep * 2).join((os.linesep.join(i), types2, types))


if __name__ == "__main__":
    src = generate()
    output_path = pathlib.Path("./comictaggerlib/ctsettings/settngs_namespace.py")
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as temporary_directory:
            generated_path = pathlib.Path(temporary_directory) / output_path.name
            generated_path.write_text(src, encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "isort",
                    "--af",
                    "--add-import",
                    "from __future__ import annotations",
                    str(generated_path),
                ],
                check=True,
            )
            subprocess.run([sys.executable, "-m", "black", str(generated_path)], check=True)
            generated = generated_path.read_text(encoding="utf-8")
        if output_path.read_text(encoding="utf-8") != generated:
            print(f"{output_path} is out of date; run the format environment to regenerate it")
            raise SystemExit(1)
    else:
        output_path.write_text(src, encoding="utf-8")
        print(src, end="")
