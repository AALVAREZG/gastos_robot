"""
Unit tests for the gasto contable-capture envelope (spec v2 — Phase B′).
The SICAL UI driver (capture_visualizador_pdf) is monkeypatched out; these
cover the phase-tagged envelope, capture failure, the inline size guard, the
out-of-band attach helper, and OperationResult serialization.

Run: pytest test_capture_and_return.py
"""

import base64
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

# Import the submodule explicitly (doc_pipeline/__init__ re-exports the
# capture_and_return *function*, which would otherwise shadow the module).
import doc_pipeline.capture_and_return as car
from doc_pipeline.sical_capture import SicalCaptureError
from sical_base import (
    OperationResult,
    OperationStatus,
    OperationEncoder,
    attach_contable_document,
)


def _make_pdf(path):
    pypdf = pytest.importorskip('pypdf')
    w = pypdf.PdfWriter()
    w.add_blank_page(width=200, height=200)
    with open(path, 'wb') as fh:
        w.write(fh)
    return path


def _cfg(tmp_path, max_inline=2 * 1024 * 1024):
    return SimpleNamespace(
        SICAL_PDF_WORKDIR=str(tmp_path / 'work'),
        MAX_INLINE_BYTES=max_inline,
    )


class TestCaptureAndReturn:
    def test_success_envelope_has_phase(self, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path)
        os.makedirs(cfg.SICAL_PDF_WORKDIR, exist_ok=True)
        pdf = _make_pdf(os.path.join(cfg.SICAL_PDF_WORKDIR, 'OP1_sical.pdf'))
        raw = open(pdf, 'rb').read()

        monkeypatch.setattr(car, 'capture_visualizador_pdf',
                            lambda v, num, d: pdf)

        env = car.capture_and_return(None, 'OP1', 'ADO', cfg)

        assert env['phase'] == 'ADO'
        assert env['capture_status'] == 'CAPTURED'
        assert env['capture_error'] is None
        assert env['filename'] == 'OP1.pdf'
        assert env['mime_type'] == 'application/pdf'
        assert env['transport'] == 'inline_base64'
        assert env['size_bytes'] == len(raw)
        assert env['sha256'] == hashlib.sha256(raw).hexdigest()
        assert base64.b64decode(env['data']) == raw
        assert env['page_count'] == 1

    def test_capture_failure(self, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path)

        def boom(v, num, d):
            raise SicalCaptureError('Visualizador not found')

        monkeypatch.setattr(car, 'capture_visualizador_pdf', boom)
        env = car.capture_and_return(None, 'OP2', 'PMP', cfg)

        assert env['phase'] == 'PMP'
        assert env['capture_status'] == 'FAILED'
        assert env['data'] is None
        assert 'sical_capture' in env['capture_error']

    def test_oversize_guard(self, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path, max_inline=10)  # tiny limit
        os.makedirs(cfg.SICAL_PDF_WORKDIR, exist_ok=True)
        pdf = _make_pdf(os.path.join(cfg.SICAL_PDF_WORKDIR, 'OP3_sical.pdf'))
        monkeypatch.setattr(car, 'capture_visualizador_pdf', lambda v, n, d: pdf)

        env = car.capture_and_return(None, 'OP3', 'ADO', cfg)

        assert env['capture_status'] == 'FAILED'
        assert env['data'] is None
        assert 'exceeds inline limit' in env['capture_error']
        assert env['size_bytes'] > 10
        assert env['sha256']

    def test_unexpected_capture_error_is_swallowed(self, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path)

        def kaboom(v, n, d):
            raise RuntimeError('COM blew up')

        monkeypatch.setattr(car, 'capture_visualizador_pdf', kaboom)
        env = car.capture_and_return(None, 'OP4', 'ADO', cfg)
        assert env['capture_status'] == 'FAILED'
        assert 'unexpected' in env['capture_error']


class TestAttachAndSerialization:
    def test_attach_appends_and_mirrors_status(self):
        r = OperationResult(status=OperationStatus.COMPLETED, init_time='t0')
        attach_contable_document(r, {'phase': 'ADO', 'capture_status': 'CAPTURED',
                                     'capture_error': None})
        docs = getattr(r, '_contable_documents')
        assert len(docs) == 1 and docs[0]['phase'] == 'ADO'
        assert r.capture_status == 'CAPTURED'
        assert r.capture_error is None

    def test_attach_accumulates_multiple_phases(self):
        r = OperationResult(status=OperationStatus.COMPLETED, init_time='t0')
        attach_contable_document(r, {'phase': 'ADO', 'capture_status': 'CAPTURED'})
        attach_contable_document(r, {'phase': 'OP', 'capture_status': 'FAILED',
                                     'capture_error': 'x'})
        docs = getattr(r, '_contable_documents')
        assert [d['phase'] for d in docs] == ['ADO', 'OP']
        # Latest mirrored onto the dataclass fields.
        assert r.capture_status == 'FAILED'
        assert r.capture_error == 'x'

    def test_operation_result_serializes_capture_fields(self):
        r = OperationResult(
            status=OperationStatus.COMPLETED,
            init_time='t0',
            num_operacion='OP42',
            capture_status='CAPTURED',
            capture_error=None,
        )
        decoded = json.loads(json.dumps(r, cls=OperationEncoder))
        assert decoded['capture_status'] == 'CAPTURED'
        assert decoded['capture_error'] is None
        # The base64 payload is carried out-of-band, NOT in the dataclass.
        assert 'data' not in decoded

    def test_default_result_has_no_capture(self):
        r = OperationResult(status=OperationStatus.COMPLETED, init_time='t0')
        decoded = json.loads(json.dumps(r, cls=OperationEncoder))
        assert decoded['capture_status'] is None
