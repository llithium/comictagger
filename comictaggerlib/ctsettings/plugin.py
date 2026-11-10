from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from functools import partial
from typing import Any, cast

import settngs

from comicapi.archivers import Archiver
from comictaggerlib.ctsettings.settngs_namespace import SettngsNS as ct_ns
from comictalker.comictalker import ComicTalker

logger = logging.getLogger("comictagger")
ARCHIVE_GROUP = "Archive"


def group_for_plugin(talker: ComicTalker) -> str:
    return f"Source {talker.id}"


def archiver_executable(archiver: type[Archiver]) -> str:
    """Use the closest declaration of an executable or its stable default."""
    for owner in archiver.__mro__:
        default = vars(owner).get("default_exe")
        if isinstance(default, str):
            return default
        if "exe" in vars(owner):
            break
    return os.path.basename(archiver.exe)


def register_archive_settings(manager: settngs.Manager, executables: Mapping[type[Archiver], str]) -> None:
    options = {settngs.sanitize_name(exe): exe for exe in executables.values()}
    for name, exe in options.items():
        manager.add_setting(f"--{name}", default=exe, help="Path to the %(default)s executable")


def register_talker_settings(manager: settngs.Manager, talkers: Mapping[str, ComicTalker]) -> None:
    for talker in talkers.values():

        def api_options(manager: settngs.Manager) -> None:
            # The default needs to be unset or None.
            # This allows this setting to be unset with the empty string, allowing the default to change
            manager.add_setting(
                f"--{talker.id}-key",
                display_name="API Key",
                help=f"API Key for {talker.name} (default: {talker.default_api_key})",
            )
            manager.add_setting(
                f"--{talker.id}-url",
                display_name="URL",
                help=f"URL for {talker.name} (default: {talker.default_api_url})",
            )

        try:
            group = group_for_plugin(talker)
            manager.add_persistent_group(group, api_options, False)
            if hasattr(talker, "register_settings"):
                manager.add_persistent_group(group, talker.register_settings, False)
        except Exception:
            logger.exception("Failed to register settings for %s", talker.id)


def apply_archive_settings(config: settngs.Config[ct_ns], executables: Mapping[type[Archiver], str]) -> None:
    cfg = settngs.normalize_config(config, file=True, cmdline=True)
    options = cfg.values.get(ARCHIVE_GROUP, {})
    for archiver, executable in executables.items():
        path = options.get(settngs.sanitize_name(executable)) or executable
        archiver.exe = os.path.abspath(path) if os.path.basename(path) != path else path


def validate_talker_settings(config: settngs.Config[ct_ns], talkers: dict[str, ComicTalker]) -> settngs.Config[ct_ns]:
    cfg = cast(settngs.Config[dict[str, Any]], settngs.normalize_config(config, True, True))
    for name, talker in list(talkers.items()):
        try:
            group = group_for_plugin(talker)
            cfg[0][group] = talker.parse_settings(cfg[0][group])
        except Exception:
            del talkers[name]
            logger.exception("Failed to initialize talker settings for %s", name)

    return cast(settngs.Config[ct_ns], settngs.get_namespace(cfg, file=True, cmdline=True))


def register_plugin_settings(
    manager: settngs.Manager, executables: Mapping[type[Archiver], str], talkers: Mapping[str, ComicTalker]
) -> None:
    manager.add_persistent_group(ARCHIVE_GROUP, partial(register_archive_settings, executables=executables), False)
    register_talker_settings(manager, talkers)
