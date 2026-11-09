"""A PyQt6 widget to display cover images

Display cover images from either a local archive, or from comic source metadata.
TODO: This should be re-factored using subclasses!
"""

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

import logging
import pathlib

from PyQt6 import QtCore, QtGui, QtNetwork, QtWidgets, uic

from comicapi.comicarchive import ComicArchive
from comictaggerlib.imagefetcher import USER_AGENT, ImageFetcher
from comictaggerlib.imagepopup import ImagePopup
from comictaggerlib.pageloader import PageLoader
from comictaggerlib.ui import ui_path
from comictaggerlib.ui.qtutils import get_qimage_from_data

logger = logging.getLogger(__name__)


def clickable(widget: QtWidgets.QWidget) -> QtCore.pyqtBoundSignal:
    """Allow a label to be clickable"""

    class Filter(QtCore.QObject):
        dblclicked = QtCore.pyqtSignal()

        def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
            if obj == widget:
                if event.type() == QtCore.QEvent.Type.MouseButtonDblClick:
                    self.dblclicked.emit()
                    return True
            return False

    flt = Filter(widget)
    widget.installEventFilter(flt)
    return flt.dblclicked


class CoverImageWidget(QtWidgets.QWidget):
    ArchiveMode = 0
    AltCoverMode = 1
    URLMode = 2
    DataMode = 3

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        mode: int,
        cache_folder: pathlib.Path | None,
        blur: bool = False,
        expand_on_click: bool = True,
    ) -> None:
        super().__init__(parent)

        self.cover_fetcher: ImageFetcher | None = None
        self.cover_network: QtNetwork.QNetworkAccessManager | None = None
        with (ui_path / "coverimagewidget.ui").open(encoding="utf-8") as uifile:
            uic.loadUi(uifile, self)

        self.cache_folder = cache_folder
        self.mode: int = mode
        self.page_loader: PageLoader | None = None
        self.showControls = True
        self.blur = blur
        self.scene = QtWidgets.QGraphicsScene(parent=self)

        self.current_pixmap = QtGui.QPixmap()

        self.comic_archive: ComicArchive | None = None
        self.url_list: list[str] = []
        self.imageIndex = -1
        self.imageCount = 1
        self.imageData = b""

        self.btnLeft.setIcon(QtGui.QIcon(":/graphics/left.png"))
        self.btnRight.setIcon(QtGui.QIcon(":/graphics/right.png"))

        self.btnLeft.clicked.connect(self.decrement_image)
        self.btnRight.clicked.connect(self.increment_image)
        if expand_on_click:
            clickable(self.graphicsView).connect(self.show_popup)
        else:
            self.graphicsView.setToolTip("")
        self.graphicsView.setScene(self.scene)

        self.update_content()

    def reset_widget(self) -> None:
        self.comic_archive = None
        self.url_list = []
        self.page_loader = None
        self.imageIndex = -1
        self.imageCount = 1
        self.imageData = b""

    def clear(self) -> None:
        self.reset_widget()
        self.update_content()

    def increment_image(self) -> None:
        self.imageIndex += 1
        if self.imageIndex == self.imageCount:
            self.imageIndex = 0
        self.update_content()

    def decrement_image(self) -> None:
        self.imageIndex -= 1
        if self.imageIndex == -1:
            self.imageIndex = self.imageCount - 1
        self.update_content()

    def set_archive(self, ca: ComicArchive, page: int = 0) -> None:
        if self.mode == CoverImageWidget.ArchiveMode:
            self.reset_widget()
            self.comic_archive = ca
            self.imageIndex = page
            self.imageCount = ca.get_number_of_pages()
            self.update_content()

    def set_url(self, url: str) -> None:
        if self.mode == CoverImageWidget.URLMode:
            self.set_url_list([url] if url else [])

    def set_image_data(self, image_data: bytes) -> None:
        if self.mode == CoverImageWidget.DataMode:
            self.reset_widget()

            if image_data:
                self.imageIndex = 0
                self.imageData = image_data
            else:
                self.imageIndex = -1

            self.update_content()

    def set_url_list(self, url_list: list[str]) -> None:
        if self.mode not in (self.URLMode, self.AltCoverMode):
            return
        self.reset_widget()
        self.url_list = list(url_list)
        self.imageIndex = 0 if url_list else -1
        self.imageCount = len(self.url_list)
        self.update_content()

    def set_page(self, pagenum: int) -> None:
        if self.mode == CoverImageWidget.ArchiveMode:
            self.imageIndex = pagenum
            self.update_content()

    def update_content(self) -> None:
        self.update_image()
        self.update_controls()

    def update_image(self) -> None:
        if self.imageIndex == -1:
            self.load_default()
        elif self.mode in [CoverImageWidget.AltCoverMode, CoverImageWidget.URLMode]:
            self.load_url()
        elif self.mode == CoverImageWidget.DataMode:
            self.cover_remote_fetch_complete("", self.imageData)
        else:
            self.load_page()

    def update_controls(self) -> None:
        if not self.showControls or self.mode == CoverImageWidget.DataMode:
            self.btnLeft.hide()
            self.btnRight.hide()
            self.label.hide()
            return

        if self.imageIndex == -1 or self.imageCount == 1:
            self.btnLeft.setEnabled(False)
            self.btnRight.setEnabled(False)
            self.btnLeft.hide()
            self.btnRight.hide()
        else:
            self.btnLeft.setEnabled(True)
            self.btnRight.setEnabled(True)
            self.btnLeft.show()
            self.btnRight.show()

        if self.imageIndex == -1 or self.imageCount == 1:
            self.label.setText("")
        elif self.mode == CoverImageWidget.AltCoverMode:
            self.label.setText(f"Cover {self.imageIndex + 1} (of {self.imageCount})")
        else:
            self.label.setText(f"Page {self.imageIndex + 1} (of {self.imageCount})")

    def load_url(self) -> None:
        self.load_default()
        url = self.url_list[self.imageIndex]
        if not url or self.cache_folder is None:
            return
        if self.cover_fetcher is None:
            self.cover_fetcher = ImageFetcher(self.cache_folder)
        if data := self.cover_fetcher.get_image_from_cache(url):
            self.cover_remote_fetch_complete(url, data)
            return

        if self.cover_network is None:
            self.cover_network = QtNetwork.QNetworkAccessManager(self)
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        request.setHeader(request.KnownHeaders.UserAgentHeader, USER_AGENT)
        reply = self.cover_network.get(request)
        reply.finished.connect(lambda: self._finish_cover_request(url, reply))

    def _finish_cover_request(self, url: str, reply: QtNetwork.QNetworkReply) -> None:
        try:
            if reply.error() != QtNetwork.QNetworkReply.NetworkError.NoError:
                logger.debug("Cover request failed for %s: %s", url, reply.errorString())
                return
            assert self.cover_fetcher is not None
            if data := self.cover_fetcher.add_image_to_cache(url, reply.readAll().data()):
                self.cover_remote_fetch_complete(url, data)
        finally:
            reply.deleteLater()

    def cover_remote_fetch_complete(self, url: str, image_data: bytes) -> None:
        if url and (not 0 <= self.imageIndex < len(self.url_list) or self.url_list[self.imageIndex] != url):
            return
        img = get_qimage_from_data(image_data)
        self.current_pixmap = QtGui.QPixmap.fromImage(img)
        self.set_display_pixmap()

    def load_page(self) -> None:
        if self.comic_archive is None:
            return
        self.page_loader = PageLoader(self.comic_archive, self.imageIndex)
        self.page_loader.loadComplete.connect(self.page_load_complete)
        self.page_loader.start()

    @QtCore.pyqtSlot(bytes)
    def page_load_complete(self, image_data: bytes) -> None:
        if self.sender() is not self.page_loader:
            return
        img = get_qimage_from_data(image_data)
        self.current_pixmap = QtGui.QPixmap.fromImage(img)
        self.set_display_pixmap()
        self.page_loader = None

    def load_default(self) -> None:
        self.current_pixmap = QtGui.QPixmap(":/graphics/nocover.png")
        self.set_display_pixmap()

    def resizeEvent(self, resize_event: QtGui.QResizeEvent) -> None:
        if self.current_pixmap is not None:
            self.set_display_pixmap()

    def set_display_pixmap(self) -> None:
        """The deltas let us know what the new width and height of the label will be"""

        new_w = self.frame.width()
        new_h = self.frame.height()
        frame_w = self.frame.width()
        frame_h = self.frame.height()

        new_h -= 8
        new_w -= 8

        new_h = max(new_h, 0)
        new_w = max(new_w, 0)

        # scale the pixmap to fit in the frame
        scaled_pixmap = self.current_pixmap.scaled(
            new_w, new_h, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation
        )
        self.scene.clear()
        qpix = self.scene.addPixmap(scaled_pixmap)
        assert qpix
        if self.blur:
            blur = QtWidgets.QGraphicsBlurEffect(parent=self)
            blur.setBlurHints(QtWidgets.QGraphicsBlurEffect.BlurHint.PerformanceHint)
            blur.setBlurRadius(30)
            qpix.setGraphicsEffect(blur)

        # move and resize the label to be centered in the fame
        img_w = scaled_pixmap.width()
        img_h = scaled_pixmap.height()
        self.scene.setSceneRect(0, 0, img_w, img_h)
        self.graphicsView.resize(img_w + 2, img_h + 2)
        self.graphicsView.move(int((frame_w - img_w) / 2), int((frame_h - img_h) / 2))

    def show_popup(self) -> None:
        ImagePopup(self, self.current_pixmap)
