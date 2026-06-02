"""Reusable elapsed-time context manager — replaces scattered t_start/t_end patterns."""
import time
from contextlib import contextmanager
from typing import Generator


class _Timer:
    __slots__ = ("ms",)

    def __init__(self) -> None:
        self.ms: int = 0


@contextmanager
def timer() -> Generator[_Timer, None, None]:
    """
    Usage::

        with timer() as t:
            await some_operation()
        print(t.ms)  # elapsed milliseconds
    """
    t = _Timer()
    start = time.perf_counter()
    try:
        yield t
    finally:
        t.ms = int((time.perf_counter() - start) * 1000)
