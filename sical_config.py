"""
SICAL Configuration - Account mappings and operation-specific configurations.

This module contains configuration data that may vary between deployments,
such as account code mappings and validation rules.
"""

from typing import Dict, Any

# =============================================================================
# ACCOUNT CODE MAPPINGS - Maps budget economica codes to accounting accounts
# =============================================================================

# Mapping from economica code to cuenta PGP (Plan General de Contabilidad)
PARTIDAS_GASTO_CUENTA_PGP: Dict[str, str] = {
    '224': '625',       # 920-224 PRIMAS DE SEGUROS
    '16205': '644',     # GASTOS SOCIALES. SEGUROS
    '311': '669',       # 932-311 COMISIONES BANCARIAS, GASTOS
    '241': '629',       # 241-629 GASTOS DIVERSOS, COMUNICACIONES Y OTROS GASTOS
    '467': '6501',      # 162-467 Transferencias a consorcios
    '20104': '561',     # FIANZA OBRAS
    '30012': '554',     # INGRESOS CTAS OP PEND APLICACION
    '30016': '554',     # INGRESOS AGENTES RECAUDADORES PEND APLICACION
}

# Default account code when no mapping is found
DEFAULT_CUENTA_PGP = '000'

# =============================================================================
# OPERATION TYPE CONFIGURATIONS
# =============================================================================

OPERATION_TYPE_CONFIG = {
    'ado220': {
        'name': 'ADO220',
        'description': 'Operación de Gasto ADO',
        'operation_code': '220',
        'requires_tesoreria': True,
        'can_finalize': True,
        'supports_duplicates_check': True,
    },
    'pmp450': {
        'name': 'PMP450',
        'description': 'Operación de Gasto PMP',
        'operation_code': '450',  # TODO: Verify actual code
        'requires_tesoreria': True,
        'can_finalize': True,
        'supports_duplicates_check': True,
    },
    'ordenarypagar': {
        'name': 'Ordenar y Pagar',
        'description': 'Proceso de Ordenación y Pago',
        'operation_code': None,
        'requires_tesoreria': False,
        'can_finalize': False,
        'supports_duplicates_check': False,
    },
}

# =============================================================================
# DEFAULT VALUES FOR OPERATIONS
# =============================================================================

DEFAULT_OPERATION_VALUES = {
    'expediente': 'rbt-apunte-ADO',
    'fpago': '10',  # Forma de pago
    'tpago': '10',  # Tipo de pago
    'texto': 'ADO....',
    'caja': '200',
}

# =============================================================================
# VALIDATION RULES
# =============================================================================

VALIDATION_RULES = {
    'tercero': {
        'min_length': 9,
        'max_length': 9,
        'pattern': r'^[A-Z][0-9]{8}$|^[0-9]{8}[A-Z]$',
    },
    'fecha': {
        'format': 'DDMMYYYY',
        'pattern': r'^\d{8}$',
    },
    'importe': {
        'min_value': 0.01,
        'max_decimals': 2,
    },
}

# =============================================================================
# FINALIZER FLAGS - Text suffixes that trigger automatic finalization
# =============================================================================

FINALIZE_SUFFIX = '_FIN'

# =============================================================================
# MESSAGE FORMAT CONFIGURATIONS
# =============================================================================

MESSAGE_FORMAT_CONFIG = {
    'v2': {
        'operation_type_field': 'tipo',
        'detail_field': 'detalle',
        'texto_field': 'texto_sical',
        'aplicaciones_field': 'aplicaciones',
    },
    'wrapped': {
        'wrapper_field': 'operation_data',
        'operation_field': 'operation',
    },
}

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

LOGGING_CONFIG = {
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    'date_format': '%Y-%m-%d %H:%M:%S',
    'max_log_entries': 1000,
    'log_rotation_size': 10 * 1024 * 1024,  # 10MB
}

# =============================================================================
# GUI CALLBACK EVENT NAMES
# =============================================================================

GUI_EVENTS = {
    'connected': 'connected',
    'disconnected': 'disconnected',
    'task_received': 'task_received',
    'task_started': 'task_started',
    'task_completed': 'task_completed',
    'task_failed': 'task_failed',
    'step': 'step',
}

# =============================================================================
# PHASE DESCRIPTIONS - Human-readable phase descriptions for tracking
# =============================================================================

PHASE_DESCRIPTIONS = {
    'data_creation': 'Created operation data',
    'duplicate_check': 'Checked for duplicate operations',
    'window_setup': 'Opened SICAL window',
    'data_entry': 'Entered operation data into form',
    'validation': 'Validated operation',
    'printing': 'Printed operation document',
    'payment_ordering': 'Ordered payment',
    'payment_completion': 'Completed payment process',
}
