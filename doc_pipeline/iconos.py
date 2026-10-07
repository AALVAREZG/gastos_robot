"""
Identificar los botones SIN nombre del Visualizador por la huella de su icono.

La barra «Herramientas» del Visualizador de Documentos son botones de icono:
UI Automation les da nombre vacio. Y la barra cambia segun el documento. En
el documento de un ADO/PMP y en la relacion de una lista (07/10/2026) son 7
botones con `2|2|3` = Guardar PDF y `2|2|6` = Salir; en el listado de
movimientos del banco (consultas_robot) son 6, y alli `2|2|3` es el de la
FIRMA -manda el documento a portafirmas- y `2|2|6` es Imprimir. El path que en
un documento guarda el PDF, en otro lo envia a firmar.

Por eso el pago por lista, que estrena documento, no pulsa la barra por path:
identifica cada boton por su icono y solo pulsa el que reconoce. Un icono que
no casa es un error, no un «probemos el de al lado».

`huella` es la misma funcion que `sical-inspector/scripts/huella_icono.py` y
que `consultas_robot/sical/iconos.py`, y tiene que seguir siendolo: las
referencias de `iconos/visualizador.json` se registraron con ella. Si se
cambia aqui, se cambia alli y se re-registran. La captura es la de
`consultas_robot/sical/captura.py`, por lo mismo: una huella solo es
comparable si la imagen se obtiene igual que la de referencia.

Las referencias valen para el equipo y el escalado de pantalla en que se
registraron (07/10/2026, en este equipo). En otro, un icono puede no casar: el
robot no pulsa y la captura sale FAILED. Se re-registran alli con la skill.
"""

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes

MARGEN = 5
LADO = 16
UMBRAL = 24
SEPARACION = 24


def ruta_referencias():
    """`iconos/visualizador.json`, tambien dentro del .exe (PyInstaller)."""
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'iconos', 'visualizador.json')


def cargar_referencias(ruta=None):
    with open(ruta or ruta_referencias(), encoding='utf-8') as fh:
        return json.load(fh)


def huella(img_boton):
    """dHash de 256 bits, en hexadecimal (64 caracteres)."""
    from PIL import Image

    w, h = img_boton.size
    if w > 2 * MARGEN + 4 and h > 2 * MARGEN + 4:
        img_boton = img_boton.crop((MARGEN, MARGEN, w - MARGEN, h - MARGEN))
    g = img_boton.convert('L').resize((LADO + 1, LADO), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for fila in range(LADO):
        base = fila * (LADO + 1)
        for col in range(LADO):
            bits = (bits << 1) | (px[base + col] > px[base + col + 1])
    return f'{bits:0{LADO * LADO // 4}x}'


def distancia(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count('1')


def identificar(h, referencias):
    """-> (nombre | None, mejor, segunda). Exige cercania Y separacion: si
    dos iconos se parecen demasiado, no adivina."""
    dist = sorted((distancia(h, ref['huella']), nombre) for nombre, ref in referencias.items())
    if not dist:
        return None, None, None
    mejor, nombre = dist[0]
    segunda = dist[1][0] if len(dist) > 1 else LADO * LADO
    if mejor <= UMBRAL and segunda - mejor >= SEPARACION:
        return nombre, mejor, segunda
    return None, mejor, segunda


class IconoNoReconocido(Exception):
    """No se reconoce el boton que habia que pulsar: no se pulsa nada."""


# --- captura de la ventana (PrintWindow) --------------------------------------
#
# Instancias propias: declarar `argtypes` sobre `ctypes.windll.*`, que es
# compartido, cambia las funciones tambien para robocorp, que las llama con
# otros tipos y revienta («argument 2: wrong type»; consultas_robot, 03/10/2026).
# Y sin restype explicito ctypes trunca los handles de 64 bits: la captura sale
# negra sin un solo error.

_HANDLE = ctypes.c_void_p
_PW_RENDERFULLCONTENT = 0x00000002
_api = {}


def _dll():
    if not _api:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
        user32.GetWindowDC.restype = _HANDLE
        user32.GetWindowDC.argtypes = [wintypes.HWND]
        user32.ReleaseDC.argtypes = [wintypes.HWND, _HANDLE]
        user32.PrintWindow.argtypes = [wintypes.HWND, _HANDLE, wintypes.UINT]
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.IsIconic.argtypes = [wintypes.HWND]
        gdi32.CreateCompatibleDC.restype = _HANDLE
        gdi32.CreateCompatibleDC.argtypes = [_HANDLE]
        gdi32.CreateCompatibleBitmap.restype = _HANDLE
        gdi32.CreateCompatibleBitmap.argtypes = [_HANDLE, ctypes.c_int, ctypes.c_int]
        gdi32.SelectObject.restype = _HANDLE
        gdi32.SelectObject.argtypes = [_HANDLE, _HANDLE]
        gdi32.DeleteObject.argtypes = [_HANDLE]
        gdi32.DeleteDC.argtypes = [_HANDLE]
        gdi32.GetDIBits.argtypes = [_HANDLE, _HANDLE, wintypes.UINT, wintypes.UINT,
                                    ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        _api['user32'], _api['gdi32'] = user32, gdi32
    return _api['user32'], _api['gdi32']


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', ctypes.c_long),
                ('biHeight', ctypes.c_long), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', ctypes.c_long),
                ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD)]


def minimizada(hwnd):
    user32, _ = _dll()
    return bool(user32.IsIconic(hwnd))


def capturar(hwnd):
    """-> (Image, (left, top) de la ventana en pantalla). None si no pinta.

    PrintWindow y no una foto de la pantalla: sale la ventana aunque haya otra
    encima -el PDF que SICAL abre al guardar, por ejemplo-.
    """
    from PIL import Image

    user32, gdi32 = _dll()
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    ancho, alto = r.right - r.left, r.bottom - r.top
    if ancho <= 0 or alto <= 0:
        return None, (r.left, r.top)
    hdc_win = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, ancho, alto)
    viejo = gdi32.SelectObject(hdc_mem, bmp)
    try:
        ok = user32.PrintWindow(hwnd, hdc_mem, _PW_RENDERFULLCONTENT)
        bih = _BITMAPINFOHEADER()
        bih.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bih.biWidth, bih.biHeight = ancho, -alto
        bih.biPlanes, bih.biBitCount = 1, 32
        buf = ctypes.create_string_buffer(ancho * alto * 4)
        gdi32.GetDIBits(hdc_mem, bmp, 0, alto, buf, ctypes.byref(bih), 0)
        img = Image.frombuffer('RGB', (ancho, alto), buf, 'raw', 'BGRX', 0, 1)
    finally:
        gdi32.SelectObject(hdc_mem, viejo)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_win)
    if not ok or img.getbbox() is None:
        return None, (r.left, r.top)
    return img, (r.left, r.top)


# --- la barra del Visualizador ------------------------------------------------

HERRAMIENTAS = 'class:"TGroupBox" and name:"Herramientas"'


def identificar_barra(visor, referencias=None):
    """
    -> {icono: elemento} de los botones de «Herramientas» que se reconocen.

    Lanza IconoNoReconocido si dos botones se identifican como el mismo icono:
    entonces la identificacion no es fiable en esta barra y no se pulsa
    ninguno.
    """
    referencias = referencias if referencias is not None else cargar_referencias()
    hwnd = visor.handle
    if minimizada(hwnd):
        # Una ventana minimizada no se puede manejar. Al guardar el PDF SICAL
        # lo abre, y eso minimiza el Visualizador.
        visor.restore_window()
        time.sleep(0.5)
    img, (wl, wt) = capturar(hwnd)
    if img is None:
        raise IconoNoReconocido('no se puede capturar el Visualizador para identificar sus botones')
    grupo = visor.find(HERRAMIENTAS, search_depth=3, timeout=2)
    encontrados, vistos = {}, []
    for b in grupo.iter_children(max_depth=1):
        if b.control_type != 'ButtonControl' or b.class_name != 'TBitBtn':
            continue
        r = b.ui_automation_control.BoundingRectangle
        rec = img.crop((r.left - wl, r.top - wt, r.right - wl, r.bottom - wt))
        nombre, mejor, segunda = identificar(huella(rec), referencias)
        vistos.append(f'{nombre or "?"}({mejor}/{segunda})')
        if nombre:
            if nombre in encontrados:
                raise IconoNoReconocido(f'dos botones del Visualizador parecen «{nombre}»: '
                                        f'no se pulsa ninguno ({", ".join(vistos)})')
            encontrados[nombre] = b
    encontrados['_vistos'] = ', '.join(vistos)
    return encontrados


def boton(barra, icono):
    """El boton de `icono` en una barra ya identificada, o IconoNoReconocido."""
    if icono not in barra:
        raise IconoNoReconocido(f'no se reconoce el boton «{icono}» en la barra del Visualizador '
                                f'({barra.get("_vistos", "")}); no se pulsa nada')
    return barra[icono]
