from __future__ import annotations

import logging
import pathlib

from comicapi.archivers.archiver import Archiver, archive_replacement, read_archive

try:
    import py7zr

    z7_support = True
except ImportError:
    z7_support = False

logger = logging.getLogger(__name__)


class SevenZipArchiver(Archiver):
    """7Z implementation"""

    enabled = z7_support
    supported_extensions = frozenset({".7z", ".cb7"})

    def __init__(self) -> None:
        super().__init__()
        self._filename_list: list[str] = []

    def read_file(self, archive_file: str) -> bytes:
        data = b""
        try:
            with py7zr.SevenZipFile(self.path, "r") as zf:
                data = zf.read([archive_file])[archive_file].read()
        except (py7zr.Bad7zFile, OSError) as e:
            logger.error("Error reading 7zip archive [%s]: %s :: %s", e, self.path, archive_file)
            raise

        return data

    def remove_file(self, archive_file: str) -> bool:
        return self.rebuild([archive_file])

    def write_file(self, archive_file: str, data: bytes) -> bool:
        files = self.get_filename_list()
        if archive_file in files:
            return self._rewrite([archive_file], (archive_file, data))

        self._filename_list = []
        try:
            with py7zr.SevenZipFile(self.path, "a") as zf:
                zf.writestr(data, archive_file)
            return True
        except (py7zr.Bad7zFile, OSError) as e:
            logger.error("Error writing 7zip archive [%s]: %s :: %s", e, self.path, archive_file)
            return False

    def get_filename_list(self) -> list[str]:
        if self._filename_list:
            return self._filename_list
        try:
            with py7zr.SevenZipFile(self.path, "r") as zf:
                namelist: list[str] = [file.filename for file in zf.list() if not file.is_directory]

            self._filename_list = namelist
            return namelist
        except (py7zr.Bad7zFile, OSError) as e:
            logger.error("Error listing files in 7zip archive [%s]: %s", e, self.path)
            return []

    def supports_files(self) -> bool:
        return True

    def rebuild(self, exclude_list: list[str]) -> bool:
        return self._rewrite(exclude_list)

    def _rewrite(self, exclude_list: list[str], replacement: tuple[str, bytes] | None = None) -> bool:
        self._filename_list = []
        try:
            with archive_replacement(self.path) as replacement_file:
                with (
                    py7zr.SevenZipFile(self.path, mode="r") as zin,
                    py7zr.SevenZipFile(replacement_file.staged, mode="w") as zout,
                ):
                    # Read retained members together because 7z compression can be solid.
                    targets = [name for name in zin.getnames() if name not in exclude_list]
                    for filename, buffer in zin.read(targets).items():
                        zout.writef(buffer, filename)
                    if replacement is not None:
                        filename, data = replacement
                        zout.writestr(data, filename)
        except (py7zr.Bad7zFile, OSError) as e:
            logger.error("Error rebuilding 7zip file [%s]: %s", e, self.path)
            return False
        return True

    def copy_from_archive(self, other_archive: Archiver) -> bool:
        self._filename_list = []
        try:
            with archive_replacement(self.path) as replacement:
                with py7zr.SevenZipFile(replacement.staged, "w") as zout, read_archive(other_archive) as read:
                    for filename in other_archive.get_filename_list():
                        data = read(filename)
                        if data is not None:
                            zout.writestr(data, filename)
        except Exception as e:
            logger.error("Error while copying to 7zip archive [%s]: from %s to %s", e, other_archive.path, self.path)
            return False
        else:
            return True

    def is_writable(self) -> bool:
        return True

    def extension(self) -> str:
        return ".cb7"

    def name(self) -> str:
        return "Seven Zip"

    @classmethod
    def is_valid(cls, path: pathlib.Path) -> bool:
        return py7zr.is_7zfile(path)
