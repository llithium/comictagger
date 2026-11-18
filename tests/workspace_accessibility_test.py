from __future__ import annotations

import pytest

QtCore = pytest.importorskip("PyQt6.QtCore")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


@pytest.mark.parametrize("return_from_pages", [False, True], ids=["startup", "after-last-archive"])
def test_opening_blank_editor_moves_keyboard_focus_to_series(workspace, qtbot, tmp_comic, return_from_pages):
    if return_from_pages:
        workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(tmp_comic.path)))
        qtbot.waitUntil(lambda: workspace.comic_archive is not None)
        workspace.tabWidget.setCurrentWidget(workspace.tabPages)
        workspace.fileSelectionList.remove_selection()
        assert workspace.welcome.isVisible()

    blank = workspace.welcome.findChild(QtWidgets.QPushButton, "blankEditor")
    blank.setFocus()
    qtbot.keyClick(blank, QtCore.Qt.Key.Key_Space)

    assert workspace.tabWidget.currentWidget() is workspace.tab
    assert workspace.leSeries.hasFocus()
    qtbot.keyClicks(workspace.focusWidget(), "Keyboard draft")
    assert workspace.leSeries.text() == "Keyboard draft"
    workspace.dirty_flag = False


def test_workspace_toolbar_can_be_operated_with_tab_and_space(workspace, qtbot, monkeypatch):
    button = workspace.toolBar.widgetForAction(workspace.actionLoad)
    blank = workspace.welcome.findChild(QtWidgets.QPushButton, "blankEditor")
    blank.setFocus()
    qtbot.keyClick(blank, QtCore.Qt.Key.Key_Space)

    assert button.focusPolicy() == QtCore.Qt.FocusPolicy.TabFocus
    if QtWidgets.QApplication.styleHints().tabFocusBehavior() == QtCore.Qt.TabFocusBehavior.TabFocusAllControls:
        visited = set()
        while (focused := workspace.focusWidget()) not in visited and focused is not button:
            assert focused is not None
            visited.add(focused)
            qtbot.keyClick(focused, QtCore.Qt.Key.Key_Tab)
    else:
        button.setFocus()

    assert button.hasFocus()
    monkeypatch.setattr(QtWidgets.QFileDialog, "open", lambda self: None)
    with qtbot.waitSignal(workspace.actionLoad.triggered):
        qtbot.keyClick(button, QtCore.Qt.Key.Key_Space)


def test_details_fit_across_the_workspace_with_long_country_and_language_options(workspace):
    workspace.show_editor()
    workspace.resize(1080, 740)
    QtWidgets.QApplication.processEvents()

    assert workspace.scrollArea.horizontalScrollBar().maximum() == 0
    for combo in (workspace.cbLanguage, workspace.cbCountry):
        longest = max(range(combo.count()), key=lambda index: len(combo.itemText(index)))
        combo.setCurrentIndex(longest)
        assert combo.toolTip() == combo.itemText(longest)
    assert workspace.scrollArea.horizontalScrollBar().maximum() == 0
    workspace.dirty_flag = False
