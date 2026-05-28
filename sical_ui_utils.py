"""Shared SICAL UI helpers.

Small utilities used by any module that drives the SICAL II Windows UI
through robocorp's ``windows`` library.

Mirrors the ``sical_ui_utils.py`` module in the sibling ``arqueos_robot``
project. Kept duplicated rather than packaged so each consumer project
remains self-contained.
"""

import time

from robocorp import windows


def wait_for_window(locator: str, timeout: float = 15.0,
                    poll_interval: float = 0.5,
                    per_call_timeout: float = 0.5):
    """Poll ``windows.find_window`` until it returns a window or the deadline
    expires.

    Workaround for cases where robocorp's own ``timeout=`` parameter is not
    reliably honoured (the call can return ``None`` well before the wait
    elapses). Driving the wait loop ourselves guarantees the effective
    timeout is always respected, regardless of library behaviour.

    Args:
        locator: robocorp window locator (e.g. ``'regex:.*mtec40'``).
        timeout: total seconds to wait before giving up.
        poll_interval: pause between attempts.
        per_call_timeout: timeout passed to each underlying ``find_window``.

    Returns:
        The window object if found, otherwise ``None``.
    """
    deadline = time.monotonic() + timeout
    while True:
        win = windows.find_window(
            locator, timeout=per_call_timeout, raise_error=False)
        if win:
            return win
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll_interval)
