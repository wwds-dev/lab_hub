"""One running copy.

Every test uses its own key. Sharing the real one would mean a test run either
turned away because the user's Lab Hub is open, or — worse — telling their
running app to come to the front mid-suite.
"""

from __future__ import annotations

import os
import uuid

import pytest

from PySide6.QtNetwork import QLocalServer

from ui.single_instance import SingleInstance


@pytest.fixture
def key():
    name = f"lab-hub-test-{uuid.uuid4().hex[:12]}"
    yield name
    QLocalServer.removeServer(name)


def test_the_first_copy_may_run(qapp, key):
    guard = SingleInstance(key)
    try:
        assert guard.acquire() is True
    finally:
        guard.release()


def test_a_second_copy_is_turned_away(qapp, key):
    first = SingleInstance(key)
    second = SingleInstance(key)
    try:
        assert first.acquire() is True
        assert second.acquire() is False, "two copies must not run at once"
    finally:
        first.release()


def test_releasing_lets_the_next_copy_in(qapp, key):
    first = SingleInstance(key)
    first.acquire()
    first.release()

    second = SingleInstance(key)
    try:
        assert second.acquire() is True
    finally:
        second.release()


def test_the_running_copy_is_told_to_come_forward(qapp, key):
    """The point of using a socket rather than a lock file."""
    first = SingleInstance(key)
    activations = []
    first.activated.connect(lambda: activations.append(True))
    first.acquire()

    try:
        SingleInstance(key).acquire()
        # newConnection is delivered through the event loop.
        for _ in range(50):
            qapp.processEvents()
            if activations:
                break
        assert activations, "the running copy was never asked to show itself"
    finally:
        first.release()


def test_a_socket_left_by_a_crash_does_not_block_startup(qapp, key):
    """A killed process leaves its socket file behind; listen() refuses to bind
    over it, so the guard must clear it rather than lock the user out."""
    orphan = SingleInstance(key)
    orphan.acquire()
    # Simulate a crash: drop the server without the tidy release path.
    orphan._server.close()
    orphan._server = None

    guard = SingleInstance(key)
    try:
        assert guard.acquire() is True, "a stale socket must not block a new run"
    finally:
        guard.release()


def test_the_key_is_per_user(qapp):
    """Two accounts on one Mac each get their own instance."""
    from ui import single_instance

    assert str(os.getuid()) in single_instance.KEY
