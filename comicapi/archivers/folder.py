from __future__ import annotations

import logging
import os
import pathlib

from comicapi.archivers.archiver import Archiver, member_destination, read_archive

logger = logging.getLogger(__name__)


class FolderArchiver(Archiver):
    """Folder implementation"""

    hashable = False

    def __init__(self) -> None:
        super().__init__()
        self.comment_file_name = "ComicTaggerFolderComment.txt"
        self._filename_list: list[str] = []

    def get_comment(self) -> str:
        try:
            return (self.path / self.comment_file_name).read_text()
        except OSError:
            return ""

    def set_comment(self, comment: str) -> bool:
        self._filename_list = []
        if comment:
            return self.write_file(self.comment_file_name, comment.encode("utf-8"))
        (self.path / self.comment_file_name).unlink(missing_ok=True)
        return True

    def supports_comment(self) -> bool:
        return True

    def read_file(self, archive_file: str) -> bytes:
        try:
            data = (self.path / archive_file).read_bytes()
        except OSError as e:
            logger.error("Error reading folder archive [%s]: %s :: %s", e, self.path, archive_file)
            raise

        return data

    def remove_file(self, archive_file: str) -> bool:
        self._filename_list = []
        try:
            (self.path / archive_file).unlink(missing_ok=True)
        except OSError as e:
            logger.error("Error removing file for folder archive [%s]: %s :: %s", e, self.path, archive_file)
            return False
        else:
            return True

    def write_file(self, archive_file: str, data: bytes) -> bool:
        self._filename_list = []
        try:
            file_path = member_destination(self.path, archive_file)
            file_path.parent.mkdir(exist_ok=True, parents=True)
            file_path.write_bytes(data)
        except (OSError, ValueError) as e:
            logger.error("Error writing folder archive [%s]: %s :: %s", e, self.path, archive_file)
            return False
        else:
            return True

    def get_filename_list(self) -> list[str]:
        if self._filename_list:
            return self._filename_list
        filenames = []
        try:
            for root, _dirs, files in os.walk(self.path):
                for f in files:
                    filenames.append(os.path.relpath(os.path.join(root, f), self.path).replace(os.path.sep, "/"))
            self._filename_list = filenames
            return filenames
        except OSError as e:
            logger.error("Error listing files in folder archive [%s]: %s", e, self.path)
            return []

    def supports_files(self) -> bool:
        return True

    def copy_from_archive(self, other_archive: Archiver) -> bool:
        self._filename_list = []
        try:
            with read_archive(other_archive) as read:
                for filename in other_archive.get_filename_list():
                    data = read(filename)
                    if data is not None and not self.write_file(filename, data):
                        return False
            comment = other_archive.get_comment()
            if comment is not None:
                if not self.set_comment(comment):
                    return False
        except Exception:
            logger.exception("Error while copying archive from %s to %s", other_archive.path, self.path)
            return False
        else:
            return True

    def is_writable(self) -> bool:
        return True

    def name(self) -> str:
        return "Folder"

    @classmethod
    def is_valid(cls, path: pathlib.Path) -> bool:
        return path.is_dir()
