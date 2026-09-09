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

    assert settings[0].settings["clear_tags"] is False
