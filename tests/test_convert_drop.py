"""The Convert tab's drag-and-drop, driven by real Qt events.

Drag-and-drop is the tab's headline feature and the easiest thing to break
silently: nothing else in the app notices if a dropped file never arrives.

These send genuine QDragEnterEvent/QDropEvent objects through
`QApplication.sendEvent`, reproducing the real sequence as closely as a test
can:

* to the list's **viewport**, not the list widget — QListWidget is a scroll
  area, and that is where the window server delivers a drop; Qt forwards it up
  to the widget's own handler;
* **DragEnter first**, then Drop, because a drop is only offered once the enter
  has been accepted;
* against a **shown** widget, since an unshown one does not route viewport
  events the same way.

The only uncovered step is the window server originating the drag.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lab_hub import config  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def tab(app):
    """One shown tab for the whole module.

    Built once rather than per test: repeatedly constructing and destroying Qt
    widgets with events still in flight crashes the interpreter, and `reset`
    clears everything a test can dirty.
    """
    from ui.convert_tab import ConvertTab

    tab = ConvertTab(config.Settings())
    tab.resize(900, 700)
    tab.show()
    app.processEvents()
    yield tab
    tab.close()


@pytest.fixture(autouse=True)
def reset(tab, app):
    tab.clear_all()
    tab.run_panel.status.setText("Idle.")
    app.processEvents()


def mime_for(paths) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    return mime


def drag_enter(widget, mime) -> QDragEnterEvent:
    event = QDragEnterEvent(
        QPoint(20, 20),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)
    return event


def drop_on(tab, paths, app) -> None:
    """Drag over the file list and let go — the full two-event sequence."""
    viewport = tab.files.viewport()

    # Held in locals for the duration of the send: the events reference the
    # QMimeData without owning it.
    enter_mime = mime_for(paths)
    drag_enter(viewport, enter_mime)

    drop_mime = mime_for(paths)
    event = QDropEvent(
        QPointF(20, 20),
        Qt.DropAction.CopyAction,
        drop_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, event)
    app.processEvents()


def book(directory, ext="epub", name="Dropped Book"):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.{ext}"
    target.write_text("not a real book, but a real file", encoding="utf-8")
    return target


def test_a_file_drag_is_accepted(tab, tmp_path):
    """If the widget refuses the drag, no drop is ever offered."""
    event = drag_enter(tab.files.viewport(), mime_for([book(tmp_path)]))
    assert event.isAccepted()


def test_a_drag_carrying_no_urls_is_not_hijacked(tab):
    mime = QMimeData()
    mime.setText("just some text")
    event = drag_enter(tab.files.viewport(), mime)
    assert not event.isAccepted()


def test_dropping_a_single_file_queues_it(tab, app, tmp_path):
    """The headline request: one file, dragged in — not a folder scan."""
    dropped = book(tmp_path)
    drop_on(tab, [dropped], app)

    assert tab._sources == [dropped.resolve()]
    assert tab.files.count() == 1


def test_dropping_several_files_at_once_queues_all_of_them(tab, app, tmp_path):
    files = [book(tmp_path, ext) for ext in ("epub", "mobi", "azw3", "docx")]
    drop_on(tab, files, app)

    assert len(tab._sources) == len(files)


def test_dropping_a_folder_scans_it(tab, app, tmp_path):
    book(tmp_path)
    book(tmp_path / "nested", "mobi")

    drop_on(tab, [tmp_path], app)

    assert len(tab._sources) == 2


def test_files_and_a_folder_in_one_drop(tab, app, tmp_path):
    single = book(tmp_path / "loose", "docx")
    book(tmp_path / "library", "mobi")

    drop_on(tab, [single, tmp_path / "library"], app)

    assert {source.name for source in tab._sources} == {
        "Dropped Book.docx",
        "Dropped Book.mobi",
    }


def test_dropping_the_same_file_twice_queues_it_once(tab, app, tmp_path):
    dropped = book(tmp_path)
    drop_on(tab, [dropped], app)
    drop_on(tab, [dropped], app)

    assert len(tab._sources) == 1


def test_an_unreadable_format_is_rejected_out_loud(tab, app, tmp_path):
    """Silently ignoring a dropped file is indistinguishable from a bug."""
    junk = tmp_path / "notes.xyz"
    junk.write_text("nope", encoding="utf-8")

    drop_on(tab, [junk], app)

    assert tab._sources == []
    assert ".xyz" in tab.run_panel.status.text()


def test_the_queue_drives_the_job(tab, app, tmp_path):
    """A dropped file must actually reach the tool the Run button calls."""
    dropped = book(tmp_path, "mobi")
    drop_on(tab, [dropped], app)

    job = tab.build_job()

    assert job.args[0] == [dropped.resolve()]
    assert job.keywords["output_ext"] == tab._current_format().ext


def test_running_with_an_empty_queue_is_refused(tab):
    with pytest.raises(ValueError, match="Add some files"):
        tab.build_job()
