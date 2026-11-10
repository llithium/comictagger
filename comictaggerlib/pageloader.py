"""A PyQt6 class to load a page image in a background thread."""

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

from PyQt6 import QtCore

from comicapi.comicarchive import ComicArchive


class PageLoader(QtCore.QThread):
    loadComplete = QtCore.pyqtSignal(bytes)
    # Qt aborts if a running QThread loses its last reference.
    _active: set[PageLoader] = set()

    def __init__(self, ca: ComicArchive, page_num: int) -> None:
        super().__init__()
        self.ca: ComicArchive = ca
        self.page_num: int = page_num
        self._active.add(self)
        self.finished.connect(self._release)

    def run(self) -> None:
        self.loadComplete.emit(self.ca.get_page(self.page_num))

    @QtCore.pyqtSlot()
    def _release(self) -> None:
        self._active.discard(self)
        self.deleteLater()
