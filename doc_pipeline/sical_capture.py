"""
SICAL UI driver: save a gasto contable document (ADO/PMP) as a PDF.

============================ !!! UNVERIFIED !!! ============================
The "Guardar PDF" button path (2|2|3) and the 'Guardar como' dialog flow are
ported from the arqueo capture (older SICAL build) and have NOT been
validated against the current gasto SICAL build. Treat every ``.find(...)``
here as a hypothesis to confirm during the SICAL dry-run.

Difference vs arqueo: the gasto processors already open the Visualizador de
Documentos (via the Consulta window -> Imprimir), so this module receives the
ALREADY-OPEN Visualizador window and only drives Guardar PDF -> Guardar como
-> close. It does not navigate the "Documento" selector.
===========================================================================
"""

import logging
import os
import time

from robocorp import windows

from sical_ui_utils import wait_for_window

logger = logging.getLogger(__name__)


class SicalCaptureError(Exception):
    """Raised when the SICAL document could not be saved to PDF."""


_VISOR_REGEX = 'regex:.*Visualizador de Documentos de SICAL v2'
# UNVERIFIED: in arqueo the Visualizador "Guardar PDF" button is path 2|2|3,
# next to Imprimir (2|2|7) and Salir (2|2|6). Same toolbar, so reused here.
_GUARDAR_PDF_PATH = 'class:"TBitBtn" and path:"2|2|3"'
_SALIR_PATH = 'class:"TBitBtn" and path:"2|2|6"'


def close_visualizador(visor=None, attempts=3):
    """
    Best-effort close of the 'Visualizador de Documentos de SICAL v2' window.

    Idempotent and never raises: the PDF is already saved by the time we get
    here, so failing to close the viewer must not fail the capture.

    When SICAL saves the document it auto-opens it, which **minimizes** the
    Visualizador. A minimized window's UI tree is not interactable, so the
    Salir button (2|2|6) can't be found/clicked until the window is restored.
    Each attempt re-finds the window fresh, restores + foregrounds it, clicks
    Salir, answers a possible exit-confirmation, and -- if Salir is
    unreachable -- falls back to a direct window close. Closure is verified.
    """
    for i in range(attempts):
        try:
            win = wait_for_window(_VISOR_REGEX, timeout=2.0) or visor
            if win is None:
                return  # already closed

            try:
                win.restore_window()
                win.foreground_window()
                time.sleep(0.5)
            except Exception as exc:  # noqa: BLE001 - best-effort
                logger.warning("restore/foreground Visualizador failed: %s", exc)

            salir = win.find(_SALIR_PATH, raise_error=False)
            if salir:
                salir.click(wait_time=0.5)
                time.sleep(0.5)
                for confirm in ('Yes', 'Sí', 'Si'):
                    btn = win.find(
                        f'class:"TButton" and name:"{confirm}"',
                        raise_error=False)
                    if btn:
                        btn.click(wait_time=0.5)
                        break
            else:
                logger.warning(
                    "Salir button not found; closing Visualizador directly")
                win.close_window()
        except Exception as exc:  # noqa: BLE001 - closing is best-effort
            logger.warning(
                "close Visualizador attempt %d/%d failed: %s",
                i + 1, attempts, exc)

        still_open = wait_for_window(_VISOR_REGEX, timeout=1.0)
        if still_open is None:
            return

    logger.warning(
        "Visualizador de Documentos still open after %d close attempt(s)",
        attempts)


def capture_visualizador_pdf(ventana_visual, num_operacion, dest_dir):
    """
    From the ALREADY-OPEN Visualizador window: Guardar PDF -> drive the
    'Guardar como' dialog to ``<dest_dir>\\<num_operacion>_sical.pdf`` ->
    close the Visualizador. Returns that path.

    Raises :class:`SicalCaptureError` on any failure. The caller treats this
    as a non-fatal capture failure (the SICAL operation is already committed).
    """
    if not num_operacion:
        raise SicalCaptureError("num_operacion is empty; cannot name the PDF")

    os.makedirs(dest_dir, exist_ok=True)
    pdf_path = os.path.join(dest_dir, f"{num_operacion}_sical.pdf")

    visor = ventana_visual
    try:
        # Re-find fresh in case the passed handle went stale; fall back to it.
        visor = wait_for_window(_VISOR_REGEX, timeout=2.0) or ventana_visual
        if visor is None:
            raise SicalCaptureError("Visualizador window not found")

        # --- UNVERIFIED: Guardar PDF ----------------------------------------
        visor.find(_GUARDAR_PDF_PATH).click()

        # --- UNVERIFIED: 'Guardar como' Windows dialog ----------------------
        save_as = wait_for_window('regex:.*Guardar como', timeout=5.0)
        if save_as:
            time.sleep(2)
            save_as.find(
                'control:"EditControl" and name:"Nombre:"'
            ).set_value(pdf_path)
            time.sleep(1)
            save_as.find('class:"Button" and name:"Guardar"').click()

        # UNVERIFIED: overwrite confirmation (file already exists).
        overwrite_yes = visor.find(
            'class:"TButton" and name:"Yes" and path:"1|2"',
            raise_error=False)
        if overwrite_yes:
            overwrite_yes.click(wait_time=0.5)
            runtime_aceptar = visor.find(
                'class:"TButton" and name:"Aceptar"', raise_error=False)
            if runtime_aceptar:
                runtime_aceptar.click(wait_time=0.5)

        # UNVERIFIED: occasional runtime-error modal after save.
        runtime_ok = visor.find(
            'class:"TButton" and name:"OK"', raise_error=False)
        if runtime_ok:
            runtime_ok.click(wait_time=0.5)

    except Exception as exc:  # noqa: BLE001 - normalize to one error type
        raise SicalCaptureError(f"SICAL capture failed: {exc}") from exc
    finally:
        # Always close the Visualizador so it does not pile up across tasks.
        close_visualizador(visor)

    # Give the writer a moment, then confirm the file landed.
    for _ in range(10):
        if os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 0:
            return pdf_path
        time.sleep(0.5)
    raise SicalCaptureError(f"expected PDF not found after save: {pdf_path}")
