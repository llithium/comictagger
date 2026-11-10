"""Load the entry points from plugin ZIP and wheel files."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import logging
import os
import pathlib
import sys
from dataclasses import dataclass, field
from typing import cast

from comicapi import utils
from comicapi.archivers import Archiver
from comicapi.pluginloader import ARCHIVER_ENTRY_POINT, TAG_ENTRY_POINT, TALKER_ENTRY_POINT, LocalPlugin
from comicapi.tags import Tag
from comictalker import ComicTalker

logger = logging.getLogger(__name__)


@dataclass
class Plugins:
    archivers: list[LocalPlugin[Archiver]] = field(default_factory=list)
    tags: list[LocalPlugin[Tag]] = field(default_factory=list)
    talkers: list[LocalPlugin[ComicTalker]] = field(default_factory=list)


def _load_plugin_archive(path: pathlib.Path, plugins: Plugins) -> None:
    groups = {ARCHIVER_ENTRY_POINT, TAG_ENTRY_POINT, TALKER_ENTRY_POINT}
    sys_path = sys.path[:]
    try:
        sys.path.append(str(path))
        for distribution in importlib_metadata.distributions(path=[str(path)]):
            for entry in distribution.entry_points:
                if entry.group not in groups:
                    continue
                try:
                    implementation = entry.load()
                    if entry.group == ARCHIVER_ENTRY_POINT:
                        plugins.archivers.append(LocalPlugin(entry.name, path, cast(type[Archiver], implementation)))
                    elif entry.group == TAG_ENTRY_POINT:
                        plugins.tags.append(LocalPlugin(entry.name, path, cast(type[Tag], implementation)))
                    else:
                        plugins.talkers.append(LocalPlugin(entry.name, path, cast(type[ComicTalker], implementation)))
                except Exception:
                    logger.exception("Failed to load local plugin %s from %s", entry.name, path)
    except Exception:
        logger.exception("Failed to read local plugin archive %s", path)
    finally:
        sys.path[:] = sys_path
        origin_prefix = f"{path}{os.sep}"
        for name, module in list(sys.modules.items()):
            spec = getattr(module, "__spec__", None)
            if spec is not None and (spec.origin or "").startswith(origin_prefix):
                sys.modules.pop(name, None)


def find_plugins(plugin_folder: pathlib.Path) -> Plugins:
    plugins = Plugins()
    if plugin_folder.is_dir():
        paths = (path for path in plugin_folder.iterdir() if path.is_file() and path.suffix in (".zip", ".whl"))
        for path in utils.os_sorted(paths):
            _load_plugin_archive(path.absolute(), plugins)
    return plugins
