"""
Pruebas de la navegacion del menu de SICAL (sical_utils.open_menu_option) sin SICAL.

Lo que se comprueba es lo que se ha quitado: la segunda busqueda del menu
principal, y pulsar ramas que ya estan plegadas. Ante cualquier duda sobre el
estado de una rama se pliega como antes.

Run: pytest test_menu.py
"""

import logging

import pytest

import sical_utils
from sical_constants import MENU_TREE_ELEMENTS_TO_COLLAPSE

LOG = logging.getLogger('test')


class _Patron:
    def __init__(self, estado):
        self.ExpandCollapseState = estado


class _UIA:
    def __init__(self, estado):
        self._estado = estado

    def GetExpandCollapsePattern(self):
        if self._estado == 'sin_patron':
            return None
        if self._estado == 'roto':
            raise RuntimeError('COM')
        return _Patron(self._estado)


class _Item:
    def __init__(self, nombre, grabado, estado=0, hijos=()):
        self.name = nombre
        self.control_type = 'TreeItemControl'
        self.ui_automation_control = _UIA(estado)
        self._grabado = grabado
        self._hijos = {h.name: h for h in hijos}

    def send_keys(self, keys=None, **kwargs):
        self._grabado.append((keys, self.name))
        return self

    def double_click(self, **kwargs):
        self._grabado.append(('doble_clic', self.name))

    def find(self, locator, search_depth=8, timeout=None, raise_error=True):
        for nombre, hijo in self._hijos.items():
            if f'name:"{nombre}"' in locator:
                self._grabado.append(('busca_bajo', self.name, nombre))
                return hijo
        if raise_error:
            raise LookupError(locator)
        return None


class _Menu:
    """El menu principal: raices plegadas salvo las que se digan."""

    def __init__(self, desplegadas=(), estados=None):
        self.grabado = []
        estados = dict(estados or {})
        proceso = _Item('PROCESO DE ORDENACION Y PAGO', self.grabado, estado=3)
        gestion = _Item('GESTION DE PAGOS', self.grabado, estado=0, hijos=[proceso])
        self.raices = [
            _Item(n, self.grabado, estado=estados.get(n, 1 if n in desplegadas else 0))
            for n in MENU_TREE_ELEMENTS_TO_COLLAPSE
        ] + [_Item('TESORERIA', self.grabado, estado=0, hijos=[gestion])]
        self.busquedas_globales = []

    def iter_children(self, max_depth=8):
        return iter(self.raices)

    def find(self, locator, search_depth=8, timeout=None, raise_error=True):
        self.busquedas_globales.append(locator)
        for raiz in self.raices:
            if f'name:"{raiz.name}"' in locator:
                return raiz
        raise LookupError(locator)

    def pulsadas(self, tecla):
        return [g[1] for g in self.grabado if g[0] == tecla]


@pytest.fixture
def menu(monkeypatch):
    m = _Menu(desplegadas=['CONSULTAS AVANZADAS'])
    llamadas = []

    def buscar_menu(*args, **kwargs):
        llamadas.append(args)
        return m
    monkeypatch.setattr(sical_utils, '_wait_for_window_shared', buscar_menu)
    m.llamadas_menu = llamadas
    return m


def test_solo_se_pliegan_las_ramas_desplegadas(menu):
    plegadas = sical_utils.collapse_all_menu_items(LOG, app=menu)

    assert plegadas == 1
    assert menu.pulsadas('{SUBTRACT}') == ['CONSULTAS AVANZADAS']
    # Una pasada por las raices, sin buscarlas una a una
    assert menu.busquedas_globales == []


@pytest.mark.parametrize('estado', ['sin_patron', 'roto', 2])
def test_ante_la_duda_se_pliega_como_antes(estado):
    m = _Menu(estados={n: estado for n in MENU_TREE_ELEMENTS_TO_COLLAPSE})
    sical_utils.collapse_all_menu_items(LOG, app=m)
    assert m.pulsadas('{SUBTRACT}') == list(MENU_TREE_ELEMENTS_TO_COLLAPSE)


def test_si_no_se_pueden_recorrer_las_raices_se_buscan_una_a_una():
    m = _Menu(desplegadas=['FACTURAS'])

    def roto(max_depth=8):
        raise RuntimeError('COM')
    m.iter_children = roto
    sical_utils.collapse_all_menu_items(LOG, app=m)

    assert m.pulsadas('{SUBTRACT}') == ['FACTURAS']
    assert len(m.busquedas_globales) == len(MENU_TREE_ELEMENTS_TO_COLLAPSE)


def test_abrir_tesoreria_busca_el_menu_una_vez_y_cada_hijo_bajo_su_padre(menu):
    ok = sical_utils.open_menu_option(
        ('TESORERIA', 'GESTION DE PAGOS', 'PROCESO DE ORDENACION Y PAGO'), LOG)

    assert ok
    assert len(menu.llamadas_menu) == 1          # antes, dos
    assert menu.pulsadas('{ADD}') == ['TESORERIA', 'GESTION DE PAGOS']
    assert ('busca_bajo', 'TESORERIA', 'GESTION DE PAGOS') in menu.grabado
    assert ('busca_bajo', 'GESTION DE PAGOS', 'PROCESO DE ORDENACION Y PAGO') in menu.grabado
    assert menu.grabado[-1] == ('doble_clic', 'PROCESO DE ORDENACION Y PAGO')
    # Solo la raiz se busca en todo el arbol
    assert menu.busquedas_globales == [sical_utils.TREE_ITEM_LOCATOR.format('TESORERIA')]


def test_si_el_hijo_no_esta_bajo_el_padre_se_busca_en_todo_el_arbol():
    m = _Menu()
    padre = _Item('SIN HIJOS', m.grabado)
    m.raices.append(_Item('PROCESO X', m.grabado, estado=3))

    item = sical_utils._find_tree_item(m, 'PROCESO X', padre)

    assert item.name == 'PROCESO X'
    assert m.busquedas_globales == [sical_utils.TREE_ITEM_LOCATOR.format('PROCESO X')]
