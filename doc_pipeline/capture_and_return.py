"""
Capture a gasto contable PDF and build the phase-tagged `contable_documents`
envelope returned to sical-robot in the result message (spec v2 §2.2,
extended for gasto's per-phase documents).

Transport: inline base64. An oversize doc (> MAX_INLINE_BYTES) is reported as
a capture failure rather than silently dropped (the consumer has no storage
backend). An ADO/PMP document is 1-2 pages / tens of KB, so this is a safety
net, not a path.

Never raises: the SICAL operation is already committed before this runs; any
failure here only sets capture_status=FAILED on the envelope.
"""

import base64
import hashlib

from .sical_capture import capture_visualizador_pdf, SicalCaptureError

import logging

logger = logging.getLogger(__name__)


def _page_count(pdf_path):
    try:
        from pypdf import PdfReader
        return len(PdfReader(pdf_path).pages)
    except Exception as exc:  # noqa: BLE001 - page count is a soft signal
        logger.debug('page_count unavailable: %s', exc)
        return None


def capture_and_return(ventana_visual, num_operacion, phase, cfg):
    """
    Capture the contable PDF currently shown in the open Visualizador window
    and return its `contable_document` envelope dict:

        {phase, filename, mime_type, page_count, size_bytes, sha256,
         transport: "inline_base64", data: "<b64>",
         capture_status: "CAPTURED"|"FAILED", capture_error: str|None}

    `phase` is the gasto contabilization phase this document belongs to
    ("ADO" or "PMP" this round). On any failure, capture_status="FAILED",
    data=None, capture_error set.
    """
    envelope = {
        'phase': phase,
        'filename': f'{num_operacion}.pdf' if num_operacion else f'{phase}.pdf',
        'mime_type': 'application/pdf',
        'page_count': None,
        'size_bytes': None,
        'sha256': None,
        'transport': 'inline_base64',
        'data': None,
        'capture_status': 'FAILED',
        'capture_error': None,
    }

    try:
        pdf_path = capture_visualizador_pdf(
            ventana_visual, num_operacion, cfg.SICAL_PDF_WORKDIR)
    except SicalCaptureError as exc:
        envelope['capture_error'] = f'sical_capture: {exc}'
        logger.warning('CONTABLE %s: %s', phase, envelope['capture_error'])
        return envelope
    except Exception as exc:  # noqa: BLE001 - never raise out of capture
        envelope['capture_error'] = f'sical_capture (unexpected): {exc}'
        logger.warning('CONTABLE %s: %s', phase, envelope['capture_error'])
        return envelope

    try:
        with open(pdf_path, 'rb') as fh:
            data = fh.read()
        size = len(data)
        envelope['size_bytes'] = size
        envelope['sha256'] = hashlib.sha256(data).hexdigest()
        envelope['page_count'] = _page_count(pdf_path)

        max_inline = int(getattr(cfg, 'MAX_INLINE_BYTES', 2 * 1024 * 1024))
        if size > max_inline:
            envelope['capture_error'] = (
                f'contable PDF {size} bytes exceeds inline limit '
                f'{max_inline}; storage_ref transport not configured on '
                f'the consumer')
            logger.warning('CONTABLE %s: %s', phase, envelope['capture_error'])
            return envelope

        envelope['data'] = base64.b64encode(data).decode('ascii')
        envelope['capture_status'] = 'CAPTURED'
        logger.info(
            "CONTABLE %s: encoded %s B / %s pages / sha=%s",
            phase, size, envelope['page_count'],
            (envelope['sha256'] or '')[:12])
        return envelope
    except Exception as exc:  # noqa: BLE001
        envelope['capture_error'] = f'read/encode: {exc}'
        logger.warning('CONTABLE %s: %s', phase, envelope['capture_error'])
        return envelope
