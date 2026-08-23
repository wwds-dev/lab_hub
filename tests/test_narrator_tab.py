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
