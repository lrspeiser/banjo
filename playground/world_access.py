"""Exclude installations from live HTTP operations without serializing those operations.

Ordinary world requests retain their existing concurrency. An installation
waits for them to finish, prevents new ones entering, and publishes once. This
protects room/spec/inventory writes as well as native session calls.
"""
from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Any, Iterator

_init = threading.Lock()


class WorldAccess:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.readers = 0
        self.writer = False
        self.waiting = 0

    @contextmanager
    def enter(self, *, exclusive: bool = False) -> Iterator[None]:
        with self.condition:
            if exclusive:
                self.waiting += 1
                try:
                    if not self.condition.wait_for(lambda: not self.writer and not self.readers, timeout=5):
                        raise ValueError("The world is busy; retry installation once the current operation finishes")
                    self.writer = True
                finally:
                    self.waiting -= 1
                    self.condition.notify_all()
            else:
                self.condition.wait_for(lambda: not self.writer and not self.waiting)
                self.readers += 1
        try:
            yield
        finally:
            with self.condition:
                if exclusive:
                    self.writer = False
                else:
                    self.readers -= 1
                self.condition.notify_all()


def gate(app: Any) -> WorldAccess:
    with _init:
        found = getattr(app, "_world_access", None)
        if found is None:
            found = app._world_access = WorldAccess()
        return found
