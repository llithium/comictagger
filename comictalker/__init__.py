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

    def load_supported_talker(name: str, implementation: type[ComicTalker]) -> ComicTalker | None:
        if name == "metron" or "metron" in implementation.__module__.casefold():
            return None
        talker = implementation(version, cache)
        return None if "metron" in talker.website.casefold() else talker

    for entry in entry_points(group=TALKER_ENTRY_POINT):
        try:
            talker = load_supported_talker(entry.name, entry.load())
            if talker is None:
                if entry.dist and not metron_location:
                    metron_location = f"pip package {entry.dist.name}"
                else:
                    metron_location = f"python module {entry.module}"
                continue
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
                talker = load_supported_talker(name, plugin.implementation)
                if talker is None:
                    local_metron_location = f"Local package {plugin.path.absolute()}"
                    continue
                talker_id = plugin.implementation.id
            else:
                name = talker_id = plugin.id
                talker = plugin(version, cache)
            talkers[talker_id] = talker
        except Exception:
            logger.exception("Failed to load talker: %s", name)

    return talkers, metron_location or local_metron_location
