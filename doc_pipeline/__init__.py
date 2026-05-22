"""Contable-document capture pipeline for the gasto consumer (spec v2).

Phase B′: capture the ADO/PMP contable PDF from SICAL's Visualizador and
return it to sical-robot for merge/stage. Vendored copy of the arqueo
pipeline, adapted because the gasto processors open the Visualizador via the
Consulta window and pass the already-open window into the capture helper.
"""

# NOTE: we deliberately do NOT re-export the `capture_and_return` function
# here — it would shadow the `doc_pipeline.capture_and_return` submodule.
# Import it as: `from doc_pipeline.capture_and_return import capture_and_return`.
from .sical_capture import (
    capture_visualizador_pdf,
    close_visualizador,
    SicalCaptureError,
)

__all__ = [
    'capture_visualizador_pdf',
    'close_visualizador',
    'SicalCaptureError',
]
