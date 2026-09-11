"""Tests for the locally maintained behavior of ComicTagger's bundled toast widget.

The widget is vendored in this repository. These tests cover the application
contract around visibility, queueing, positioning, and notification presets;
they are not a general upstream getter/setter inventory.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QMainWindow

from comictaggerlib.ui.pyqttoast import Toast, ToastPosition, ToastPreset
from comictaggerlib.ui.pyqttoast.constants import (
    DEFAULT_BACKGROUND_COLOR,
    DEFAULT_BACKGROUND_COLOR_DARK,
    DROP_SHADOW_SIZE,
    WARNING_ACCENT_COLOR,
)


@pytest.fixture(autouse=True)
def reset_toast_state() -> None:
    Toast.reset()


def test_count_methods(qtbot):
    for _ in range(5):
        toast = Toast()
        qtbot.addWidget(toast)
        toast.show()

    assert Toast.getCount() == 5
    assert Toast.getVisibleCount() == 3
    assert Toast.getQueuedCount() == 2


def test_set_maximum_on_screen(qtbot):
    Toast.setMaximumOnScreen(2)
    toasts = [Toast() for _ in range(5)]
    for toast in toasts:
        qtbot.addWidget(toast)
        toast.show()

    assert [toast.isVisible() for toast in toasts] == [True, True, False, False, False]


def test_set_maximum_on_screen_while_toasts_are_shown(qtbot):
    Toast.setMaximumOnScreen(2)
    toasts = [Toast() for _ in range(5)]
    for toast in toasts:
        qtbot.addWidget(toast)
        toast.show()

    Toast.setMaximumOnScreen(4)

    assert [toast.isVisible() for toast in toasts] == [True, True, True, True, False]


def test_set_spacing(qtbot):
    Toast.setSpacing(50)
    toast_1 = Toast()
    toast_2 = Toast()
    toast_1.setFadeInDuration(0)
    toast_2.setFadeInDuration(0)
    for toast in (toast_1, toast_2):
        qtbot.addWidget(toast)
        toast.show()
    qtbot.wait(250)

    spacing = toast_1.pos().y() - toast_2.pos().y() - toast_2.height() + 2 * DROP_SHADOW_SIZE
    assert spacing == 50


def test_set_offset(qtbot):
    Toast.setOffset(130, 140)
    toast = Toast()
    toast.setFadeInDuration(0)
    qtbot.addWidget(toast)
    toast.show()
    qtbot.wait(250)

    screen = QGuiApplication.primaryScreen()
    offset_x = screen.geometry().width() - toast.pos().x() - toast.width() + DROP_SHADOW_SIZE
    offset_y = screen.geometry().height() - toast.pos().y() - toast.height() + DROP_SHADOW_SIZE

    assert (offset_x, offset_y) == (130, 140)


def test_set_position_relative_to_widget(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    Toast.setPositionRelativeToWidget(window)
    Toast.setOffset(0, 0)
    toast = Toast()
    toast.setFadeInDuration(0)
    qtbot.addWidget(toast)
    toast.show()
    qtbot.wait(250)

    assert toast.x() == window.x() + window.width() - toast.width() + DROP_SHADOW_SIZE


def test_set_move_position_with_widget(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    Toast.setPositionRelativeToWidget(window)
    Toast.setOffset(0, 0)
    toast = Toast()
    toast.setFadeInDuration(0)
    qtbot.addWidget(toast)
    toast.show()
    window.show()
    qtbot.wait(250)

    initial_position = toast.pos()
    window.move(100, 100)
    qtbot.wait(250)
    moved_position = toast.pos()
    assert moved_position != initial_position

    Toast.setMovePositionWithWidget(False)
    window.move(250, 250)
    qtbot.wait(250)
    assert toast.pos() == moved_position


def test_set_always_on_main_screen(qtbot):
    Toast.setAlwaysOnMainScreen(True)
    toast = Toast()
    toast.setFadeInDuration(0)
    qtbot.addWidget(toast)
    toast.show()
    qtbot.wait(250)

    assert QGuiApplication.primaryScreen().geometry().contains(toast.geometry())


@patch("PyQt6.QtGui.QScreen")
def test_set_fixed_screen(MockedQScreen, qtbot):
    fixed_screen = MockedQScreen()
    fixed_screen.geometry.return_value = QRect(-3840, 0, 1920, 1080)
    Toast.setFixedScreen(fixed_screen)

    toast = Toast()
    toast.setFadeInDuration(0)
    qtbot.addWidget(toast)
    toast.show()
    qtbot.wait(250)

    assert fixed_screen.geometry().contains(toast.geometry())


@pytest.mark.parametrize(
    "position",
    [
        ToastPosition.BOTTOM_LEFT,
        ToastPosition.BOTTOM_MIDDLE,
        ToastPosition.BOTTOM_RIGHT,
        ToastPosition.TOP_LEFT,
        ToastPosition.TOP_MIDDLE,
        ToastPosition.TOP_RIGHT,
        ToastPosition.CENTER,
    ],
)
def test_set_position(position, qtbot):
    Toast.setPosition(position)
    toast = Toast()
    toast.setFadeInDuration(0)
    qtbot.addWidget(toast)
    toast.show()
    qtbot.wait(250)

    screen = QGuiApplication.primaryScreen().geometry()
    if position == ToastPosition.CENTER:
        expected_y = int(screen.y() + screen.height() / 2 - toast.height() / 2)
        expected_x = int(screen.x() + screen.width() / 2 - toast.width() / 2)
    elif position in (ToastPosition.TOP_LEFT, ToastPosition.TOP_MIDDLE, ToastPosition.TOP_RIGHT):
        expected_y = screen.y() + Toast.getOffsetY() - DROP_SHADOW_SIZE
        expected_x = (
            screen.x() + Toast.getOffsetX() - DROP_SHADOW_SIZE
            if position == ToastPosition.TOP_LEFT
            else (
                screen.width() - toast.width() - Toast.getOffsetX() + DROP_SHADOW_SIZE
                if position == ToastPosition.TOP_RIGHT
                else int(screen.x() + screen.width() / 2 - toast.width() / 2)
            )
        )
    else:
        expected_y = screen.height() - Toast.getOffsetY() - toast.height() + DROP_SHADOW_SIZE
        expected_x = (
            screen.x() + Toast.getOffsetX() - DROP_SHADOW_SIZE
            if position == ToastPosition.BOTTOM_LEFT
            else (
                screen.width() - toast.width() - Toast.getOffsetX() + DROP_SHADOW_SIZE
                if position == ToastPosition.BOTTOM_RIGHT
                else int(screen.x() + screen.width() / 2 - toast.width() / 2)
            )
        )

    assert (toast.pos().x(), toast.pos().y()) == (expected_x, expected_y)


def test_reset(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    Toast.setMaximumOnScreen(10)
    Toast.setSpacing(25)
    Toast.setOffset(100, 150)
    Toast.setPositionRelativeToWidget(window)
    Toast.setMovePositionWithWidget(False)
    Toast.setAlwaysOnMainScreen(True)
    Toast.setFixedScreen(QGuiApplication.primaryScreen())
    Toast.setPosition(ToastPosition.CENTER)

    toast = Toast()
    qtbot.addWidget(toast)
    toast.show()
    Toast.reset()

    assert Toast.getMaximumOnScreen() == 3
    assert Toast.getSpacing() == 10
    assert Toast.getOffset() == (20, 45)
    assert Toast.getPositionRelativeToWidget() is None
    assert Toast.isMovePositionWithWidget() is True
    assert Toast.isAlwaysOnMainScreen() is False
    assert Toast.getFixedScreen() is None
    assert Toast.getPosition() == ToastPosition.BOTTOM_RIGHT
    assert Toast.getCount() == 0
    assert Toast.getQueuedCount() == 0
    assert Toast.getVisibleCount() == 0
    assert toast.isVisible() is False


@pytest.mark.parametrize(
    ("preset", "background"),
    [
        (ToastPreset.WARNING, DEFAULT_BACKGROUND_COLOR),
        (ToastPreset.WARNING_DARK, DEFAULT_BACKGROUND_COLOR_DARK),
    ],
)
def test_warning_presets_match_app_notification_contract(preset, background, qtbot):
    toast = Toast()
    toast.applyPreset(preset)
    toast.setTitle("Unable to write Tags")
    toast.setText("Archive is not writeable")
    toast.setDuration(0)
    qtbot.addWidget(toast)
    toast.show()

    assert toast.isVisible() is True
    assert toast.isShowIcon() is True
    assert toast.getIconColor() == WARNING_ACCENT_COLOR
    assert toast.getBackgroundColor() == background


def test_show_twice(qtbot):
    toast = Toast()
    toast.setDuration(100)
    toast.setFadeInDuration(0)
    toast.setFadeOutDuration(0)
    qtbot.addWidget(toast)
    toast.show()

    assert toast.isVisible() is True
    toast.hide()
    qtbot.wait(50)
    assert toast.isVisible() is False
    toast.show()
    assert toast.isVisible() is False


def test_hide(qtbot):
    toast_1 = Toast()
    toast_2 = Toast()
    for toast in (toast_1, toast_2):
        toast.setFadeInDuration(0)
        toast.setFadeOutDuration(0)
        qtbot.addWidget(toast)
        toast.show()

    assert toast_1.isVisible() is True
    assert toast_2.isVisible() is True
    toast_1.hide()
    qtbot.wait(50)
    assert toast_1.isVisible() is False
    assert toast_2.isVisible() is True
