"""
Tesoreria > Gestion de pagos > Proceso de ordenacion y pago.

Un solo sitio para ordenar y pagar. Habia una copia de este flujo en
ado220_processor.py y otra casi identica en pmp450_processor.py -mas una
tercera, a medias, en ordenar_tasks.py-, y cada arreglo habia que hacerlo dos
veces: el de los modales con `find_control` (29/08/2026) se hizo dos veces.
"""

import logging
import time
from typing import Any, Dict

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


class TesoreriaPagosWindowManager(SicalWindowManager):
    """Window manager for Tesoreria Pagos windows."""

    @property
    def window_pattern(self) -> str:
        return SICAL_WINDOWS['tesoreria']


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


def salir(ventana) -> None:
    """Cierra la impresion que deja el pago y sale de Tesoreria Pagos."""
    ventana.find(TESORERIA_PAGOS_PATHS['salir_impresion_button']).click()
    time.sleep(0.5)
    ventana.find(TESORERIA_PAGOS_PATHS['salir_button']).click()


def ordenar_y_pagar(ventana, datos_pago: Dict[str, Any], logger: logging.Logger) -> None:
    """
    El cierre de un ADO/PMP recien validado: fecha, ordenar, pagar y salir.

    `datos_pago` lleva `num_operacion` y `fecha_ordenamiento`; la fecha de
    ordenacion es tambien la del pago.
    """
    num_operacion = datos_pago['num_operacion']
    establecer_fecha(ventana, datos_pago['fecha_ordenamiento'])
    ordenar_operacion(ventana, num_operacion, logger)
    pagar_operacion(ventana, num_operacion)
    salir(ventana)
