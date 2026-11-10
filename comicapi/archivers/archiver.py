from __future__ import annotations

import ctypes
import errno
import os
import pathlib
import stat
import sys
import tempfile
from collections.abc import Callable, Collection, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext, suppress
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from comicapi.utils import file_name_candidates


@runtime_checkable
class Archiver(Protocol):
    """Archiver Protocol"""

    """The path to the archive"""
    path: pathlib.Path

    """
    The name of the executable used for this archiver. This should be the base name of the executable.
    For example if 'rar.exe' is needed this should be "rar".
    If an executable is not used this should be the empty string.
    """
    exe: str = ""

    """
    Whether or not this archiver is enabled.
    If external imports are required and are not available this should be false. See rar.py and sevenzip.py.
    """
    enabled: bool = True

    """
    If self.path is a single file that can be hashed.
    For example directories cannot be hashed.
    """
    hashable: bool = True

    supported_extensions: Collection[str] = set()

    def __init__(self) -> None:
        self.path = pathlib.Path()

    def get_comment(self) -> str:
        """
        Returns the comment from the current archive as a string.
        Should always return a string. If comments are not supported in the archive the empty string should be returned.
        """
        return ""

    def set_comment(self, comment: str) -> bool:
        """
        Returns True if the comment was successfully set on the current archive.
        Should always return a boolean. If comments are not supported in the archive False should be returned.
        """
        return False

    def supports_comment(self) -> bool:
        """
        Returns True if the current archive supports comments.
        Should always return a boolean. If comments are not supported in the archive False should be returned.
        """
        return False

    def read_file(self, archive_file: str) -> bytes:
        """
        Reads the named file from the current archive.
        archive_file should always come from the output of get_filename_list.
        Should always return a bytes object. Exceptions should be of the type OSError.
        """
        raise NotImplementedError

    def remove_file(self, archive_file: str) -> bool:
        """
        Removes the named file from the current archive.
        archive_file should always come from the output of get_filename_list.
        Should always return a boolean. Failures should return False.

        Rebuilding the archive without the named file is a standard way to remove a file.
        """
        return False

    def write_file(self, archive_file: str, data: bytes) -> bool:
        """
        Writes the named file to the current archive.
        Should always return a boolean. Failures should return False.
        """
        return False

    def get_filename_list(self) -> list[str]:
        """
        Returns a list of filenames in the current archive.
        Should always return a list of string. Failures should return an empty list.
        """
        return []

    def supports_files(self) -> bool:
        """
        Returns True if the current archive supports arbitrary non-picture files.
        Should always return a boolean.
        If arbitrary non-picture files are not supported in the archive False should be returned.
        """
        return False

    def copy_from_archive(self, other_archive: Archiver) -> bool:
        """
        Copies the contents of another achive to the current archive.
        Should always return a boolean. Failures should return False.
        """
        return False

    def is_writable(self) -> bool:
        """
        Retuns True if the current archive is writeable
        Should always return a boolean. Failures should return False.
        """
        return False

    def extension(self) -> str:
        """
        Returns the extension that this archiver should use eg ".cbz".
        Should always return a string. Failures should return the empty string.
        """
        return ""

    def name(self) -> str:
        """
        Returns the name of this archiver for display purposes eg "CBZ".
        Should always return a string. Failures should return the empty string.
        """
        return ""

    @classmethod
    def is_valid(cls, path: pathlib.Path) -> bool:
        """
        Returns True if the given path can be opened by this archiver.
        Should always return a boolean. Failures should return False.
        """
        return False

    @classmethod
    def open(cls, path: pathlib.Path) -> Archiver:
        """
        Opens the given archive.
        Should always return a an Archver.
        Should never cause an exception no file operations should take place in this method,
        is_valid will always be called before open.
        """
        archiver = cls()
        archiver.path = path
        return archiver


@runtime_checkable
class ReadSessionArchiver(Protocol):
    """Optional capability for sharing a reader within one operation."""

    def read_session(self) -> AbstractContextManager[Callable[[str], bytes]]: ...


@runtime_checkable
class BulkRemoveArchiver(Protocol):
    """Optional capability returning filenames removed or already absent."""

    def remove_files(self, archive_files: Collection[str]) -> list[str]: ...


def read_archive(archive: Archiver) -> AbstractContextManager[Callable[[str], bytes]]:
    # Keep existing third-party archivers compatible without requiring new methods.
    if isinstance(archive, ReadSessionArchiver):
        return archive.read_session()
    return nullcontext(archive.read_file)


def member_destination(root: pathlib.Path, name: str) -> pathlib.Path:
    root = root.resolve()
    destination = (root / name).resolve()
    if destination == root or not destination.is_relative_to(root):
        raise ValueError(f"Archive member escapes destination: {name!r}")
    return destination


def _rename_exclusive(source: pathlib.Path, target: pathlib.Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    args: tuple[int | bytes, ...]
    try:
        if sys.platform == "darwin":
            rename = libc.renamex_np
            rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            args = (os.fsencode(source), os.fsencode(target), 0x4)  # RENAME_EXCL
        elif sys.platform == "linux":
            rename = libc.renameat2
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            at_fdcwd = -100
            args = (at_fdcwd, os.fsencode(source), at_fdcwd, os.fsencode(target), 1)  # RENAME_NOREPLACE
        else:
            raise AttributeError("exclusive rename")
    except AttributeError:
        raise OSError(errno.ENOSYS, "Exclusive rename is unavailable", target) from None

    rename.restype = ctypes.c_int
    if rename(*args) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), target)


_EXCLUSIVE_UNSUPPORTED = (errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EINVAL)


def _publish_at_path(staged: pathlib.Path, path: pathlib.Path) -> None:
    if os.name == "nt":
        staged.rename(path)
        return

    try:
        os.link(staged, path)
    except OSError as error:
        # FAT drivers can also report EPERM when hard links are unsupported.
        if error.errno not in (*_EXCLUSIVE_UNSUPPORTED, errno.EPERM):
            raise
        _rename_exclusive(staged, path)


def _publish_export_folder(staged: pathlib.Path, path: pathlib.Path) -> pathlib.Path:
    folder = pathlib.Path(tempfile.mkdtemp(prefix="ComicTagger-export-", dir=path.parent))
    named_archive = staged.with_name(path.name)
    try:
        if named_archive != staged:
            staged.rename(named_archive)
        # A directory rename can only replace an empty directory. The finished
        # CBZ becomes visible inside it in one step.
        staged.parent.replace(folder)
    except OSError:
        with suppress(OSError):
            folder.rmdir()
        raise
    return folder / path.name


def _publish_new_archive(
    staged: pathlib.Path, path: pathlib.Path, *, allow_export_folder: bool, unique: bool
) -> pathlib.Path:
    candidates = file_name_candidates(path)
    while True:
        candidate = next(candidates)
        try:
            _publish_at_path(staged, candidate)
        except FileExistsError:
            if not unique:
                raise
        except OSError as error:
            if not allow_export_folder or os.name == "nt" or error.errno not in _EXCLUSIVE_UNSUPPORTED:
                raise
            if not os.path.lexists(candidate):
                return _publish_export_folder(staged, candidate)
            if not unique:
                raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), candidate) from None
        else:
            return candidate


@dataclass
class ArchiveReplacement:
    staged: pathlib.Path
    published: pathlib.Path | None = None


@contextmanager
def archive_replacement(
    path: pathlib.Path, *, overwrite: bool = True, allow_export_folder: bool = False, unique: bool = False
) -> Iterator[ArchiveReplacement]:
    """Publish a closed, complete archive when the writer finishes successfully."""
    mode = None
    if overwrite:
        with suppress(FileNotFoundError):
            mode = stat.S_IMODE(path.stat().st_mode)
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        replacement = ArchiveReplacement(pathlib.Path(directory) / path.name)
        yield replacement
        if overwrite:
            if mode is not None:
                replacement.staged.chmod(mode)
            replacement.published = replacement.staged.replace(path)
        else:
            replacement.published = _publish_new_archive(
                replacement.staged, path, allow_export_folder=allow_export_folder, unique=unique
            )
