"""
Guardar en PDF lo que muestra el Visualizador, pulsando sus botones por icono.

Lo usa la relacion de una lista (processors/tesoreria_pagos.py). Hace lo mismo
que `sical_capture.capture_visualizador_pdf` -Guardar PDF -> «Guardar como» ->
cerrar-, con dos diferencias que vienen de consultas_robot:

- **Los botones se identifican por su icono** (doc_pipeline/iconos.py), no por
  su path: la barra cambia con el documento, y en el listado del banco el
  `2|2|3` que aqui guarda el PDF es el que lo manda a portafirmas.
- **Se borra el destino ANTES de guardar.** Con el fichero de una ejecucion
  anterior ahi, un guardado que fallara devolveria el documento VIEJO como si
  fuera el nuevo.

La captura de ADO/PMP sigue en sical_capture: esta verificada en vivo y no se
toca por esto.
"""

import logging
import os
import time

from sical_constants import SICAL_WINDOWS
from sical_ui_utils import wait_for_window

from . import iconos

logger = logging.getLogger(__name__)

# Mientras SICAL compone el documento la barra puede estar desactivada, con
# los iconos en gris (otra huella): se espera a reconocer el de Guardar PDF.
ESPERA_BARRA_S = 20.0
ESPERA_GUARDAR_COMO_S = 10.0
ESPERA_FICHERO_S = 30.0

# Los del dialogo de Windows, verificados con ADO/PMP (sical_capture)
_GUARDAR_COMO = 'regex:.*Guardar como'
_NOMBRE = 'control:"EditControl" and name:"Nombre:"'
_GUARDAR = 'class:"Button" and name:"Guardar"'


class ErrorVisualizador(Exception):
    """No se ha podido guardar el PDF. No escribe nada en SICAL."""


def _esperar_barra(visor, icono, referencias):
    limite = time.monotonic() + ESPERA_BARRA_S
    while True:
        barra = iconos.identificar_barra(visor, referencias)
        if icono in barra or time.monotonic() >= limite:
            return barra
        time.sleep(0.5)


def _pdf_entero(ruta):
    """
    Los bytes del PDF si ya esta entero, o None para seguir esperando.

    «Entero» = tamaño estable en dos lecturas, empieza por %PDF y acaba en
    %%EOF. Un fichero que existe no es un fichero que sirve: mientras SICAL
    escribe, existe y esta cortado.
    """
    if not os.path.isfile(ruta):
        return None
    t1 = os.path.getsize(ruta)
    if t1 == 0:
        return None
    time.sleep(0.4)
    if os.path.getsize(ruta) != t1:
        return None
    try:
        with open(ruta, 'rb') as fh:
            datos = fh.read()
    except OSError:
        return None     # bloqueado mientras SICAL lo escribe
    if not datos.startswith(b'%PDF') or b'%%EOF' not in datos[-1024:]:
        return None
    return datos


def guardar_pdf(visor, destino, referencias=None):
    """
    Desde el Visualizador ya abierto: Guardar PDF -> «Guardar como» ->
    `destino`. No cierra el Visualizador (ver `cerrar`). Devuelve `destino`.

    Raises:
        ErrorVisualizador | iconos.IconoNoReconocido
    """
    referencias = referencias if referencias is not None else iconos.cargar_referencias()
    barra = _esperar_barra(visor, 'pdf', referencias)
    boton_pdf = iconos.boton(barra, 'pdf')

    os.makedirs(os.path.dirname(destino), exist_ok=True)
    try:
        if os.path.exists(destino):
            os.remove(destino)
    except OSError as exc:
        raise ErrorVisualizador(f'no se puede borrar el PDF anterior {destino} ({exc}); '
                                f'seguir devolveria el viejo como si fuera el nuevo') from exc

    visor.foreground_window()
    boton_pdf.click(wait_time=0.5)

    dialogo = wait_for_window(_GUARDAR_COMO, timeout=ESPERA_GUARDAR_COMO_S)
    if not dialogo:
        raise ErrorVisualizador('no se ha abierto «Guardar como» tras pulsar Guardar PDF')
    # El dialogo tarda en estar listo para escribir (sical_capture espera 2 s)
    time.sleep(1.5)
    dialogo.find(_NOMBRE, timeout=5).set_value(destino)
    time.sleep(0.5)
    dialogo.find(_GUARDAR, timeout=5).click()

    limite = time.monotonic() + ESPERA_FICHERO_S
    while time.monotonic() < limite:
        datos = _pdf_entero(destino)
        if datos is not None:
            logger.info('PDF guardado: %s (%d bytes)', destino, len(datos))
            return destino
        time.sleep(0.5)
    raise ErrorVisualizador(f'SICAL no ha terminado de escribir {destino} en {ESPERA_FICHERO_S:.0f} s')


def cerrar(referencias=None, intentos=2):
    """
    Cierra el Visualizador con su boton Salir, identificado por icono.

    -> True si ya no queda. Nunca lanza: se llama en un `finally`, y el
    documento ya esta guardado o ya ha fallado por otra causa.

    Al guardar, SICAL abre el PDF y eso **minimiza** el Visualizador; una
    ventana minimizada no se puede manejar, asi que se restaura y se trae al
    frente antes de buscar el boton. Si no se reconoce el de Salir no se pulsa
    nada: se deja abierto y se dice.
    """
    for _ in range(intentos):
        try:
            visor = wait_for_window(SICAL_WINDOWS['visual_documentos'], timeout=1.0)
            if visor is None:
                return True
            barra = iconos.identificar_barra(
                visor, referencias if referencias is not None else iconos.cargar_referencias())
            salir = iconos.boton(barra, 'salir')
            visor.foreground_window()
            salir.click(wait_time=0.8)
            _confirmar_salida(visor)
        except iconos.IconoNoReconocido as exc:
            logger.warning('Visualizador: %s; se deja abierto', exc)
            return False
        except Exception as exc:  # noqa: BLE001 - cerrar es best-effort
            logger.warning('no se pudo cerrar el Visualizador: %s', exc)
        if wait_for_window(SICAL_WINDOWS['visual_documentos'], timeout=1.0) is None:
            return True
    logger.warning('el Visualizador sigue abierto tras %d intentos', intentos)
    return False


def _confirmar_salida(visor):
    """
    Contesta «Sí» si SICAL pregunta al salir. Lo normal es que no pregunte y
    la ventana ya no exista: buscar en ella lanza («`root_element` provided is
    no longer valid», 07/10/2026), y eso no es un fallo al cerrar.
    """
    for nombre in ('Yes', 'Sí', 'Si'):
        try:
            confirmar = visor.find(f'class:"TButton" and name:"{nombre}"', timeout=0.5, raise_error=False)
        except Exception:  # noqa: BLE001 - la ventana ya se cerro
            return
        if confirmar:
            confirmar.click(wait_time=0.5)
            return
