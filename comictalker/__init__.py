from __future__ import annotations

import logging
import pathlib
from collections.abc import Sequence
from importlib.metadata import entry_points

from comicapi.pluginloader import TALKER_ENTRY_POINT, LocalPlugin
from comictalker.comictalker import ComicTalker, TalkerError

logger = logging.getLogger(__name__)

__all__ = [
    "ComicTalker",
    "TalkerError",
]


def get_talkers(
    version: str,
    cache: pathlib.Path,
    local_plugins: Sequence[LocalPlugin[ComicTalker] | type[ComicTalker]] = (),
) -> tuple[dict[str, ComicTalker], str]:
    talkers: dict[str, ComicTalker] = {}
    metron_location = ""

    def is_metron(name: str, talker: type[ComicTalker]) -> bool:
        return name == "metron" or "metron" in talker.website.casefold() or "metron" in talker.__module__.casefold()

    for entry in entry_points(group=TALKER_ENTRY_POINT):
        try:
            talker_cls: type[ComicTalker] = entry.load()
            if is_metron(entry.name, talker_cls):
                if entry.dist and not metron_location:
                    metron_location = f"pip package {entry.dist.name}"
                else:
                    metron_location = f"python module {entry.module}"
                continue
            talker = talker_cls(version, cache)
            if talker.id != entry.name:
                logger.error("Talker ID must be the same as the entry point name")
                continue
            talkers[entry.name] = talker
        except Exception:
            logger.exception("Failed to load talker: %s", entry.name)

    local_metron_location = ""
    for plugin in local_plugins:
        name = "<local plugin>"
        try:
            if isinstance(plugin, LocalPlugin):
                name = plugin.name
                talker_cls = plugin.implementation
                if is_metron(name, talker_cls):
                    local_metron_location = f"Local package {plugin.path.absolute()}"
                    continue
            else:
                talker_cls = plugin
                name = talker_cls.id
            talker = talker_cls(version, cache)
            talkers[talker_cls.id] = talker
        except Exception:
            logger.exception("Failed to load talker: %s", name)

    return talkers, metron_location or local_metron_location
