from contextlib import contextmanager
from threading import local

_state = local()


def should_skip_signals() -> bool:
    return bool(getattr(_state, "skip_signals", False))


def set_skip_signals(value: bool) -> None:
    _state.skip_signals = bool(value)


@contextmanager
def signals_disabled():
    previous = should_skip_signals()
    set_skip_signals(True)
    try:
        yield
    finally:
        set_skip_signals(previous)
