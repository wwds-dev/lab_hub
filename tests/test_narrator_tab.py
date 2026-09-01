"""Narrator is owned and launched by Lab Hub."""

from pathlib import Path

import pytest

from lab_hub import config
from ui.narrator_tab import NarratorTab


def test_narrator_is_a_lab_hub_tab(window):
    assert window.tabs.indexOf(window.tools_tabs) >= 0
    index = window.tools_tabs.indexOf(window.narrator_tab)
    assert index >= 0
    assert window.tools_tabs.tabText(index) == "Narrator"


def test_form_rejects_a_missing_book(qapp, tmp_path, monkeypatch):
    tab = NarratorTab(config.Settings(narrator_output=str(tmp_path)))
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr("ui.narrator_tab.shutil.which", lambda name: "/usr/bin/ffmpeg")
    with pytest.raises(ValueError, match="Choose an ebook"):
        tab._validate()


def test_form_values_reach_the_lab_hub_worker(qapp, tmp_path, monkeypatch):
    book = tmp_path / "book.epub"
    book.write_text("test", encoding="utf-8")
    tab = NarratorTab(config.Settings(
        narrator_input=str(book), narrator_output=str(tmp_path), narrator_voice="nova"
    ))
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr("ui.narrator_tab.shutil.which", lambda name: "/usr/bin/ffmpeg")
    source, output = tab._validate()
    assert source == book
    assert output == Path(tmp_path)
    assert tab.voice.currentText() == "nova"


def test_narrator_has_native_library_tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("ui.narrator_library.find_catalog", lambda: None)
    tab = NarratorTab(config.Settings(narrator_output=str(tmp_path)))
    assert tab.sections.count() == 2
    assert tab.sections.tabText(0) == "Convert"
    assert tab.sections.tabText(1) == "Library"


def test_library_selection_moves_book_into_converter(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("ui.narrator_library.find_catalog", lambda: None)
    book = tmp_path / "selected.epub"
    book.write_text("test", encoding="utf-8")
    tab = NarratorTab(config.Settings(narrator_output=str(tmp_path)))
    tab.sections.setCurrentIndex(1)
    tab._use_library_book(str(book))
    assert tab.input_edit.text() == str(book)
    assert tab.sections.currentIndex() == 0
