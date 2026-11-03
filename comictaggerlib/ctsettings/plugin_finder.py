"""Functions related to finding and loading plugins."""

# Lifted from flake8 https://github.com/PyCQA/flake8/blob/main/src/flake8/plugins/finder.py#L127

from __future__ import annotations

import importlib.metadata as importlib_metadata
import logging
import pathlib
import sys
from collections.abc import Generator
from typing import Any, NamedTuple

from comicapi import utils

logger = logging.getLogger(__name__)

PLUGIN_GROUPS = frozenset(("comictagger.talker", "comicapi.archiver", "comicapi.tags"))


class FailedToLoadPlugin(Exception):
    """Exception raised when a plugin fails to load."""

    FORMAT = 'ComicTagger failed to load local plugin "{name}" due to {exc}.'

    def __init__(self, plugin_name: str, exception: Exception) -> None:
        """Initialize our FailedToLoadPlugin exception."""
        self.plugin_name = plugin_name
        self.original_exception = exception
        super().__init__(plugin_name, exception)

    def __str__(self) -> str:
        """Format our exception message."""
        return self.FORMAT.format(
            name=self.plugin_name,
            exc=self.original_exception,
        )


class Plugin(NamedTuple):
    """A plugin before loading."""

    package: str
    version: str
    entry_point: importlib_metadata.EntryPoint
    path: pathlib.Path

    def load(self) -> LoadedPlugin:
        return LoadedPlugin(self, self.entry_point.load())


class LoadedPlugin(NamedTuple):
    """Represents a plugin after being imported."""

    plugin: Plugin
    obj: Any

    @property
    def entry_name(self) -> str:
        """Return the name given in the packaging metadata."""
        return self.plugin.entry_point.name

    @property
    def display_name(self) -> str:
        """Return the name for use in user-facing / error messages."""
        return f"{self.plugin.package}[{self.entry_name}]"


class Plugins(NamedTuple):
    """Classified plugins."""

    archivers: list[LoadedPlugin]
    tags: list[LoadedPlugin]
    talkers: list[LoadedPlugin]


def _find_local_plugins(plugin_path: pathlib.Path) -> Generator[Plugin]:
    logger.debug("Checking for distributions in %s", plugin_path)
    for dist in importlib_metadata.distributions(path=[str(plugin_path)]):
        logger.debug("found distribution %s", dist.name)
        eps = dist.entry_points
        for group in PLUGIN_GROUPS:
            for ep in eps.select(group=group):
                logger.debug("found EntryPoint group %s %s=%s", group, ep.name, ep.value)
                yield Plugin(plugin_path.name, dist.version, ep, plugin_path)


def find_plugins(plugin_folder: pathlib.Path) -> Plugins:
    """Discovers all plugins (but does not load them)."""
    ret: list[LoadedPlugin] = []
    if not plugin_folder.is_dir():
        return _classify_plugins(ret)

    zips = [x for x in plugin_folder.iterdir() if x.is_file() and x.suffix in (".zip", ".whl")]

    for plugin_path in utils.os_sorted(zips):
        logger.debug("looking for plugins in %s", plugin_path)
        sys_path = sys.path.copy()
        try:
            sys.path.append(str(plugin_path))
            for plugin in _find_local_plugins(plugin_path):
                logger.debug("Attempting to load %s from %s", plugin.entry_point.name, plugin.path)
                ret.append(plugin.load())
        except Exception as err:
            logger.exception(FailedToLoadPlugin(plugin_path.name, err))
        finally:
            sys.path = sys_path
            for mod in list(sys.modules.values()):
                if (
                    mod is not None
                    and hasattr(mod, "__spec__")
                    and mod.__spec__
                    and str(plugin_path) in (mod.__spec__.origin or "")
                ):
                    sys.modules.pop(mod.__name__)

    return _classify_plugins(ret)


def _classify_plugins(plugins: list[LoadedPlugin]) -> Plugins:
    archivers = []
    tags = []
    talkers = []

    for p in plugins:
        if p.plugin.entry_point.group == "comictagger.talker":
            talkers.append(p)
        elif p.plugin.entry_point.group == "comicapi.tags":
            tags.append(p)
        elif p.plugin.entry_point.group == "comicapi.archiver":
            archivers.append(p)
        else:
            logger.warning(NotImplementedError(f"what plugin type? {p}"))

    return Plugins(
        tags=tags,
        archivers=archivers,
        talkers=talkers,
    )
