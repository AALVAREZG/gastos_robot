"""Dialogos que salen tras validar un ADO220 (SICAL actualizado el 21/10/2026)."""

import logging
from types import SimpleNamespace

import pytest
from robocorp import windows

import processors.ado220_processor as ado
from sical_base import OperationResult, OperationStatus
from sical_constants import ADO220_FORM_PATHS, SICAL_WINDOWS


class _Dialogo:
    def __init__(self, handle):
        self.handle = handle
        self.pulsado = []

    def find(self, locator, **kwargs):
        dialogo = self

        class _Boton:
            def click(self, **kw):
                dialogo.pulsado.append(locator)
        return _Boton()


@pytest.fixture
def procesador(monkeypatch):
    monkeypatch.setattr(ado.time, 'sleep', lambda s: None)
    return ado.ADO220Processor.__new__(ado.ADO220Processor)


def _ventanas(monkeypatch, info=None, confirms=()):
    """`confirms`: lo que devuelve cada busqueda sucesiva de «Confirm»."""
    pendientes = list(confirms)

    def esperar(locator, timeout=15.0):
        nonlocal info
        if locator == SICAL_WINDOWS['information_dialog']:
            hallado, info = info, None
            return hallado
        return pendientes.pop(0) if pendientes else None
    monkeypatch.setattr(ado, 'wait_for_window', esperar)


def test_sin_information_contesta_no_a_adjuntar(procesador, monkeypatch):
    adjuntar = _Dialogo(handle=2)
    _ventanas(monkeypatch, confirms=[adjuntar])
    procesador._cerrar_dialogos_tras_validar(handle_validar=1)
    assert adjuntar.pulsado == [ado.COMMON_DIALOG_PATHS['no_button']]


def test_con_information_lo_cierra_antes(procesador, monkeypatch):
    info, adjuntar = _Dialogo(handle=3), _Dialogo(handle=2)
    _ventanas(monkeypatch, info=info, confirms=[adjuntar])
    procesador._cerrar_dialogos_tras_validar(handle_validar=1)
    assert info.pulsado == [ado.COMMON_DIALOG_PATHS['info_ok']]
    assert adjuntar.pulsado == [ado.COMMON_DIALOG_PATHS['no_button']]


def test_nunca_contesta_no_al_confirm_de_validar(procesador, monkeypatch):
    validar, adjuntar = _Dialogo(handle=1), _Dialogo(handle=2)
    _ventanas(monkeypatch, confirms=[validar, validar, adjuntar])
    procesador._cerrar_dialogos_tras_validar(handle_validar=1)
    assert validar.pulsado == []
    assert adjuntar.pulsado == [ado.COMMON_DIALOG_PATHS['no_button']]


def test_sin_dialogo_de_adjuntar_falla(procesador, monkeypatch):
    _ventanas(monkeypatch)
    with pytest.raises(windows.ElementNotFound):
        procesador._cerrar_dialogos_tras_validar(handle_validar=1, timeout=0.01)


class _Campo:
    def __init__(self, valor):
        self.valor = valor

    def get_value(self):
        return self.valor


class _New30:
    """Ventana del ADO: botones que se pulsan y el campo del nº de operacion."""

    def __init__(self, campo):
        self.campo = campo
        self.pulsado = []

    def find(self, locator, **kwargs):
        if locator == ADO220_FORM_PATHS['num_operacion']:
            return self.campo
        ventana = self

        class _Boton:
            def click(self, **kw):
                ventana.pulsado.append(locator)
        return _Boton()


def _validar(procesador, monkeypatch, campo):
    ventana = _New30(campo)
    procesador.window_manager = SimpleNamespace(ventana_proceso=ventana)
    procesador.logger = logging.getLogger('test')
    procesador.phase_clock = SimpleNamespace(mark=lambda *a, **k: None)
    monkeypatch.setattr(ado, 'wait_for_window', lambda locator, timeout=15.0: _Dialogo(handle=1))
    monkeypatch.setattr(procesador, '_cerrar_dialogos_tras_validar', lambda handle: None)
    resultado = OperationResult(status=OperationStatus.PENDING, init_time='')
    return procesador._validate_operation(resultado), ventana


@pytest.mark.parametrize('campo', [None, _Campo(''), _Campo('   ')])
def test_validada_sin_numero_falla_avisando_de_que_puede_estar_hecha(procesador, monkeypatch, campo):
    # 01/11/2026: validada en SICAL, numero sin leer, devuelta como COMPLETED
    resultado, _ = _validar(procesador, monkeypatch, campo)
    assert resultado.status == OperationStatus.FAILED
    assert resultado.num_operacion is None
    assert 'puede estar ya terminada en SICAL' in resultado.error
    assert 'comprobar en SICAL antes de reenviar' in resultado.error


def test_validada_con_numero_sigue(procesador, monkeypatch):
    resultado, ventana = _validar(procesador, monkeypatch, _Campo(' 226102999 '))
    assert resultado.status == OperationStatus.COMPLETED
    assert resultado.num_operacion == '226102999'
    assert ADO220_FORM_PATHS['salir_button'] in ventana.pulsado
