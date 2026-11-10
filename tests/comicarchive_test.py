from __future__ import annotations

import errno
import os
import pathlib
import shutil
from importlib.metadata import entry_points

import pytest

import comicapi.archivers.rar
import comicapi.archivers.zip
import comicapi.comicarchive
import comicapi.genericmetadata
from comicapi.archivers.folder import FolderArchiver
from comicapi.archivers.sevenzip import SevenZipArchiver
from testing.filenames import datadir


@pytest.mark.skipif(not comicapi.archivers.rar.rar_support, reason="rar support")
def test_getPageNameList():
    c = comicapi.comicarchive.ComicArchive(pathlib.Path(str(datadir)) / "fake_cbr.cbr")
    assert c.seems_to_be_a_comic_archive()
    pageNameList = c.get_page_name_list()

    assert pageNameList == [
        "!cover.jpg",  # Depending on locale punctuation or numbers might come first (Linux)
        "00.jpg",
        "page0.jpg",
        "Page1.jpeg",
        "Page2.png",
        "Page3.gif",
        "page4.webp",
        "page10.jpg",
    ]


def test_page_type_read(cbz):
    md = cbz.read_tags("cr")

    assert md.pages[0].type == comicapi.genericmetadata.PageType.FrontCover


def test_read_tags(cbz, md_saved):
    md = cbz.read_tags("cr")
    assert md == md_saved


def test_preloaded_tags_include_page_names_and_are_safe_to_edit(tmp_comic):
    expected = tmp_comic.read_tags("cr")
    tmp_comic.load_cache(["cr"])

    editable = tmp_comic.read_tags("cr")
    assert [page.filename for page in editable.pages] == [page.filename for page in expected.pages]
    editable.pages[0].filename = "changed.jpg"
    editable.series = "Changed in memory"

    reread = tmp_comic.read_tags("cr")
    assert reread.pages[0].filename == expected.pages[0].filename
    assert reread.series == expected.series


def test_failed_zip_export_preserves_destination(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "001.jpg").write_bytes(b"page one")
    (source / "002.jpg").write_bytes(b"page two")
    archiver = FolderArchiver.open(source)
    archive = comicapi.comicarchive.ComicArchive(archiver)
    read_file = archiver.read_file
    monkeypatch.setattr(archiver, "get_filename_list", lambda: ["001.jpg", "002.jpg"])

    def fail_second_page(name):
        if name == "002.jpg":
            raise OSError("unreadable page")
        return read_file(name)

    monkeypatch.setattr(archiver, "read_file", fail_second_page)
    destination = tmp_path / "export.cbz"
    destination.write_bytes(b"previous export")

    assert not archive.export_as_zip(destination)
    assert destination.read_bytes() == b"previous export"
    assert set(tmp_path.iterdir()) == {source, destination}


def test_failed_seven_zip_replacement_preserves_original_archive(cbz, tmp_path, monkeypatch):
    py7zr = pytest.importorskip("py7zr")
    path = tmp_path / "archive.cb7"
    archive = SevenZipArchiver.open(path)
    assert archive.copy_from_archive(cbz.archiver)
    original = path.read_bytes()

    def fail_write(*args, **kwargs):
        raise OSError("cannot write replacement member")

    monkeypatch.setattr(py7zr.SevenZipFile, "writestr", fail_write)
    assert not archive.write_file("ComicInfo.xml", b"<ComicInfo/>")

    assert path.read_bytes() == original
    assert set(tmp_path.iterdir()) == {path}


def test_zip_export_does_not_replace_a_destination_created_during_copy(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "001.jpg").write_bytes(b"page")
    archiver = FolderArchiver.open(source)
    archive = comicapi.comicarchive.ComicArchive(archiver)
    destination = tmp_path / "export.cbz"
    read_file = archiver.read_file

    def create_destination_during_read(name):
        destination.write_bytes(b"another export")
        return read_file(name)

    monkeypatch.setattr(archiver, "read_file", create_destination_during_read)

    assert not archive.export_as_zip(destination, overwrite=False)
    assert destination.read_bytes() == b"another export"
    assert set(tmp_path.iterdir()) == {source, destination}


def test_zip_export_leaves_no_output_if_exclusive_publication_is_unsupported(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "001.jpg").write_bytes(b"page")
    archive = comicapi.comicarchive.ComicArchive(FolderArchiver.open(source))
    destination = tmp_path / "export.cbz"

    def unsupported_link(*args):
        raise OSError(errno.EOPNOTSUPP, "hard links are not supported")

    monkeypatch.setattr(os, "link", unsupported_link)

    assert not archive.export_as_zip(destination, overwrite=False)
    assert set(tmp_path.iterdir()) == {source}


def test_write_cr(tmp_comic):
    md = tmp_comic.read_tags("cr")
    md.apply_default_page_list(tmp_comic.get_page_name_list())
    md.series = "Persisted series"

    assert tmp_comic.write_tags(md, "cr")

    persisted_md = comicapi.comicarchive.ComicArchive(tmp_comic.path).read_tags("cr")
    assert persisted_md.series == "Persisted series"


@pytest.mark.skipif(not (comicapi.archivers.rar.rar_support and shutil.which("rar")), reason="rar support")
def test_save_cr_rar(tmp_path, md_saved, md):
    cbr_path = datadir / "fake_cbr.cbr"
    shutil.copy(cbr_path, tmp_path)

    tmp_comic = comicapi.comicarchive.ComicArchive(tmp_path / cbr_path.name)
    assert tmp_comic.seems_to_be_a_comic_archive()
    assert tmp_comic.write_tags(md, "cr")

    new_md = tmp_comic.read_tags("cr")

    # This is a fake CBR we don't need to care about the pages for this test
    new_md.pages = []
    md_saved.pages = []
    assert new_md == md_saved


def test_page_type_write(tmp_comic):
    md = tmp_comic.read_tags("cr")
    t = md.pages[1]
    t.type = comicapi.genericmetadata.PageType.BackCover

    assert tmp_comic.write_tags(md, "cr")

    persisted_md = comicapi.comicarchive.ComicArchive(tmp_comic.path).read_tags("cr")
    assert persisted_md.pages[1].type == comicapi.genericmetadata.PageType.BackCover


def test_invalid_zip(tmp_comic: comicapi.comicarchive.ComicArchive, md):
    with open(tmp_comic.path, mode="b+r") as f:
        # Corrupting the first file only breaks the first file. If it is never read then no exception will be raised
        f.seek(-10, os.SEEK_END)  # seek to a probably bad place in th Central Directory and write some bytes
        f.write(b"PK\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000")

    result = tmp_comic.write_tags(md, "cr")  # This is not the first file
    assert result
    assert not tmp_comic.seems_to_be_a_comic_archive()  # Calls archiver.is_valid


archivers = []

for x in entry_points(group="comicapi.archiver"):
    archiver = x.load()
    supported = archiver.enabled
    exe_found = True
    if archiver.exe != "":
        exe_found = bool(shutil.which(archiver.exe))
    archivers.append(
        pytest.param(archiver, marks=pytest.mark.skipif(not (supported and exe_found), reason="archiver not enabled"))
    )


@pytest.mark.parametrize("archiver", archivers)
def test_copy_from_archive(archiver, tmp_path, cbz, md_saved):
    comic_path = tmp_path / cbz.path.with_suffix("").name

    archive = archiver.open(comic_path)

    assert archive.copy_from_archive(cbz.archiver)

    comic_archive = comicapi.comicarchive.ComicArchive(comic_path)

    assert comic_archive.seems_to_be_a_comic_archive()
    assert set(cbz.archiver.get_filename_list()) == set(comic_archive.archiver.get_filename_list())

    md = comic_archive.read_tags("cr")
    assert md == md_saved


def test_rename(tmp_comic, tmp_path):
    old_path = tmp_comic.path
    tmp_comic.rename(tmp_path / "test.cbz")
    assert not old_path.exists()
    assert tmp_comic.path.exists()
    assert tmp_comic.path != old_path


def test_rename_removes_an_empty_source_directory(tmp_comic, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_path = source_dir / tmp_comic.path.name
    tmp_comic.rename(source_path)

    tmp_comic.rename(tmp_path / "library" / "renamed.cbz", remove_empty_source_dir=True)

    assert not source_dir.exists()


def test_rename_keeps_a_nonempty_source_directory(tmp_comic, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_path = source_dir / tmp_comic.path.name
    tmp_comic.rename(source_path)
    (source_dir / "keep.txt").touch()

    tmp_comic.rename(tmp_path / "library" / "renamed.cbz", remove_empty_source_dir=True)

    assert source_dir.exists()


@pytest.mark.skipif(not comicapi.archivers.rar.rar_support, reason="rar support")
def test_rename_reopens_cached_rar_archive(tmp_path):
    source = datadir / "fake_cbr.cbr"
    old_path = tmp_path / source.name
    new_path = tmp_path / "renamed.cbr"
    shutil.copy(source, old_path)
    archive = comicapi.comicarchive.ComicArchive(old_path)
    archive_files = archive.archiver.get_filename_list()
    expected_contents = archive.archiver.read_file(archive_files[0])

    archive.rename(new_path)

    assert archive.archiver.read_file(archive_files[0]) == expected_contents


def test_rename_failure_preserves_original(tmp_comic, tmp_path, monkeypatch):
    old_path = tmp_comic.path

    def fail_move(*args, **kwargs):
        raise OSError("move failed")

    monkeypatch.setattr(shutil, "move", fail_move)
    with pytest.raises(OSError, match="move failed"):
        tmp_comic.rename(tmp_path / "test.cbz")

    assert old_path.exists()
    assert tmp_comic.path == old_path
    assert tmp_comic.archiver.path == old_path


def test_page_scan_shares_reader_and_releases_it(tmp_comic, monkeypatch):
    from unittest.mock import Mock

    from comicapi.archivers.archiver import read_archive

    tmp_comic.get_page_name_list()
    md = comicapi.genericmetadata.GenericMetadata()
    factory = Mock(wraps=comicapi.archivers.zip.ZipFile)
    monkeypatch.setattr(comicapi.archivers.zip, "ZipFile", factory)
    tmp_comic.apply_archive_info_to_metadata(md, True, True)

    assert factory.call_count == 1
    assert all(p.width and p.height and p.byte_size for p in md.pages)
    # A later session must see writes made after the first reader was closed.
    assert tmp_comic.archiver.write_file("new.txt", b"new contents")
    with read_archive(tmp_comic.archiver) as read:
        assert read("new.txt") == b"new contents"


def test_bulk_delete_preserves_remaining_contents_and_comment(tmp_comic, monkeypatch):
    from unittest.mock import Mock

    original = {name: tmp_comic.archiver.read_file(name) for name in tmp_comic.archiver.get_filename_list()}
    names = tmp_comic.get_page_name_list().copy()
    assert len(names) >= 2
    tmp_comic.archiver.set_comment("Preserved comment")
    repacks = Mock()
    original_repack = comicapi.archivers.zip.ZipFile.repack

    def repack(archive, removed):
        repacks()
        return original_repack(archive, removed)

    monkeypatch.setattr(comicapi.archivers.zip.ZipFile, "repack", repack)
    assert tmp_comic.remove_pages([0, 1, 1, -1, 99999]) == [0, 1]
    assert repacks.call_count == 1
    assert tmp_comic.get_page_name_list() == names[2:]
    assert tmp_comic.archiver.get_comment() == "Preserved comment"
    remaining = {name: tmp_comic.archiver.read_file(name) for name in tmp_comic.archiver.get_filename_list()}
    assert remaining == {name: data for name, data in original.items() if name not in names[:2]}


def test_legacy_archiver_bulk_fallback_and_partial_failure(tmp_comic):
    from comicapi.archivers.archiver import read_archive

    underlying = tmp_comic.archiver
    names = tmp_comic.get_page_name_list().copy()

    class LegacyArchiver:
        def read_file(self, name):
            return underlying.read_file(name)

        def remove_file(self, name):
            return name != names[0] and underlying.remove_file(name)

    tmp_comic.archiver = LegacyArchiver()
    with read_archive(tmp_comic.archiver) as read:
        assert read(names[0]) == underlying.read_file(names[0])
    assert tmp_comic.remove_pages([0, 1]) == [1]
    assert names[0] in underlying.get_filename_list()
    assert names[1] not in underlying.get_filename_list()


def test_page_scan_continues_after_bad_image(tmp_comic):
    name = tmp_comic.get_page_name_list()[0]
    assert tmp_comic.archiver.write_file(name, b"invalid image")
    md = comicapi.genericmetadata.GenericMetadata()
    tmp_comic.apply_archive_info_to_metadata(md, True, True)
    assert md.pages[0].byte_size == len(b"invalid image")
    assert md.pages[0].width is None
    assert all(p.width and p.height for p in md.pages[1:])
