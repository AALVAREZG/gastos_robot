"""Dialogos que salen tras validar un ADO220 (SICAL actualizado el 21/10/2026)."""

import logging

import pytest
from robocorp import windows

import processors.ado220_processor as ado
from sical_constants import SICAL_WINDOWS


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
