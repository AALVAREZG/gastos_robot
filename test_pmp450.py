"""PMP450 tras la actualizacion de SICAL del 21/10/2026."""

import pytest
from robocorp import windows

import processors.pmp450_processor as pmp
from sical_constants import PMP450_FORM_PATHS


class _Control:
    def __init__(self, nombre, left, top, ancho=30):
        self.nombre = nombre
        self.left, self.top, self.right = left, top, left + ancho


class _Panel(_Control):
    """Panel de Tesoreria: rect [94, 246, 804, 298] en mona30."""

    def __init__(self, edits):
        super().__init__('panel', 94, 246, ancho=710)
        self.edits = edits

    def find_many(self, locator, **kwargs):
        assert locator == 'class:"TDBEdit"'
        return list(self.edits)


def _con_panel(monkeypatch, edits):
    panel = _Panel(edits)

    def buscar(ventana, locator, **kwargs):
        assert locator == PMP450_FORM_PATHS['tesoreria_panel']
        return panel
    monkeypatch.setattr(pmp, 'find_control', buscar)


# Cajas leidas de los volcados del 27/10/2026, en el orden UIA de cada estado
F_PAGO = _Control('F. Pago', 150, 254)
T_PAGO = _Control('T. Pago', 150, 275)
PERCEPTOR = _Control('C/B Perceptor', 490, 254)
PAGADOR = _Control('C/B Pagador', 490, 275)


def _nombres(campos):
    return {clave: c.nombre for clave, c in campos.items()}


def test_pmp_nueva_sin_perceptor(monkeypatch):
    _con_panel(monkeypatch, [PAGADOR, T_PAGO, F_PAGO])
    assert _nombres(pmp.campos_tesoreria(None)) == {
        'forma_pago': 'F. Pago', 'tipo_pago': 'T. Pago', 'caja': 'C/B Pagador'}


def test_con_perceptor_nunca_lo_toma_por_tipo_de_pago(monkeypatch):
    _con_panel(monkeypatch, [PAGADOR, PERCEPTOR, T_PAGO, F_PAGO])
    assert _nombres(pmp.campos_tesoreria(None)) == {
        'forma_pago': 'F. Pago', 'tipo_pago': 'T. Pago', 'caja': 'C/B Pagador'}


def test_sin_tesoreria_marcada_falla_con_error_claro(monkeypatch):
    _con_panel(monkeypatch, [])
    with pytest.raises(windows.ElementNotFound, match='Tesoreria'):
        pmp.campos_tesoreria(None)


def test_disposicion_inesperada_falla(monkeypatch):
    _con_panel(monkeypatch, [PAGADOR, T_PAGO, F_PAGO, _Control('otro', 150, 290)])
    with pytest.raises(windows.ElementNotFound):
        pmp.campos_tesoreria(None)


def test_nuevo_se_busca_por_nombre():
    # 3|4 es ahora «Consulta Gral.»
    assert PMP450_FORM_PATHS['nuevo_button'] == 'class:"TBitBtn" and name:"Nuevo"'


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


class _Mona30:
    """Devuelve, busqueda a busqueda, el Information y los Confirm indicados."""

    def __init__(self, info=None, confirms=()):
        self.info, self.confirms = info, list(confirms)

    def find(self, locator, **kwargs):
        if locator == PMP450_FORM_PATHS['dialogo_information']:
            hallado, self.info = self.info, None
            return hallado
        return self.confirms.pop(0) if self.confirms else None


@pytest.fixture
def procesador(monkeypatch):
    monkeypatch.setattr(pmp.time, 'sleep', lambda s: None)
    return pmp.PMP450Processor.__new__(pmp.PMP450Processor)


def test_validar_cierra_information_y_contesta_no_a_adjuntar(procesador):
    # Orden visto el 31/10/2026: Confirm validar, Information, Confirm adjuntar
    validar, info, adjuntar = _Dialogo(1), _Dialogo(2), _Dialogo(3)
    procesador._cerrar_dialogos_tras_validar(_Mona30(info, [validar, adjuntar]), handle_validar=1)
    assert info.pulsado == [pmp.COMMON_DIALOG_PATHS['ok_button']]
    assert validar.pulsado == []
    assert adjuntar.pulsado == [pmp.COMMON_DIALOG_PATHS['no_button']]


def test_validar_sin_information_tambien_vale(procesador):
    adjuntar = _Dialogo(3)
    procesador._cerrar_dialogos_tras_validar(_Mona30(confirms=[adjuntar]), handle_validar=1)
    assert adjuntar.pulsado == [pmp.COMMON_DIALOG_PATHS['no_button']]


def test_sin_dialogo_de_adjuntar_falla(procesador):
    with pytest.raises(windows.ElementNotFound):
        procesador._cerrar_dialogos_tras_validar(_Mona30(), handle_validar=1, timeout=0.01)
