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


def test_lista_solo_se_paga(proc):
    datos = proc.create_operation_data({'num_lista': '57', 'fecha_pago': '01/10/2026'})
    assert datos['modo'] == tp.MODO_LISTA
    assert not datos['ordenar'] and datos['pagar']

    with pytest.raises(ValueError, match='ya esta ordenada'):
        proc.create_operation_data({'num_lista': '57', 'ordenar': True, 'fecha_pago': '01/10/2026'})


def test_un_mensaje_invalido_no_abre_sical(proc, monkeypatch):
    abierta = []
    monkeypatch.setattr(proc, 'setup_operation_window', lambda: abierta.append(1) or True)

    result = proc.execute({'num_operacion': '1', 'num_lista': '57', 'fecha_pago': '01/10/2026'})

    assert result.status == OperationStatus.FAILED
    assert 'solo uno' in result.error
    assert abierta == []
    assert result.sical_is_open is False


# --- pago por lista contra una ventana de mentira -----------------------------
#
# Lo que importa en los fallos es lo que NO se hace: ni teclear la lista ni
# validar. Se graba cada click y cada tecla.

class _Control:
    def __init__(self, nombre, grabado, items=None):
        self.nombre = nombre
        self._grabado = grabado
        self._items = items
        self.handle = 0
        self.name = nombre

    def click(self, wait_time=None):
        self._grabado.append(('click', self.nombre))
        return self

    def send_keys(self, keys=None, **kwargs):
        self._grabado.append(('teclas', self.nombre, keys))
        return self

    def iter_children(self, max_depth=8):
        return iter([_Hijo(i) for i in (self._items or [])])


class _Ventana:
    def __init__(self, listas):
        self.grabado = []
        P = tp.TESORERIA_PAGOS_PATHS
        self._controles = {
            P[clave]: _Control(clave, self.grabado)
            for clave in ('pagar_button', 'option_num_lista', 'cancel_operation_button',
                          'validar_op_button', 'validar_orden_button')
        }
        self._controles[P['num_lista_combo']] = _Control('num_lista_combo', self.grabado, items=listas)

    def find(self, locator, **kwargs):
        return self._controles.get(locator)

    def tecleado(self):
        return [g for g in self.grabado if g[0] == 'teclas']

    def pulsado(self):
        return [g[1] for g in self.grabado if g[0] == 'click']


def test_lista_ya_pagada_cancela_sin_teclear(monkeypatch):
    ventana = _Ventana(listas=['58', '61'])
    with pytest.raises(tp.ListaNoPendiente, match='57 no esta entre las pendientes'):
        tp.pagar_lista(ventana, '57', LOG)

    assert ventana.tecleado() == []
    assert ventana.pulsado()[-1] == 'cancel_operation_button'
    assert 'validar_op_button' not in ventana.pulsado()


def test_lista_pendiente_con_el_pago_por_lista_apagado_cancela_sin_teclear(monkeypatch):
    monkeypatch.setattr(tp, 'PAGO_LISTA_DISPONIBLE', False)
    ventana = _Ventana(listas=['0057', '58'])
    with pytest.raises(tp.PagoListaNoDisponible, match='57 esta pendiente'):
        tp.pagar_lista(ventana, '57', LOG)

    assert ventana.tecleado() == []
    assert ventana.pulsado()[-1] == 'cancel_operation_button'


def test_desplegable_ilegible_no_se_paga_sin_comprobar_la_lista():
    assert tp.PAGO_LISTA_DISPONIBLE is True
    ventana = _Ventana(listas=[])   # UI Automation sin elementos: ilegible
    with pytest.raises(tp.ListaNoComprobable, match='sin comprobarla'):
        tp.pagar_lista(ventana, '57', LOG)

    assert ventana.tecleado() == []
    assert ventana.pulsado()[-1] == 'cancel_operation_button'


def test_lista_pendiente_con_el_paso_disponible_teclea_y_valida(monkeypatch, lista_disponible):
    monkeypatch.setattr(tp, 'seleccionar_todas_las_operaciones',
                        lambda v: v.grabado.append(('click', 'seleccionar_todas')))
    # El OK final es un modal que la ventana de mentira no tiene
    monkeypatch.setattr(tp, 'find_control',
                        lambda v, loc, **k: v.find(loc) or _Control('info_ok', v.grabado))
    ventana = _Ventana(listas=['57'])

    tp.pagar_lista(ventana, '57', LOG)

    assert ('teclas', 'num_lista_combo', '57') in ventana.tecleado()
    pulsado = ventana.pulsado()
    assert pulsado.index('validar_op_button') < pulsado.index('seleccionar_todas') \
        < pulsado.index('validar_orden_button')
    assert 'cancel_operation_button' not in pulsado


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
        self.class_name = ''


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
    monkeypatch.setattr(tp, 'consultar_listas_pendientes', lambda v, f, l: ['57', '58'])

    result = proc.execute({})

    assert result.status == OperationStatus.COMPLETED, result.error
    assert result.pago == {'modo': 'consulta_listas', 'listas_pendientes': ['57', '58']}


def test_consulta_de_listas_ilegible_falla(monkeypatch):
    proc = ListasPendientesPagoProcessor(LOG)
    monkeypatch.setattr(proc, 'setup_operation_window', lambda: True)
    monkeypatch.setattr(tp, 'consultar_listas_pendientes', lambda v, f, l: None)

    result = proc.execute({})

    assert result.status == OperationStatus.FAILED
    assert result.pago['listas_pendientes'] is None


def test_consulta_usa_hoy_si_no_trae_fecha():
    from datetime import date
    datos = ListasPendientesPagoProcessor(LOG).create_operation_data({})
    assert datos['fecha'] == date.today().strftime('%d%m%Y')
    assert ListasPendientesPagoProcessor(LOG).create_operation_data({'fecha': '01/10/2026'})['fecha'] == '01102026'


# --- consulta de listas contra la ventana de mentira --------------------------

def test_consulta_teclea_la_fecha_antes_de_pulsar_pagar_y_sale(monkeypatch):
    # La primera prueba en SICAL pulso Pagar sin fecha y el dialogo no salio.
    ventana = _Ventana(listas=['0', '20130213', '20260103'])
    orden = []
    monkeypatch.setattr(tp, 'establecer_fecha', lambda v, f: orden.append(('fecha', f)))
    monkeypatch.setattr(tp, 'salir', lambda v, tras_pago=True: orden.append(('salir', tras_pago)))
    monkeypatch.setattr(tp, 'find_control', lambda v, loc, **k: v.find(loc))

    listas = tp.consultar_listas_pendientes(ventana, '02102026', LOG)

    assert listas == ['20130213', '20260103']   # sin el «0»
    assert orden == [('fecha', '02102026'), ('salir', False)]
    assert ventana.pulsado()[0] == 'pagar_button'
    assert ventana.pulsado()[-1] == 'cancel_operation_button'


def test_si_no_aparece_el_desplegable_no_pulsa_cancelar_y_sale(monkeypatch):
    # El boton de cancelar va por posicion: sin el dialogo podria ser otro.
    ventana = _Ventana(listas=['57'])
    del ventana._controles[tp.TESORERIA_PAGOS_PATHS['num_lista_combo']]
    salidas = []
    monkeypatch.setattr(tp, 'establecer_fecha', lambda v, f: None)
    monkeypatch.setattr(tp, 'salir', lambda v, tras_pago=True: salidas.append(tras_pago))

    def no_aparece(v, loc, **k):
        if v.find(loc) is None:
            raise RuntimeError(f'Could not locate control with locator: {loc!r}')
        return v.find(loc)
    monkeypatch.setattr(tp, 'find_control', no_aparece)

    with pytest.raises(RuntimeError, match='Could not locate'):
        tp.consultar_listas_pendientes(ventana, '02102026', LOG)

    assert 'cancel_operation_button' not in ventana.pulsado()
    assert salidas == [False]


def test_la_lista_cero_no_cuenta_como_pendiente(monkeypatch):
    ventana = _Ventana(listas=['0'])
    with pytest.raises(tp.ListaNoPendiente, match=r'pendientes de pago: \[\]'):
        tp.pagar_lista(ventana, '0000', LOG)


# --- comprobar el pago de una operacion, sin pagar ---------------------------

def test_comprobar_no_ordena_ni_paga(proc):
    datos = proc.create_operation_data({'num_operacion': '326100196', 'comprobar': True,
                                        'fecha_pago': '02/10/2026'})
    assert datos['comprobar'] and not datos['ordenar'] and not datos['pagar']


@pytest.mark.parametrize('detalle, motivo', [
    ({'num_lista': '57', 'comprobar': True, 'fecha_pago': '02/10/2026'}, 'solo para num_operacion'),
    ({'num_operacion': '1', 'comprobar': True, 'pagar': True, 'fecha_pago': '02/10/2026'}, 'no ordena ni paga'),
])
def test_comprobar_no_se_mezcla(proc, detalle, motivo):
    with pytest.raises(ValueError, match=motivo):
        proc.create_operation_data(detalle)


class _Modal:
    def __init__(self, texto, ventana, cierra=True):
        self.name = 'Error'
        self.class_name = 'TMessageForm'
        self._texto = texto
        self._ventana = ventana
        self._cierra = cierra

    def iter_children(self, max_depth=8):
        return iter([_Hijo(self._texto, control_type='TextControl')])

    def find(self, locator, **kwargs):
        if not self._cierra:
            return None
        modal = self

        class _Ok:
            def click(self, wait_time=None):
                modal._ventana.grabado.append(('click', 'ok_aviso'))
                modal._ventana.modales.remove(modal)
        return _Ok()


def _ventana_de_pago(modales_textos=(), cierra=True):
    ventana = _Ventana(listas=[])
    P = tp.TESORERIA_PAGOS_PATHS
    for clave in ('option_num_operacion', 'num_operacion_input'):
        ventana._controles[P[clave]] = _Control(clave, ventana.grabado)
    ventana.modales = [_Modal(t, ventana, cierra) for t in modales_textos]
    return ventana


@pytest.fixture
def modales(monkeypatch):
    def buscar(v, loc, **k):
        if 'TMessageForm' in loc:
            return v.modales[0] if v.modales else None
        return v.find(loc)
    monkeypatch.setattr(tp, 'find_control', buscar)


def test_comprobar_sin_aviso_cancela_sin_validar(modales):
    ventana = _ventana_de_pago()
    r = tp.comprobar_pago_operacion(ventana, '326100196', LOG)

    assert r == {'acepta': True, 'aviso_sical': None, 'avisos_cerrados': 0, 'no_seleccionable': False}
    assert ('teclas', 'num_operacion_input', '326100196') in ventana.tecleado()
    assert ventana.pulsado()[-1] == 'cancel_operation_button'
    assert 'validar_op_button' not in ventana.pulsado()
    assert 'validar_orden_button' not in ventana.pulsado()


def test_comprobar_con_aviso_lo_lee_lo_cierra_y_cancela(modales):
    ventana = _ventana_de_pago(['La operacion ya esta pagada', 'Proceso cancelado'])
    r = tp.comprobar_pago_operacion(ventana, '326100196', LOG)

    assert r['acepta'] is False
    assert r['aviso_sical'] == 'La operacion ya esta pagada | Proceso cancelado'
    assert r['avisos_cerrados'] == 2
    assert ventana.pulsado()[-1] == 'cancel_operation_button'
    assert 'validar_op_button' not in ventana.pulsado()


def test_comprobar_si_el_aviso_no_se_cierra_no_toca_nada_mas(modales):
    ventana = _ventana_de_pago(['Algo raro'], cierra=False)
    with pytest.raises(tp.ErrorSicalPago, match='Algo raro'):
        tp.comprobar_pago_operacion(ventana, '1', LOG)

    assert 'cancel_operation_button' not in ventana.pulsado()


def test_execute_comprobar_devuelve_lo_que_dijo_sical(proc, monkeypatch):
    monkeypatch.setattr(proc, 'setup_operation_window', lambda: True)

    def comprobar(v, estado, logger):
        estado['comprobacion'] = {'acepta': False, 'aviso_sical': 'ya pagada', 'avisos_cerrados': 1}
        estado['error_sical'] = 'ya pagada'
    monkeypatch.setattr(tp, 'comprobar_pago_y_salir', comprobar)

    result = proc.execute({'num_operacion': '326100196', 'comprobar': True, 'fecha_pago': '02/10/2026'})

    assert result.status == OperationStatus.COMPLETED, result.error
    assert result.pago['comprobacion']['aviso_sical'] == 'ya pagada'
    assert result.pago['ordenacion'] == tp.NO_SOLICITADO
    assert result.pago['pago'] == tp.NO_SOLICITADO


AVISO_REAL = 'Nº de Operación no seleccionable para la etapa de tesorería'


def test_comprobar_reconoce_el_aviso_de_no_seleccionable(modales):
    # El aviso sale dos veces y hay que pulsar OK en las dos (02/10/2026).
    ventana = _ventana_de_pago([AVISO_REAL, AVISO_REAL])
    r = tp.comprobar_pago_operacion(ventana, '326100219', LOG)

    assert r['acepta'] is False
    assert r['no_seleccionable'] is True
    assert r['avisos_cerrados'] == 2
    assert ventana.pulsado().count('ok_aviso') == 2


def test_pagar_una_operacion_no_pagable_cierra_los_avisos_y_cancela_sin_validar(modales):
    ventana = _ventana_de_pago([AVISO_REAL, AVISO_REAL])
    with pytest.raises(tp.OperacionNoPagable, match='no seleccionable'):
        tp.pagar_operacion(ventana, '326100219')

    pulsado = ventana.pulsado()
    assert pulsado.count('ok_aviso') == 2
    assert pulsado[-1] == 'cancel_operation_button'
    assert 'validar_op_button' not in pulsado
    assert 'validar_orden_button' not in pulsado


def test_ordenar_y_pagar_sale_limpio_si_no_es_pagable(monkeypatch):
    salidas = []
    monkeypatch.setattr(tp, 'establecer_fecha', lambda v, f: None)
    monkeypatch.setattr(tp, 'salir', lambda v, tras_pago=True: salidas.append(tras_pago))

    def no_pagable(v, num):
        raise tp.OperacionNoPagable(f'SICAL no deja pagar la operacion {num}: {AVISO_REAL}')
    monkeypatch.setattr(tp, 'pagar_operacion', no_pagable)

    estado = tp.nuevo_estado(tp.MODO_OPERACION, '326100219', fecha_pago='02102026', ordenar=False)
    with pytest.raises(tp.OperacionNoPagable):
        tp.ordenar_y_pagar(None, estado, LOG)

    assert salidas == [False]
    assert estado['pago'] == tp.PENDIENTE
    assert 'no seleccionable' in estado['error_sical']


def test_el_texto_cerrar_se_descarta_aunque_no_diga_que_es_boton(monkeypatch):
    monkeypatch.setattr(tp, '_texto_por_portapapeles', lambda modal: AVISO_REAL)
    modal = _Modal('Cerrar', None)
    modal.iter_children = lambda max_depth=8: iter([_Hijo('Cerrar', control_type='')])
    assert tp._texto_de(modal) == AVISO_REAL


# --- boton «Todos» del pago por lista -----------------------------------------

class _Boton:
    def __init__(self, pulsado, activo_tras=0):
        self._pulsado = pulsado
        self._consultas = 0
        self._activo_tras = activo_tras
        me = self

        class _UIA:
            @property
            def IsEnabled(self):
                me._consultas += 1
                return me._consultas > me._activo_tras
        self.ui_automation_control = _UIA()

    def click(self, wait_time=None):
        self._pulsado.append('todos')


@pytest.fixture
def todos(monkeypatch):
    pulsado = []
    estado = {'boton': _Boton(pulsado), 'aviso': None, 'error': None}
    monkeypatch.setattr(tp, 'leer_error_sical', lambda v: estado['error'])
    monkeypatch.setattr(tp.time, 'sleep', lambda s: None)

    def buscar(v, loc, **k):
        if loc == tp.TESORERIA_PAGOS_PATHS['todos_button']:
            return estado['boton']
        if 'TMessageForm' in loc:
            return estado['aviso']
        return None
    monkeypatch.setattr(tp, 'find_control', buscar)
    estado['pulsado'] = pulsado
    return estado


def test_todos_espera_a_que_el_boton_se_active(todos):
    todos['boton'] = _Boton(todos['pulsado'], activo_tras=3)
    tp.seleccionar_todas_las_operaciones(None)
    assert todos['pulsado'] == ['todos']


def test_todos_no_se_pulsa_con_la_ventana_de_errores_delante(todos):
    # TFVerError tiene su propio boton «Todos».
    todos['error'] = 'La lista tiene operaciones con errores'
    with pytest.raises(tp.ErrorSicalPago, match='antes de seleccionar'):
        tp.seleccionar_todas_las_operaciones(None)
    assert todos['pulsado'] == []


def test_un_aviso_al_seleccionar_para_sin_validar(todos):
    todos['aviso'] = _Modal('Las operaciones llevan retenciones', None)
    with pytest.raises(tp.ErrorSicalPago, match='retenciones'):
        tp.seleccionar_todas_las_operaciones(None)
    assert todos['pulsado'] == ['todos']
