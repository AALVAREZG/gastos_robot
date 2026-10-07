"""
Tesoreria > Gestion de pagos > Proceso de ordenacion y pago.

Un solo sitio para ordenar y pagar. Habia una copia de este flujo en
ado220_processor.py y otra casi identica en pmp450_processor.py -mas una
tercera, a medias y ya retirada, en ordenar_tasks.py-, y cada arreglo habia
que hacerlo dos veces: el de los modales con `find_control` (29/08/2026) se
hizo dos veces. Lo usan el cierre de un ADO/PMP recien validado y
`ordenarypagar` (processors/ordenar_pagar_processor.py).

El estado del pago
------------------
Cada paso deja escrito hasta donde llego en un dict (`nuevo_estado`) que viaja
en `OperationResult.pago`. Antes un fallo aqui solo dejaba un texto libre en
`error` y no se sabia si la operacion habia quedado ordenada: las cuatro tareas
que han fallado en este flujo se cerraron a mano mirando SICAL. Con el estado,
el productor sabe que falta -solo pagar, u ordenar y pagar- y lo puede pedir.
Cada campo se escribe en cuanto su paso termina, asi que una excepcion a mitad
deja el estado bueno.
"""

import ctypes
import logging
import re
import time
from ctypes import wintypes
from typing import Callable, List, Optional

from robocorp import windows

from sical_base import SicalWindowManager
from sical_constants import (
    SICAL_WINDOWS,
    SICAL_MENU_PATHS,
    TESORERIA_PAGOS_PATHS,
    COMMON_DIALOG_PATHS,
)
from sical_utils import open_menu_option
from sical_ui_utils import wait_for_window, find_control
from doc_pipeline import visualizador


MODO_OPERACION = 'num_operacion'
MODO_LISTA = 'num_lista'

# El pago por lista tiene un paso propio -marcar todas las operaciones de la
# lista- cuyo localizador aun no esta. Mientras sea False, el pago por lista
# llega hasta comprobar la lista en el desplegable y cancela **antes de
# teclearla**: recorre el camino real hasta el ultimo punto seguro y nunca paga.
# Es lo que permite probar en SICAL el fallo -una lista ya pagada- antes que el
# acierto.
PAGO_LISTA_DISPONIBLE = True

# Valores de estado['ordenacion'] y estado['pago']
PENDIENTE = 'pendiente'          # pedido y no terminado: es lo que falta
NO_SOLICITADO = 'no_solicitado'
HECHO = 'hecho'
YA_ESTABA = 'ya_estaba'          # solo ordenacion: SICAL respondio con error al teclear el numero


class TesoreriaPagosWindowManager(SicalWindowManager):
    """Window manager for Tesoreria Pagos windows."""

    @property
    def window_pattern(self) -> str:
        return SICAL_WINDOWS['tesoreria']


class ErrorSicalPago(Exception):
    """SICAL se ha negado y ha dicho por que: el mensaje es su texto."""


class PagoCancelado(ErrorSicalPago):
    """
    Se ha cancelado el dialogo de Pagar sin teclear nada: se puede salir limpio.

    `motivo` es el codigo que viaja en `estado['motivo']`, para que el
    productor no tenga que interpretar el texto.
    """
    motivo = 'pago_cancelado'


class ListaNoPendiente(PagoCancelado):
    """
    La lista no esta entre las pendientes de pago: ya pagada, todavia sin
    ordenar o un numero que no es. El robot no puede distinguirlo.
    """
    motivo = 'lista_no_pendiente'


class PagoListaNoDisponible(PagoCancelado):
    """La lista se podria pagar, pero falta el paso de seleccionar sus operaciones."""
    motivo = 'pago_lista_no_disponible'


class ListaNoComprobable(PagoCancelado):
    """No se ha podido leer el desplegable: sin comprobar la lista no se paga."""
    motivo = 'lista_no_comprobable'


class OperacionNoPagable(PagoCancelado):
    """
    SICAL no deja seleccionar la operacion para pagarla: ya pagada o todavia
    sin ordenar. Se lanza tras cerrar sus avisos y cancelar, sin haber
    validado nada.
    """
    motivo = 'operacion_no_seleccionable'


# Lo que dice SICAL al teclear en «Pagar» una operacion ya pagada (02/10/2026,
# 326100219, comprobado a mano). Es un «no se puede pagar», no un «ya esta
# pagada»: con una operacion sin ordenar es de esperar el mismo aviso.
AVISO_NO_SELECCIONABLE = 'no seleccionable para la etapa de tesorer'


def nuevo_estado(modo: str, numero: str, fecha_ordenamiento: Optional[str] = None,
                 fecha_pago: Optional[str] = None, ordenar: bool = True,
                 pagar: bool = True) -> dict:
    """
    Estado de partida de un pago. Es lo que se devuelve en `result.pago`.

    `fecha_pago` None quiere decir «la misma que la de ordenacion», que es lo
    que hace el cierre de un ADO/PMP: teclea una fecha y ordena y paga con ella.
    """
    return {
        'modo': modo,
        'num_operacion': numero if modo == MODO_OPERACION else None,
        'num_lista': numero if modo == MODO_LISTA else None,
        'fecha_ordenamiento': fecha_ordenamiento,
        'fecha_pago': fecha_pago,
        'ordenacion': PENDIENTE if ordenar else NO_SOLICITADO,
        'pago': PENDIENTE if pagar else NO_SOLICITADO,
        'error_sical': None,
        # Por que no se hizo lo pedido, cuando se sabe: el `motivo` de la
        # excepcion PagoCancelado que lo paro. None si se hizo o si el fallo
        # fue otro.
        'motivo': None,
    }


def estado_completo(estado: dict) -> bool:
    """True si no queda nada pendiente de lo que se pidio."""
    return estado['ordenacion'] != PENDIENTE and estado['pago'] != PENDIENTE


def abrir_ventana(window_manager: TesoreriaPagosWindowManager,
                  logger: logging.Logger) -> bool:
    """
    Abre Tesoreria Pagos desde el menu y la deja en `window_manager`.

    La espera es larga a proposito. La ventana tarda lo que tarde la base de
    datos remota: 7,6 s en una prueba y mas de 10 en la anterior, que con los
    10 s de `find_proceso_window` se dio por fallida mientras SICAL seguia
    abriendola. La ventana aparecia despues, se quedaba abierta y la tarea
    siguiente abria otra encima: es lo que se veia como «abrir la ventana de
    pagos dos veces».

    Por lo mismo, si al empezar ya hay una abierta -de una tarea anterior que
    fallo- se intenta cerrar antes de abrir la nueva.
    """
    _cerrar_si_quedo_abierta(window_manager, logger)

    if not open_menu_option(SICAL_MENU_PATHS['tesoreria_pagos'], logger):
        return False

    window_manager.ventana_proceso = wait_for_window(window_manager.window_pattern,
                                                     timeout=ESPERA_VENTANA_S)
    logger.debug(f'Tesoreria window: {window_manager.ventana_proceso}')
    if window_manager.ventana_proceso:
        # Si la anterior no se dejo cerrar, SICAL devuelve esa misma: se
        # despeja otra vez antes de empezar.
        despejar(window_manager.ventana_proceso, logger)
    return bool(window_manager.ventana_proceso)


ESPERA_VENTANA_S = 45.0


def _cerrar_si_quedo_abierta(window_manager: TesoreriaPagosWindowManager,
                             logger: logging.Logger) -> None:
    """
    Sale de una Tesoreria Pagos que haya quedado abierta.

    Antes de «Salir» se despeja lo que tenga encima: con el dialogo de
    seleccion abierto «Salir» no responde, SICAL devuelve la misma ventana al
    abrirla desde el menu y el robot no encuentra la fecha (02/10/2026: habia
    quedado abierta con el dialogo esperando el numero de operacion, y hubo que
    cerrarla a mano).
    """
    vieja = wait_for_window(window_manager.window_pattern, timeout=0.5)
    if not vieja:
        return
    logger.warning('Tesoreria Pagos ya estaba abierta (de una tarea anterior); se cierra antes de abrirla')
    try:
        despejar(vieja, logger)
        salir_btn = vieja.find(TESORERIA_PAGOS_PATHS['salir_button'], timeout=1.0, raise_error=False)
        if salir_btn:
            salir_btn.click(wait_time=1.0)
    except Exception as e:
        logger.warning(f'No se pudo cerrar la Tesoreria Pagos anterior: {e}')


def despejar(ventana, logger: logging.Logger, intentos: int = 4) -> list:
    """
    Cierra lo que haya encima de la ventana principal: avisos (con OK) y el
    dialogo de seleccion (con su boton de cancelar).

    Solo actua sobre lo que reconoce. El boton de cancelar va por posicion, y
    por eso solo se pulsa con el dialogo de seleccion presente, que es donde
    esa posicion es la suya.

    Returns:
        Lo que se ha cerrado, por orden ('aviso: <texto>' o 'dialogo de seleccion').
    """
    cerrado = []
    for _ in range(intentos):
        modal = ventana.find('class:"TMessageForm"', search_depth=2, timeout=0.3, raise_error=False)
        if modal:
            ok = modal.find(COMMON_DIALOG_PATHS['ok_button'], timeout=1.0, raise_error=False)
            if not ok:
                break
            texto = _texto_de(modal) or modal.name
            ok.click(wait_time=0.8)
            cerrado.append(f'aviso: {texto}')
            continue
        dialogo = ventana.find(TESORERIA_PAGOS_PATHS['dialogo_seleccion'], search_depth=2,
                               timeout=0.3, raise_error=False)
        if dialogo:
            _cancelar_dialogo(ventana)
            cerrado.append('dialogo de seleccion')
            continue
        # El panel de listados: lo deja abierto un pago, o una relacion de
        # lista que fallo a mitad. Con el delante «Salir» no esta en 2|8.
        if ventana.find(TESORERIA_PAGOS_PATHS['panel_listados'], search_depth=2,
                        timeout=0.3, raise_error=False):
            cerrar_panel_listados(ventana)
            cerrado.append('panel de listados')
            continue
        break
    if cerrado:
        logger.warning(f'Se ha despejado Tesoreria Pagos: {cerrado}')
    return cerrado


# Los modales de este flujo se buscan con `find_control` y no con
# `ventana.find`. En el resto del robot cada modal se espera antes como ventana
# (`wait_for_window`, que sondea en bucle); aqui se buscaban directos sobre la
# ventana padre, sujetos al `timeout=` de robocorp que no se respeta -lo dice
# el docstring de wait_for_window y se midio el 29/08/2026: una busqueda que
# declaraba 10 s se rindio en menos de 1,5-. De ahi que este flujo concentre
# los fallos: ese `TButton OK path:"1|1"` es el localizador que mas tareas ha
# tumbado en todo el historico, 10 de 65.

def establecer_fecha(ventana, fecha: str) -> None:
    """Teclea la fecha de ordenacion/pago (DDMMYYYY) en la ventana principal."""
    # A principio de año, hasta cerrar el ejercicio anterior, SICAL pide ademas
    # el ejercicio, y el desplegable solo existe entonces. Estaba en el
    # ordenar_tasks.py retirado (20/01/2026) y en una rama sin fusionar
    # (30/01/2026), pero no en los procesadores.
    combo_ejercicio = ventana.find(TESORERIA_PAGOS_PATHS['ejercicio_combo'], timeout=0.3, raise_error=False)
    if combo_ejercicio:
        combo_ejercicio.click(wait_time=0.5)
        combo_ejercicio.select(fecha[-4:])

    fecha_element = ventana.find(TESORERIA_PAGOS_PATHS['fecha_orden'])
    fecha_element.send_keys(fecha, interval=0.1, wait_time=0.5, send_enter=True)

    # Handle date change confirmation dialog
    modal_fecha = find_control(ventana, COMMON_DIALOG_PATHS['info_ok_alt'], timeout=2.0, raise_error=False)
    if modal_fecha:
        modal_fecha.click(wait_time=0.5)


def ordenar_operacion(ventana, num_operacion: str, logger: logging.Logger) -> bool:
    """
    Ordena una operacion por su numero.

    Returns:
        True si se ha ordenado ahora; False si SICAL respondio con error al
        teclear el numero, que hasta hoy se lee como «ya estaba ordenada».
    """
    # Click "Ordenar" button
    ventana.find(TESORERIA_PAGOS_PATHS['ordenar_button']).click(wait_time=0.8)

    # Select "Nº Operación" option
    ventana.find(TESORERIA_PAGOS_PATHS['option_num_operacion']).click(wait_time=0.5)

    # Enter operation number
    num_op_element = ventana.find(TESORERIA_PAGOS_PATHS['num_operacion_input']).click(wait_time=0.2)
    num_op_element.send_keys(num_operacion, interval=0.1, wait_time=0.5, send_enter=True)

    # Check if operation is already ordered
    modal_error = find_control(ventana, 'class:"TMessageForm" and name:"Error"', timeout=1.0, raise_error=False)

    if not modal_error:
        # Operation not yet ordered - proceed with ordering
        _completar_ordenacion(ventana)
        return True

    # Operation already ordered - skip ordering
    logger.info('Operation already ordered, skipping to payment')
    find_control(ventana, COMMON_DIALOG_PATHS['ok_button']).click(wait_time=0.8)
    find_control(ventana, COMMON_DIALOG_PATHS['ok_button']).click(wait_time=0.8)
    ventana.find(TESORERIA_PAGOS_PATHS['cancel_operation_button']).click(wait_time=0.8)
    return False


def _completar_ordenacion(ventana) -> None:
    """Complete the ordering process after entering operation number."""
    time.sleep(0.1)

    # Validate operation
    ventana.find(TESORERIA_PAGOS_PATHS['validar_op_button']).click(wait_time=0.1)
    ventana.find(TESORERIA_PAGOS_PATHS['validar_orden_button']).click(wait_time=0.1)
    find_control(ventana, COMMON_DIALOG_PATHS['info_ok_alt']).click(wait_time=1.0)

    # Select payment mandate printing
    ventana.find(TESORERIA_PAGOS_PATHS['check_mto_pago']).click(wait_time=0.2)
    ventana.find(TESORERIA_PAGOS_PATHS['validar_mto_button']).click(wait_time=0.2)

    # Confirm dialogs
    find_control(ventana, COMMON_DIALOG_PATHS['confirm_yes_alt']).click(wait_time=0.2)
    find_control(ventana, COMMON_DIALOG_PATHS['confirm_yes_alt']).click(wait_time=0.2)
    find_control(ventana, COMMON_DIALOG_PATHS['confirm_yes_alt']).click(wait_time=0.2)

    # Print dialog
    ventana_imprimir = wait_for_window(SICAL_WINDOWS['print_dialog'], timeout=15.0)
    if not ventana_imprimir:
        raise windows.ElementNotFound('Print dialog did not appear within 15s')
    find_control(ventana_imprimir, COMMON_DIALOG_PATHS['print_accept']).click(wait_time=1.0)

    # Final confirmation
    find_control(ventana, COMMON_DIALOG_PATHS['info_ok_alt']).click(wait_time=0.5)


def pagar_operacion(ventana, num_operacion: str) -> None:
    """Paga una operacion ya ordenada, por su numero."""
    # Click "Pagar" button
    ventana.find(TESORERIA_PAGOS_PATHS['pagar_button']).click(wait_time=0.4)

    # Select operation number option again
    ventana.find(TESORERIA_PAGOS_PATHS['option_num_operacion']).click(wait_time=0.5)

    # Enter operation number
    num_op_element = ventana.find(TESORERIA_PAGOS_PATHS['num_operacion_input']).click(wait_time=0.2)
    num_op_element.send_keys(num_operacion, interval=0.1, wait_time=0.5, send_enter=True)

    # Si SICAL no la deja pagar lo dice aqui, con avisos («no seleccionable
    # para la etapa de tesoreria» si ya esta pagada). Antes se seguia pulsando
    # Validar con el aviso delante, y el fallo acababa en un localizador.
    aviso, _ = _leer_y_cerrar_avisos(ventana, ESPERA_AVISO_PAGO_S)
    if aviso:
        _cancelar_dialogo(ventana)
        raise OperacionNoPagable(f'SICAL no deja pagar la operacion {num_operacion}: {aviso}')

    # Validate payment
    ventana.find(TESORERIA_PAGOS_PATHS['validar_op_button']).click(wait_time=1.0)
    ventana.find(TESORERIA_PAGOS_PATHS['validar_orden_button']).click(wait_time=1.0)
    find_control(ventana, COMMON_DIALOG_PATHS['info_ok_alt']).click(wait_time=1.0)


def salir(ventana, tras_pago: bool = True) -> None:
    """
    Sale de Tesoreria Pagos.

    Tras un pago queda abierto su dialogo de impresion y hay que cerrarlo
    antes; tras una ordenacion sola, no.
    """
    if tras_pago:
        ventana.find(TESORERIA_PAGOS_PATHS['salir_impresion_button']).click()
        time.sleep(0.5)
    ventana.find(TESORERIA_PAGOS_PATHS['salir_button']).click()


def leer_error_sical(ventana) -> Optional[str]:
    """
    Lo que SICAL esta diciendo, si esta diciendo algo. Solo lee; no cierra nada.

    Mira dos sitios:

    - la ventana de errores `TFVerError` -un TMemo con el texto y los botones
      Imprimir/Todos/Salir-. Es la que tenia delante el robot en los tres PMP
      del 31/08/2026 que fallaron «buscando el boton Pagar»: el boton no estaba
      porque SICAL habia abierto su ventana de errores encima, y el resultado
      solo decia que no encontraba el localizador;
    - un modal `TMessageForm` (los avisos de SICAL).

    Returns:
        El texto, o un aviso de que la ventana esta pero no se pudo leer. None
        si no hay ninguna de las dos.
    """
    if ventana is None:
        return None
    try:
        form = ventana.find(TESORERIA_PAGOS_PATHS['ver_error_form'], search_depth=2,
                            timeout=0.5, raise_error=False)
        if form:
            memo = form.find(TESORERIA_PAGOS_PATHS['ver_error_memo'], timeout=0.5, raise_error=False)
            texto = _valor_de(memo)
            return texto or 'SICAL ha abierto su ventana de errores (texto no legible)'

        modal = ventana.find('class:"TMessageForm"', search_depth=2, timeout=0.5, raise_error=False)
        if modal:
            texto = _texto_de(modal)
            return texto or f'SICAL ha mostrado un aviso «{modal.name}» (texto no legible)'
    except Exception:
        # Diagnosticar no puede tapar el fallo que se esta diagnosticando.
        return None
    return None


def _valor_de(elemento) -> Optional[str]:
    if not elemento:
        return None
    try:
        valor = elemento.get_value()
    except Exception:
        valor = elemento.name
    valor = (valor or '').strip()
    return valor or None


# Lo que hay en un aviso y no es el mensaje: sus botones y la barra de titulo,
# cuyo boton de cerrar se llama «Cerrar».
_NO_ES_MENSAJE = ('ButtonControl', 'TitleBarControl', 'MenuBarControl', 'MenuItemControl')
_BOTONES_DE_VENTANA = ('Cerrar', 'Close', 'Minimizar', 'Maximizar', 'Restaurar', 'Sistema', 'System')


def _texto_de(modal) -> Optional[str]:
    """
    El mensaje de un aviso de SICAL.

    El texto de un aviso de Delphi es una etiqueta pintada sin ventana propia:
    UI Automation no la ve. Primera prueba con una operacion ya pagada
    (02/10/2026): dos avisos, y de ellos solo se leyo «Cerrar» -el boton de la
    barra de titulo-. Por eso, si no queda nada legible, se pide el texto a
    Delphi: Ctrl+C sobre un aviso copia al portapapeles titulo, mensaje y
    botones.
    """
    partes = []
    try:
        for hijo in modal.iter_children(max_depth=3):
            nombre = (hijo.name or '').strip()
            if (nombre and nombre != modal.name and hijo.class_name != 'TButton'
                    and nombre not in _BOTONES_DE_VENTANA
                    and getattr(hijo, 'control_type', '') not in _NO_ES_MENSAJE):
                partes.append(nombre)
    except Exception:
        pass
    return ' '.join(partes) or _texto_por_portapapeles(modal)


def _texto_por_portapapeles(modal) -> Optional[str]:
    """Ctrl+C sobre el aviso y lectura del portapapeles, que se deja como estaba."""
    try:
        previo = portapapeles_leer()
        secuencia = ctypes.windll.user32.GetClipboardSequenceNumber()
        modal.send_keys('{Ctrl}c', wait_time=0.3)
        if ctypes.windll.user32.GetClipboardSequenceNumber() == secuencia:
            return None
        copiado = portapapeles_leer()
    except Exception:
        return None
    finally:
        try:
            if 'previo' in locals() and previo is not None:
                portapapeles_escribir(previo)
        except Exception:
            pass
    return mensaje_de_copia(copiado)


def mensaje_de_copia(copiado: Optional[str]) -> Optional[str]:
    """
    El mensaje de lo que copia un aviso de Delphi con Ctrl+C::

        ---------------------------
        Error
        ---------------------------
        La operacion ya esta pagada.
        ---------------------------
        OK
        ---------------------------
    """
    if not copiado:
        return None
    bloques, actual = [], []
    for linea in copiado.replace('\r\n', '\n').split('\n'):
        if linea.strip() and set(linea.strip()) == {'-'}:
            bloques.append(actual)
            actual = []
        else:
            actual.append(linea)
    bloques.append(actual)
    bloques = [' '.join(l.strip() for l in b if l.strip()) for b in bloques]
    bloques = [b for b in bloques if b]
    if len(bloques) >= 3:
        return bloques[1]               # titulo, mensaje, botones
    texto = ' '.join(bloques).strip()
    return texto or None


_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002


def _api_portapapeles():
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.OpenClipboard.argtypes = [wintypes.HWND]
    u.GetClipboardData.restype = wintypes.HANDLE
    u.GetClipboardData.argtypes = [wintypes.UINT]
    u.SetClipboardData.restype = wintypes.HANDLE
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    k.GlobalLock.restype = wintypes.LPVOID
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    return u, k


def portapapeles_leer() -> Optional[str]:
    """El texto del portapapeles, o None si no hay texto."""
    u, k = _api_portapapeles()
    if not u.OpenClipboard(None):
        return None
    try:
        h = u.GetClipboardData(_CF_UNICODETEXT)
        if not h:
            return None
        p = k.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()


def portapapeles_escribir(texto: str) -> None:
    u, k = _api_portapapeles()
    datos = ctypes.create_unicode_buffer(texto)
    tam = ctypes.sizeof(datos)
    h = k.GlobalAlloc(_GMEM_MOVEABLE, tam)
    p = k.GlobalLock(h)
    ctypes.memmove(p, datos, tam)
    k.GlobalUnlock(h)
    if not u.OpenClipboard(None):
        return
    try:
        u.EmptyClipboard()
        u.SetClipboardData(_CF_UNICODETEXT, h)
    finally:
        u.CloseClipboard()


def _relanzar_con_error_sical(ventana, estado: dict, exc: Exception,
                              logger: logging.Logger) -> None:
    """Si SICAL tiene un error suyo abierto, relanza `exc` con su texto; si no, tal cual."""
    texto = leer_error_sical(ventana)
    if texto is None:
        raise exc
    estado['error_sical'] = texto
    numero = estado['num_operacion'] or estado['num_lista']
    logger.error(f'SICAL error during order/pay of {numero}: {texto} (fallo original: {exc})')
    raise ErrorSicalPago(f'SICAL: {texto}') from exc


def ordenar_y_pagar(ventana, estado: dict, logger: logging.Logger,
                    avisar: Optional[Callable[[str], None]] = None) -> None:
    """
    Ordena y/o paga una operacion por su numero y sale de la ventana.

    Hace lo que `estado` deja pendiente y anota cada paso al terminarlo. Si
    algo falla y SICAL tiene abierto un error suyo, se relanza como
    `ErrorSicalPago` con su texto -que tambien queda en `estado['error_sical']`-
    en vez del volcado del localizador que no se encontro.

    `avisar` recibe el nombre de cada paso (el latido del procesador).
    """
    avisar = avisar or (lambda paso: None)
    num_operacion = estado['num_operacion']
    fecha_orden = estado['fecha_ordenamiento'] or estado['fecha_pago']
    fecha_pago = estado['fecha_pago'] or fecha_orden
    try:
        if estado['ordenacion'] == PENDIENTE:
            establecer_fecha(ventana, fecha_orden)
            avisar('Ordering operation')
            ordenada_ahora = ordenar_operacion(ventana, num_operacion, logger)
            estado['ordenacion'] = HECHO if ordenada_ahora else YA_ESTABA
            if estado['pago'] == PENDIENTE and fecha_pago != fecha_orden:
                establecer_fecha(ventana, fecha_pago)
        elif estado['pago'] == PENDIENTE:
            establecer_fecha(ventana, fecha_pago)

        if estado['pago'] == PENDIENTE:
            avisar('Paying operation')
            pagar_operacion(ventana, num_operacion)
            estado['pago'] = HECHO

        salir(ventana, tras_pago=estado['pago'] == HECHO)

    except PagoCancelado as e:
        # El dialogo ya esta cancelado: se puede salir limpio.
        estado['error_sical'] = str(e)
        estado['motivo'] = e.motivo
        try:
            salir(ventana, tras_pago=False)
        except Exception as salida:
            logger.warning(f'No se pudo salir de Tesoreria Pagos: {salida}')
        raise
    except Exception as e:
        _relanzar_con_error_sical(ventana, estado, e, logger)


# =============================================================================
# Comprobar el pago de una operacion, sin pagar
# =============================================================================
#
# Para saber que dice SICAL de una operacion -ya pagada, sin ordenar, no
# existe- sin arriesgar nada: se teclea el numero en el dialogo de «Pagar»,
# se lee el aviso si sale, y se cancela sin pulsar «Validar». Es el «fallo
# primero» del pago por operacion: con una operacion ya pagada enseña el aviso
# que SICAL da en ese caso, que es lo que hace falta para tratarlo bien.

ESPERA_AVISO_S = 2.0
# En el pago real la espera se paga en cada operacion, tambien en las buenas.
ESPERA_AVISO_PAGO_S = 1.5


def _leer_y_cerrar_avisos(ventana, espera: float):
    """
    Lee y cierra con OK los avisos que saque SICAL (hasta tres seguidos).

    Returns:
        (texto de los avisos unidos por « | », o None si no hubo; cuantos se cerraron)

    Raises:
        ErrorSicalPago si queda un aviso que no se sabe cerrar: entonces no se
        pulsa nada mas.
    """
    aviso = None
    cerrados = 0
    modal = find_control(ventana, 'class:"TMessageForm"', timeout=espera, raise_error=False)
    while modal and cerrados < 3:
        texto = _texto_de(modal) or f'«{modal.name}» (texto no legible)'
        aviso = texto if aviso is None else f'{aviso} | {texto}'
        ok = modal.find(COMMON_DIALOG_PATHS['ok_button'], timeout=1.0, raise_error=False)
        if not ok:
            break
        ok.click(wait_time=0.8)
        cerrados += 1
        modal = find_control(ventana, 'class:"TMessageForm"', timeout=1.0, raise_error=False)

    if modal:
        raise ErrorSicalPago(f'SICAL: {aviso} (el aviso sigue abierto; cierralo a mano)')
    return aviso, cerrados


def comprobar_pago_operacion(ventana, num_operacion: str, logger: logging.Logger) -> dict:
    """
    Teclea la operacion en el dialogo de Pagar y cancela sin validar.

    Returns:
        {'acepta': bool, 'aviso_sical': texto o None, 'avisos_cerrados': n}.
        `acepta` False quiere decir que SICAL saco un aviso al teclear el numero.
    """
    ventana.find(TESORERIA_PAGOS_PATHS['pagar_button']).click(wait_time=0.4)
    ventana.find(TESORERIA_PAGOS_PATHS['option_num_operacion']).click(wait_time=0.5)
    campo = ventana.find(TESORERIA_PAGOS_PATHS['num_operacion_input']).click(wait_time=0.2)
    # A partir de aqui el dialogo esta abierto: cancelar por posicion es seguro.
    campo.send_keys(num_operacion, interval=0.1, wait_time=0.5, send_enter=True)

    aviso, cerrados = _leer_y_cerrar_avisos(ventana, ESPERA_AVISO_S)

    _cancelar_dialogo(ventana)
    logger.info(f'Comprobacion de pago de {num_operacion}: '
                f'{"SICAL lo acepta" if aviso is None else "aviso: " + aviso}')
    return {
        'acepta': aviso is None,
        'aviso_sical': aviso,
        'avisos_cerrados': cerrados,
        'no_seleccionable': bool(aviso and AVISO_NO_SELECCIONABLE in aviso.lower()),
    }


def comprobar_pago_y_salir(ventana, estado: dict, logger: logging.Logger) -> dict:
    """Teclea la fecha, comprueba la operacion de `estado` y sale. No paga nada."""
    try:
        establecer_fecha(ventana, estado['fecha_pago'] or estado['fecha_ordenamiento'])
        comprobacion = comprobar_pago_operacion(ventana, estado['num_operacion'], logger)
        estado['comprobacion'] = comprobacion
        if comprobacion['aviso_sical']:
            estado['error_sical'] = comprobacion['aviso_sical']
        salir(ventana, tras_pago=False)
        return comprobacion
    except Exception as e:
        _relanzar_con_error_sical(ventana, estado, e, logger)


# =============================================================================
# Pago por lista
# =============================================================================
#
# El dialogo que abre «Pagar» trae marcada por defecto la opcion «Nº Lista» y,
# en el sitio del campo de numero de operacion, un desplegable con las listas
# pendientes de pago. Se teclea el numero en el desplegable; en la ventana
# siguiente hay un paso que el pago por operacion no tiene: marcar todas las
# operaciones de la lista.

CB_GETCOUNT = 0x0146
CB_GETLBTEXT = 0x0148
CB_GETLBTEXTLEN = 0x0149


def leer_items_desplegable(combo) -> Optional[List[str]]:
    """
    Los elementos de un TComboBox de SICAL, sin desplegarlo.

    Primero por mensajes de Win32 (CB_GETCOUNT / CB_GETLBTEXT) sobre el handle
    del control: un TComboBox de Delphi es un COMBOBOX nativo, y Windows
    traslada entre procesos los mensajes de sistema como estos. Si no hay
    handle, por los hijos que exponga UI Automation.

    Returns:
        La lista -vacia si no hay elementos- o None si no se ha podido leer.
        La diferencia importa: None no autoriza a decir que no hay listas.
    """
    hwnd = getattr(combo, 'handle', 0) or 0
    if hwnd:
        send = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM)(
            ('SendMessageW', ctypes.windll.user32))
        total = send(hwnd, CB_GETCOUNT, 0, 0)
        if total >= 0:
            items = []
            for i in range(total):
                largo = send(hwnd, CB_GETLBTEXTLEN, i, 0)
                if largo < 0:
                    return None
                buf = ctypes.create_unicode_buffer(largo + 1)
                send(hwnd, CB_GETLBTEXT, i, ctypes.addressof(buf))
                items.append(buf.value.strip())
            return items

    try:
        items = [(hijo.name or '').strip() for hijo in combo.iter_children(max_depth=3)
                 if hijo.control_type == 'ListItemControl' and (hijo.name or '').strip()]
    except Exception:
        return None
    return items or None


def numero_de_lista(texto) -> Optional[str]:
    """El numero con que empieza un elemento del desplegable, sin ceros a la izquierda."""
    m = re.match(r'\s*0*(\d+)', str(texto or ''))
    return m.group(1) if m else None


def _desplegable_de_listas(ventana):
    """Con el dialogo de Pagar abierto, deja marcada «Nº Lista» y devuelve su desplegable."""
    # Viene marcada por defecto; se marca igual por si SICAL recordara la
    # ultima opcion usada.
    opcion = ventana.find(TESORERIA_PAGOS_PATHS['option_num_lista'], timeout=1.0, raise_error=False)
    if opcion:
        opcion.click(wait_time=0.3)
    return find_control(ventana, TESORERIA_PAGOS_PATHS['num_lista_combo'], timeout=5.0)


def _cancelar_dialogo(ventana) -> None:
    """
    Cancela el dialogo de Pagar. Solo se llama con el desplegable ya
    encontrado: el boton se localiza por su posicion y no por su nombre, y con
    el dialogo cerrado esa posicion puede ser otro boton de la ventana.
    """
    cancelar = ventana.find(TESORERIA_PAGOS_PATHS['cancel_operation_button'], timeout=1.0, raise_error=False)
    if cancelar:
        cancelar.click(wait_time=0.5)


def _sin_lista_cero(items: Optional[List[str]]) -> Optional[List[str]]:
    """El desplegable trae un «0» que no es ninguna lista."""
    if items is None:
        return None
    return [item for item in items if numero_de_lista(item) != '0']


def listas_pendientes(ventana, logger: logging.Logger) -> Optional[List[str]]:
    """Abre el dialogo de Pagar, lee las listas del desplegable y lo cancela."""
    ventana.find(TESORERIA_PAGOS_PATHS['pagar_button']).click(wait_time=0.4)
    # Si el desplegable no aparece se lanza sin cancelar nada: no se sabe que
    # hay en pantalla, y el boton de cancelar va por posicion.
    combo = _desplegable_de_listas(ventana)
    try:
        listas = _sin_lista_cero(leer_items_desplegable(combo))
        logger.info(f'Listas pendientes de pago: {listas}')
        return listas
    finally:
        _cancelar_dialogo(ventana)


def consultar_listas_pendientes(ventana, fecha: str, logger: logging.Logger) -> Optional[List[str]]:
    """
    Las listas pendientes de pago, saliendo despues de Tesoreria Pagos.

    Se teclea antes la fecha, como en un pago. La primera prueba en SICAL
    (02/10/2026) pulso «Pagar» nada mas abrir la ventana y el dialogo no
    aparecio; la siguiente, que si tecleo la fecha, lo encontro y lo leyo.
    """
    establecer_fecha(ventana, fecha)
    try:
        listas = listas_pendientes(ventana, logger)
    except Exception:
        # Sin el dialogo no queda nada a medias: se intenta salir para no
        # dejar Tesoreria Pagos abierta a la tarea siguiente.
        try:
            salir(ventana, tras_pago=False)
        except Exception as salida:
            logger.warning(f'No se pudo salir de Tesoreria Pagos: {salida}')
        raise
    salir(ventana, tras_pago=False)
    return listas


ESPERA_TODOS_S = 10.0


def seleccionar_todas_las_operaciones(ventana) -> None:
    """
    Paso propio del pago por lista: en la ventana que sigue a validar la lista
    hay que marcar todas sus operaciones -boton «Todos»- antes de validar el
    pago.

    Se espera a que el boton este activo: la lista tarda en cargar lo que
    tarde la base remota, y pulsarlo desactivado no marcaria nada.

    Si tras pulsarlo SICAL saca un aviso -puede avisar de que llevan
    retenciones; no se ha visto aun- no se toca: se para con su texto, sin
    validar, y se depura sobre la marcha.
    """
    texto = leer_error_sical(ventana)
    if texto is not None:
        # La ventana de errores tiene su propio «Todos»: no se pulsa con ella delante.
        raise ErrorSicalPago(f'SICAL: {texto} (antes de seleccionar las operaciones)')

    limite = time.monotonic() + ESPERA_TODOS_S
    todos = find_control(ventana, TESORERIA_PAGOS_PATHS['todos_button'], timeout=ESPERA_TODOS_S)
    while not _activo(todos) and time.monotonic() < limite:
        time.sleep(0.3)
    if not _activo(todos):
        raise ErrorSicalPago('el boton «Todos» no se ha activado: la lista no ha cargado sus operaciones')
    todos.click(wait_time=0.8)

    aviso = find_control(ventana, 'class:"TMessageForm"', timeout=ESPERA_AVISO_S, raise_error=False)
    if aviso:
        raise ErrorSicalPago(
            f'SICAL avisa al seleccionar las operaciones: {_texto_de(aviso) or aviso.name} '
            f'(no se ha validado nada; el aviso sigue abierto)')


def _activo(control) -> bool:
    try:
        return bool(control.ui_automation_control.IsEnabled)
    except Exception:
        # Si no se puede saber, se da por activo, como hasta ahora con cualquier boton.
        return True


def pagar_lista(ventana, num_lista: str, logger: logging.Logger) -> None:
    """Paga una lista ya ordenada, por su numero."""
    ventana.find(TESORERIA_PAGOS_PATHS['pagar_button']).click(wait_time=0.4)
    combo = _desplegable_de_listas(ventana)

    # La lista tiene que estar entre las pendientes antes de teclearla. Es lo
    # que impide pagar dos veces la misma lista, o pagar otra por un numero mal
    # tecleado. Si el desplegable no se ha podido leer no hay con que
    # comprobarlo y se sigue, avisando.
    pendientes = _sin_lista_cero(leer_items_desplegable(combo))
    logger.info(f'Listas pendientes de pago: {pendientes}')
    if pendientes is not None and not any(
            numero_de_lista(item) == numero_de_lista(num_lista) for item in pendientes):
        _cancelar_dialogo(ventana)
        raise ListaNoPendiente(f'la lista {num_lista} no esta entre las pendientes de pago: {pendientes}')

    if not PAGO_LISTA_DISPONIBLE:
        _cancelar_dialogo(ventana)
        como = 'esta pendiente' if pendientes is not None else 'no se ha podido comprobar'
        raise PagoListaNoDisponible(
            f'la lista {num_lista} {como}, pero el pago por lista aun no esta disponible '
            f'(falta seleccionar todas las operaciones); se ha cancelado sin teclear nada')

    if pendientes is None:
        # La comprobacion es lo unico que impide pagar dos veces la misma
        # lista: sin ella no se paga.
        _cancelar_dialogo(ventana)
        raise ListaNoComprobable(f'no se han podido leer las listas pendientes; '
                                 f'no se paga la {num_lista} sin comprobarla')

    # El desplegable trae ya un valor («0»): se borra antes de teclear.
    combo.click(wait_time=0.2)
    combo.send_keys('{End}{Back 10}', wait_time=0.2)
    combo.send_keys(num_lista, interval=0.1, wait_time=0.5, send_enter=True)

    ventana.find(TESORERIA_PAGOS_PATHS['validar_op_button']).click(wait_time=1.0)
    seleccionar_todas_las_operaciones(ventana)
    ventana.find(TESORERIA_PAGOS_PATHS['validar_orden_button']).click(wait_time=1.0)
    find_control(ventana, COMMON_DIALOG_PATHS['info_ok_alt']).click(wait_time=1.0)


def pagar_lista_y_salir(ventana, estado: dict, logger: logging.Logger,
                        avisar: Optional[Callable[[str], None]] = None,
                        tras_pagar: Optional[Callable[[object], None]] = None) -> None:
    """
    Paga la lista de `estado` y sale de la ventana, anotando el estado como `ordenar_y_pagar`.

    `tras_pagar(ventana)`, si se da, se llama con la lista ya pagada y la
    ventana todavia abierta: es donde se saca su relacion. Va despues del pago
    y nunca lo deshace: lo que falle ahi no cambia `estado` ni impide salir.
    """
    avisar = avisar or (lambda paso: None)
    try:
        establecer_fecha(ventana, estado['fecha_pago'] or estado['fecha_ordenamiento'])
        avisar('Paying list')
        pagar_lista(ventana, estado['num_lista'], logger)
        estado['pago'] = HECHO
        if tras_pagar is None:
            salir(ventana, tras_pago=True)
        else:
            # El panel que SICAL deja abierto tras pagar es el de listados, con
            # lo que el haya marcado: se cierra, y la relacion lo abre de nuevo
            # por «Imprimir», que es el estado mapeado.
            cerrar_panel_listados(ventana)
            try:
                tras_pagar(ventana)
            except Exception as e:
                logger.error(f'Lista {estado["num_lista"]} pagada; su documento ha fallado: {e}')
            ventana.foreground_window()
            ventana.find(TESORERIA_PAGOS_PATHS['salir_button']).click()

    except PagoCancelado as e:
        # El dialogo ya esta cancelado: se puede salir limpio.
        estado['error_sical'] = str(e)
        estado['motivo'] = e.motivo
        try:
            salir(ventana, tras_pago=False)
        except Exception as salida:
            logger.warning(f'No se pudo salir de Tesoreria Pagos: {salida}')
        raise
    except Exception as e:
        _relanzar_con_error_sical(ventana, estado, e, logger)


# =============================================================================
# Relacion de la lista: el documento del pago por lista
# =============================================================================
#
# El justificante de un pago por lista es la «Relacion de las Operaciones
# Procesadas» de esa lista: cada operacion con su orden, su pago, el tercero y
# el liquido, y el total. Sale por la via de impresion de esta ventana, no por
# ConOpera -que trabaja por operacion, y una lista no tiene numero de operacion
# que teclear-, y por eso no lo saca el robot de documentos.
#
# Mapeado con sical-inspector el 07/10/2026 sobre la lista 20260111:
#
#   1. Con la fecha tecleada se activa «Imprimir» (grupo «Operaciones»). Abre
#      el panel «Seleccionar Listados» (TFLisSele) SIN ninguna casilla
#      marcada, con «Nº Lista» elegida y el desplegable de listas en 0.
#   2. Marcar «Relacion de Operaciones Procesadas» abre «Ordenar el listado
#      por ...» (TInputQueryForm) con 1 por defecto: (1) Nº Operacion,
#      (2) Nº Orden o (3) Nº Pago. Se pide el 3.
#   3. Se elige la lista en el desplegable y se pulsa el boton del check (se
#      activa al aceptar el orden): se abre el Visualizador.
#   4. Al salir del Visualizador el panel se cerro con el, o en los 5 s
#      siguientes: no se sabe cual. Se comprueba y, si sigue, se cierra con su
#      puerta.
#
# El desplegable trae TODAS las listas del ejercicio -104 el 07/10/2026,
# tambien las ya pagadas-, asi que la relacion se puede sacar cuando se quiera:
# si falla al pagar, se repite sin volver a pagar (tipo `relacion_lista`).
#
# Es un listado: no escribe en SICAL. Lo que si hay que evitar es generar
# otros listados del mismo panel -cartas, mandamientos, cheques- que van a la
# impresora. Por eso se comprueba que el panel se abre sin nada marcado y que,
# antes del check, solo esta marcada la relacion.

RELACION_OPERACIONES = 'Relación de Operaciones Procesadas'
ORDEN_POR_PAGO = '3'
ESPERA_PANEL_S = 10.0
# Lo que tarde SICAL en componer el listado; una lista larga tarda mas.
ESPERA_VISUALIZADOR_S = 30.0

CB_GETCURSEL = 0x0147


class ErrorRelacion(Exception):
    """No se ha podido sacar la relacion de la lista. Nada ha cambiado en SICAL."""


class ListaInexistente(ErrorRelacion):
    """La lista no esta en el desplegable de listados: numero equivocado o de otro ejercicio."""


def cerrar_panel_listados(ventana) -> bool:
    """Cierra el panel de listados con su puerta, si esta abierto. True si ya no queda."""
    P = TESORERIA_PAGOS_PATHS
    panel = ventana.find(P['panel_listados'], search_depth=2, timeout=0.5, raise_error=False)
    if not panel:
        return True
    puerta = panel.find(P['salir_listado_button'], timeout=1.0, raise_error=False)
    if puerta:
        puerta.click(wait_time=0.8)
    return not ventana.find(P['panel_listados'], search_depth=2, timeout=0.5, raise_error=False)


def _marcada(casilla) -> bool:
    return casilla.ui_automation_control.GetTogglePattern().ToggleState == 1


def listados_marcados(panel) -> List[str]:
    """Los listados marcados en el panel, por su nombre."""
    grupo = panel.find(TESORERIA_PAGOS_PATHS['grupo_listados'], timeout=2.0)
    return [c.name for c in grupo.iter_children(max_depth=1) if _marcada(c)]


def valor_desplegable(combo) -> Optional[str]:
    """
    Lo que muestra un TComboBox: CB_GETCURSEL + CB_GETLBTEXT sobre su handle
    -como `leer_items_desplegable`-, y si no, lo que diga UI Automation.
    """
    hwnd = getattr(combo, 'handle', 0) or 0
    if hwnd:
        send = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM)(
            ('SendMessageW', ctypes.windll.user32))
        i = send(hwnd, CB_GETCURSEL, 0, 0)
        if i < 0:
            return None
        largo = send(hwnd, CB_GETLBTEXTLEN, i, 0)
        if largo >= 0:
            buf = ctypes.create_unicode_buffer(largo + 1)
            send(hwnd, CB_GETLBTEXT, i, ctypes.addressof(buf))
            return buf.value.strip()
    try:
        return (combo.ui_automation_control.GetLegacyIAccessiblePattern().Value or '').strip() or None
    except Exception:
        return None


def abrir_panel_listados(ventana):
    """«Imprimir» de la ventana -> el panel de listados, recien abierto."""
    P = TESORERIA_PAGOS_PATHS
    # Si quedo abierto (de un pago, o de una relacion que fallo) se cierra:
    # su estado no se conoce, y el recien abierto si.
    if not cerrar_panel_listados(ventana):
        raise ErrorRelacion('el panel de listados estaba abierto y no se ha podido cerrar')
    grupo = ventana.find(P['operaciones_group'], timeout=2.0)
    imprimir = grupo.find(P['imprimir_button'], timeout=2.0)
    if not _activo(imprimir):
        raise ErrorRelacion('«Imprimir» esta desactivado: SICAL lo activa al teclear la fecha')
    imprimir.click(wait_time=0.8)
    return find_control(ventana, P['panel_listados'], timeout=ESPERA_PANEL_S)


def pedir_orden_por_pago(ventana) -> None:
    """Contesta «Ordenar el listado por ...» con el 3 (Nº Pago), comprobando que lo tiene."""
    P = TESORERIA_PAGOS_PATHS
    modal = find_control(ventana, P['orden_listado_form'], timeout=5.0)
    campo = modal.find(P['orden_listado_input'], timeout=2.0)
    try:
        campo.set_value(ORDEN_POR_PAGO)
    except Exception:
        pass
    if _valor_de(campo) != ORDEN_POR_PAGO:
        # Trae «1»: se borra y se teclea
        campo.send_keys('{End}{Back 5}' + ORDEN_POR_PAGO, wait_time=0.3)
    valor = _valor_de(campo)
    if valor != ORDEN_POR_PAGO:
        _cancelar_orden(modal)
        raise ErrorRelacion(f'el dialogo de orden no acepta el {ORDEN_POR_PAGO} (muestra {valor!r})')
    modal.find(COMMON_DIALOG_PATHS['ok_button'], timeout=2.0).click(wait_time=0.5)


def _cancelar_orden(modal) -> None:
    cancelar = modal.find('class:"TButton" and name:"Cancel"', timeout=1.0, raise_error=False)
    if cancelar:
        cancelar.click(wait_time=0.5)


def elegir_lista(panel, num_lista: str) -> None:
    """
    Elige la lista en el desplegable del panel y comprueba que es la que
    muestra. Sin esa comprobacion, un desplegable que no hizo caso sacaria
    la relacion de la lista que estuviera puesta, y llegaria a la tarea como
    si fuera la suya.
    """
    P = TESORERIA_PAGOS_PATHS
    opcion = panel.find(P['opcion_lista_listado'], timeout=1.0)
    if not opcion.ui_automation_control.GetSelectionItemPattern().IsSelected:
        opcion.click(wait_time=0.3)
    combo = panel.find(P['combo_lista_listado'], timeout=2.0)
    elemento = _elemento_de_lista(combo, num_lista)
    combo.select(elemento)
    muestra = valor_desplegable(combo)
    if numero_de_lista(muestra) != numero_de_lista(num_lista):
        raise ErrorRelacion(f'el desplegable muestra {muestra!r} y no la lista {num_lista}: '
                            f'no se saca la relacion de otra')


def _elemento_de_lista(combo, num_lista: str) -> str:
    """El elemento del desplegable que es `num_lista`, tal como esta escrito."""
    items = leer_items_desplegable(combo)
    if items is None:
        raise ErrorRelacion('no se puede leer el desplegable de listas del panel')
    for item in items:
        if numero_de_lista(item) == numero_de_lista(num_lista):
            return item
    raise ListaInexistente(f'la lista {num_lista} no esta en el desplegable de listados '
                           f'({len(items)} listas)')


def relacion_lista_pdf(ventana, num_lista: str, destino: str, logger: logging.Logger,
                       avisar: Optional[Callable[[str], None]] = None) -> str:
    """
    Saca en PDF la relacion de operaciones de una lista, en `destino`.

    Necesita Tesoreria Pagos abierta y con la fecha tecleada (es lo que activa
    «Imprimir»). Deja la ventana como la encontro: sin Visualizador ni panel,
    tambien si falla.

    Raises:
        ErrorRelacion, visualizador.ErrorVisualizador, iconos.IconoNoReconocido,
        o lo que lance robocorp al no encontrar un control.
    """
    avisar = avisar or (lambda paso: None)
    P = TESORERIA_PAGOS_PATHS
    try:
        avisar('Opening list report')
        panel = abrir_panel_listados(ventana)
        marcadas = listados_marcados(panel)
        if marcadas:
            raise ErrorRelacion(f'el panel de listados se abrio con listados marcados {marcadas}: '
                                f'no es el estado conocido y no se genera nada')
        # Antes de marcar nada: que la lista exista (solo lee)
        _elemento_de_lista(panel.find(P['combo_lista_listado'], timeout=2.0), num_lista)

        grupo = panel.find(P['grupo_listados'], timeout=2.0)
        grupo.find(P['check_relacion_operaciones'], timeout=2.0).click(wait_time=0.5)
        pedir_orden_por_pago(ventana)

        marcadas = listados_marcados(panel)
        if marcadas != [RELACION_OPERACIONES]:
            raise ErrorRelacion(f'listados marcados {marcadas}; solo puede estarlo '
                                f'«{RELACION_OPERACIONES}»: los demas van a la impresora')
        elegir_lista(panel, num_lista)

        aceptar = panel.find(P['aceptar_listado_button'], timeout=2.0)
        if not _activo(aceptar):
            raise ErrorRelacion('el boton que genera el listado sigue desactivado')
        avisar('Generating list report')
        aceptar.click(wait_time=1.0)

        visor = wait_for_window(SICAL_WINDOWS['visual_documentos'], timeout=ESPERA_VISUALIZADOR_S)
        if not visor:
            texto = leer_error_sical(ventana)
            raise ErrorRelacion(f'el Visualizador no se ha abierto en {ESPERA_VISUALIZADOR_S:.0f} s'
                                + (f' (SICAL: {texto})' if texto else ''))
        avisar('Saving list report')
        ruta = visualizador.guardar_pdf(visor, destino)
        logger.info(f'Relacion de la lista {num_lista}: {ruta}')
        return ruta
    finally:
        # Lo que quede abierto, se cierra: la ventana sigue y tiene que poder
        # salir. Nunca lanza, para no tapar el fallo de dentro.
        try:
            visualizador.cerrar()
            modal = ventana.find(P['orden_listado_form'], search_depth=2, timeout=0.3, raise_error=False)
            if modal:
                _cancelar_orden(modal)
            ventana.foreground_window()
            if not cerrar_panel_listados(ventana):
                logger.warning('El panel de listados sigue abierto')
        except Exception as e:
            logger.warning(f'No se pudo dejar Tesoreria Pagos como estaba: {e}')
