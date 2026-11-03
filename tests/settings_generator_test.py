from __future__ import annotations

import importlib.util
import pathlib
import sys

from comicapi import comicarchive

spec = importlib.util.spec_from_file_location("settings_generator", pathlib.Path("build-tools/generate_settngs.py"))
assert spec and spec.loader
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def test_generation_ignores_runtime_plugins_and_arguments(monkeypatch, tmp_path):
    baseline = generator.generate()
    original_archivers = comicarchive.archivers.copy()
    original_tags = comicarchive.tags.copy()

    class UserArchiver:
        exe = "user-only-executable"

    try:
        comicarchive.archivers[:] = [UserArchiver]
        comicarchive.tags.clear()
        comicarchive.tags["user-only-tag"] = object()
        monkeypatch.setattr(sys, "argv", ["generate_settngs.py", "--config", str(tmp_path / "user")])
        assert generator.generate() == baseline
        assert comicarchive.archivers == [UserArchiver]
        assert list(comicarchive.tags) == ["user-only-tag"]
    finally:
        comicarchive.archivers[:] = original_archivers
        comicarchive.tags.clear()
        comicarchive.tags.update(original_tags)

    assert "Source_comicvine" in baseline
    assert "user_only_executable" not in baseline
