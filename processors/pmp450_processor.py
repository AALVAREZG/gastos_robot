"""
PMP450 Processor - Handles PMP450 (Gasto) operations in SICAL.

This processor implements the workflow for PMP450 expense operations.
It mirrors the ADO220 processor structure but uses PMP450-specific constants.

TODO: Configure actual PMP450 paths when SICAL access is available.
"""

import time
import logging
from typing import Any, Dict
from datetime import datetime
from robocorp import windows

from sical_base import (
    SicalOperationProcessor,
    SicalWindowManager,
    OperationResult,
    OperationStatus,
)
from sical_constants import (
    SICAL_WINDOWS,
    SICAL_MENU_PATHS,
    PMP450_FORM_PATHS,
    OPERATION_CODES,
    CONSULTA_FORM_PATHS,
    FILTROS_FORM_PATHS,
    TESORERIA_PAGOS_PATHS,
    VISUAL_DOCUMENTOS_PATHS,
    COMMON_DIALOG_PATHS,
    DEFAULT_TIMING,
)
from sical_config import (
    PARTIDAS_GASTO_CUENTA_PGP,
    DEFAULT_CUENTA_PGP,
    DEFAULT_OPERATION_VALUES,
)
from sical_utils import (
    open_menu_option,
    transform_date_to_sical_format,
    extract_caja_code,
    check_finalize_flag,
    show_windows_message_box,
    find_element_with_fallback,
    handle_error_cleanup,
)
from sical_security import (
    get_confirmation_manager,
    get_rate_limiter,
    audit_log_force_create,
)


class PMP450WindowManager(SicalWindowManager):
    """Window manager for PMP450 operation windows."""

    @property
    def window_pattern(self) -> str:
        return SICAL_WINDOWS['pmp450']


class PMP450Processor(SicalOperationProcessor):
    """
    Processor for PMP450 expense operations.

    This processor handles the PMP450 workflow following the same pattern as ADO220:
    1. Data preparation and transformation
    2. Duplicate checking (optional)
    3. Form data entry
    4. Validation and operation number assignment
    5. Document printing
    6. Payment ordering

    TODO: Update paths and constants when SICAL access is available.
    """

    @property
    def operation_type(self) -> str:
        return 'pmp450'

    @property
    def operation_name(self) -> str:
        return 'PMP450'

    def create_window_manager(self) -> SicalWindowManager:
        return PMP450WindowManager(self.logger)

    def create_operation_data(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform operation data from v2 message format into SICAL-compatible format.

        Args:
            operation_data: Operation data from RabbitMQ message (v2 format)

        Returns:
            Transformed data compatible with SICAL processing functions
        """
        # Extract texto field from texto_sical array
        texto_sical = operation_data.get('texto_sical', [])
        if texto_sical and len(texto_sical) > 0:
            # PMP450 might use a different text field - adjust as needed
            texto_operacion = str(texto_sical[0].get('texto_ado', DEFAULT_OPERATION_VALUES['texto']))
        else:
            texto_operacion = DEFAULT_OPERATION_VALUES['texto']

        # Check if operation should be finalized
        texto_operacion, finalizar_operacion = check_finalize_flag(texto_operacion)

        # Convert fecha from DD/MM/YYYY to DDMMYYYY format
        fecha = transform_date_to_sical_format(operation_data.get('fecha', ''))

        # Extract caja code
        caja_raw = operation_data.get('caja', DEFAULT_OPERATION_VALUES['caja'])
        caja = extract_caja_code(caja_raw)

        return {
            'fecha': fecha,
            'expediente': operation_data.get('expediente', DEFAULT_OPERATION_VALUES['expediente']),
            'tercero': operation_data.get('tercero'),
            'fpago': operation_data.get('fpago', DEFAULT_OPERATION_VALUES['fpago']),
            'tpago': operation_data.get('tpago', DEFAULT_OPERATION_VALUES['tpago']),
            'caja': caja,
            'caja_tercero': operation_data.get('caja_tercero'),
            'texto': texto_operacion,
            'aplicaciones': self._create_aplicaciones(operation_data.get('aplicaciones', [])),
            'finalizar_operacion': finalizar_operacion,
            'descuentos': operation_data.get('descuentos', []),
            'aux_data': operation_data.get('aux_data', {}),
            'metadata': operation_data.get('metadata', {}),
            # Keep original data for payment ordering
            'fecha_ordenamiento': operation_data.get('fecha_ordenamiento', fecha),
            'fecha_pago': operation_data.get('fecha_pago', operation_data.get('fecha_ordenamiento', fecha)),
            # Security: Duplicate handling policy and token
            'duplicate_policy': operation_data.get('duplicate_policy', 'abort_on_duplicate'),
            'duplicate_confirmation_token': operation_data.get('duplicate_confirmation_token'),
            'duplicate_check_id': operation_data.get('duplicate_check_id'),
        }

    def _create_aplicaciones(self, aplicaciones_data: list) -> list:
        """
        Transform aplicaciones data from v2 message format into SICAL-compatible format.

        Args:
            aplicaciones_data: List of aplicacion objects from message

        Returns:
            List of aplicaciones in SICAL-compatible format
        """
        aplicaciones = []
        for aplicacion in aplicaciones_data:
            economica = str(aplicacion['economica'])

            # Prefer cuenta_pgp from message, fallback to mapping table
            if 'cuenta_pgp' in aplicacion and aplicacion['cuenta_pgp']:
                cuenta = str(aplicacion['cuenta_pgp'])
            else:
                cuenta = PARTIDAS_GASTO_CUENTA_PGP.get(economica, DEFAULT_CUENTA_PGP)

            importe = str(aplicacion['importe'])

            aplicacion_obj = {
                'funcional': str(aplicacion['funcional']),
                'economica': economica,
                'gfa': aplicacion.get('proyecto'),
                'importe': importe,
                'cuenta': cuenta,
                'otro': False,
                'year': str(aplicacion.get('year', '')),
                'contraido': bool(aplicacion.get('contraido', False)),
                'base_imponible': float(aplicacion.get('base_imponible', 0.0)),
                'tipo': float(aplicacion.get('tipo', 0.0)),
                'aux': str(aplicacion.get('aux', ''))
            }

            aplicaciones.append(aplicacion_obj)

        return aplicaciones

    def setup_operation_window(self) -> bool:
        """
        Open and setup the PMP450 SICAL window.

        TODO: Verify the correct menu path for PMP450 operations.
        """
        menu_path = SICAL_MENU_PATHS['pmp450']
        time.sleep(DEFAULT_TIMING['medium_wait'])

        if not open_menu_option(menu_path, self.logger):
            time.sleep(DEFAULT_TIMING['extra_long_wait'])
            if not open_menu_option(menu_path, self.logger):
                self.logger.error(f'Unable to open PMP450 window via menu: {menu_path}')
                return False

        self.window_manager.ventana_proceso = self.window_manager.find_proceso_window()
        self.logger.debug(f'PMP450 window: {self.window_manager.ventana_proceso}')
        return bool(self.window_manager.ventana_proceso)

    def process_operation_form(
        self,
        operation_data: Dict[str, Any],
        result: OperationResult
    ) -> OperationResult:
        """
        Process the complete PMP450 operation workflow.

        Args:
            operation_data: Prepared SICAL-compatible operation data
            result: Current operation result object

        Returns:
            Updated operation result
        """
        self.logger.info(f'Processing PMP450 - Tercero: {operation_data.get("tercero")}, '
                        f'Fecha: {operation_data.get("fecha")}, '
                        f'Lines: {len(operation_data.get("aplicaciones", []))}')

        finalizar_operacion = operation_data.get('finalizar_operacion', False)
        duplicate_policy = operation_data.get('duplicate_policy', 'abort_on_duplicate')

        # SECURITY: Validate force_create token before processing
        if duplicate_policy == 'force_create':
            confirmation_manager = get_confirmation_manager()
            token_id = operation_data.get('duplicate_confirmation_token')

            is_valid, error_msg = confirmation_manager.validate_token(token_id, operation_data)

            # Audit log the attempt
            audit_log_force_create(operation_data, is_valid, error_msg)

            if not is_valid:
                self.logger.error(f'SECURITY: Invalid force_create attempt: {error_msg}')
                result.status = OperationStatus.FAILED
                result.error = f'Security validation failed: {error_msg}'
                return result

            self.logger.info(f'force_create token validated successfully for tercero: {operation_data.get("tercero")}')

        # Phase: Check for duplicate operations (based on policy)
        if duplicate_policy in ('check_only', 'abort_on_duplicate', 'warn_and_continue'):
            result = self._check_for_duplicates(operation_data, result)

            if duplicate_policy == 'check_only':
                # ONLY check, don't create operation
                if result.status == OperationStatus.P_DUPLICATED:
                    self.logger.info(f'Check-only mode: Found {result.similiar_records_encountered} duplicates')
                else:
                    self.logger.info('Check-only mode: No duplicates found')
                return result  # Return immediately without creating operation

            elif duplicate_policy == 'abort_on_duplicate':
                # Current behavior: abort if duplicates found
                if result.status in (OperationStatus.FAILED, OperationStatus.P_DUPLICATED):
                    return result

            elif duplicate_policy == 'warn_and_continue':
                # Log warning but continue creating operation
                if result.status == OperationStatus.P_DUPLICATED:
                    self.logger.warning(
                        f'Duplicates found but continuing due to policy: '
                        f'{result.similiar_records_encountered} similar records'
                    )
                    result.status = OperationStatus.IN_PROGRESS  # Reset status to continue

        # elif duplicate_policy == 'force_create':
        #     Skip duplicate check entirely - already validated token above

        # Phase: Enter operation data
        self.notify_step('Entering operation data into form')
        result = self._enter_operation_data(operation_data, result)

        if result.status == OperationStatus.FAILED:
            return result

        self.logger.info(f'Operation data entered - Will finalize: {finalizar_operacion}')

        # Phase: Validate, print, and order payment (if finalizing)
        if result.status == OperationStatus.COMPLETED and finalizar_operacion:
            # Check for duplicate warning flag
            if result.similiar_records_encountered > 0:
                self.logger.warning('Skipping finalization due to duplicate warning')
                return result

            # Validate operation
            self.notify_step('Validating operation')
            result = self._validate_operation(result)

            if result.status == OperationStatus.COMPLETED and result.num_operacion:
                self.logger.info(f'Operation validated - Number: {result.num_operacion}')

                # Print operation document
                self.notify_step('Printing operation document')
                result = self._print_operation_document(result)

                # Order and pay
                self.notify_step('Ordering payment')
                result = self._order_and_pay(operation_data, result)

        return result

    def _check_for_duplicates(
        self,
        operation_data: Dict[str, Any],
        result: OperationResult
    ) -> OperationResult:
        """
        Check for duplicate operations using the Consulta window.

        This method now returns detailed duplicate information and generates
        confirmation tokens for force_create operations.

        Args:
            operation_data: Operation data to search for
            result: Current operation result

        Returns:
            Updated operation result with duplicate details and token (if duplicates found)
        """
        self.logger.info('Checking for duplicate operations')
        self.notify_step('Checking for duplicate operations')

        # Import ADO220 processor's consulta window manager
        from .ado220_processor import ConsultaWindowManager

        consulta_manager = ConsultaWindowManager(self.logger)
        duplicate_policy = operation_data.get('duplicate_policy', 'abort_on_duplicate')

        try:
            # Setup consulta window
            if not self._setup_consulta_window(consulta_manager):
                result.status = OperationStatus.FAILED
                result.error = 'Failed to open Consulta window'
                return result

            result.sical_is_open = True

            # Open filters window
            consulta_manager.ventana_proceso.find(CONSULTA_FORM_PATHS['filtros_button']).click()
            time.sleep(DEFAULT_TIMING['medium_wait'])

            filtros_window = windows.find_window(
                SICAL_WINDOWS['filtros'],
                timeout=1.5,
                raise_error=False
            )

            if not filtros_window:
                result.status = OperationStatus.FAILED
                result.error = 'Failed to open Filters window'
                return result

            # Fill filter criteria and get search criteria for metadata
            search_criteria = self._fill_duplicate_check_filters(filtros_window, operation_data)

            # Execute search
            filtros_window.find(FILTROS_FORM_PATHS['consultar_button']).click()
            time.sleep(DEFAULT_TIMING['short_wait'])

            # Check for results
            modal_error = filtros_window.find(
                'class:"TMessageForm" and name:"Error"',
                timeout=1.0,
                raise_error=False
            )

            if not modal_error:
                # Records found - potential duplicates
                num_registros = filtros_window.find(FILTROS_FORM_PATHS['num_registros']).get_value()
                result.similiar_records_encountered = int(num_registros) if num_registros else 0

                self.logger.warning(f'Found {num_registros} similar records')

                # TODO: Extract duplicate details from grid
                # This requires knowledge of the SICAL grid structure
                result.duplicate_details = []  # Placeholder for detailed extraction

                # Generate confirmation token
                confirmation_manager = get_confirmation_manager()
                token_id, expires_at = confirmation_manager.generate_token(operation_data)

                result.duplicate_confirmation_token = token_id
                result.duplicate_token_expires_at = expires_at
                result.duplicate_check_metadata = {
                    'check_id': operation_data.get('duplicate_check_id'),
                    'check_timestamp': datetime.now().isoformat(),
                    'search_criteria': search_criteria
                }

                result.status = OperationStatus.P_DUPLICATED

                # Only show message box if policy is 'abort_on_duplicate'
                if duplicate_policy == 'abort_on_duplicate':
                    txt_message = f'Possible duplicate operation found, similar records: {result.similiar_records_encountered}'
                    show_windows_message_box(txt_message, 'Proceso abortado')

                # Close filtros window
                filtros_window.find(FILTROS_FORM_PATHS['cerrar_button']).click()

            else:
                # No records found - safe to proceed
                result.similiar_records_encountered = 0
                result.duplicate_details = []
                result.duplicate_check_metadata = {
                    'check_id': operation_data.get('duplicate_check_id'),
                    'check_timestamp': datetime.now().isoformat(),
                    'search_criteria': search_criteria
                }

                self.logger.info('No similar records found - proceeding with operation')
                filtros_window.find(COMMON_DIALOG_PATHS['ok_button']).click()
                filtros_window.find(FILTROS_FORM_PATHS['cerrar_button']).click()
                time.sleep(DEFAULT_TIMING['short_wait'])

            result.completed_phases.append({
                'phase': 'duplicate_check',
                'description': f'Similar records checked: {result.similiar_records_encountered} found'
            })

        except windows.ElementNotFound as e:
            self.logger.error(f'Element not found during duplicate check: {e}')
            result.status = OperationStatus.FAILED
            result.error = str(e)
        except Exception as e:
            self.logger.error(f'Error checking for duplicates: {e}')
            result.status = OperationStatus.FAILED
            result.error = str(e)

        return result

    def _setup_consulta_window(self, window_manager) -> bool:
        """Setup the Consulta operations window."""
        menu_path = SICAL_MENU_PATHS['consulta']

        if not open_menu_option(menu_path, self.logger):
            time.sleep(3)
            if not open_menu_option(menu_path, self.logger):
                self.logger.error(f'Unable to open Consulta window: {menu_path}')
                return False

        time.sleep(2)
        window_manager.ventana_proceso = window_manager.find_proceso_window()
        self.logger.debug(f'Consulta window: {window_manager.ventana_proceso}')
        return bool(window_manager.ventana_proceso)

    def _fill_duplicate_check_filters(
        self,
        filtros_window,
        operation_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Fill the filter fields for duplicate checking.

        Returns:
            Dictionary with search criteria used
        """
        wait_time = DEFAULT_TIMING['short_wait']
        interval = DEFAULT_TIMING['short_wait']

        # Build search criteria dictionary
        search_criteria = {
            'tercero': operation_data['tercero'],
            'fecha': operation_data['fecha'],
            'caja': operation_data['caja']
        }

        # Tercero
        tercero_field = filtros_window.find(FILTROS_FORM_PATHS['tercero'])
        tercero_field.double_click()
        tercero_field.send_keys(operation_data['tercero'], interval=interval, wait_time=wait_time, send_enter=True)

        # Date range
        fecha = operation_data['fecha']
        from_date_field = filtros_window.find(FILTROS_FORM_PATHS['fecha_desde'])
        from_date_field.double_click()
        from_date_field.send_keys(fecha, interval=0.01, wait_time=wait_time, send_enter=True)

        to_date_field = filtros_window.find(FILTROS_FORM_PATHS['fecha_hasta'])
        to_date_field.double_click()
        to_date_field.send_keys(fecha, interval=0.01, wait_time=wait_time, send_enter=True)

        # Aplicacion
        if operation_data.get('aplicaciones'):
            first_app = operation_data['aplicaciones'][0]

            search_criteria.update({
                'funcional': first_app['funcional'],
                'economica': first_app['economica'],
                'importe_min': first_app['importe'],
                'importe_max': first_app['importe']
            })

            funcional_field = filtros_window.find(FILTROS_FORM_PATHS['funcional'])
            funcional_field.double_click()
            funcional_field.send_keys(first_app['funcional'], interval=0.01, wait_time=wait_time, send_enter=True)

            economica_field = filtros_window.find(FILTROS_FORM_PATHS['economica'])
            economica_field.double_click()
            economica_field.send_keys(first_app['economica'], interval=0.01, wait_time=wait_time, send_enter=True)

            importe_desde = filtros_window.find(FILTROS_FORM_PATHS['importe_desde'])
            importe_desde.double_click()
            importe_desde.send_keys(first_app['importe'], interval=0.01, wait_time=wait_time, send_enter=True)

            importe_hasta = filtros_window.find(FILTROS_FORM_PATHS['importe_hasta'])
            importe_hasta.double_click()
            importe_hasta.send_keys(first_app['importe'], interval=0.01, wait_time=wait_time, send_enter=True)

        # Caja
        caja_field = filtros_window.find(FILTROS_FORM_PATHS['caja'])
        caja_field.click()
        caja_field.send_keys(operation_data['caja'], interval=0.01, wait_time=wait_time, send_enter=True)

        return search_criteria

    def _enter_operation_data(
        self,
        operation_data: Dict[str, Any],
        result: OperationResult
    ) -> OperationResult:
        """
        Enter operation data into the PMP450 form.

        TODO: Update paths when SICAL access is available.

        Args:
            operation_data: Prepared operation data
            result: Current operation result

        Returns:
            Updated operation result
        """
        ventana = self.window_manager.ventana_proceso
        default_wait = DEFAULT_TIMING['default_wait']

        try:
            # Initialize form - click "Nuevo" button
            ventana.find(PMP450_FORM_PATHS['nuevo_button']).click()
            modal_confirm = windows.find_window(SICAL_WINDOWS['confirm_dialog'], raise_error=True)
            modal_confirm.find(COMMON_DIALOG_PATHS['confirm_ok']).click()

            # Fill operation code - PMP450 uses code 450
            cod_op_element = ventana.find(PMP450_FORM_PATHS['cod_operacion']).click(wait_time=default_wait)
            cod_op_element.send_keys(keys=OPERATION_CODES['pmp450'], interval=0.05, wait_time=default_wait)
            cod_op_element.send_keys(keys='{Enter}', wait_time=default_wait)

            # Fill main panel data
            self._fill_main_panel(ventana, operation_data, default_wait)

            # Fill aplicaciones (line items)
            result = self._fill_aplicaciones(ventana, operation_data['aplicaciones'], result)

            result.completed_phases.append({
                'phase': 'data_entry',
                'description': 'Operation data entered into form'
            })

            if result.status != OperationStatus.FAILED:
                result.status = OperationStatus.COMPLETED

        except Exception as e:
            self.logger.error(f'Error entering operation data: {e}')
            result.status = OperationStatus.FAILED
            result.error = f'Data entry error: {str(e)}'

        return result

    def _fill_main_panel(
        self,
        ventana,
        operation_data: Dict[str, Any],
        wait_time: float
    ) -> None:
        """
        Fill the main panel fields in the PMP450 form.

        TODO: Verify these paths are correct for PMP450.
        """
        # Fecha
        fecha_element = ventana.find(PMP450_FORM_PATHS['fecha']).double_click()
        fecha_element.send_keys(operation_data['fecha'], interval=0.03, wait_time=wait_time)

        # Expediente
        expediente_element = ventana.find(PMP450_FORM_PATHS['expediente']).double_click()
        expediente_element.send_keys(operation_data['expediente'], wait_time=wait_time)

        # Tercero
        tercero_element = ventana.find(PMP450_FORM_PATHS['tercero']).double_click()
        tercero_element.send_keys(operation_data['tercero'], interval=0.05, wait_time=wait_time)

        # Tesoreria checkbox
        ventana.find(PMP450_FORM_PATHS['tesoreria_check']).click(wait_time=wait_time)

        # Forma de pago
        forma_pago = find_element_with_fallback(
            ventana,
            PMP450_FORM_PATHS['forma_pago_primary'],
            PMP450_FORM_PATHS['forma_pago_alternate'],
            raise_error=True
        )
        forma_pago.double_click(wait_time=wait_time)
        forma_pago.send_keys(keys=operation_data['fpago'], interval=0.01, wait_time=wait_time)
        forma_pago.send_keys(keys='{Enter}', wait_time=wait_time)

        # Tipo de pago
        tipo_pago = find_element_with_fallback(
            ventana,
            PMP450_FORM_PATHS['tipo_pago_primary'],
            PMP450_FORM_PATHS['tipo_pago_alternate'],
            raise_error=True
        )
        tipo_pago.double_click(wait_time=wait_time)
        tipo_pago.send_keys(keys=operation_data['tpago'], interval=0.01, wait_time=wait_time)
        tipo_pago.send_keys(keys='{Enter}', wait_time=wait_time)

        # Caja
        caja_element = find_element_with_fallback(
            ventana,
            PMP450_FORM_PATHS['caja_primary'],
            PMP450_FORM_PATHS['caja_alternate'],
            raise_error=True
        )
        caja_element.click(wait_time=wait_time)
        caja_element.send_keys(keys=operation_data['caja'], interval=wait_time, wait_time=wait_time)

        # Texto
        texto_element = ventana.find(PMP450_FORM_PATHS['texto']).double_click()
        texto_element.send_keys(keys='{Ctrl}{A}', wait_time=wait_time)
        texto_element.send_keys(operation_data['texto'], wait_time=DEFAULT_TIMING['default_wait'])
        texto_element.send_keys(keys='{Enter}', wait_time=wait_time)

    def _fill_aplicaciones(
        self,
        ventana,
        aplicaciones: list,
        result: OperationResult
    ) -> OperationResult:
        """Fill the aplicaciones (line items) grid."""
        default_wait = DEFAULT_TIMING['default_wait']

        ventana.find(PMP450_FORM_PATHS['aplicaciones_grid']).double_click()

        suma_aplicaciones = 0.0

        for i, aplicacion in enumerate(aplicaciones):
            self.logger.debug(f'Processing aplicacion {i + 1}: {aplicacion}')
            self.notify_step(
                f'Processing line item {i + 1} of {len(aplicaciones)}',
                current_line_item=i + 1,
                total_line_items=len(aplicaciones),
                line_item_details=f"Func: {aplicacion['funcional']}, Econ: {aplicacion['economica']}, Amount: {aplicacion['importe']}"
            )

            ventana.find(PMP450_FORM_PATHS['new_line_button']).click()

            ventana.send_keys(keys='{Tab}', interval=0.05, wait_time=default_wait, send_enter=False)
            ventana.send_keys(keys=aplicacion['funcional'], interval=default_wait, wait_time=default_wait, send_enter=True)
            ventana.send_keys(keys=aplicacion['economica'], interval=default_wait, wait_time=0.0, send_enter=True)

            if aplicacion.get('gfa'):
                ventana.send_keys(keys=aplicacion['gfa'], interval=default_wait, wait_time=default_wait, send_enter=True)

            ventana.send_keys(keys='{Tab}', wait_time=0.05, interval=default_wait)
            ventana.send_keys(keys=aplicacion['importe'], interval=0.05, wait_time=default_wait, send_enter=False)
            ventana.send_keys(keys='{Enter}', wait_time=default_wait)

            ventana.send_keys(keys=aplicacion['cuenta'], interval=default_wait, wait_time=DEFAULT_TIMING['default_wait'])

            ventana.find(PMP450_FORM_PATHS['confirm_line_button']).click()

            try:
                suma_aplicaciones += float(aplicacion['importe'].replace(',', '.'))
            except ValueError:
                pass

        result.suma_aplicaciones = suma_aplicaciones
        result.total_operacion = 0

        return result

    def _validate_operation(self, result: OperationResult) -> OperationResult:
        """Validate the PMP450 operation in SICAL."""
        ventana = self.window_manager.ventana_proceso
        result.status = OperationStatus.PENDING

        try:
            self.logger.info(f'Validating PMP450 operation in window: {ventana}')
            ventana.find(PMP450_FORM_PATHS['validar_button']).click(wait_time=DEFAULT_TIMING['default_wait'])

            modal_confirm = windows.find_window(SICAL_WINDOWS['confirm_dialog'])
            modal_confirm.find(COMMON_DIALOG_PATHS['confirm_yes']).click()
            time.sleep(DEFAULT_TIMING['long_wait'])

            modal_info = windows.find_window(SICAL_WINDOWS['information_dialog'])
            modal_info.find(COMMON_DIALOG_PATHS['info_ok']).click()
            time.sleep(DEFAULT_TIMING['long_wait'])

            num_operacion_field = ventana.find(PMP450_FORM_PATHS['num_operacion'], raise_error=False)
            if num_operacion_field:
                num_operacion = num_operacion_field.get_value()
                self.logger.info(f'Operation number assigned: {num_operacion}')
                result.num_operacion = num_operacion

            ventana.find(PMP450_FORM_PATHS['salir_button']).click(wait_time=DEFAULT_TIMING['medium_wait'])

            result.status = OperationStatus.COMPLETED
            result.completed_phases.append({
                'phase': 'validation',
                'description': f'Operation validated: {result.num_operacion}'
            })

        except Exception as e:
            self.logger.error(f'Validation error: {e}')
            result.status = OperationStatus.FAILED
            result.error = f'Validation error: {str(e)}'

        return result

    def _print_operation_document(self, result: OperationResult) -> OperationResult:
        """
        Print the operation document.

        Uses the same printing mechanism as ADO220 via Consulta window.
        """
        num_operacion = result.num_operacion
        if not num_operacion:
            self.logger.error('Cannot print - no operation number')
            return result

        self.logger.info(f'Printing document for operation: {num_operacion}')

        try:
            ventana_consulta = windows.find_window(
                SICAL_WINDOWS['consulta'],
                timeout=1.5,
                raise_error=False
            )

            if not ventana_consulta:
                open_menu_option(SICAL_MENU_PATHS['consulta'], self.logger)
                ventana_consulta = windows.find_window(SICAL_WINDOWS['consulta'], raise_error=False)

            if not ventana_consulta:
                self.logger.error('Failed to open Consulta window for printing')
                return result

            campo_id = ventana_consulta.find(CONSULTA_FORM_PATHS['id_operacion'])
            campo_id.send_keys(num_operacion, interval=0.1, wait_time=DEFAULT_TIMING['default_wait'], send_enter=True)

            ventana_consulta.find(CONSULTA_FORM_PATHS['imprimir_button']).click()

            campo_estado = ventana_consulta.find(CONSULTA_FORM_PATHS['estado_documento'], raise_error=False)
            if campo_estado:
                campo_estado.send_keys(keys='I', interval=0.1, send_enter=True, wait_time=3.0)

            ventana_visual = windows.find_window(SICAL_WINDOWS['visual_documentos'])
            ventana_visual.find(VISUAL_DOCUMENTOS_PATHS['imprimir_button']).click()
            ventana_visual.find(VISUAL_DOCUMENTOS_PATHS['salir_button']).click()
            ventana_consulta.find(CONSULTA_FORM_PATHS['salir_button']).click()

            f_menu_sical = windows.find_window(SICAL_WINDOWS['main_menu'])
            try:
                f_menu_sical.find('control:"TreeItemControl" and name:"CONSULTAS AVANZADAS"').double_click(wait_time=1.0)
            except windows.ActionNotPossible:
                pass

            result.completed_phases.append({
                'phase': 'printing',
                'description': f'Print operation document ID: {num_operacion}'
            })

        except Exception as e:
            self.logger.error(f'Error printing document: {e}')
            result.completed_phases.append({
                'phase': 'printing',
                'description': f'Print failed: {str(e)}'
            })

        return result

    def _order_and_pay(
        self,
        operation_data: Dict[str, Any],
        result: OperationResult
    ) -> OperationResult:
        """
        Order and pay the operation.

        Uses the same payment ordering mechanism as ADO220.
        """
        num_operacion = result.num_operacion
        if not num_operacion:
            self.logger.error('Cannot order payment - no operation number')
            return result

        self.logger.info(f'Ordering payment for operation: {num_operacion}')
        self.notify_step('Opening payment window')

        # Import from ADO220 processor to reuse payment logic
        from .ado220_processor import TesoreriaPagosWindowManager

        pagos_manager = TesoreriaPagosWindowManager(self.logger)

        try:
            if not self._setup_tesoreria_window(pagos_manager):
                result.status = OperationStatus.FAILED
                result.error = 'Failed to open Tesoreria Pagos window'
                return result

            datos_pago = {
                'num_operacion': num_operacion,
                'fecha_ordenamiento': operation_data.get('fecha_ordenamiento', operation_data['fecha']),
                'fecha_pago': operation_data.get('fecha_pago', operation_data.get('fecha_ordenamiento', operation_data['fecha']))
            }

            self.logger.info(f'Payment data: {datos_pago}')
            result = self._execute_payment_ordering(pagos_manager.ventana_proceso, datos_pago, result)

        except Exception as e:
            self.logger.error(f'Error in payment ordering: {e}')
            result.error = str(e)

            if result.sical_is_open:
                handle_error_cleanup(pagos_manager.ventana_proceso)

        return result

    def _setup_tesoreria_window(self, window_manager) -> bool:
        """Setup the Tesoreria Pagos window."""
        menu_path = SICAL_MENU_PATHS['tesoreria_pagos']

        if not open_menu_option(menu_path, self.logger):
            return False

        window_manager.ventana_proceso = window_manager.find_proceso_window()
        self.logger.debug(f'Tesoreria window: {window_manager.ventana_proceso}')
        return bool(window_manager.ventana_proceso)

    def _execute_payment_ordering(
        self,
        ventana,
        datos_pago: Dict[str, Any],
        result: OperationResult
    ) -> OperationResult:
        """
        Execute the payment ordering and payment process.

        This follows the same logic as ADO220.
        """
        self.logger.info('Starting payment order process')
        self.notify_step('Processing payment order')

        try:
            fecha_element = ventana.find(TESORERIA_PAGOS_PATHS['fecha_orden'])
            fecha_element.send_keys(datos_pago['fecha_ordenamiento'], interval=0.1, wait_time=0.5, send_enter=True)

            modal_fecha = ventana.find(COMMON_DIALOG_PATHS['info_ok_alt'], raise_error=False)
            if modal_fecha:
                modal_fecha.click(wait_time=0.5)

            ventana.find(TESORERIA_PAGOS_PATHS['ordenar_button']).click(wait_time=0.8)
            ventana.find(TESORERIA_PAGOS_PATHS['option_num_operacion']).click(wait_time=0.5)

            num_op_element = ventana.find(TESORERIA_PAGOS_PATHS['num_operacion_input']).click(wait_time=0.2)
            num_op_element.send_keys(datos_pago['num_operacion'], interval=0.1, wait_time=0.5, send_enter=True)

            modal_error = ventana.find('class:"TMessageForm" and name:"Error"', timeout=1.0, raise_error=False)

            if not modal_error:
                self._complete_ordering_process(ventana)
            else:
                self.logger.info('Operation already ordered, skipping to payment')
                ventana.find(COMMON_DIALOG_PATHS['ok_button']).click(wait_time=0.8)
                ventana.find(COMMON_DIALOG_PATHS['ok_button']).click(wait_time=0.8)
                ventana.find(TESORERIA_PAGOS_PATHS['cancel_operation_button']).click(wait_time=0.8)

            self._complete_payment_process(ventana, datos_pago)

            result.completed_phases.append({
                'phase': 'payment_ordering',
                'description': f'Operation ordered and paid: {datos_pago["num_operacion"]}'
            })

        except Exception as e:
            self.logger.error(f'Error in order and pay: {e}')
            result.status = OperationStatus.FAILED
            result.error = f'Error ordering/paying operation: {datos_pago["num_operacion"]} - {str(e)}'

        return result

    def _complete_ordering_process(self, ventana) -> None:
        """Complete the ordering process after entering operation number."""
        time.sleep(0.1)

        ventana.find(TESORERIA_PAGOS_PATHS['validar_op_button']).click(wait_time=0.1)
        ventana.find(TESORERIA_PAGOS_PATHS['validar_orden_button']).click(wait_time=0.1)
        ventana.find(COMMON_DIALOG_PATHS['info_ok_alt']).click(wait_time=1.0)

        ventana.find(TESORERIA_PAGOS_PATHS['check_mto_pago']).click(wait_time=0.2)
        ventana.find(TESORERIA_PAGOS_PATHS['validar_mto_button']).click(wait_time=0.2)

        ventana.find(COMMON_DIALOG_PATHS['confirm_yes_alt']).click(wait_time=0.2)
        ventana.find(COMMON_DIALOG_PATHS['confirm_yes_alt']).click(wait_time=0.2)
        ventana.find(COMMON_DIALOG_PATHS['confirm_yes_alt']).click(wait_time=0.2)

        ventana_imprimir = windows.find_window(SICAL_WINDOWS['print_dialog'])
        ventana_imprimir.find(COMMON_DIALOG_PATHS['print_accept']).click(wait_time=1.0)

        ventana.find(COMMON_DIALOG_PATHS['info_ok_alt']).click(wait_time=0.5)

    def _complete_payment_process(self, ventana, datos_pago: Dict[str, Any]) -> None:
        """Complete the payment process after ordering."""
        ventana.find(TESORERIA_PAGOS_PATHS['pagar_button']).click(wait_time=0.4)
        ventana.find(TESORERIA_PAGOS_PATHS['option_num_operacion']).click(wait_time=0.5)

        num_op_element = ventana.find(TESORERIA_PAGOS_PATHS['num_operacion_input']).click(wait_time=0.2)
        num_op_element.send_keys(datos_pago['num_operacion'], interval=0.1, wait_time=0.5, send_enter=True)

        ventana.find(TESORERIA_PAGOS_PATHS['validar_op_button']).click(wait_time=1.0)
        ventana.find(TESORERIA_PAGOS_PATHS['validar_orden_button']).click(wait_time=1.0)
        ventana.find(COMMON_DIALOG_PATHS['info_ok_alt']).click(wait_time=1.0)

        ventana.find(TESORERIA_PAGOS_PATHS['salir_impresion_button']).click()
        time.sleep(0.5)
        ventana.find(TESORERIA_PAGOS_PATHS['salir_button']).click()
