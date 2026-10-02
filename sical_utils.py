"""
SICAL Utilities - Shared functions for SICAL automation.

This module contains utility functions used across different operation processors.
"""

import time
import ctypes
import logging
from typing import Optional, Tuple, Any
from robocorp import windows

from sical_constants import (
    SICAL_WINDOWS,
    MENU_TREE_ELEMENTS_TO_COLLAPSE,
    DEFAULT_TIMING,
    COMMON_DIALOG_PATHS,
)
from sical_ui_utils import wait_for_window as _wait_for_window_shared
import run_trace

logger = logging.getLogger(__name__)

TREE_ITEM_LOCATOR = 'control:"TreeItemControl" and name:"{}"'


def _find_tree_item(app: Any, name: str, parent: Optional[Any] = None,
                    timeout: Optional[float] = DEFAULT_TIMING['short_wait']) -> Any:
    """
    Un item del arbol del menu.

    Se busca primero entre los hijos del item que se acaba de desplegar -una
    busqueda de un nivel- y solo si no esta ahi, en todo el arbol como antes.
    """
    locator = TREE_ITEM_LOCATOR.format(name)
    if parent is not None:
        try:
            item = parent.find(locator, search_depth=1,
                               timeout=DEFAULT_TIMING['short_wait'], raise_error=False)
            if item:
                return item
        except Exception:
            pass
    return app.find(locator, timeout=timeout)


def open_menu_option(menu_path: Tuple[str, ...], operation_logger: logging.Logger) -> bool:
    """
    Navigate to and open a menu option in SICAL by expanding the tree path.

    Args:
        menu_path: Tuple of menu items to navigate through
        operation_logger: Logger instance for this operation

    Returns:
        bool: True if menu option was opened successfully, False otherwise
    """
    operation_logger.debug(f'Opening menu path: {menu_path}')
    t_inicio = time.monotonic()

    app = _wait_for_window_shared(SICAL_WINDOWS['main_menu'], timeout=5.0)
    if not app:
        operation_logger.error('SICAL main menu not found - ensure SICAL is open')
        return False
    t_menu = time.monotonic()

    # Collapse menu elements before navigation to avoid path conflicts. Se le
    # pasa la ventana: buscarla otra vez costaba ~1,5 s -la busqueda, traerla
    # al frente y la espera de 0,5 s que robocorp hace despues-.
    plegadas = collapse_all_menu_items(operation_logger, app=app)
    t_plegado = time.monotonic()

    # Expand each menu item in the path except the last one
    parent = None
    for element_name in menu_path[:-1]:
        max_retries = 2
        for attempt in range(max_retries):
            try:
                # Re-find the main window on each attempt to get fresh handles
                if attempt > 0:
                    operation_logger.debug(f'Retry {attempt} for menu item "{element_name}"')
                    time.sleep(DEFAULT_TIMING['medium_wait'])
                    app = _wait_for_window_shared(SICAL_WINDOWS['main_menu'], timeout=5.0)
                    if not app:
                        operation_logger.error('SICAL main menu lost during navigation')
                        return False
                    parent = None

                element = _find_tree_item(app, element_name, parent)
                element.send_keys(keys='{ADD}', wait_time=DEFAULT_TIMING['short_wait'])
                parent = element
                break  # Success, exit retry loop
            except AttributeError as e:
                # Handle the specific __handle error
                if '__handle' in str(e):
                    if attempt < max_retries - 1:
                        operation_logger.warning(f'UI handle lost for "{element_name}", retrying...')
                        continue
                    else:
                        operation_logger.error(f'CRITICAL: UI handle broken after {max_retries} retries for "{element_name}"')
                        operation_logger.error('=' * 80)
                        operation_logger.error('SICAL COM STATE IS CORRUPTED')
                        operation_logger.error('ACTION REQUIRED: Close SICAL completely and restart it')
                        operation_logger.error('=' * 80)
                        return False
                operation_logger.error(f'Failed to expand menu item "{element_name}": {e}')
                return False
            except Exception as e:
                error_msg = str(e)
                # Check for COM event error
                if 'no pudo invocar' in error_msg or '-2147220991' in error_msg:
                    operation_logger.error(f'COM event error: {e}')
                    operation_logger.error('=' * 80)
                    operation_logger.error('SICAL COM STATE IS CORRUPTED')
                    operation_logger.error('ACTION REQUIRED: Close SICAL completely and restart it')
                    operation_logger.error('=' * 80)
                    return False
                operation_logger.error(f'Failed to expand menu item "{element_name}": {e}')
                return False

    t_desplegado = time.monotonic()

    # Double-click on the last item to open the window
    max_retries = 2
    for attempt in range(max_retries):
        try:
            # Re-find the main window for final step
            if attempt > 0:
                operation_logger.debug(f'Retry {attempt} for final menu option')
                time.sleep(DEFAULT_TIMING['medium_wait'])
                app = _wait_for_window_shared(SICAL_WINDOWS['main_menu'], timeout=5.0)
                if not app:
                    operation_logger.error('SICAL main menu lost during final navigation')
                    return False
                parent = None

            last_element_name = menu_path[-1]
            _find_tree_item(app, last_element_name, parent, timeout=None).double_click()
            operation_logger.debug(f'Opened menu option: {last_element_name}')
            _registrar_tiempos_menu(operation_logger, menu_path, plegadas, t_inicio,
                                    t_menu, t_plegado, t_desplegado, time.monotonic())
            return True
        except AttributeError as e:
            # Handle the specific __handle error
            if '__handle' in str(e):
                if attempt < max_retries - 1:
                    operation_logger.warning(f'UI handle lost for final option "{last_element_name}", retrying...')
                    continue
                else:
                    operation_logger.error(f'CRITICAL: UI handle broken after {max_retries} retries for final menu')
                    operation_logger.error('=' * 80)
                    operation_logger.error('SICAL COM STATE IS CORRUPTED')
                    operation_logger.error('ACTION REQUIRED: Close SICAL completely and restart it')
                    operation_logger.error('=' * 80)
                    return False
            operation_logger.error(f'Failed to open menu option "{menu_path[-1]}": {e}')
            return False
        except Exception as e:
            error_msg = str(e)
            # Check for COM event error
            if 'no pudo invocar' in error_msg or '-2147220991' in error_msg:
                operation_logger.error(f'COM event error: {e}')
                operation_logger.error('=' * 80)
                operation_logger.error('SICAL COM STATE IS CORRUPTED')
                operation_logger.error('ACTION REQUIRED: Close SICAL completely and restart it')
                operation_logger.error('=' * 80)
                return False
            operation_logger.error(f'Failed to open menu option "{menu_path[-1]}": {e}')
            return False

    return False


def collapse_all_menu_items(operation_logger: logging.Logger, app: Optional[Any] = None) -> Optional[int]:
    """
    Collapse all menu tree elements to ensure clean navigation state.

    Se recorren una vez las raices del arbol y solo se pulsan las que estan
    desplegadas. Antes se buscaba y se pulsaba cada una de las nueve aunque ya
    estuviera plegada -lo normal es que haya una o ninguna abierta-: en el
    robot de documentos se midieron 3,3 s entre plegar, desplegar y abrir
    (sical_docs.abrir_rapido). Plegar sigue haciendose con la tecla, como
    siempre; lo nuevo es solo saltarse las que no hace falta.

    Args:
        operation_logger: Logger instance for this operation
        app: la ventana del menu principal, si quien llama ya la tiene

    Returns:
        Cuantas ramas se han plegado, o None si no se pudo recorrer el arbol.
    """
    try:
        if app is None:
            app = _wait_for_window_shared(SICAL_WINDOWS['main_menu'], timeout=10.0)
        if not app:
            raise windows.ElementNotFound('SICAL main menu not found')
        operation_logger.debug('Collapsing menu tree elements')

        raices = _raices_del_menu(app)
        plegadas = 0
        for element_name in MENU_TREE_ELEMENTS_TO_COLLAPSE:
            try:
                element = raices.get(element_name) or app.find(
                    TREE_ITEM_LOCATOR.format(element_name),
                    search_depth=2,
                    timeout=DEFAULT_TIMING['short_wait']
                )
                if _esta_plegado(element):
                    continue
                element.send_keys(keys='{SUBTRACT}', wait_time=DEFAULT_TIMING['short_wait'])
                plegadas += 1
            except Exception:
                # Element might not be found or already collapsed, continue
                pass
        return plegadas
    except Exception as e:
        operation_logger.warning(f'Error collapsing menu items: {e}')
        return None


def _raices_del_menu(app: Any) -> dict:
    """Las raices del arbol que hay que plegar, en una sola pasada. {} si no se puede."""
    raices = {}
    try:
        for elemento in app.iter_children(max_depth=2):
            if (elemento.control_type == 'TreeItemControl'
                    and elemento.name in MENU_TREE_ELEMENTS_TO_COLLAPSE):
                raices.setdefault(elemento.name, elemento)
    except Exception:
        return {}
    return raices


def _esta_plegado(element: Any) -> bool:
    """
    True solo si UI Automation dice que esta plegado o que es una hoja.

    Ante la duda -sin el patron, o si la lectura falla- False: se pliega como
    siempre, y lo peor que pasa es lo de antes.
    """
    try:
        patron = element.ui_automation_control.GetExpandCollapsePattern()
        if not patron:
            return False
        return patron.ExpandCollapseState in (0, 3)  # Collapsed, LeafNode
    except Exception:
        return False


def _registrar_tiempos_menu(operation_logger: logging.Logger, menu_path, plegadas,
                            t_inicio, t_menu, t_plegado, t_desplegado, t_fin) -> None:
    """Cuanto cuesta cada tramo de la navegacion, para el registro y el rastro."""
    tramos = {
        'buscar_menu_s': round(t_menu - t_inicio, 2),
        'plegar_s': round(t_plegado - t_menu, 2),
        'desplegar_s': round(t_desplegado - t_plegado, 2),
        'abrir_s': round(t_fin - t_desplegado, 2),
    }
    operation_logger.info(
        f'Menu {" > ".join(menu_path)}: {round(t_fin - t_inicio, 2)} s '
        f'(menu {tramos["buscar_menu_s"]}, plegar {tramos["plegar_s"]} [{plegadas} ramas], '
        f'desplegar {tramos["desplegar_s"]}, abrir {tramos["abrir_s"]})')
    run_trace.event('menu', ruta=list(menu_path), plegadas=plegadas,
                    total_s=round(t_fin - t_inicio, 2), **tramos)


def handle_error_cleanup(ventana_proceso: Optional[Any] = None) -> None:
    """
    Clean up SICAL windows in case of error.

    Args:
        ventana_proceso: Optional window to clean up
    """
    try:
        # Close any error dialog that might be open
        modal_dialog = _wait_for_window_shared(SICAL_WINDOWS['error_dialog'], timeout=1.0)
        if modal_dialog:
            modal_dialog.find(COMMON_DIALOG_PATHS['ok_button']).click()

        # Additional cleanup for specific window if provided
        if ventana_proceso:
            # Attempt to close any modal dialogs on the window
            pass

    except Exception as e:
        logger.warning(f'Error during cleanup: {e}')


def transform_date_to_sical_format(date_str: str) -> str:
    """
    Transform date from DD/MM/YYYY format to DDMMYYYY format required by SICAL.

    Args:
        date_str: Date string in DD/MM/YYYY format

    Returns:
        Date string in DDMMYYYY format
    """
    return date_str.replace('/', '')


def extract_caja_code(caja_raw: str) -> str:
    """
    Extract caja code from composite format.

    Args:
        caja_raw: Raw caja string like "200_CAIXABNK - 2064"

    Returns:
        Extracted caja code like "200"
    """
    if '_' in caja_raw:
        return caja_raw.split('_')[0]
    return caja_raw


def check_finalize_flag(texto: str) -> Tuple[str, bool]:
    """
    Check if operation text ends with finalize flag and extract clean text.

    Args:
        texto: Operation text that may contain _FIN suffix

    Returns:
        Tuple of (cleaned_text, should_finalize)
    """
    from sical_config import FINALIZE_SUFFIX

    if texto.endswith(FINALIZE_SUFFIX):
        return texto.rstrip(FINALIZE_SUFFIX), True
    return texto, False


def show_windows_message_box(txt_message: str, txt_title: str) -> None:
    """
    Display a Windows message box with the given message and title.

    Args:
        txt_message: Message to display
        txt_title: Title of the message box
    """
    MB_OK = 0x0
    MB_ICONINFORMATION = 0x40
    MB_SYSTEMMODAL = 0x1000

    MessageBox = ctypes.windll.user32.MessageBoxW
    MessageBox(None, txt_message, txt_title, MB_SYSTEMMODAL | MB_ICONINFORMATION)


def wait_for_window(
    window_pattern: str,
    timeout: float = 5.0,
    retry_interval: float = 0.5
) -> Optional[Any]:
    """
    Wait for a window to appear with the given pattern.

    Backward-compatible shim that delegates to the shared
    ``sical_ui_utils.wait_for_window``, which polls
    ``windows.find_window`` with short per-call timeouts to work around
    cases where robocorp does not honour its own ``timeout=`` parameter.

    Args:
        window_pattern: Regex pattern for the window name
        timeout: Maximum time to wait in seconds
        retry_interval: Time between retries

    Returns:
        Window object if found, None otherwise
    """
    return _wait_for_window_shared(
        window_pattern, timeout=timeout, poll_interval=retry_interval)


def click_with_retry(
    window: Any,
    element_path: str,
    max_retries: int = 3,
    retry_delay: float = 0.5,
    **click_kwargs
) -> bool:
    """
    Click on an element with retry logic.

    Args:
        window: Window containing the element
        element_path: Path to the element
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries
        **click_kwargs: Additional kwargs to pass to click()

    Returns:
        bool: True if click was successful, False otherwise
    """
    for attempt in range(max_retries):
        try:
            element = window.find(element_path, raise_error=False)
            if element:
                element.click(**click_kwargs)
                return True
        except Exception as e:
            logger.debug(f'Click attempt {attempt + 1} failed: {e}')

        if attempt < max_retries - 1:
            time.sleep(retry_delay)

    return False


def send_keys_with_validation(
    window: Any,
    element_path: str,
    keys: str,
    interval: float = 0.05,
    wait_time: float = 0.2,
    send_enter: bool = False
) -> bool:
    """
    Send keys to an element with proper timing and optional validation.

    Args:
        window: Window containing the element
        element_path: Path to the element
        keys: Keys to send
        interval: Interval between keystrokes
        wait_time: Wait time after sending keys
        send_enter: Whether to send Enter after keys

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        element = window.find(element_path)
        element.send_keys(keys=keys, interval=interval, wait_time=wait_time, send_enter=send_enter)
        return True
    except Exception as e:
        logger.error(f'Failed to send keys to {element_path}: {e}')
        return False

def find_element_with_fallback(
    window: Any,
    paths: list[str],
    raise_error: bool = True
) -> Optional[Any]:
    """
    Find an element by trying each path in order, returning the first match.

    Args:
        window: Window to search in
        paths: Ordered list of element paths to try (primary first, then fallbacks)
        raise_error: Whether to raise error if no path resolves to an element

    Returns:
        Element if found, None otherwise (or raises if raise_error=True)
    """
    if not paths:
        raise ValueError("At least one path must be provided")

    *candidates, last = paths

    for path in candidates:
        element = window.find(path, raise_error=False)
        if element:
            return element

    # Delegate raise_error responsibility to the final attempt
    return window.find(last, raise_error=raise_error)


def find_element_with_fallback_old(
    window: Any,
    primary_path: str,
    fallback_path: str,
    raise_error: bool = True
) -> Optional[Any]:
    """
    Find an element using primary path, falling back to alternate path if not found.

    Args:
        window: Window to search in
        primary_path: Primary element path
        fallback_path: Fallback element path
        raise_error: Whether to raise error if neither path found

    Returns:
        Element if found, None otherwise (or raises if raise_error=True)
    """
    element = window.find(primary_path, raise_error=False)
    if element:
        return element

    element = window.find(fallback_path, raise_error=raise_error)
    return element


def format_amount_for_sical(amount: float) -> str:
    """
    Format a numeric amount for SICAL input.

    Args:
        amount: Numeric amount

    Returns:
        String formatted for SICAL (uses comma as decimal separator)
    """
    return str(amount).replace('.', ',')


def calculate_duration_string(start_time, end_time) -> str:
    """
    Calculate duration string between two datetime objects.

    Args:
        start_time: Start datetime
        end_time: End datetime

    Returns:
        Duration as string
    """
    return str(end_time - start_time)


def validate_tercero_format(tercero: str) -> bool:
    """
    Validate tercero (third party) ID format.

    Args:
        tercero: Tercero ID string

    Returns:
        bool: True if valid format
    """
    import re
    from sical_config import VALIDATION_RULES

    pattern = VALIDATION_RULES['tercero']['pattern']
    return bool(re.match(pattern, tercero))


def clean_boolean_value(value: Any) -> bool:
    """
    Clean and convert various representations to boolean.

    Args:
        value: Value to convert (bool, str, int, etc.)

    Returns:
        Boolean value
    """
    if isinstance(value, bool):
        return value
    elif isinstance(value, str):
        return value.lower() == 'true'
    elif isinstance(value, int):
        return bool(value)
    return bool(value)
