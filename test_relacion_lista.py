"""
Pruebas de la relacion de una lista -el documento del pago por lista- sin SICAL.

Lo que importa es lo que NO se pulsa: el panel de listados tiene al lado de la
relacion cartas, mandamientos y cheques que van a la impresora, y la barra del
Visualizador un boton que manda el documento a portafirmas. Cada guardia se
prueba haciendo que falle su condicion y comprobando que no se llega a pulsar
lo que generaria el listado. Los localizadores no se prueban aqui; eso solo lo
dice SICAL.

Run: pytest test_relacion_lista.py
"""

import json
import logging
import os
from types import SimpleNamespace

import pytest

from doc_pipeline import iconos, visualizador
from processors import tesoreria_pagos as tp
from processors import ordenar_pagar_processor as opp
from processors.ordenar_pagar_processor import (OrdenarPagarProcessor, RelacionListaProcessor,
                                                capturar_relacion)
from sical_base import OperationResult, OperationStatus
import document_mode

LOG = logging.getLogger('test')
P = tp.TESORERIA_PAGOS_PATHS


# --- iconos -------------------------------------------------------------------

def test_huella_es_la_de_la_skill():
    # Calculada con sical-inspector/scripts/huella_icono.py el 07/10/2026. Si
    # esto cambia, las referencias de iconos/visualizador.json dejan de valer.
    from PIL import Image
    img = Image.new('RGB', (33, 31))
    img.putdata([((x * 7 + y * 3) % 256, (x * y) % 256, (x * 13) % 256)
                 for y in range(31) for x in range(33)])
    assert iconos.huella(img) == '00200020002000230027001c003000e001c00120032106230c260c2c18191833'


def test_las_referencias_se_reconocen_cada_una_como_si_misma():
    referencias = iconos.cargar_referencias()
    assert {'pdf', 'salir', 'firma', 'imprimir', 'imprimir2', 'excel'} <= set(referencias)
    for nombre, ref in referencias.items():
        assert iconos.identificar(ref['huella'], referencias)[0] == nombre


def test_no_adivina_entre_dos_iconos_parecidos():
    referencias = {'a': {'huella': '0' * 64}, 'b': {'huella': '0' * 62 + '07'}}
    assert iconos.identificar('0' * 64, referencias)[0] is None


def test_un_boton_que_no_se_reconoce_no_se_pulsa():
    with pytest.raises(iconos.IconoNoReconocido, match='pdf'):
        iconos.boton({'salir': object(), '_vistos': 'salir(0/90), ?(80/95)'}, 'pdf')


# --- Visualizador: guardar el PDF ---------------------------------------------

class _Boton:
    def __init__(self, nombre, pulsado, al_pulsar=None):
        self.nombre, self._pulsado, self._al_pulsar = nombre, pulsado, al_pulsar

    def click(self, wait_time=None):
        self._pulsado.append(self.nombre)
        if self._al_pulsar:
            self._al_pulsar()
        return self


class _Visor:
    def foreground_window(self):
        pass


def _pdf_con_texto(ruta, texto):
    """Un PDF minimo con una linea de texto que pypdf sabe extraer."""
    contenido = f'BT /F1 12 Tf 20 100 Td ({texto}) Tj ET'.encode('latin-1')
    objetos = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] '
        b'/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
        b'<< /Length ' + str(len(contenido)).encode() + b' >>\nstream\n' + contenido + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    salida = bytearray(b'%PDF-1.4\n')
    posiciones = []
    for i, obj in enumerate(objetos, 1):
        posiciones.append(len(salida))
        salida += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(salida)
    salida += f'xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n'.encode()
    for p in posiciones:
        salida += f'{p:010d} 00000 n \n'.encode()
    salida += f'trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    with open(ruta, 'wb') as fh:
        fh.write(salida)
    return ruta


@pytest.fixture
def visor_falso(monkeypatch):
    """Un Visualizador cuya barra se reconoce entera y un «Guardar como» que escribe el PDF."""
    pulsado = []
    estado = {'nombre': None}
    barra = {nombre: _Boton(nombre, pulsado) for nombre in ('pdf', 'salir', 'firma', 'imprimir')}
    barra['_vistos'] = ''
    monkeypatch.setattr(iconos, 'identificar_barra', lambda visor, referencias=None: barra)
    monkeypatch.setattr(visualizador, 'ESPERA_BARRA_S', 0)
    monkeypatch.setattr(visualizador.time, 'sleep', lambda s: None)

    campo = SimpleNamespace(set_value=lambda v: estado.update(nombre=v))
    guardar = _Boton('guardar', pulsado,
                     al_pulsar=lambda: _pdf_con_texto(estado['nombre'], 'Lista 20260111'))
    dialogo = SimpleNamespace(find=lambda loc, **k: campo if 'Nombre' in loc else guardar)
    monkeypatch.setattr(visualizador, 'wait_for_window', lambda patron, **k: dialogo)
    return SimpleNamespace(pulsado=pulsado, barra=barra)


def test_guardar_pdf_pulsa_el_icono_de_pdf_y_nunca_el_de_firma(tmp_path, visor_falso):
    destino = str(tmp_path / 'lista.pdf')
    assert visualizador.guardar_pdf(_Visor(), destino, referencias={}) == destino
    assert visor_falso.pulsado == ['pdf', 'guardar']
    assert open(destino, 'rb').read().startswith(b'%PDF')


def test_guardar_pdf_borra_antes_el_de_otra_ejecucion(tmp_path, visor_falso, monkeypatch):
    # Con el viejo ahi, un guardado que fallara devolveria el viejo como nuevo.
    destino = tmp_path / 'lista.pdf'
    destino.write_bytes(b'%PDF viejo %%EOF')
    borrado_antes = []
    visor_falso.barra['pdf']._al_pulsar = lambda: borrado_antes.append(not destino.exists())
    visualizador.guardar_pdf(_Visor(), str(destino), referencias={})
    assert borrado_antes == [True]


def test_cerrar_con_la_ventana_ya_cerrada_no_es_un_fallo(visor_falso, monkeypatch, caplog):
    # 07/10/2026: tras pulsar Salir, buscar el «Sí» en la ventana ya cerrada
    # lanzo, y el registro dijo «no se pudo cerrar» de una ventana cerrada.
    abiertas = []

    class _VisorQueSeCierra(_Visor):
        def find(self, locator, **kw):
            raise RuntimeError('`root_element` provided is no longer valid.')
    visor = _VisorQueSeCierra()
    abiertas.append(visor)
    visor_falso.barra['salir']._al_pulsar = abiertas.clear
    monkeypatch.setattr(visualizador, 'wait_for_window',
                        lambda patron, **k: abiertas[0] if abiertas else None)

    with caplog.at_level(logging.WARNING):
        assert visualizador.cerrar(referencias={}) is True
    assert visor_falso.pulsado == ['salir']
    assert not [r for r in caplog.records if 'no se pudo cerrar' in r.getMessage()]


def test_sin_icono_de_pdf_no_se_pulsa_nada(tmp_path, visor_falso):
    del visor_falso.barra['pdf']
    with pytest.raises(iconos.IconoNoReconocido):
        visualizador.guardar_pdf(_Visor(), str(tmp_path / 'x.pdf'), referencias={})
    assert visor_falso.pulsado == []


# --- Tesoreria Pagos: la via de impresion ----------------------------------------

class _Patron:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Control:
    """Un control con lo que lee el robot: activo, marcado, seleccionado."""

    def __init__(self, nombre, sesion, activo=True, marcada=False, al_pulsar=None):
        self.name = nombre
        self._sesion = sesion
        self.marcada = marcada
        self._al_pulsar = al_pulsar
        self.ui_automation_control = _Patron(
            IsEnabled=activo,
            GetTogglePattern=lambda: _Patron(ToggleState=1 if self.marcada else 0),
            GetSelectionItemPattern=lambda: _Patron(IsSelected=True))

    def click(self, wait_time=None):
        self._sesion.pulsado.append(self.name)
        if self._al_pulsar:
            self._al_pulsar()
        return self


class _Combo:
    def __init__(self, sesion, listas, hace_caso=True):
        self.handle = 0
        self._sesion = sesion
        self._listas = listas
        self._hace_caso = hace_caso
        self.valor = '0'
        self.ui_automation_control = _Patron(
            GetLegacyIAccessiblePattern=lambda: _Patron(Value=self.valor))

    def iter_children(self, max_depth=8):
        return iter([_Patron(name=l, control_type='ListItemControl') for l in self._listas])

    def select(self, valor):
        self._sesion.pulsado.append(f'elegir {valor}')
        if self._hace_caso:
            self.valor = valor


class _Campo:
    def __init__(self, acepta=True):
        self.valor = '1'
        self._acepta = acepta

    def set_value(self, v):
        if self._acepta:
            self.valor = v

    def send_keys(self, keys, **kw):
        pass

    def get_value(self):
        return self.valor


class _TesPagos:
    """
    Tesoreria Pagos con su panel de listados, el dialogo de orden y lo que
    hace cada boton, segun el recorrido mapeado el 07/10/2026.
    """

    def __init__(self, listas=('20260103', '20260111'), imprimir_activo=True,
                 ya_marcada=None, combo_hace_caso=True, orden_acepta=True, marca_tambien=None):
        self.pulsado = []
        self.panel_abierto = False
        self.modal_abierto = False
        self.visor_abierto = False
        self.combo = _Combo(self, ['0', *listas], hace_caso=combo_hace_caso)
        self.campo = _Campo(acepta=orden_acepta)
        self.casillas = [_Control(n, self) for n in
                         ('Carta de Pagos de Descuento', 'Mandamientos de Pagos', tp.RELACION_OPERACIONES)]
        relacion = self.casillas[-1]

        def marcar_relacion():
            relacion.marcada = True
            self.modal_abierto = True
            for c in self.casillas:
                if c.name == marca_tambien:
                    c.marcada = True
        relacion._al_pulsar = marcar_relacion
        self._ya_marcada = ya_marcada
        self.imprimir = _Control('imprimir', self, activo=imprimir_activo, al_pulsar=self._abrir_panel)
        self.aceptar = _Control('generar listado', self, al_pulsar=lambda: setattr(self, 'visor_abierto', True))
        self.puerta = _Control('puerta', self, al_pulsar=lambda: setattr(self, 'panel_abierto', False))
        self.ok = _Control('ok', self, al_pulsar=lambda: setattr(self, 'modal_abierto', False))
        self.cancel = _Control('cancel', self, al_pulsar=lambda: setattr(self, 'modal_abierto', False))

    def _abrir_panel(self):
        self.panel_abierto = True
        for c in self.casillas:
            c.marcada = c.name == self._ya_marcada

    def foreground_window(self):
        pass

    def find(self, locator, **kw):
        if locator == P['operaciones_group']:
            return SimpleNamespace(find=lambda loc, **k: self.imprimir)
        if locator == P['panel_listados']:
            return _PanelFalso(self) if self.panel_abierto else None
        if locator == P['orden_listado_form']:
            if not self.modal_abierto:
                return None
            return SimpleNamespace(find=lambda loc, **k: {P['orden_listado_input']: self.campo,
                                                          tp.COMMON_DIALOG_PATHS['ok_button']: self.ok,
                                                          'class:"TButton" and name:"Cancel"': self.cancel}[loc])
        return None


class _PanelFalso:
    def __init__(self, v):
        self._v = v

    def find(self, locator, **kw):
        v = self._v
        grupo = SimpleNamespace(iter_children=lambda max_depth=1: iter(v.casillas),
                                find=lambda loc, **k: v.casillas[-1])
        return {
            P['grupo_listados']: grupo,
            P['combo_lista_listado']: v.combo,
            P['opcion_lista_listado']: _Control('Nº Lista', v),
            P['aceptar_listado_button']: v.aceptar,
            P['salir_listado_button']: v.puerta,
        }.get(locator)


@pytest.fixture
def sin_visor(monkeypatch):
    """El Visualizador sustituido: aparece al generar el listado y guarda sin mas."""
    guardado = []

    def esperar(patron, timeout=15.0, **k):
        return SimpleNamespace(foreground_window=lambda: None) if guardado is not None else None
    monkeypatch.setattr(tp, 'leer_error_sical', lambda v: None)
    monkeypatch.setattr(visualizador, 'guardar_pdf', lambda visor, destino: guardado.append(destino) or destino)
    monkeypatch.setattr(visualizador, 'cerrar', lambda: True)
    monkeypatch.setattr(tp, 'wait_for_window', esperar)
    return guardado


def test_relacion_recorre_el_camino_mapeado(sin_visor):
    v = _TesPagos()
    ruta = tp.relacion_lista_pdf(v, '20260111', 'C:/tmp/lista.pdf', LOG)

    assert ruta == 'C:/tmp/lista.pdf' and sin_visor == ['C:/tmp/lista.pdf']
    assert v.pulsado == ['imprimir', tp.RELACION_OPERACIONES, 'ok', 'elegir 20260111',
                         'generar listado', 'puerta']
    assert v.campo.valor == '3'
    assert not v.panel_abierto and not v.modal_abierto


def test_lista_que_no_esta_no_marca_ni_genera_nada(sin_visor):
    v = _TesPagos(listas=('20260103',))
    with pytest.raises(tp.ListaInexistente):
        tp.relacion_lista_pdf(v, '20260111', 'x.pdf', LOG)
    assert v.pulsado == ['imprimir', 'puerta']
    assert sin_visor == []


def test_panel_con_otro_listado_marcado_no_genera_nada(sin_visor):
    # Los mandamientos van a la impresora: con uno marcado no se pulsa el check.
    v = _TesPagos(ya_marcada='Mandamientos de Pagos')
    with pytest.raises(tp.ErrorRelacion, match='marcados'):
        tp.relacion_lista_pdf(v, '20260111', 'x.pdf', LOG)
    assert 'generar listado' not in v.pulsado and tp.RELACION_OPERACIONES not in v.pulsado
    assert not v.panel_abierto


def test_otro_listado_marcado_antes_del_check_no_genera_nada(sin_visor):
    # Aunque el panel se abra limpio, lo que cuenta es lo que hay marcado al
    # pulsar el check: los mandamientos irian a la impresora.
    v = _TesPagos(marca_tambien='Mandamientos de Pagos')
    with pytest.raises(tp.ErrorRelacion, match='impresora'):
        tp.relacion_lista_pdf(v, '20260111', 'x.pdf', LOG)
    assert 'generar listado' not in v.pulsado
    assert sin_visor == []


def test_desplegable_que_no_hace_caso_no_saca_la_relacion_de_otra(sin_visor):
    v = _TesPagos(combo_hace_caso=False)
    with pytest.raises(tp.ErrorRelacion, match='desplegable muestra'):
        tp.relacion_lista_pdf(v, '20260111', 'x.pdf', LOG)
    assert 'generar listado' not in v.pulsado
    assert sin_visor == []


def test_dialogo_de_orden_que_no_acepta_el_3_se_cancela(sin_visor):
    v = _TesPagos(orden_acepta=False)
    with pytest.raises(tp.ErrorRelacion, match='orden'):
        tp.relacion_lista_pdf(v, '20260111', 'x.pdf', LOG)
    assert 'cancel' in v.pulsado and 'ok' not in v.pulsado
    assert 'generar listado' not in v.pulsado
    assert not v.modal_abierto and not v.panel_abierto


def test_sin_fecha_imprimir_esta_desactivado_y_no_se_pulsa(sin_visor):
    v = _TesPagos(imprimir_activo=False)
    with pytest.raises(tp.ErrorRelacion, match='fecha'):
        tp.relacion_lista_pdf(v, '20260111', 'x.pdf', LOG)
    assert v.pulsado == []


def test_el_panel_que_deja_un_pago_se_cierra_antes_de_abrirlo_limpio(sin_visor):
    v = _TesPagos()
    v._abrir_panel()
    v.casillas[1].marcada = True    # lo que SICAL deje marcado tras pagar
    tp.relacion_lista_pdf(v, '20260111', 'x.pdf', LOG)
    assert v.pulsado[:2] == ['puerta', 'imprimir']


def test_despejar_cierra_el_panel_de_listados_que_quedo_abierto():
    v = _TesPagos()
    v._abrir_panel()
    assert tp.despejar(v, LOG) == ['panel de listados']
    assert v.pulsado == ['puerta']


# --- pagar la lista y traerse su relacion -------------------------------------

@pytest.fixture
def pago(monkeypatch):
    grabado = []
    monkeypatch.setattr(tp, 'establecer_fecha', lambda v, f: grabado.append(('fecha', f)))
    monkeypatch.setattr(tp, 'pagar_lista', lambda v, n, l: grabado.append(('pagar_lista', n)))
    monkeypatch.setattr(tp, 'cerrar_panel_listados', lambda v: grabado.append(('cerrar_panel',)) or True)
    monkeypatch.setattr(tp, 'salir', lambda v, tras_pago=True: grabado.append(('salir', tras_pago)))
    monkeypatch.setattr(tp, 'leer_error_sical', lambda v: None)
    salir = SimpleNamespace(click=lambda wait_time=None: grabado.append(('Salir',)))
    ventana = SimpleNamespace(foreground_window=lambda: None, find=lambda loc, **k: salir)
    return SimpleNamespace(grabado=grabado, ventana=ventana)


def _estado():
    return tp.nuevo_estado(tp.MODO_LISTA, '20260111', fecha_ordenamiento='07102026',
                           fecha_pago='07102026', ordenar=False)


def test_tras_pagar_va_despues_del_pago_y_antes_de_salir(pago):
    estado = _estado()
    tp.pagar_lista_y_salir(pago.ventana, estado, LOG,
                           tras_pagar=lambda v: pago.grabado.append(('documento',)))
    assert pago.grabado == [('fecha', '07102026'), ('pagar_lista', '20260111'),
                            ('cerrar_panel',), ('documento',), ('Salir',)]
    assert estado['pago'] == tp.HECHO


def test_un_documento_que_falla_no_toca_el_pago(pago):
    def falla(v):
        raise RuntimeError('el Visualizador no se ha abierto')
    estado = _estado()
    tp.pagar_lista_y_salir(pago.ventana, estado, LOG, tras_pagar=falla)
    assert estado['pago'] == tp.HECHO and estado['error_sical'] is None
    assert pago.grabado[-1] == ('Salir',)


def test_sin_documento_sale_como_siempre(pago):
    tp.pagar_lista_y_salir(pago.ventana, _estado(), LOG)
    assert pago.grabado == [('fecha', '07102026'), ('pagar_lista', '20260111'), ('salir', True)]


# --- el procesador ----------------------------------------------------------------

def _cfg(tmp_path):
    return SimpleNamespace(SICAL_PDF_WORKDIR=str(tmp_path), MAX_INLINE_BYTES=2 * 1024 * 1024)


def test_el_sobre_de_la_lista_es_de_la_fase_de_pago(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, 'relacion_lista_pdf',
                        lambda v, n, destino, l, a=None: _pdf_con_texto(destino, f'N de Lista {n}'))
    sobre = capturar_relacion(None, '20260111', LOG, cfg=_cfg(tmp_path))
    assert sobre['capture_status'] == 'CAPTURED', sobre['capture_error']
    assert sobre['phase'] == 'P' and sobre['filename'] == 'lista_20260111.pdf'
    assert sobre['data']


def test_un_pdf_de_otra_lista_no_se_da_por_bueno(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, 'relacion_lista_pdf',
                        lambda v, n, destino, l, a=None: _pdf_con_texto(destino, 'N de Lista 20260103'))
    sobre = capturar_relacion(None, '20260111', LOG, cfg=_cfg(tmp_path))
    assert sobre['capture_status'] == 'FAILED'
    assert 'no nombra la lista 20260111' in sobre['capture_error']


def test_capturar_relacion_nunca_lanza(tmp_path, monkeypatch):
    def falla(*a, **k):
        raise tp.ListaInexistente('la lista 20260111 no esta en el desplegable')
    monkeypatch.setattr(tp, 'relacion_lista_pdf', falla)
    sobre = capturar_relacion(None, '20260111', LOG, cfg=_cfg(tmp_path))
    assert sobre['capture_status'] == 'FAILED' and 'desplegable' in sobre['capture_error']


@pytest.mark.parametrize('modo, captura', [
    (document_mode.INLINE_CAPTURE, True),
    (document_mode.DEFERRED, False),
    (document_mode.LEGACY_PRINT, False),
])
def test_el_pago_por_lista_trae_la_relacion_solo_si_se_pide(modo, captura, monkeypatch):
    proc = OrdenarPagarProcessor(LOG)
    proc.set_document_mode(modo)
    monkeypatch.setattr(proc, 'setup_operation_window', lambda: True)
    recibido = {}

    def pagar(v, estado, logger, avisar=None, tras_pagar=None):
        recibido['tras_pagar'] = tras_pagar
        estado['pago'] = tp.HECHO
        if tras_pagar:
            tras_pagar(v)
    monkeypatch.setattr(tp, 'pagar_lista_y_salir', pagar)
    monkeypatch.setattr(opp, 'capturar_relacion',
                        lambda v, n, l, avisar=None: {'phase': 'P', 'capture_status': 'CAPTURED',
                                                      'capture_error': None})

    result = proc.execute({'num_lista': '20260111', 'fecha_pago': '07/10/2026'})
    assert result.status == OperationStatus.COMPLETED, result.error
    assert (recibido['tras_pagar'] is not None) == captura
    assert bool(getattr(result, '_contable_documents', None)) == captura


@pytest.mark.parametrize('detalle, motivo', [
    ({}, 'num_lista'),
    ({'num_lista': '2026a'}, 'num_lista'),
    ({'num_lista': '0'}, 'num_lista'),
    ({'num_lista': '20260111', 'fecha': '31/02/2026'}, 'fecha'),
])
def test_relacion_lista_rechaza_lo_que_no_cuadra(detalle, motivo):
    with pytest.raises(ValueError, match=motivo):
        RelacionListaProcessor(LOG).create_operation_data(detalle)


@pytest.mark.parametrize('estado_captura, status', [('CAPTURED', OperationStatus.COMPLETED),
                                                    ('FAILED', OperationStatus.FAILED)])
def test_relacion_lista_sale_bien_solo_con_el_documento(estado_captura, status, monkeypatch):
    proc = RelacionListaProcessor(LOG)
    proc.set_document_mode(document_mode.DEFERRED)      # el documento es la tarea: se ignora
    monkeypatch.setattr(proc, 'setup_operation_window', lambda: True)
    pasos = []
    monkeypatch.setattr(tp, 'establecer_fecha', lambda v, f: pasos.append(('fecha', f)))
    monkeypatch.setattr(tp, 'salir', lambda v, tras_pago=True: pasos.append(('salir', tras_pago)))
    monkeypatch.setattr(opp, 'capturar_relacion',
                        lambda v, n, l, avisar=None: {'phase': 'P', 'capture_status': estado_captura,
                                                      'capture_error': None if estado_captura == 'CAPTURED'
                                                      else 'relacion de la lista: no se abrio'})

    result = proc.execute({'num_lista': '20260111', 'fecha': '07/10/2026'})
    assert result.status == status
    assert pasos == [('fecha', '07102026'), ('salir', False)]
    assert result._contable_documents[0]['phase'] == 'P'


def test_el_consumidor_enruta_relacion_lista():
    from gasto_task_consumer import OPERATION_PROCESSORS
    assert OPERATION_PROCESSORS['relacion_lista'] is RelacionListaProcessor


def test_las_referencias_van_en_el_exe():
    spec = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gastos_robot.spec'),
                encoding='utf-8').read()
    assert "('iconos/visualizador.json', 'iconos')" in spec
    assert "'doc_pipeline.visualizador'" in spec and "'doc_pipeline.iconos'" in spec
