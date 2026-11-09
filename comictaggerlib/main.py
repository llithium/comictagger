"""A python app to (automatically) tag comic archives"""

#
# Copyright 2012-2014 ComicTagger Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import argparse
import importlib.metadata as importlib_metadata
import json
import locale
import logging
import logging.handlers
import os
import pathlib
import shlex
import signal
import subprocess
import sys
from collections.abc import Collection, Iterable
from typing import cast

import settngs

import comicapi.comicarchive
import comicapi.utils
import comictalker
from comictaggerlib import cli, ctsettings, pillow_plugins
from comictaggerlib.ctsettings import ComicTaggerPaths, ct_ns, plugin_finder
from comictaggerlib.ctversion import version
from comictaggerlib.log import setup_logging
from comictaggerlib.resulttypes import Action
from comictalker.comictalker import ComicTalker

logger = logging.getLogger("comictagger")


logger.setLevel(logging.DEBUG)


def _lang_code_mac() -> str:
    # Adapted from https://github.com/mu-editor/mu for GUI launches without LANG.
    status, output = subprocess.getstatusoutput("defaults read -g AppleLocale")
    if status == 0:
        return output
    logger.warning("Language detection command failed: %r", output)
    return ""


def configure_locale() -> None:
    if sys.platform == "darwin" and "LANG" not in os.environ:
        code = _lang_code_mac()
        if code:
            os.environ["LANG"] = f"{code}.utf-8"

    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        locale.setlocale(locale.LC_ALL, "C")
        logger.error("Couldn't set the locale: unsupported locale setting; falling back to 'C' locale")
    sys.stdout.reconfigure(encoding=sys.getdefaultencoding())  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding=sys.getdefaultencoding())  # type: ignore[union-attr]
    sys.stdin.reconfigure(encoding=sys.getdefaultencoding())  # type: ignore[union-attr]


def configure_rar_search_path() -> None:
    if comicapi.utils.which("rar"):
        return
    if sys.platform == "win32":
        drives = ("C", "D") if pathlib.Path("D:/").exists() else ("C",)
        for drive in drives:
            comicapi.utils.add_to_path(rf"{drive}:\Program Files\WinRAR")
            comicapi.utils.add_to_path(rf"{drive}:\Program Files (x86)\WinRAR")
        return
    if sys.platform == "darwin":
        try:
            result = subprocess.run(("/usr/libexec/path_helper", "-s"), capture_output=True, text=True, check=True)
            tokens = shlex.split(result.stdout)
            if tokens and tokens[0].startswith("PATH="):
                for directory in reversed(tokens[0].removeprefix("PATH=").rstrip(";").split(os.pathsep)):
                    comicapi.utils.add_to_path(directory)
        except (OSError, subprocess.CalledProcessError, ValueError):
            logger.debug("Could not read the system search path", exc_info=True)
        comicapi.utils.add_to_path("/opt/homebrew/bin")


def update_publishers(config: settngs.Config[ct_ns]) -> None:
    json_file = config[0].Runtime_Options__config.user_config_dir / "publishers.json"
    if json_file.exists():
        try:
            comicapi.utils.update_publishers(json.loads(json_file.read_text("utf-8")))
        except Exception as e:
            logger.exception("Failed to load publishers from %s: %s", json_file, e)


class App:
    def __init__(self) -> None:
        self.config: settngs.Config[ct_ns]
        self.config_load_success = False
        self.talkers: dict[str, ComicTalker] = {}
        self.metron_location = ""

    def run(self) -> None:
        configure_locale()
        pillow_plugins.register()
        conf = self.initialize()
        self.initialize_dirs(conf.config)
        self.load_plugins(conf)
        self.register_settings(conf.enable_quick_tag)
        self.config = self.parse_settings(conf.config)
        configure_rar_search_path()

        self.main()

    def load_plugins(self, opts: argparse.Namespace) -> None:
        local_plugins = plugin_finder.find_plugins(opts.config.user_plugin_dir)

        comicapi.comicarchive.load_archive_plugins(local_plugins=[p.implementation for p in local_plugins.archivers])
        comicapi.comicarchive.load_tag_plugins(
            version=version, local_plugins=[p.implementation for p in local_plugins.tags]
        )
        self.talkers, self.metron_location = comictalker.get_talkers(
            version, opts.config.user_cache_dir, local_plugins=local_plugins.talkers
        )

    def list_plugins(
        self,
        talkers: Collection[comictalker.ComicTalker],
        archivers: Collection[type[comicapi.comicarchive.Archiver]],
        tags: Collection[comicapi.comicarchive.Tag],
    ) -> None:
        def show(title: str, row_format: str, rows: Iterable[dict[str, str | bool]]) -> None:
            if not self.config[0].Runtime_Options__json:
                print(title)  # noqa: T201
            for row in rows:
                if self.config[0].Runtime_Options__json:
                    print(json.dumps(row))  # noqa: T201
                else:
                    print(row_format.format_map(row))  # noqa: T201

        def archive_rows() -> Iterable[dict[str, str | bool]]:
            for archiver in archivers:
                try:
                    archive = archiver()
                    enabled, name, extension, executable = (
                        archive.enabled,
                        archive.name(),
                        archive.extension(),
                        archive.exe,
                    )
                except Exception:
                    logger.exception("Failed to inspect archive plugin: %s", archiver)
                    enabled, name, extension, executable = archiver.enabled, "", "", archiver.exe
                yield {"type": "archiver", "enabled": enabled, "name": name, "extension": extension, "exe": executable}

        show(
            "Metadata Sources: (ID: Name, URL)",
            "{id:<10}: {name:<21}, {website}",
            ({"type": "talker", "id": talker.id, "name": talker.name, "website": talker.website} for talker in talkers),
        )
        show(
            "\nComic Archive: (Enabled, Name: extension, exe)",
            "{enabled!s:<5}, {name:<10}: {extension:<5}, {exe}",
            archive_rows(),
        )
        show(
            "\nTags: (Enabled, ID: Name)",
            "{enabled!s:<5}, {id:<10}: {name}",
            ({"type": "tag", "enabled": tag.enabled, "name": tag.name(), "id": tag.id} for tag in tags),
        )

    def initialize(self) -> argparse.Namespace:
        conf, _ = ctsettings.initial_commandline_parser().parse_known_intermixed_args()
        setup_logging(conf.verbose, conf.config.user_log_dir)
        return conf

    def register_settings(self, enable_quick_tag: bool) -> None:
        self.archiver_executables = {
            archiver: getattr(archiver, "default_exe", os.path.basename(archiver.exe))
            for archiver in comicapi.comicarchive.archivers
            if archiver.exe
        }
        self.manager = ctsettings.create_manager(
            enable_quick_tag=enable_quick_tag,
            archiver_executables=self.archiver_executables,
            tags=comicapi.comicarchive.tags,
            talkers=self.talkers,
        )

    def parse_settings(self, config_paths: ComicTaggerPaths, *args: str) -> settngs.Config[ct_ns]:
        cfg, self.config_load_success = ctsettings.parse_config(
            self.manager, config_paths.settings_file, list(args) or None
        )
        config = cast(settngs.Config[ct_ns], self.manager.get_namespace(cfg, file=True, cmdline=True))
        config[0].Runtime_Options__config = config_paths

        config = ctsettings.validate_commandline_settings(config, self.manager, comicapi.comicarchive.tags)
        config = ctsettings.validate_file_settings(config)
        ctsettings.apply_archive_settings(config, self.archiver_executables)
        return ctsettings.validate_talker_settings(config, self.talkers)

    def initialize_dirs(self, paths: ComicTaggerPaths) -> None:
        paths.user_config_dir.mkdir(parents=True, exist_ok=True)
        paths.user_cache_dir.mkdir(parents=True, exist_ok=True)
        paths.user_log_dir.mkdir(parents=True, exist_ok=True)
        paths.user_plugin_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("user_config_dir: %s", paths.user_config_dir)
        logger.debug("user_cache_dir: %s", paths.user_cache_dir)
        logger.debug("user_log_dir: %s", paths.user_log_dir)
        logger.debug("user_plugin_dir: %s", paths.user_plugin_dir)

    def main(self) -> None:
        error = None

        if not self.talkers:
            error = (
                "Failed to load any talkers, please re-install and check the log located in '"
                + str(self.config[0].Runtime_Options__config.user_log_dir)
                + "' for more details",
                True,
            )

        signal.signal(signal.SIGINT, signal.SIG_DFL)

        logger.debug("Installed Packages")
        for pkg in sorted(importlib_metadata.distributions(), key=lambda x: x.name):
            logger.debug("%s\t%s", pkg.metadata["Name"], pkg.metadata["Version"])

        comicapi.utils.load_publishers()
        update_publishers(self.config)

        if self.config[0].Commands__command == Action.list_plugins:
            self.list_plugins(
                list(self.talkers.values()),
                comicapi.comicarchive.archivers,
                comicapi.comicarchive.tags.values(),
            )
            return

        if self.config[0].Commands__command == Action.save_config and self.config_load_success:
            settings_path = self.config[0].Runtime_Options__config.settings_file
            if not ctsettings.save_file(self.config, settings_path):
                raise SystemExit(1)
            print("Settings saved")  # noqa: T201
            return

        if not self.config_load_success:
            error = (
                "Failed to load settings, check the log located in '"
                + str(self.config[0].Runtime_Options__config.user_log_dir)
                + "' for more details",
                True,
            )

        if not self.config[0].Runtime_Options__no_gui:
            if self.metron_location:
                error = (
                    f"Metron is no longer supported please remove the metron plugin: {self.metron_location}.\n\nSee https://github.com/comictagger/comictagger/issues/783 for more details.",
                    True,
                )
            try:
                import comictaggerlib.graphics.resources  # noqa: F401
                from comictaggerlib import gui

                if not gui.qt_available:
                    raise gui.import_error
                return gui.open_tagger_window(self.talkers, self.config, error)
            except ImportError:
                self.config[0].Runtime_Options__no_gui = True
                logger.warning("PyQt6 is not available. ComicTagger is limited to command-line mode.")

        if self.metron_location:
            print(  # noqa: T201
                f"Metron is no longer supported please remove the metron plugin: {self.metron_location}.\nSee https://github.com/comictagger/comictagger/issues/783 for more details.",
                True,
            )
            raise SystemExit(9)
        if error and error[1]:
            print(f"A fatal error occurred please check the log for more information: {error[0]}")  # noqa: T201
            raise SystemExit(1)

        try:
            raise SystemExit(cli.CLI(self.config[0], self.talkers).run())
        except Exception:
            logger.exception("CLI mode failed")
            raise SystemExit(1)


def main() -> None:
    App().run()
