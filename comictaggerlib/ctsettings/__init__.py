from __future__ import annotations

import json
import logging
import pathlib
from collections.abc import Mapping
from enum import Enum
from typing import Any

import settngs

from comicapi._url import Url
from comicapi.archivers import Archiver
from comicapi.tags import Tag
from comictaggerlib.ctsettings.commandline import (
    initial_commandline_parser,
    register_commandline_settings,
    validate_commandline_settings,
)
from comictaggerlib.ctsettings.file import register_file_settings, validate_file_settings
from comictaggerlib.ctsettings.plugin import (
    apply_archive_settings,
    group_for_plugin,
    register_plugin_settings,
    validate_talker_settings,
)
from comictaggerlib.ctsettings.settngs_namespace import SettngsNS as ct_ns
from comictaggerlib.ctsettings.types import ComicTaggerPaths
from comictalker import ComicTalker

logger = logging.getLogger(__name__)

__all__ = [
    "initial_commandline_parser",
    "validate_commandline_settings",
    "validate_file_settings",
    "apply_archive_settings",
    "validate_talker_settings",
    "ComicTaggerPaths",
    "ct_ns",
    "group_for_plugin",
]


def create_manager(
    *,
    enable_quick_tag: bool,
    archiver_executables: Mapping[type[Archiver], str],
    tags: Mapping[str, Tag],
    talkers: Mapping[str, ComicTalker],
) -> settngs.Manager:
    manager = settngs.Manager(
        description="A utility for reading and writing metadata to comic archives.\n\n\n"
        + "If no options are given, %(prog)s will run in windowed mode.\nPlease keep the '-v' option separated '-so -v' not '-sov'",
        epilog="For more help visit the wiki at: https://github.com/comictagger/comictagger/wiki",
    )
    register_commandline_settings(manager, enable_quick_tag, tags)
    register_file_settings(manager, "cix" if "cix" in tags else "cr")
    register_plugin_settings(manager, archiver_executables, talkers)
    return manager


def _json_setting(value: Any) -> Any:
    # Url is a named tuple, so JSONEncoder.default would not see it.
    if isinstance(value, (pathlib.Path, Url)):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_setting(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_setting(item) for item in value]
    return value


def validate_types(config: settngs.Config[settngs.Values]) -> settngs.Config[settngs.Values]:
    for group in config.definitions.values():
        for setting in group.v.values():
            value, is_default = settngs.get_option(config.values, setting)
            converter = setting.type
            if is_default or converter is None:
                continue
            is_enum = isinstance(converter, type) and issubclass(converter, Enum)
            if is_enum and isinstance(value, list):
                config.values[setting.group][setting.dest] = [converter(item) for item in value]
            elif is_enum or isinstance(value, str):
                config.values[setting.group][setting.dest] = converter(value)
    return config


def parse_config(
    manager: settngs.Manager,
    config_path: pathlib.Path,
    args: list[str] | None = None,
) -> tuple[settngs.Config[settngs.Values], bool]:
    """
    Function to parse options from a json file and passes the resulting Config object to parse_cmdline.

    Args:
        manager: settngs Manager object
        config_path: A `pathlib.Path` object
        args: Passed to argparse.ArgumentParser.parse_args
    """
    file_options, success = settngs.parse_file(manager.definitions, config_path)
    file_options = validate_types(file_options)
    cmdline_options = settngs.parse_cmdline(
        manager.definitions,
        manager.description,
        manager.epilog,
        args,
        file_options,
    )

    final_options = settngs.normalize_config(cmdline_options, file=True, cmdline=True)
    return final_options, success


def save_file(
    config: settngs.Config[settngs.T],
    filename: pathlib.Path,
) -> bool:
    """
    Helper function to save options from a json dictionary to a file

    Args:
        config: The options to save to a json dictionary
        filename: A pathlib.Path object to save the json dictionary to
    """
    file_options = settngs.clean_config(config, file=True)
    try:
        json_str = json.dumps(_json_setting(file_options), indent=2)
        filename.parent.mkdir(exist_ok=True, parents=True)
        filename.write_text(json_str + "\n", encoding="utf-8")
    except Exception:
        logger.exception("Failed to save config file: %s", filename)
        return False
    return True
