from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from comictaggerlib.autotagstartwindow import AutoTagStartWindow


@pytest.fixture(scope="module")
def qapplication():
    return QApplication.instance() or QApplication([])


def test_clear_existing_tags_preference_is_restored_and_emitted(config, qapplication):
    config[0].Auto_Tag__clear_tags = True
    dialog = AutoTagStartWindow(None, config[0], "")
    settings = []
    dialog.startAutoTag.connect(settings.append)

    assert dialog.cbxClearMetadata.isChecked()

    dialog.cbxClearMetadata.setChecked(False)
    dialog.accept()

    assert settings[0].new_settings(config[0]).Auto_Tag__clear_tags is False
    assert config[0].Auto_Tag__clear_tags is True


def test_unchecking_custom_search_ignores_the_entered_text(config, qapplication):
    dialog = AutoTagStartWindow(None, config[0], "")
    emitted = []
    dialog.startAutoTag.connect(emitted.append)
    dialog.cbxSpecifySearchString.setChecked(True)
    dialog.leSearchString.setText("2000 AD")
    dialog.cbxSpecifySearchString.setChecked(False)

    dialog.accept()

    assert emitted[0].search_string == ""
