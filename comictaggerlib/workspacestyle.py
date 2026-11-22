"""Drawing helpers and cover thumbnails shared by the editor's file list and the Auto-Tag review."""

from __future__ import annotations

import logging
import pathlib
from typing import Protocol

from PyQt6 import QtCore, QtGui, QtWidgets

from comicapi.comicarchive import ComicArchive

logger = logging.getLogger(__name__)

# Light palette; TaggerWindow.apply_workspace_style passes the live palette (light or dark) to each widget.
DEFAULT_COLORS = {
    "canvas": "#f1f2f5",
    "surface": "#ffffff",
    "ink": "#1f2330",
    "muted": "#5d6473",
    "edge": "#d9dce3",
    "accent": "#2f5bd3",
    "onAccent": "#ffffff",
    "wash": "#e7e9ee",
    "selection": "#dbe5fb",
    "accSoft": "#e3eafc",
    "ok": "#1f8a4c",
    "okSoft": "#e2f4ea",
    "warn": "#9a5c00",
    "warnSoft": "#fdf0d9",
    "bad": "#c23b3b",
    "badSoft": "#fbe5e5",
}


class HasColors(Protocol):
    colors: dict[str, str]


def set_property(widget: QtWidgets.QWidget, name: str, value: object) -> None:
    """Change a property that the stylesheet selects on, and repaint with the new style."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)


def chip(text: str = "", tone: str = "warn") -> QtWidgets.QLabel:
    """A small rounded status label; the stylesheet colours it by its "tone" property."""
    label = QtWidgets.QLabel(text)
    label.setObjectName("chip")
    label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    label.setProperty("tone", tone)
    label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Fixed)
    return label


def section_label(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text.upper())
    label.setObjectName("sectionLabel")
    return label


class Painter:
    """Row backgrounds and status chips for list delegates, coloured from ``owner.colors``."""

    def __init__(self, owner: HasColors) -> None:
        self.owner = owner

    def color(self, name: str) -> QtGui.QColor:
        return QtGui.QColor(self.owner.colors.get(name, DEFAULT_COLORS.get(name, "#808080")))

    def background(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, inset: int) -> None:
        rect = QtCore.QRectF(option.rect.adjusted(inset, 1, -inset, -1))
        state = option.state
        if state & QtWidgets.QStyle.StateFlag.State_Selected:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(self.color("selection"))
            painter.drawRoundedRect(rect, 6, 6)
        elif state & QtWidgets.QStyle.StateFlag.State_MouseOver:
            hover = self.color("selection")
            hover.setAlpha(110)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(hover)
            painter.drawRoundedRect(rect, 6, 6)
        if state & QtWidgets.QStyle.StateFlag.State_HasFocus:
            pen = QtGui.QPen(self.color("accent"))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)

    def chip(self, painter: QtGui.QPainter, x: float, y: float, text: str, tone: str, font: QtGui.QFont) -> float:
        """Draw a chip with its top-left corner at (x, y) and return its width."""
        small = QtGui.QFont(font)
        small.setPointSizeF(max(font.pointSizeF() * 0.85, 7))
        small.setBold(True)
        metrics = QtGui.QFontMetricsF(small)
        rect = QtCore.QRectF(x, y, metrics.horizontalAdvance(text) + 16, metrics.height() + 4)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self.color(tone + "Soft"))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setPen(self.color(tone))
        painter.setFont(small)
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)
        return rect.width()

    def thumbnail(self, painter: QtGui.QPainter, rect: QtCore.QRect, pixmap: QtGui.QPixmap | None) -> None:
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                rect.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            painter.save()
            painter.setClipRect(rect)
            painter.drawPixmap(rect.topLeft(), scaled)
            painter.restore()
        else:
            painter.fillRect(rect, self.color("edge"))


class _ThumbnailSignals(QtCore.QObject):
    loaded = QtCore.pyqtSignal(str, QtGui.QImage)


class _ThumbnailJob(QtCore.QRunnable):
    def __init__(self, path: pathlib.Path, height: int, signals: _ThumbnailSignals) -> None:
        super().__init__()
        self.path = path
        self.height = height
        self.signals = signals

    def run(self) -> None:
        image = QtGui.QImage()
        try:
            # A fresh archive object, so this thread never shares a file handle with the editor.
            data = ComicArchive(self.path).get_page(0)
            image = QtGui.QImage.fromData(data) if data else QtGui.QImage()
            if not image.isNull():
                image = image.scaledToHeight(self.height, QtCore.Qt.TransformationMode.SmoothTransformation)
        except Exception:
            logger.debug("No thumbnail for %s", self.path, exc_info=True)
        try:
            self.signals.loaded.emit(str(self.path), image)
        except RuntimeError:
            pass  # the list was closed while this cover was loading


class ThumbnailCache(QtCore.QObject):
    """Cover thumbnails read on a background thread; ``changed`` fires when one arrives."""

    changed = QtCore.pyqtSignal()

    def __init__(self, parent: QtCore.QObject, height: int = 120) -> None:
        super().__init__(parent)
        self.height = height
        self._pixmaps: dict[str, QtGui.QPixmap] = {}
        self._pending: set[str] = set()
        self._pool = QtCore.QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _ThumbnailSignals(self)
        self._signals.loaded.connect(self._loaded)

    def get(self, path: pathlib.Path) -> QtGui.QPixmap | None:
        key = str(path)
        if key in self._pixmaps:
            return self._pixmaps[key]
        if key not in self._pending:
            self._pending.add(key)
            self._pool.start(_ThumbnailJob(path, self.height, self._signals))
        return None

    def forget(self, path: pathlib.Path) -> None:
        self._pixmaps.pop(str(path), None)

    def clear(self) -> None:
        self._pixmaps.clear()

    def wait(self, msecs: int = 5000) -> bool:
        return self._pool.waitForDone(msecs)

    def _loaded(self, key: str, image: QtGui.QImage) -> None:
        self._pending.discard(key)
        self._pixmaps[key] = QtGui.QPixmap.fromImage(image) if not image.isNull() else QtGui.QPixmap()
        self.changed.emit()
