"""
Tesoreria > Gestion de pagos > Proceso de ordenacion y pago.

Un solo sitio para ordenar y pagar. Habia una copia de este flujo en
ado220_processor.py y otra casi identica en pmp450_processor.py -mas una
tercera, a medias, en ordenar_tasks.py-, y cada arreglo habia que hacerlo dos
veces: el de los modales con `find_control` (29/08/2026) se hizo dos veces.

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

import logging
import time
from typing import Optional

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


MODO_OPERACION = 'num_operacion'

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
        'fecha_ordenamiento': fecha_ordenamiento,
        'fecha_pago': fecha_pago,
        'ordenacion': PENDIENTE if ordenar else NO_SOLICITADO,
        'pago': PENDIENTE if pagar else NO_SOLICITADO,
        'error_sical': None,
    }


def estado_completo(estado: dict) -> bool:
    """True si no queda nada pendiente de lo que se pidio."""
    return estado['ordenacion'] != PENDIENTE and estado['pago'] != PENDIENTE


def abrir_ventana(window_manager: TesoreriaPagosWindowManager,
                  logger: logging.Logger) -> bool:
    """Abre Tesoreria Pagos desde el menu y la deja en `window_manager`."""
    if not open_menu_option(SICAL_MENU_PATHS['tesoreria_pagos'], logger):
        return False

    window_manager.ventana_proceso = window_manager.find_proceso_window()
    logger.debug(f'Tesoreria window: {window_manager.ventana_proceso}')
    return bool(window_manager.ventana_proceso)


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
    # el ejercicio, y el desplegable solo existe entonces. Estaba en
    # ordenar_tasks.py (20/01/2026) y en una rama sin fusionar (30/01/2026),
    # pero no en los procesadores.
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


def _texto_de(modal) -> Optional[str]:
    """Los textos de un modal que no son botones ni su propio titulo."""
    partes = []
    try:
        for hijo in modal.iter_children(max_depth=3):
            nombre = (hijo.name or '').strip()
            if nombre and hijo.class_name != 'TButton' and nombre != modal.name:
                partes.append(nombre)
    except Exception:
        pass
    return ' '.join(partes) or None


def ordenar_y_pagar(ventana, estado: dict, logger: logging.Logger) -> None:
    """
    Ordena y/o paga una operacion por su numero y sale de la ventana.

    Hace lo que `estado` deja pendiente y anota cada paso al terminarlo. Si
    algo falla y SICAL tiene abierto un error suyo, se relanza como
    `ErrorSicalPago` con su texto -que tambien queda en `estado['error_sical']`-
    en vez del volcado del localizador que no se encontro.
    """
    num_operacion = estado['num_operacion']
    fecha_orden = estado['fecha_ordenamiento'] or estado['fecha_pago']
    fecha_pago = estado['fecha_pago'] or fecha_orden
    try:
        if estado['ordenacion'] == PENDIENTE:
            establecer_fecha(ventana, fecha_orden)
            ordenada_ahora = ordenar_operacion(ventana, num_operacion, logger)
            estado['ordenacion'] = HECHO if ordenada_ahora else YA_ESTABA
            if estado['pago'] == PENDIENTE and fecha_pago != fecha_orden:
                establecer_fecha(ventana, fecha_pago)
        elif estado['pago'] == PENDIENTE:
            establecer_fecha(ventana, fecha_pago)

        if estado['pago'] == PENDIENTE:
            pagar_operacion(ventana, num_operacion)
            estado['pago'] = HECHO

        salir(ventana, tras_pago=estado['pago'] == HECHO)

    except Exception as e:
        texto = leer_error_sical(ventana)
        if texto is None:
            raise
        estado['error_sical'] = texto
        logger.error(f'SICAL error during order/pay of {num_operacion}: {texto} (fallo original: {e})')
        raise ErrorSicalPago(f'SICAL: {texto}') from e
