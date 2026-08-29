"""Shared SICAL UI helpers.

Small utilities used by any module that drives the SICAL II Windows UI
through robocorp's ``windows`` library.

Mirrors the ``sical_ui_utils.py`` module in the sibling ``arqueos_robot``
project. Kept duplicated rather than packaged so each consumer project
remains self-contained.
"""

import time

from robocorp import windows


def find_control(parent, locator: str, timeout: float = 10.0,
                 poll_interval: float = 0.3,
                 per_call_timeout: float = 0.5,
                 raise_error: bool = True):
    """Igual que ``wait_for_window``, pero para un control dentro de una ventana.

    Mismo motivo, y el mismo que ya justifica ``wait_for_window`` unas lineas
    mas abajo: el ``timeout=`` de robocorp no se respeta. El envoltorio se
    escribio en su dia para las ventanas y los controles se quedaron con la
    busqueda cruda -en el flujo de pago, 11 esperas protegidas frente a 27
    ``find`` sin proteger-.

    Medido el 29/08/2026 sobre la operacion 226102369, en el mismo registro:

        11:22:37.289  Starting payment order process
        11:22:39.303  Could not locate ... 'TButton OK path:"1|1"' (timeout: 10.0)

    Dos segundos, y en ellos cupieron ademas un ``find`` del campo de fecha y un
    ``send_keys`` con ``wait_time=0.5``: la busqueda que declara 10 s se rindio
    en menos de 1,5. El modal si aparecio -el volcado del error lo enseña en su
    sitio-, solo que despues. Ese localizador es el que mas tareas ha tumbado en
    todo el historico: 10 de 65.

    **No cambia ningun tiempo de espera**: hace que los que ya estan escritos se
    cumplan de verdad. Es para modales -lo que SICAL pinta cuando le parece-;
    un control del formulario existe ya cuando existe la ventana y no tiene esa
    carrera, asi que no necesita esto.
    """
    deadline = time.monotonic() + timeout
    while True:
        el = parent.find(locator, timeout=per_call_timeout, raise_error=False)
        if el:
            return el
        if time.monotonic() >= deadline:
            if raise_error:
                raise windows.ElementNotFound(
                    f'Could not locate control with locator: {locator!r} '
                    f'(esperado {timeout}s sondeando cada {poll_interval}s)')
            return None
        time.sleep(poll_interval)


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
