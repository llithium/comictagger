from __future__ import annotations

import logging
import os
import pathlib
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Collection, Iterator
from contextlib import ExitStack, contextmanager
from typing import cast

import chardet
from zipremove import ZipFile

from comicapi.archivers.archiver import Archiver, read_archive

logger = logging.getLogger(__name__)


class ZipArchiver(Archiver):
    """ZIP implementation"""

    supported_extensions = frozenset((".cbz", ".zip"))

    def __init__(self) -> None:
        super().__init__()
        self._filename_list: list[str] = []

    def supports_comment(self) -> bool:
        return True

    def get_comment(self) -> str:
        with ZipFile(self.path, "r") as zf:
            encoding = chardet.detect(zf.comment, True)
            if encoding["confidence"] > 60:
                try:
                    comment = zf.comment.decode(encoding["encoding"])
                except UnicodeDecodeError:
                    comment = zf.comment.decode("utf-8", errors="replace")
            else:
                comment = zf.comment.decode("utf-8", errors="replace")
        return comment

    def set_comment(self, comment: str) -> bool:
        with ZipFile(self.path, mode="a") as zf:
            zf.comment = bytes(comment, "utf-8")
        return True

    def read_file(self, archive_file: str) -> bytes:
        with ZipFile(self.path, mode="r") as zf:
            try:
                data = zf.read(archive_file)
            except (zipfile.BadZipfile, OSError) as e:
                logger.exception("Error reading zip archive [%s]: %s :: %s", e, self.path, archive_file)
                raise
        return data

    @contextmanager
    def read_session(self) -> Iterator[Callable[[str], bytes]]:
        # Open lazily so callers retain their per-file error handling.
        with ExitStack() as stack:
            zf: ZipFile | None = None

            def read(archive_file: str) -> bytes:
                nonlocal zf
                if zf is None:
                    zf = stack.enter_context(ZipFile(self.path, mode="r"))
                return zf.read(archive_file)

            yield read

    def remove_file(self, archive_file: str) -> bool:
        return archive_file in self.remove_files([archive_file])

    def remove_files(self, archive_files: Collection[str]) -> list[str]:
        requested = list(dict.fromkeys(archive_files))
        if not requested:
            return []
        self._filename_list = []
        try:
            with ZipFile(self.path, mode="a", allowZip64=True, compression=zipfile.ZIP_DEFLATED) as zf:
                existing = set(zf.namelist())
                removed = [zf.remove(name) for name in requested if name in existing]
                if removed:
                    zf.repack(removed)
            # Removing an already absent file is a successful no-op, as before.
            return requested
        except (zipfile.BadZipfile, OSError) as e:
            logger.error("Error writing zip archive [%s]: %s :: %s", e, self.path, requested)
            return []

    def write_file(self, archive_file: str, data: bytes) -> bool:
        files = self.get_filename_list()
        self._filename_list = []

        try:
            # now just add the archive file as a new one
            with ZipFile(self.path, mode="a", allowZip64=True, compression=zipfile.ZIP_DEFLATED) as zf:
                if archive_file in files:
                    zf.repack([zf.remove(archive_file)])
                zf.writestr(archive_file, data)
            return True
        except (zipfile.BadZipfile, OSError) as e:
            logger.error("Error writing zip archive [%s]: %s :: %s", e, self.path, archive_file)
            return False

    def get_filename_list(self) -> list[str]:
        if self._filename_list:
            return self._filename_list
        try:
            with ZipFile(self.path, mode="r") as zf:
                self._filename_list = [file.filename for file in zf.infolist() if not file.is_dir()]
                return self._filename_list
        except (zipfile.BadZipfile, OSError) as e:
            logger.error("Error listing files in zip archive [%s]: %s", e, self.path)
            return []

    def supports_files(self) -> bool:
        return True

    def rebuild(self, exclude_list: list[str]) -> bool:
        """Zip helper func

        This recompresses the zip archive, without the files in the exclude_list
        """
        self._filename_list = []
        try:
            with ZipFile(
                tempfile.NamedTemporaryFile(dir=os.path.dirname(self.path), delete=False), "w", allowZip64=True
            ) as zout:
                with ZipFile(self.path, mode="r") as zin:
                    for item in zin.infolist():
                        buffer = zin.read(item.filename)
                        if item.filename not in exclude_list:
                            zout.writestr(item, buffer)

                    # preserve the old comment
                    zout.comment = zin.comment

                # replace with the new file
                self.path.unlink(missing_ok=True)
                zout.close()  # Required on windows

                shutil.move(cast(str, zout.filename), self.path)

        except (zipfile.BadZipfile, OSError) as e:
            logger.error("Error rebuilding zip file [%s]: %s", e, self.path)
            return False
        return True

    def copy_from_archive(self, other_archive: Archiver) -> bool:
        """Replace the current zip with one copied from another archive"""
        self._filename_list = []
        try:
            with ZipFile(self.path, mode="w", allowZip64=True) as zout, read_archive(other_archive) as read:
                for filename in other_archive.get_filename_list():
                    data = read(filename)
                    if data is not None:
                        zout.writestr(filename, data)

            # preserve the old comment
            comment = other_archive.get_comment()
            if comment is not None:
                if not self.set_comment(comment):
                    return False
        except Exception as e:
            logger.error("Error while copying to zip archive [%s]: from %s to %s", e, other_archive.path, self.path)
            return False
        else:
            return True

    def is_writable(self) -> bool:
        return True

    def extension(self) -> str:
        return ".cbz"

    def name(self) -> str:
        return "ZIP"

    @classmethod
    def is_valid(cls, path: pathlib.Path) -> bool:
        return zipfile.is_zipfile(path)  # only checks central directory ot the end of the archive
