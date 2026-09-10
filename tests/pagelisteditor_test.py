from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from comicapi.genericmetadata import PageMetadata
from comictaggerlib.pagelisteditor import PageListEditor


def page(archive_index: int, page_type: str = "") -> PageMetadata:
    return PageMetadata(
        archive_index=archive_index,
        display_index=archive_index,
        filename=f"page-{archive_index}.jpg",
        type=page_type,
        bookmark="",
    )


def make_editor(qtbot, pages: list[PageMetadata], comic_archive=None) -> PageListEditor:
    editor = PageListEditor(None)  # type: ignore[arg-type]
    qtbot.addWidget(editor)
    if comic_archive is None:
        for metadata in pages:
            item = QtWidgets.QListWidgetItem(editor.list_entry_text(metadata))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, metadata)
            editor.listWidget.addItem(item)
        editor.listWidget.setCurrentRow(0)
    else:
        editor.pageWidget.set_archive = lambda *_args: None
        editor.set_data(comic_archive, pages)
    return editor


def test_move_buttons_reorder_selected_pages(qtbot) -> None:
    editor = make_editor(qtbot, [page(0), page(1), page(2)])
    editor.listWidget.setCurrentRow(1)

    qtbot.mouseClick(editor.btnUp, QtCore.Qt.MouseButton.LeftButton)

    assert [metadata.archive_index for metadata in editor.get_page_list()] == [1, 0, 2]
    assert [metadata.display_index for metadata in editor.get_page_list()] == [0, 1, 2]


def test_delete_button_removes_page_after_confirmation(qtbot, monkeypatch, tmp_comic) -> None:
    pages = [page(index) for index in range(tmp_comic.get_number_of_pages())]
    editor = make_editor(qtbot, pages, tmp_comic)
    editor.listWidget.setCurrentRow(1)
    original_names = tmp_comic.get_page_name_list().copy()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *_args: QtWidgets.QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(editor.btnDelete, QtCore.Qt.MouseButton.LeftButton)

    assert tmp_comic.get_page_name_list() == original_names[:1] + original_names[2:]
    assert [metadata.archive_index for metadata in editor.get_page_list()] == list(range(len(original_names) - 1))


def test_delete_button_keeps_page_when_confirmation_is_cancelled(qtbot, monkeypatch, tmp_comic) -> None:
    pages = [page(index) for index in range(tmp_comic.get_number_of_pages())]
    editor = make_editor(qtbot, pages, tmp_comic)
    editor.listWidget.setCurrentRow(1)
    original_names = tmp_comic.get_page_name_list().copy()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *_args: QtWidgets.QMessageBox.StandardButton.No,
    )

    qtbot.mouseClick(editor.btnDelete, QtCore.Qt.MouseButton.LeftButton)

    assert tmp_comic.get_page_name_list() == original_names
