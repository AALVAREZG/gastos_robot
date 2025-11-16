"""
SICAL Constants - Centralized configuration for all SICAL UI paths and values.

This module contains all hardcoded paths, window names, and operation-specific
constants used throughout the SICAL automation system.
"""

from typing import Dict, Tuple

# =============================================================================
# WINDOW PATTERNS - Regex patterns for finding SICAL windows
# =============================================================================

SICAL_WINDOWS = {
    'main_menu': 'regex:.*FMenuSical',
    'ado220': 'regex:.*SICAL II 4.2 new30',
    'pmp450': 'regex:.*SICAL II 4.2 new30',  # TODO: Update when PMP450 window pattern is known
    'consulta': 'regex:.*SICAL II 4.2 ConOpera',
    'tesoreria': 'regex:.*SICAL II 4.2 TesPagos',
    'filtros': 'regex:.*SICAL II 4.2 FilOpera',
    'confirm_dialog': 'regex:.*Confirm',
    'information_dialog': 'regex:.*Information',
    'error_dialog': 'regex:.*mtec40',
    'visual_documentos': 'regex:.*Visualizador de Documentos de SICAL v2',
    'print_dialog': 'regex:.*Imprimir',
}

# =============================================================================
# MENU PATHS - Navigation paths in SICAL menu tree
# =============================================================================

SICAL_MENU_PATHS = {
    'ado220': ('GASTOS', 'OPERACIONES DE PRESUPUESTO CORRIENTE'),
    'pmp450': ('GASTOS', 'OPERACIONES DE PRESUPUESTO CORRIENTE'),  # TODO: Verify actual path for PMP450
    'consulta': ('CONSULTAS AVANZADAS', 'CONSULTA DE OPERACIONES'),
    'tesoreria_pagos': ('TESORERIA', 'GESTION DE PAGOS', 'PROCESO DE ORDENACION Y PAGO'),
    'arqueo': ('TESORERIA', 'GESTION DE COBROS', 'ARQUEOS. APLICACION DIRECTA',
               'TRATAMIENTO INDIVIDUALIZADO/RESUMEN'),
}

# Menu tree elements to collapse before navigation
MENU_TREE_ELEMENTS_TO_COLLAPSE = [
    'TERCEROS',
    'GASTOS CON FINANCIACION AFECTADA \\ PROYECTO',
    'PAGOS A JUSTIFICAR Y ANTICIPOS DE CAJA FIJA',
    'ADMINISTRACION DEL SISTEMA',
    'TRANSACCIONES ESPECIALES',
    'CONSULTAS AVANZADAS',
    'FACTURAS',
    'OFICINA DE PRESUPUESTO',
    'INVENTARIO CONTABLE'
]

# =============================================================================
# OPERATION CODES - Operation type codes used in SICAL forms
# =============================================================================

OPERATION_CODES = {
    'ado220': '220',
    'pmp450': '450',  # TODO: Verify actual code for PMP450
}

# =============================================================================
# ADO220 FORM PATHS - UI element locators for ADO220 operation
# =============================================================================

ADO220_FORM_PATHS = {
    # Main panel elements
    'cod_operacion': 'class:"TComboBox" and path:"3|5|1"',
    'fecha': 'class:"TDBDateEdit" and path:"3|5|4|8"',
    'expediente': 'class:"TDBEdit" and path:"3|5|4|7"',
    'tercero': 'class:"TDBEdit" and path:"3|5|4|5"',
    'tesoreria_check': 'class:"TDBCheckBox" and name:"Tesorería" and path:"3|5|4|3"',

    # Payment form elements - Primary paths (may vary)
    'forma_pago_primary': 'class:"TDBEdit" and path:"3|5|4|9|3"',
    'forma_pago_alternate': 'class:"TDBEdit" and path:"3|5|5|9|3"',
    'tipo_pago_primary': 'class:"TDBEdit" and path:"3|5|4|9|2"',
    'tipo_pago_alternate': 'class:"TDBEdit" and path:"3|5|5|9|2"',
    'caja_primary': 'class:"TDBEdit" and path:"3|5|4|9|1"',
    'caja_alternate': 'class:"TDBEdit" and path:"3|5|5|9|1"',

    # Text and aplicaciones
    'texto': 'path:"3|1|1" and class:"TDBMemo"',
    'aplicaciones_grid': 'path:"3|2|1|1"',
    'new_line_button': 'class:"TBitBtn" and path:"3|3|3"',
    'confirm_line_button': 'class:"TBitBtn" and path:"3|3|5"',

    # Action buttons
    'nuevo_button': 'path:"2|2"',
    'validar_button': 'name:"Validar" and path:"2|5"',
    'salir_button': 'class:"TBitBtn" and name:"Salir"',
    'cerrar_button': 'name:"Cerrar"',

    # Result fields
    'num_operacion': 'class:"TEdit" and path:"3|5|3"',
    'total_operacion': 'class:"TCurrencyEdit" and path:"3|6|6"',
}

# =============================================================================
# PMP450 FORM PATHS - UI element locators for PMP450 operation
# TODO: These paths need to be configured when SICAL access is available
# =============================================================================

PMP450_FORM_PATHS = {
    # Main panel elements - TODO: Update with actual paths
    'cod_operacion': 'class:"TComboBox" and path:"3|5|1"',
    'fecha': 'class:"TDBDateEdit" and path:"3|5|4|8"',
    'expediente': 'class:"TDBEdit" and path:"3|5|4|7"',
    'tercero': 'class:"TDBEdit" and path:"3|5|4|5"',
    'tesoreria_check': 'class:"TDBCheckBox" and name:"Tesorería" and path:"3|5|4|3"',

    # Payment form elements
    'forma_pago_primary': 'class:"TDBEdit" and path:"3|5|4|9|3"',
    'forma_pago_alternate': 'class:"TDBEdit" and path:"3|5|5|9|3"',
    'tipo_pago_primary': 'class:"TDBEdit" and path:"3|5|4|9|2"',
    'tipo_pago_alternate': 'class:"TDBEdit" and path:"3|5|5|9|2"',
    'caja_primary': 'class:"TDBEdit" and path:"3|5|4|9|1"',
    'caja_alternate': 'class:"TDBEdit" and path:"3|5|5|9|1"',

    # Text and aplicaciones
    'texto': 'path:"3|1|1" and class:"TDBMemo"',
    'aplicaciones_grid': 'path:"3|2|1|1"',
    'new_line_button': 'class:"TBitBtn" and path:"3|3|3"',
    'confirm_line_button': 'class:"TBitBtn" and path:"3|3|5"',

    # Action buttons
    'nuevo_button': 'path:"2|2"',
    'validar_button': 'name:"Validar" and path:"2|5"',
    'salir_button': 'class:"TBitBtn" and name:"Salir"',
    'cerrar_button': 'name:"Cerrar"',

    # Result fields
    'num_operacion': 'class:"TEdit" and path:"3|5|3"',
    'total_operacion': 'class:"TCurrencyEdit" and path:"3|6|6"',
}

# =============================================================================
# CONSULTA OPERATION PATHS - UI element locators for consultation window
# =============================================================================

CONSULTA_FORM_PATHS = {
    'id_operacion': 'class:"TEdit" and path:"1|38"',
    'imprimir_button': 'class:"TBitBtn" and name:"Imprimir"',
    'estado_documento': 'class:"TEdit" and path:"1|3"',
    'filtros_button': 'class:"TBitBtn" and name:"Filtros"',
    'salir_button': 'class:"TBitBtn" and name:"Salir"',
}

# =============================================================================
# FILTROS OPERATION PATHS - UI element locators for filters window
# =============================================================================

FILTROS_FORM_PATHS = {
    'tercero': 'class:"TEdit" and path:"2|34"',
    'fecha_desde': 'control:"EditControl" and path:"2|29"',
    'fecha_hasta': 'control:"EditControl" and path:"2|18"',
    'funcional': 'class:"TEdit" and path:"2|39"',
    'economica': 'class:"TEdit" and path:"2|38"',
    'importe_desde': 'class:"TEdit" and path:"2|5"',
    'importe_hasta': 'class:"TEdit" and path:"2|4"',
    'caja': 'class:"Edit" and path:"2|16|1"',
    'consultar_button': 'class:"TBitBtn" and name:"Consultar"',
    'num_registros': 'class:"TEdit" and path:"1|1|2"',
    'cerrar_button': 'control:"ButtonControl" and name:"Cerrar"',
}

# =============================================================================
# TESORERIA PAGOS PATHS - UI element locators for payment ordering
# =============================================================================

TESORERIA_PAGOS_PATHS = {
    'fecha_orden': 'class:"TMaskEdit" and path:"2|1|1"',
    'ordenar_button': 'name:"Ordenar" and path:"2|7"',
    'option_num_operacion': 'name:"Nº Operación" and class:"TGroupButton"',
    'num_operacion_input': 'class:"TEdit" and path:"1|1|4"',
    'validar_op_button': 'class:"TBitBtn" and path:"1|1|1"',
    'validar_orden_button': 'class:"TBitBtn" and path:"2|1|3|12" and name:"Validar"',
    'check_mto_pago': 'class:"TCheckBox" and name:"Mandamientos de Pagos"',
    'validar_mto_button': 'class:"TBitBtn" and path:"1|1|9"',
    'pagar_button': 'class:"TBitBtn" and name:"Pagar" and path:"2|5"',
    'salir_impresion_button': 'class:"TBitBtn" and path:"1|1|10"',
    'salir_button': 'class:"TBitBtn" and name:"Salir" and path:"2|8"',
    'cancel_operation_button': 'class:"TBitBtn" and path:"1|1|2"',
}

# =============================================================================
# VISUAL DOCUMENTOS PATHS - UI element locators for document viewer
# =============================================================================

VISUAL_DOCUMENTOS_PATHS = {
    'imprimir_button': 'class:"TBitBtn" and path:"2|2|7"',
    'guardar_pdf_button': 'class:"TBitBtn" and path:"2|2|3"',
    'salir_button': 'class:"TBitBtn" and path:"2|2|6"',
}

# =============================================================================
# COMMON DIALOG PATHS - UI element locators for common dialogs
# =============================================================================

COMMON_DIALOG_PATHS = {
    'ok_button': 'class:"TButton" and name:"OK"',
    'yes_button': 'class:"TButton" and name:"Yes"',
    'no_button': 'class:"TButton" and name:"No"',
    'confirm_ok': 'name:"OK" and path:"2"',
    'confirm_yes': 'class:"TButton" and name:"Yes" and path:"2"',
    'confirm_yes_alt': 'class:"TButton" and name:"Yes" and path:"1|2"',
    'info_ok': 'class:"TButton" and name:"OK" and path:"1"',
    'info_ok_alt': 'class:"TButton" and name:"OK" and path:"1|1"',
    'print_accept': 'class:"Button" and name:"Aceptar" and path:"26"',
}

# =============================================================================
# TIMING CONSTANTS - Default wait times for UI interactions
# =============================================================================

DEFAULT_TIMING = {
    'short_wait': 0.1,
    'default_wait': 0.2,
    'medium_wait': 0.5,
    'long_wait': 1.0,
    'extra_long_wait': 2.0,
    'key_interval': 0.05,
    'slow_key_interval': 0.1,
}

# =============================================================================
# DATA DIRECTORIES - File system paths
# =============================================================================

import os
from pathlib import Path

ROBOT_DIR = Path(__file__).parent.absolute()
DATA_FOLDER_NAME = 'data'
DATA_DIR = os.path.join(ROBOT_DIR, DATA_FOLDER_NAME)
PENDING_DIR = os.path.join(DATA_DIR, 'pending')
PROCESSED_DIR = os.path.join(DATA_DIR, 'processed')
FAILED_DIR = os.path.join(DATA_DIR, 'z_failed')

# =============================================================================
# OPERATION STATUS MESSAGES - Standard messages for different operations
# =============================================================================

STATUS_MESSAGES = {
    'ado220': {
        'start': 'Starting ADO220 operation',
        'data_prepared': 'ADO220 data prepared',
        'window_opened': 'ADO220 window opened',
        'data_entered': 'Operation data entered',
        'validated': 'Operation validated',
        'printed': 'Operation document printed',
        'payment_ordered': 'Payment ordered',
        'completed': 'ADO220 operation completed',
        'failed': 'ADO220 operation failed',
    },
    'pmp450': {
        'start': 'Starting PMP450 operation',
        'data_prepared': 'PMP450 data prepared',
        'window_opened': 'PMP450 window opened',
        'data_entered': 'Operation data entered',
        'validated': 'Operation validated',
        'printed': 'Operation document printed',
        'payment_ordered': 'Payment ordered',
        'completed': 'PMP450 operation completed',
        'failed': 'PMP450 operation failed',
    },
}
