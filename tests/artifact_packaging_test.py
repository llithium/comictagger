from __future__ import annotations

import importlib.util
import pathlib
import tarfile
import zipfile

import pytest


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_archives_preserve_contents_and_unrelated_basename(tmp_path, kind):
    spec = importlib.util.spec_from_file_location("zip_artifacts", pathlib.Path("build-tools/zip_artifacts.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    source = tmp_path / "app"
    (source / "empty").mkdir(parents=True)
    (source / "nested").mkdir()
    (source / "nested" / "file.txt").write_text("payload", encoding="utf-8")
    destination = tmp_path / "release"
    destination.write_bytes(b"unrelated")

    if kind == "zip":
        module.Zip(destination, source)
        with zipfile.ZipFile(f"{destination}.zip") as archive:
            assert archive.namelist() == ["app/", "app/empty/", "app/nested/", "app/nested/file.txt"]
            assert archive.read("app/nested/file.txt") == b"payload"
    else:
        module.Tar(destination, source)
        with tarfile.open(f"{destination}.tar.gz") as archive:
            assert archive.getnames() == ["app", "app/empty", "app/nested", "app/nested/file.txt"]
            assert archive.extractfile("app/nested/file.txt").read() == b"payload"
    assert destination.read_bytes() == b"unrelated"


def test_tar_preserves_directory_symlink(tmp_path):
    spec = importlib.util.spec_from_file_location("zip_artifacts", pathlib.Path("build-tools/zip_artifacts.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "app"
    (source / "real").mkdir(parents=True)
    (source / "real" / "file.txt").write_text("payload", encoding="utf-8")
    try:
        (source / "link").symlink_to("real", target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    destination = tmp_path / "release"
    module.Tar(destination, source)
    with tarfile.open(f"{destination}.tar.gz") as archive:
        assert archive.getmember("app/link").issym()
        assert archive.getmember("app/link").linkname == "real"
        assert "app/link/file.txt" not in archive.getnames()
        assert archive.extractfile("app/real/file.txt").read() == b"payload"
