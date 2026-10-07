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
import re

from .sical_capture import capture_visualizador_pdf, SicalCaptureError

import logging

logger = logging.getLogger(__name__)


def _texto_pdf(pdf_path):
    """Texto de todas las paginas, o None si no se puede leer."""
    try:
        from pypdf import PdfReader
        return '\n'.join((p.extract_text() or '') for p in PdfReader(pdf_path).pages)
    except Exception as exc:  # noqa: BLE001
        return None


def nombra_operacion(pdf_path, num_operacion):
    """
    Es el PDF capturado el de la operacion que se pidio?

    Existe porque la captura puede salir "bien" con el documento EQUIVOCADO y
    ningun estado lo delata: si el numero se teclea en el campo que no es, la
    consulta no cambia y SICAL reimprime la operacion que siguiera cargada. El
    29/08/2026 se colaron asi dos documentos de la 226102358 dentro de la tarea
    de la 226102357 -mismo tercero, indistinguibles a ojo- y llegaron hasta el
    outbox de firma marcados CAPTURED/STAGED. Solo el contenido lo dice.

    Se busca el numero como **token suelto** y no anclado a su rotulo: pypdf
    extrae en orden de dibujo y en el Talon de Cargo el rotulo
    "N. de Operacion:" y su valor caen en lineas distintas, asi que un patron
    con rotulo funciona en el gasto y falla en el arqueo.

    Medido sobre los 398 contables ya capturados: acepta 397 y rechaza 1, y ese
    1 es una tarea cuyo numero GUARDADO es el que esta mal (2600540 por
    26000540). Cero falsos negativos.

    @returns True | False | None  (None = no se pudo comprobar)
    """
    num = str(num_operacion or '').strip()
    if not num:
        return None
    txt = _texto_pdf(pdf_path)
    if not txt or not txt.strip():
        return None
    return bool(re.search(r'(?<!\d)' + re.escape(num) + r'(?!\d)', txt))


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
    envelope = sobre_vacio(phase, f'{num_operacion}.pdf' if num_operacion else f'{phase}.pdf')

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

    return completar_sobre(envelope, pdf_path, num_operacion, cfg)


def sobre_vacio(phase, filename):
    """El sobre de un documento todavia sin capturar: FAILED hasta que se rellene."""
    return {
        'phase': phase,
        'filename': filename,
        'mime_type': 'application/pdf',
        'page_count': None,
        'size_bytes': None,
        'sha256': None,
        'transport': 'inline_base64',
        'data': None,
        'capture_status': 'FAILED',
        'capture_error': None,
    }


def completar_sobre(envelope, pdf_path, numero, cfg, que='operacion'):
    """
    Rellena `envelope` con el PDF ya guardado en `pdf_path` y lo da por
    CAPTURED, salvo que sea demasiado grande o no nombre `numero` (el de la
    operacion, o el de la lista con `que='lista'`). Nunca lanza.
    """
    phase = envelope['phase']
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

        # Ultima puerta antes de dar la captura por buena: que el
        # documento hable de la operacion que se pidio. Ver
        # `nombra_operacion`.
        coincide = nombra_operacion(pdf_path, numero)
        if coincide is False:
            envelope['capture_error'] = (
                f'el PDF capturado no nombra la {que} {numero}: '
                f'es el documento de otra {que}')
            logger.error('CONTABLE %s: %s', phase, envelope['capture_error'])
            return envelope
        if coincide is None:
            # No bloquea: medido 0 de 398 contables sin capa de texto,
            # y tumbar una captura buena por no poder leerla seria peor
            # que el fallo del que protege.
            logger.warning('CONTABLE %s: no se pudo comprobar que el PDF nombre la %s %s; se acepta igual', phase, que, numero)

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
