"""Tracks which admin is making the current change, so model signals can record it."""
from contextlib import contextmanager
from contextvars import ContextVar

_current_user = ContextVar("audit_current_user", default=None)


def get_current_user():
    return _current_user.get()


@contextmanager
def acting_as(user):
    """Attribute changes made inside this block to `user` (for commands, tests and API calls)."""
    token = _current_user.set(user)
    try:
        yield
    finally:
        _current_user.reset(token)
