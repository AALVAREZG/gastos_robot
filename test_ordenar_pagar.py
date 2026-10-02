"""
Pruebas de `ordenarypagar` y `listas_pendientes_pago` sin SICAL.

Cubren la validacion del mensaje -todo lo que no cuadra se rechaza antes de
abrir SICAL-, el enrutado en el consumidor y el orden de pasos del pago por
lista. Los localizadores no se prueban aqui; eso solo lo dice SICAL.

Run: pytest test_ordenar_pagar.py
"""

import logging

import pytest

from processors import tesoreria_pagos as tp
from processors.ordenar_pagar_processor import (
    OrdenarPagarProcessor,
    ListasPendientesPagoProcessor,
)
from sical_base import OperationStatus

LOG = logging.getLogger('test')


@pytest.fixture
def proc():
    return OrdenarPagarProcessor(LOG)


@pytest.fixture
def lista_disponible(monkeypatch):
    monkeypatch.setattr(tp, 'PAGO_LISTA_DISPONIBLE', True)


# --- validacion del mensaje -------------------------------------------------

def test_operacion_por_defecto_ordena_y_paga(proc):
    datos = proc.create_operation_data({'num_operacion': '326100196', 'fecha_ordenamiento': '31/08/2026'})
    assert datos['modo'] == tp.MODO_OPERACION
    assert datos['numero'] == '326100196'
    assert datos['ordenar'] and datos['pagar']
    assert datos['fecha_ordenamiento'] == '31082026'
    assert datos['fecha_pago'] == '31082026'
    # Sin politica de duplicados: execute() no debe buscarlos
    assert datos['duplicate_policy'] is None


def test_solo_pagar_con_fecha_de_pago(proc):
    datos = proc.create_operation_data({'num_operacion': 326100196, 'ordenar': False,
                                        'fecha_pago': '02102026'})
    assert datos['numero'] == '326100196'
    assert not datos['ordenar'] and datos['pagar']
    assert datos['fecha_ordenamiento'] == '02102026'
    assert datos['fecha_pago'] == '02102026'


@pytest.mark.parametrize('detalle, motivo', [
    ({'fecha_pago': '01/10/2026'}, 'num_operacion o num_lista'),
    ({'num_operacion': '1', 'num_lista': '2', 'fecha_pago': '01/10/2026'}, 'solo uno'),
    ({'num_operacion': '12a', 'fecha_pago': '01/10/2026'}, 'no es un numero'),
    ({'num_operacion': '0', 'fecha_pago': '01/10/2026'}, 'no es un numero'),
    ({'num_operacion': '1'}, 'falta la fecha'),
    ({'num_operacion': '1', 'fecha_pago': '31/02/2026'}, 'no es una fecha'),
    ({'num_operacion': '1', 'fecha_pago': '01/10/2026', 'ordenar': 'false', 'pagar': 'false'},
     'nada que hacer'),
    ({'num_operacion': '1', 'fecha_pago': '01/10/2026', 'pagar': 'quizas'}, 'booleano'),
])
def test_mensajes_que_no_cuadran_se_rechazan(proc, detalle, motivo):
    with pytest.raises(ValueError, match=motivo):
        proc.create_operation_data(detalle)


def test_pago_por_lista_se_rechaza_mientras_falte_el_paso_de_seleccionar(proc):
    assert tp.PAGO_LISTA_DISPONIBLE is False
    with pytest.raises(ValueError, match='aun no esta disponible'):
        proc.create_operation_data({'num_lista': '57', 'fecha_pago': '01/10/2026'})


def test_lista_solo_se_paga(proc, lista_disponible):
    datos = proc.create_operation_data({'num_lista': '57', 'fecha_pago': '01/10/2026'})
    assert datos['modo'] == tp.MODO_LISTA
    assert not datos['ordenar'] and datos['pagar']

    with pytest.raises(ValueError, match='ya esta ordenada'):
        proc.create_operation_data({'num_lista': '57', 'ordenar': True, 'fecha_pago': '01/10/2026'})


def test_un_mensaje_invalido_no_abre_sical(proc, monkeypatch):
    abierta = []
    monkeypatch.setattr(proc, 'setup_operation_window', lambda: abierta.append(1) or True)

    result = proc.execute({'num_lista': '57', 'fecha_pago': '01/10/2026'})

    assert result.status == OperationStatus.FAILED
    assert 'aun no esta disponible' in result.error
    assert abierta == []
    assert result.sical_is_open is False


# --- proceso completo con los pasos de SICAL sustituidos ----------------------

def test_execute_operacion_devuelve_estado_y_numero(proc, monkeypatch):
    monkeypatch.setattr(proc, 'setup_operation_window', lambda: True)
    llamadas = []
    monkeypatch.setattr(tp, 'ordenar_y_pagar',
                        lambda v, estado, logger, avisar=None: (
                            llamadas.append(estado['num_operacion']),
                            estado.update(ordenacion=tp.YA_ESTABA, pago=tp.HECHO)))

    result = proc.execute({'num_operacion': '226102509', 'fecha_ordenamiento': '23/09/2026'})

    assert result.status == OperationStatus.COMPLETED, result.error
    assert llamadas == ['226102509']
    assert result.num_operacion == '226102509'
    assert result.pago['ordenacion'] == tp.YA_ESTABA
    assert result.pago['pago'] == tp.HECHO


def test_execute_fallo_a_mitad_deja_el_estado(proc, monkeypatch):
    monkeypatch.setattr(proc, 'setup_operation_window', lambda: True)

    def falla(v, estado, logger, avisar=None):
        estado['ordenacion'] = tp.HECHO
        raise tp.ErrorSicalPago('SICAL: saldo insuficiente')
    monkeypatch.setattr(tp, 'ordenar_y_pagar', falla)

    result = proc.execute({'num_operacion': '1', 'fecha_ordenamiento': '23/09/2026'})

    assert result.status == OperationStatus.FAILED
    assert 'saldo insuficiente' in result.error
    assert result.pago['ordenacion'] == tp.HECHO
    assert result.pago['pago'] == tp.PENDIENTE


@pytest.fixture
def pasos_lista(monkeypatch):
    grabado = []
    monkeypatch.setattr(tp, 'establecer_fecha', lambda v, f: grabado.append(('fecha', f)))
    monkeypatch.setattr(tp, 'pagar_lista', lambda v, n, l: grabado.append(('pagar_lista', n)))
    monkeypatch.setattr(tp, 'salir', lambda v, tras_pago=True: grabado.append(('salir', tras_pago)))
    monkeypatch.setattr(tp, 'leer_error_sical', lambda v: None)
    return grabado


def test_pagar_lista_y_salir(pasos_lista):
    estado = tp.nuevo_estado(tp.MODO_LISTA, '57', fecha_ordenamiento='01102026',
                             fecha_pago='01102026', ordenar=False)
    tp.pagar_lista_y_salir(None, estado, LOG)

    assert pasos_lista == [('fecha', '01102026'), ('pagar_lista', '57'), ('salir', True)]
    assert estado['num_lista'] == '57' and estado['num_operacion'] is None
    assert estado['pago'] == tp.HECHO


def test_lista_no_pendiente_sale_limpio_y_lo_dice(pasos_lista, monkeypatch):
    def no_pendiente(v, n, l):
        raise tp.ListaNoPendiente('la lista 57 no esta entre las pendientes de pago: [\'58\']')
    monkeypatch.setattr(tp, 'pagar_lista', no_pendiente)

    estado = tp.nuevo_estado(tp.MODO_LISTA, '57', fecha_pago='01102026', ordenar=False)
    with pytest.raises(tp.ListaNoPendiente):
        tp.pagar_lista_y_salir(None, estado, LOG)

    assert pasos_lista[-1] == ('salir', False)
    assert estado['pago'] == tp.PENDIENTE
    assert 'no esta entre las pendientes' in estado['error_sical']


# --- desplegable de listas ---------------------------------------------------

@pytest.mark.parametrize('texto, numero', [
    ('57', '57'), ('0057', '57'), (' 57 - Nomina septiembre', '57'), ('0', '0'),
    ('', None), (None, None), ('Lista', None),
])
def test_numero_de_lista(texto, numero):
    assert tp.numero_de_lista(texto) == numero


class _Hijo:
    def __init__(self, name, control_type='ListItemControl'):
        self.name = name
        self.control_type = control_type


class _Combo:
    handle = 0

    def __init__(self, hijos):
        self._hijos = hijos

    def iter_children(self, max_depth=8):
        return iter(self._hijos)


def test_sin_handle_lee_los_elementos_por_ui_automation():
    combo = _Combo([_Hijo('57'), _Hijo('58'), _Hijo('', 'ListItemControl'), _Hijo('x', 'ButtonControl')])
    assert tp.leer_items_desplegable(combo) == ['57', '58']


def test_si_no_se_puede_leer_es_none_y_no_lista_vacia():
    # None no autoriza a decir «no hay listas»: pagar_lista no bloquea con None
    assert tp.leer_items_desplegable(_Combo([])) is None


# --- enrutado en el consumidor ------------------------------------------------

def test_el_consumidor_enruta_los_tipos_nuevos():
    from gasto_task_consumer import OPERATION_PROCESSORS
    assert OPERATION_PROCESSORS['ordenarypagar'] is OrdenarPagarProcessor
    assert OPERATION_PROCESSORS['listas_pendientes_pago'] is ListasPendientesPagoProcessor


def test_consulta_de_listas(monkeypatch):
    proc = ListasPendientesPagoProcessor(LOG)
    monkeypatch.setattr(proc, 'setup_operation_window', lambda: True)
    monkeypatch.setattr(tp, 'consultar_listas_pendientes', lambda v, l: ['57', '58'])

    result = proc.execute({})

    assert result.status == OperationStatus.COMPLETED, result.error
    assert result.pago == {'modo': 'consulta_listas', 'listas_pendientes': ['57', '58']}


def test_consulta_de_listas_ilegible_falla(monkeypatch):
    proc = ListasPendientesPagoProcessor(LOG)
    monkeypatch.setattr(proc, 'setup_operation_window', lambda: True)
    monkeypatch.setattr(tp, 'consultar_listas_pendientes', lambda v, l: None)

    result = proc.execute({})

    assert result.status == OperationStatus.FAILED
    assert result.pago['listas_pendientes'] is None
