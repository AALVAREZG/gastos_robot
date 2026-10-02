"""
Pruebas del orden de pasos y del estado del pago (processors/tesoreria_pagos.py).

Los pasos que tocan SICAL se sustituyen por grabadoras: lo que se comprueba es
que se hacen los pasos pedidos, en orden, con la fecha que toca, y que el estado
dice la verdad cuando algo falla a mitad. Los localizadores no se prueban aqui;
eso solo lo dice SICAL.

Run: pytest test_tesoreria_pagos.py
"""

import json
import logging

import pytest

from processors import tesoreria_pagos as tp
from sical_base import OperationResult, OperationStatus, OperationEncoder

LOG = logging.getLogger('test')


@pytest.fixture
def pasos(monkeypatch):
    """Sustituye los pasos de SICAL por una grabadora y la devuelve."""
    grabado = []

    def fecha(ventana, f):
        grabado.append(('fecha', f))

    def ordenar(ventana, num, logger):
        grabado.append(('ordenar', num))
        return True

    def pagar(ventana, num):
        grabado.append(('pagar', num))

    def salir(ventana, tras_pago=True):
        grabado.append(('salir', tras_pago))

    monkeypatch.setattr(tp, 'establecer_fecha', fecha)
    monkeypatch.setattr(tp, 'ordenar_operacion', ordenar)
    monkeypatch.setattr(tp, 'pagar_operacion', pagar)
    monkeypatch.setattr(tp, 'salir', salir)
    monkeypatch.setattr(tp, 'leer_error_sical', lambda ventana: None)
    return grabado


def test_cierre_de_ado_ordena_y_paga_con_una_sola_fecha(pasos):
    # Lo que hacen ADO220 y PMP450 al finalizar: una fecha para todo.
    estado = tp.nuevo_estado(tp.MODO_OPERACION, '226102509', fecha_ordenamiento='23092026')
    tp.ordenar_y_pagar(None, estado, LOG)

    assert pasos == [('fecha', '23092026'), ('ordenar', '226102509'),
                     ('pagar', '226102509'), ('salir', True)]
    assert estado['ordenacion'] == tp.HECHO
    assert estado['pago'] == tp.HECHO
    assert tp.estado_completo(estado)


def test_ya_ordenada_se_anota_y_se_paga(pasos, monkeypatch):
    monkeypatch.setattr(tp, 'ordenar_operacion', lambda v, n, l: False)
    estado = tp.nuevo_estado(tp.MODO_OPERACION, '1', fecha_ordenamiento='01102026')
    tp.ordenar_y_pagar(None, estado, LOG)

    assert estado['ordenacion'] == tp.YA_ESTABA
    assert estado['pago'] == tp.HECHO


def test_solo_pagar_usa_la_fecha_de_pago(pasos):
    estado = tp.nuevo_estado(tp.MODO_OPERACION, '326100196',
                             fecha_ordenamiento='31082026', fecha_pago='02102026',
                             ordenar=False)
    tp.ordenar_y_pagar(None, estado, LOG)

    assert pasos == [('fecha', '02102026'), ('pagar', '326100196'), ('salir', True)]
    assert estado['ordenacion'] == tp.NO_SOLICITADO


def test_fechas_distintas_se_teclea_la_de_pago_antes_de_pagar(pasos):
    estado = tp.nuevo_estado(tp.MODO_OPERACION, '9', fecha_ordenamiento='30092026',
                             fecha_pago='01102026')
    tp.ordenar_y_pagar(None, estado, LOG)

    assert pasos == [('fecha', '30092026'), ('ordenar', '9'),
                     ('fecha', '01102026'), ('pagar', '9'), ('salir', True)]


def test_solo_ordenar_sale_sin_cerrar_la_impresion_del_pago(pasos):
    estado = tp.nuevo_estado(tp.MODO_OPERACION, '9', fecha_ordenamiento='30092026', pagar=False)
    tp.ordenar_y_pagar(None, estado, LOG)

    assert pasos == [('fecha', '30092026'), ('ordenar', '9'), ('salir', False)]
    assert estado['pago'] == tp.NO_SOLICITADO


def test_fallo_al_pagar_deja_constancia_de_que_ya_estaba_ordenada(pasos, monkeypatch):
    # Los tres PMP del 31/08/2026: ordenaron y cayeron buscando «Pagar».
    def pagar_falla(ventana, num):
        raise RuntimeError('Could not locate control ... name:"Pagar"')
    monkeypatch.setattr(tp, 'pagar_operacion', pagar_falla)

    estado = tp.nuevo_estado(tp.MODO_OPERACION, '326100196', fecha_ordenamiento='31082026')
    with pytest.raises(RuntimeError):
        tp.ordenar_y_pagar(None, estado, LOG)

    assert estado['ordenacion'] == tp.HECHO
    assert estado['pago'] == tp.PENDIENTE
    assert not tp.estado_completo(estado)
    assert estado['error_sical'] is None


def test_si_sical_tiene_un_error_abierto_se_devuelve_su_texto(pasos, monkeypatch):
    def pagar_falla(ventana, num):
        raise RuntimeError('Could not locate control ... name:"Pagar"')
    monkeypatch.setattr(tp, 'pagar_operacion', pagar_falla)
    monkeypatch.setattr(tp, 'leer_error_sical', lambda ventana: 'Saldo insuficiente en la caja')

    estado = tp.nuevo_estado(tp.MODO_OPERACION, '326100196', fecha_ordenamiento='31082026')
    with pytest.raises(tp.ErrorSicalPago, match='Saldo insuficiente'):
        tp.ordenar_y_pagar(None, estado, LOG)

    assert estado['error_sical'] == 'Saldo insuficiente en la caja'
    assert estado['ordenacion'] == tp.HECHO


def test_el_estado_viaja_en_el_resultado():
    result = OperationResult(status=OperationStatus.FAILED, init_time='t')
    result.pago = tp.nuevo_estado(tp.MODO_OPERACION, '1', fecha_ordenamiento='01102026')

    encoded = json.loads(json.dumps(result, cls=OperationEncoder))
    assert encoded['pago']['ordenacion'] == tp.PENDIENTE

    import dataclasses
    assert dataclasses.asdict(result)['pago']['num_operacion'] == '1'


class _Elemento:
    """Lo minimo de un ControlElement de robocorp para leer_error_sical."""

    def __init__(self, name='', class_name='', valor=None, hijos=None, encuentra=None):
        self.name = name
        self.class_name = class_name
        self._valor = valor
        self._hijos = hijos or []
        self._encuentra = encuentra or {}

    def find(self, locator, **kwargs):
        return self._encuentra.get(locator)

    def get_value(self):
        return self._valor

    def iter_children(self, max_depth=8):
        return iter(self._hijos)


def test_lee_el_texto_de_la_ventana_de_errores():
    memo = _Elemento(class_name='TMemo', valor='  La operacion 326100196 no tiene ordinal de pago \r\n')
    form = _Elemento(class_name='TFVerError', encuentra={'class:"TMemo"': memo})
    ventana = _Elemento(encuentra={'class:"TFVerError"': form})

    assert tp.leer_error_sical(ventana) == 'La operacion 326100196 no tiene ordinal de pago'


def test_lee_el_texto_de_un_aviso_sin_los_botones():
    modal = _Elemento(name='Error', class_name='TMessageForm', hijos=[
        _Elemento(name='Operacion ya pagada', class_name=''),
        _Elemento(name='OK', class_name='TButton'),
    ])
    ventana = _Elemento(encuentra={'class:"TMessageForm"': modal})

    assert tp.leer_error_sical(ventana) == 'Operacion ya pagada'


def test_sin_error_abierto_devuelve_none_y_nunca_lanza():
    assert tp.leer_error_sical(_Elemento()) is None
    assert tp.leer_error_sical(None) is None

    class Rota:
        def find(self, *a, **k):
            raise RuntimeError('COM roto')
    assert tp.leer_error_sical(Rota()) is None


def test_abrir_ventana_espera_lo_que_tarde_la_base_y_cierra_la_que_quedo(monkeypatch):
    salir = _Elemento(name='Salir')
    pulsado = []
    salir.click = lambda wait_time=None: pulsado.append('salir')
    vieja = _Elemento(encuentra={tp.TESORERIA_PAGOS_PATHS['salir_button']: salir})
    nueva = _Elemento(name='nueva')
    esperas = []

    def esperar(patron, timeout=15.0, **k):
        esperas.append(timeout)
        return vieja if len(esperas) == 1 else nueva
    monkeypatch.setattr(tp, 'wait_for_window', esperar)
    monkeypatch.setattr(tp, 'open_menu_option', lambda ruta, logger: True)

    manager = tp.TesoreriaPagosWindowManager(LOG)
    assert tp.abrir_ventana(manager, LOG)

    assert pulsado == ['salir']
    assert esperas[1] == tp.ESPERA_VENTANA_S >= 30
    assert manager.ventana_proceso is nueva
