# PMP450 Consumer Processing Guide

This guide describes how the SICAL Gastos Robot consumer correctly processes PMP450 (Operación de Gasto PMP) tasks received from producers.

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [Message Reception Flow](#message-reception-flow)
- [Input Validation](#input-validation)
- [Data Transformation](#data-transformation)
- [Processing Workflow](#processing-workflow)
- [Duplicate Detection](#duplicate-detection)
- [Error Handling](#error-handling)
- [Response Generation](#response-generation)
- [Configuration Requirements](#configuration-requirements)
- [Testing Guidelines](#testing-guidelines)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### Component Stack

```
RabbitMQ Queue (sical_queue.gasto)
        ↓
GastoTaskConsumer (gasto_task_consumer.py)
        ↓
PMP450Processor (processors/pmp450_processor.py)
        ↓
SICAL Application (UI Automation)
        ↓
OperationResult Response
```

### Key Components

| Component | File | Responsibility |
|-----------|------|----------------|
| **Consumer** | `gasto_task_consumer.py` | Receives messages from RabbitMQ, routes to processors |
| **Processor** | `processors/pmp450_processor.py` | Handles PMP450 workflow, data transformation |
| **Window Manager** | `sical_base.py` | Manages SICAL window lifecycle |
| **Config** | `sical_config.py` | Operation defaults, mappings, validation rules |
| **Constants** | `sical_constants.py` | Window paths, form element locators, timing |
| **Utils** | `sical_utils.py` | Date transformation, field extraction, error handling |
| **Security** | `sical_security.py` | Duplicate detection, token validation, rate limiting |

---

## Message Reception Flow

### 1. RabbitMQ Message Reception

**File:** `gasto_task_consumer.py`

The consumer receives messages from the RabbitMQ queue `sical_queue.gasto`:

```python
def on_message(self, channel, method, properties, body):
    """Callback for RabbitMQ message reception."""
    try:
        # Parse JSON message
        message = json.loads(body)

        # Extract operation data (supports v1 and v2 formats)
        operation_data = self._extract_operation_data(message)

        # Route to appropriate processor
        self._route_to_processor(operation_data, properties, method)

    except Exception as e:
        self.logger.error(f"Failed to process message: {e}")
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
```

### 2. Format Detection

The consumer supports **two message formats**:

#### Format v2 (Current - Recommended)

```json
{
  "task_id": "unique-task-id",
  "operation_data": {
    "tipo": "pmp450",
    "detalle": {
      "fecha": "17/09/2025",
      "tercero": "P4001500D",
      ...
    }
  },
  "reply_to": "response_queue_name"
}
```

#### Format v1 (Legacy - Auto-converted)

```json
{
  "task_id": "task-12345",
  "operation_data": {
    "operation": {
      "tipo": "pmp450",
      "fecha": "17092025",
      "tercero": "P4001500D",
      ...
    }
  }
}
```

### 3. Operation Type Routing

Based on the `tipo` field, the consumer routes to the appropriate processor:

```python
def _route_to_processor(self, operation_data, properties, method):
    """Route operation to appropriate processor."""
    tipo = operation_data.get('tipo', '').lower()

    processors = {
        'pmp450': PMP450Processor,
        'ado220': ADO220Processor,
        'ordenarypagar': self._handle_legacy_ordenar,
    }

    processor_class = processors.get(tipo)
    if not processor_class:
        raise ValueError(f"Unknown operation type: {tipo}")

    # Create processor instance and execute
    processor = processor_class(logger=self.logger, gui_callback=self.gui_callback)
    result = processor.execute(operation_data)

    # Publish response
    self._publish_response(result, properties)
```

---

## Input Validation

### Required Field Validation

**File:** `processors/pmp450_processor.py`

The processor validates all required fields before processing:

```python
def validate_input(self, operation_data: Dict[str, Any]) -> None:
    """Validate required fields in operation data."""
    required_fields = ['fecha', 'tercero', 'caja', 'texto_sical', 'aplicaciones']

    for field in required_fields:
        if field not in operation_data or operation_data[field] is None:
            raise ValueError(f"Missing required field: {field}")

    # Validate fecha format
    if not self._validate_date_format(operation_data['fecha']):
        raise ValueError(f"Invalid date format: {operation_data['fecha']}. Expected DD/MM/YYYY")

    # Validate tercero format
    if not self._validate_tercero(operation_data['tercero']):
        raise ValueError(f"Invalid tercero format: {operation_data['tercero']}. Must be 9 characters")

    # Validate aplicaciones
    if not operation_data['aplicaciones'] or len(operation_data['aplicaciones']) == 0:
        raise ValueError("At least one aplicación is required")

    # Validate each aplicación
    for i, aplicacion in enumerate(operation_data['aplicaciones']):
        self._validate_aplicacion(aplicacion, i)
```

### Field Format Validation

#### Date Validation

```python
def _validate_date_format(self, fecha: str) -> bool:
    """Validate date is in DD/MM/YYYY format."""
    import re
    pattern = r'^\d{2}/\d{2}/\d{4}$'
    if not re.match(pattern, fecha):
        return False

    # Additional validation: check if date is valid
    try:
        from datetime import datetime
        datetime.strptime(fecha, '%d/%m/%Y')
        return True
    except ValueError:
        return False
```

#### Tercero Validation

```python
def _validate_tercero(self, tercero: str) -> bool:
    """Validate tercero is exactly 9 characters."""
    if not tercero or len(tercero) != 9:
        return False

    # Pattern: Letter + 8 digits OR 8 digits + Letter
    import re
    pattern1 = r'^[A-Z][0-9]{8}$'
    pattern2 = r'^[0-9]{8}[A-Z]$'

    return bool(re.match(pattern1, tercero) or re.match(pattern2, tercero))
```

#### Aplicación Validation

```python
def _validate_aplicacion(self, aplicacion: Dict, index: int) -> None:
    """Validate aplicación fields."""
    required = ['year', 'funcional', 'economica', 'importe']

    for field in required:
        if field not in aplicacion or aplicacion[field] is None:
            raise ValueError(f"Aplicación {index}: Missing required field '{field}'")

    # Validate importe is a valid number
    try:
        importe = float(aplicacion['importe'])
        if importe <= 0:
            raise ValueError(f"Aplicación {index}: importe must be greater than 0")
    except (ValueError, TypeError):
        raise ValueError(f"Aplicación {index}: Invalid importe value")
```

---

## Data Transformation

### Main Operation Data Transformation

**File:** `processors/pmp450_processor.py:89`

The processor transforms v2 format data into SICAL-compatible format:

```python
def create_operation_data(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform operation data from v2 message format into SICAL-compatible format.

    Transformations:
    - fecha: DD/MM/YYYY → DDMMYYYY
    - texto_sical: array → string (extract texto_ado)
    - caja: "CODE_BANKNAME - NUMBER" → "CODE"
    - _FIN flag: detect and set finalizar_operacion
    - aplicaciones: transform to SICAL format
    """
    # Extract texto from texto_sical array
    texto_sical = operation_data.get('texto_sical', [])
    if texto_sical and len(texto_sical) > 0:
        texto_operacion = str(texto_sical[0].get('texto_ado', DEFAULT_OPERATION_VALUES['texto']))
    else:
        texto_operacion = DEFAULT_OPERATION_VALUES['texto']

    # Check for _FIN flag
    texto_operacion, finalizar_operacion = check_finalize_flag(texto_operacion)

    # Transform fecha: DD/MM/YYYY → DDMMYYYY
    fecha = transform_date_to_sical_format(operation_data.get('fecha', ''))

    # Extract caja code: "200_CAIXABNK - 2064" → "200"
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
        'duplicate_policy': operation_data.get('duplicate_policy', 'abort_on_duplicate'),
        'duplicate_confirmation_token': operation_data.get('duplicate_confirmation_token'),
        'duplicate_check_id': operation_data.get('duplicate_check_id'),
    }
```

### Aplicaciones Transformation

**File:** `processors/pmp450_processor.py:140`

Each aplicación is transformed with cuenta_pgp mapping:

```python
def _create_aplicaciones(self, aplicaciones_data: list) -> list:
    """
    Transform aplicaciones from v2 format to SICAL format.

    Key transformations:
    - proyecto → gfa (field rename)
    - economica → cuenta_pgp (auto-mapping if not provided)
    - All values converted to strings for UI entry
    """
    aplicaciones = []

    for aplicacion in aplicaciones_data:
        economica = str(aplicacion['economica'])

        # Prefer cuenta_pgp from message, fallback to mapping table
        if 'cuenta_pgp' in aplicacion and aplicacion['cuenta_pgp']:
            cuenta = str(aplicacion['cuenta_pgp'])
        else:
            # Auto-map based on economica code
            cuenta = PARTIDAS_GASTO_CUENTA_PGP.get(economica, DEFAULT_CUENTA_PGP)

        aplicaciones.append({
            'funcional': str(aplicacion['funcional']),
            'economica': economica,
            'gfa': aplicacion.get('proyecto'),  # proyecto → gfa
            'importe': str(aplicacion['importe']),
            'cuenta': cuenta,
            'year': str(aplicacion.get('year', '')),
            'contraido': bool(aplicacion.get('contraido', False)),
            'base_imponible': float(aplicacion.get('base_imponible', 0.0)),
            'tipo': float(aplicacion.get('tipo', 0.0)),
            'aux': str(aplicacion.get('aux', ''))
        })

    return aplicaciones
```

### Helper Functions

**File:** `sical_utils.py`

#### Date Transformation

```python
def transform_date_to_sical_format(fecha: str) -> str:
    """
    Transform date from DD/MM/YYYY to DDMMYYYY.

    Args:
        fecha: Date in DD/MM/YYYY format

    Returns:
        Date in DDMMYYYY format
    """
    if not fecha:
        return ''

    # If already in DDMMYYYY format (8 digits), return as-is
    if len(fecha) == 8 and fecha.isdigit():
        return fecha

    # Remove slashes: DD/MM/YYYY → DDMMYYYY
    return fecha.replace('/', '')
```

#### Caja Code Extraction

```python
def extract_caja_code(caja_raw: str) -> str:
    """
    Extract caja code from full format.

    Input: "200_CAIXABNK - 2064"
    Output: "200"

    Args:
        caja_raw: Full caja format

    Returns:
        Caja code only
    """
    if not caja_raw:
        return DEFAULT_OPERATION_VALUES['caja']

    # Extract code before underscore
    if '_' in caja_raw:
        return caja_raw.split('_')[0]

    # If no underscore, return as-is (already just the code)
    return caja_raw
```

#### Finalization Flag Check

```python
def check_finalize_flag(texto: str) -> tuple[str, bool]:
    """
    Check if texto contains _FIN flag and remove it.

    Args:
        texto: Operation text

    Returns:
        Tuple of (cleaned_texto, should_finalize)
    """
    if not texto:
        return '', False

    if texto.strip().endswith('_FIN'):
        # Remove _FIN suffix
        cleaned = texto.replace('_FIN', '').strip()
        return cleaned, True

    return texto, False
```

---

## Processing Workflow

### Complete Execution Flow

**File:** `processors/pmp450_processor.py` (inherits from `sical_base.py`)

```python
def execute(self, operation_data: Dict[str, Any]) -> OperationResult:
    """
    Execute complete PMP450 operation workflow.

    Phases:
    1. Data Creation - Transform and validate input
    2. Duplicate Check - Check for existing operations (if policy requires)
    3. Window Setup - Open SICAL PMP450 window
    4. Form Entry - Fill operation form and aplicaciones
    5. Validation - Validate and get operation number
    6. Printing - Print operation document
    7. Payment Ordering - Order and process payment (if _FIN flag)

    Returns:
        OperationResult with status, num_operacion, errors, etc.
    """
    result = OperationResult(
        status=OperationStatus.IN_PROGRESS,
        init_time=datetime.now().isoformat(),
    )

    try:
        # Phase 1: Create and validate operation data
        self._log_phase("Data Creation")
        validated_data = self.create_operation_data(operation_data)
        result.completed_phases.append({
            'phase': 'data_creation',
            'timestamp': datetime.now().isoformat()
        })

        # Phase 1.5: Duplicate check (if required by policy)
        duplicate_policy = validated_data.get('duplicate_policy', 'abort_on_duplicate')
        if duplicate_policy in ['abort_on_duplicate', 'check_only']:
            self._log_phase("Duplicate Check")
            duplicate_result = self.check_for_duplicates_pre_window(validated_data)

            if duplicate_result['found']:
                # Handle duplicate detection
                return self._handle_duplicate_found(duplicate_result, result, validated_data)

        elif duplicate_policy == 'force_create':
            # Validate security token
            self._validate_force_create_token(validated_data)

        # Phase 2: Setup SICAL window
        self._log_phase("Window Setup")
        self.window_manager.open_window(
            menu_path=SICAL_MENU_PATHS['pmp450']
        )
        result.sical_is_open = True
        result.completed_phases.append({
            'phase': 'window_setup',
            'timestamp': datetime.now().isoformat()
        })

        # Phase 3: Process operation form
        self._log_phase("Form Entry")
        self.process_operation_form(validated_data)
        result.completed_phases.append({
            'phase': 'form_entry',
            'timestamp': datetime.now().isoformat()
        })

        # Phase 4: Validate operation
        self._log_phase("Validation")
        num_operacion = self.validate_operation(validated_data)
        result.num_operacion = num_operacion
        result.completed_phases.append({
            'phase': 'validation',
            'timestamp': datetime.now().isoformat()
        })

        # Phase 5: Print document
        self._log_phase("Printing")
        self.print_operation_document()
        result.completed_phases.append({
            'phase': 'printing',
            'timestamp': datetime.now().isoformat()
        })

        # Phase 6: Order payment (if _FIN flag present)
        if validated_data.get('finalizar_operacion', False):
            self._log_phase("Payment Ordering")
            self.order_payment(validated_data)
            result.completed_phases.append({
                'phase': 'payment_ordering',
                'timestamp': datetime.now().isoformat()
            })

        # Success!
        result.status = OperationStatus.COMPLETED
        result.end_time = datetime.now().isoformat()

    except Exception as e:
        self.logger.error(f"PMP450 operation failed: {e}")
        result.status = OperationStatus.FAILED
        result.error = str(e)
        result.end_time = datetime.now().isoformat()

        # Cleanup SICAL windows
        handle_error_cleanup(self.window_manager)

    return result
```

### Phase Breakdown

#### Phase 1: Data Creation

- Validate all required fields
- Transform date format (DD/MM/YYYY → DDMMYYYY)
- Extract texto from texto_sical array
- Check for _FIN flag
- Extract caja code
- Transform aplicaciones with cuenta_pgp mapping

#### Phase 1.5: Duplicate Check

- Open Consulta (query) window
- Search for operations matching:
  - Same tercero
  - Same fecha (±7 days)
  - Similar importe
- If duplicates found:
  - `abort_on_duplicate`: Return P_DUPLICATED status immediately
  - `check_only`: Return P_DUPLICATED with confirmation token
  - `force_create`: Validate token and continue

#### Phase 2: Window Setup

- Open SICAL main window
- Navigate menu: GASTOS → OPERACIONES DE PRESUPUESTO CORRIENTE
- Wait for PMP450 operation window
- Click "Nuevo" button to start new operation

#### Phase 3: Form Entry

**Main Panel Fields:**
- Código de Operación: 450
- Fecha: DDMMYYYY
- Expediente
- Tercero
- Tesorería checkbox: ✓ (enabled)
- Forma de Pago
- Tipo de Pago
- Caja
- Caja Tercero (if provided)
- Texto: Operation description

**Aplicaciones Grid:**
For each aplicación:
- Click "Nueva Línea" button
- Fill fields:
  - Funcional
  - Económica
  - Proyecto/GFA
  - Importe
  - Cuenta PGP
  - Year
  - Contraído (checkbox)

#### Phase 4: Validation

- Click "Validar" button
- Wait for validation to complete
- Extract num_operacion from result field
- Check for validation errors
- Calculate total amounts

#### Phase 5: Printing

- Open document printing dialog
- Select operation document
- Print to default printer or PDF
- Close printing dialog

#### Phase 6: Payment Ordering (if _FIN)

- Navigate to Tesorería → Ordenar Pagos
- Search for operation by num_operacion
- Select operation
- Click "Ordenar" button
- Confirm payment ordering
- Close payment window

---

## Duplicate Detection

### Duplicate Check Implementation

**File:** `sical_base.py`

```python
def check_for_duplicates_pre_window(self, operation_data: Dict[str, Any]) -> Dict:
    """
    Check for duplicate operations BEFORE opening main operation window.

    Search criteria:
    - tercero: Exact match
    - fecha: ±7 days range
    - importe: Within 5% tolerance (optional)

    Returns:
        {
            'found': bool,
            'count': int,
            'details': List[Dict],
            'confirmation_token': str (if found),
            'search_criteria': Dict
        }
    """
    self.logger.info("Checking for duplicate operations...")

    # Open Consulta (query) window
    consulta_window = self._open_consulta_window()

    try:
        # Set search filters
        tercero = operation_data.get('tercero')
        fecha = operation_data.get('fecha')

        self._fill_consulta_filters({
            'tercero': tercero,
            'fecha_desde': self._calculate_date_range(fecha, -7),
            'fecha_hasta': self._calculate_date_range(fecha, +7),
            'tipo_operacion': '450',  # PMP450
        })

        # Execute search
        self._click_search_button()
        time.sleep(DEFAULT_TIMING['search_wait'])

        # Extract results
        duplicates = self._extract_search_results()

        if len(duplicates) > 0:
            # Generate confirmation token
            token = self._generate_confirmation_token(operation_data)

            return {
                'found': True,
                'count': len(duplicates),
                'details': duplicates,
                'confirmation_token': token,
                'token_expires_at': time.time() + (15 * 60),  # 15 minutes
                'search_criteria': {
                    'tercero': tercero,
                    'fecha': fecha,
                    'date_range': 7
                }
            }

        return {
            'found': False,
            'count': 0,
            'details': [],
            'search_criteria': {}
        }

    finally:
        # Close Consulta window
        consulta_window.close()
```

### Duplicate Policies

#### Policy: abort_on_duplicate

```python
if duplicate_policy == 'abort_on_duplicate':
    if duplicate_result['found']:
        # Abort immediately, return P_DUPLICATED status
        result.status = OperationStatus.P_DUPLICATED
        result.similiar_records_encountered = duplicate_result['count']
        result.duplicate_details = duplicate_result['details']
        result.duplicate_confirmation_token = duplicate_result['confirmation_token']
        result.duplicate_token_expires_at = duplicate_result['token_expires_at']
        result.end_time = datetime.now().isoformat()
        return result
```

#### Policy: check_only

```python
if duplicate_policy == 'check_only':
    if duplicate_result['found']:
        # Return duplicate info with token, DO NOT open SICAL window
        result.status = OperationStatus.P_DUPLICATED
        result.similiar_records_encountered = duplicate_result['count']
        result.duplicate_details = duplicate_result['details']
        result.duplicate_confirmation_token = duplicate_result['confirmation_token']
        result.duplicate_token_expires_at = duplicate_result['token_expires_at']
        result.duplicate_check_id = operation_data.get('duplicate_check_id')
        result.end_time = datetime.now().isoformat()
        return result
    else:
        # No duplicates found in check_only mode - still don't create
        result.status = OperationStatus.COMPLETED
        result.similiar_records_encountered = 0
        result.end_time = datetime.now().isoformat()
        return result
```

#### Policy: force_create

```python
if duplicate_policy == 'force_create':
    # Validate confirmation token
    token = operation_data.get('duplicate_confirmation_token')
    check_id = operation_data.get('duplicate_check_id')

    confirmation_manager = get_confirmation_manager()
    if not confirmation_manager.validate_token(token, check_id):
        raise ValueError("Invalid or expired confirmation token")

    # Check rate limits
    rate_limiter = get_rate_limiter()
    tercero = operation_data.get('tercero')
    if not rate_limiter.check_limit(tercero):
        raise ValueError(f"Rate limit exceeded for tercero {tercero}")

    # Log force create for audit
    audit_log_force_create(operation_data, token)

    # Continue with operation creation (bypass duplicate check)
```

---

## Error Handling

### Error Types and Handling

**File:** `processors/pmp450_processor.py`

#### Validation Errors

```python
try:
    self.validate_input(operation_data)
except ValueError as e:
    result.status = OperationStatus.FAILED
    result.error = f"Validation error: {e}"
    result.end_time = datetime.now().isoformat()
    return result
```

#### SICAL Window Errors

```python
try:
    self.window_manager.open_window(menu_path=SICAL_MENU_PATHS['pmp450'])
except Exception as e:
    result.status = OperationStatus.FAILED
    result.error = f"Failed to open SICAL window: {e}"
    result.sical_is_open = False
    result.end_time = datetime.now().isoformat()
    return result
```

#### Form Entry Errors

```python
try:
    self._fill_form_field('fecha', validated_data['fecha'])
except Exception as e:
    result.status = OperationStatus.FAILED
    result.error = f"Failed to fill fecha field: {e}"
    handle_error_cleanup(self.window_manager)
    return result
```

#### Validation Errors

```python
try:
    num_operacion = self.validate_operation(validated_data)
except Exception as e:
    result.status = OperationStatus.FAILED
    result.error = f"Operation validation failed: {e}"
    handle_error_cleanup(self.window_manager)
    return result
```

### Error Cleanup

**File:** `sical_utils.py`

```python
def handle_error_cleanup(window_manager: SicalWindowManager) -> None:
    """
    Clean up SICAL windows after an error.

    Args:
        window_manager: Window manager instance
    """
    try:
        # Close any open dialogs
        window_manager.close_error_dialogs()

        # Close main operation window
        window_manager.close_window()

        # Return to SICAL main window
        window_manager.return_to_main()

    except Exception as e:
        logging.error(f"Error during cleanup: {e}")
```

### Error Response Structure

```json
{
  "status": "FAILED",
  "init_time": "2025-01-13T10:30:00.123Z",
  "end_time": "2025-01-13T10:30:05.678Z",
  "duration": "0:00:05.555000",
  "error": "Validation error: Missing required field 'tercero'",
  "num_operacion": null,
  "total_operacion": null,
  "suma_aplicaciones": null,
  "sical_is_open": false,
  "completed_phases": [
    {"phase": "data_creation", "timestamp": "2025-01-13T10:30:01.000Z"}
  ],
  "similiar_records_encountered": 0,
  "duplicate_details": []
}
```

---

## Response Generation

### OperationResult Structure

**File:** `sical_base.py`

```python
@dataclass
class OperationResult:
    """Result of a SICAL operation execution."""

    # Status and timing
    status: OperationStatus
    init_time: str
    end_time: Optional[str] = None
    duration: Optional[str] = None

    # Operation details
    num_operacion: Optional[str] = None
    total_operacion: Optional[float] = None
    suma_aplicaciones: Optional[float] = None

    # Execution state
    sical_is_open: bool = False
    completed_phases: List[Dict] = field(default_factory=list)

    # Error information
    error: Optional[str] = None

    # Duplicate detection
    similiar_records_encountered: int = 0
    duplicate_details: List[Dict] = field(default_factory=list)
    duplicate_check_metadata: Dict = field(default_factory=dict)
    duplicate_confirmation_token: Optional[str] = None
    duplicate_token_expires_at: Optional[float] = None
    duplicate_check_id: Optional[str] = None
```

### Response Publishing

**File:** `gasto_task_consumer.py`

```python
def _publish_response(self, result: OperationResult, properties) -> None:
    """
    Publish operation result to reply_to queue.

    Args:
        result: OperationResult object
        properties: RabbitMQ message properties
    """
    if not properties.reply_to:
        self.logger.warning("No reply_to queue specified, skipping response")
        return

    try:
        # Convert OperationResult to JSON
        response_data = {
            'status': result.status.value,
            'init_time': result.init_time,
            'end_time': result.end_time,
            'duration': result.duration,
            'num_operacion': result.num_operacion,
            'total_operacion': result.total_operacion,
            'suma_aplicaciones': result.suma_aplicaciones,
            'sical_is_open': result.sical_is_open,
            'completed_phases': result.completed_phases,
            'error': result.error,
            'similiar_records_encountered': result.similiar_records_encountered,
            'duplicate_details': result.duplicate_details,
            'duplicate_check_metadata': result.duplicate_check_metadata,
            'duplicate_confirmation_token': result.duplicate_confirmation_token,
            'duplicate_token_expires_at': result.duplicate_token_expires_at,
            'duplicate_check_id': result.duplicate_check_id,
        }

        # Publish to reply_to queue
        self.channel.basic_publish(
            exchange='',
            routing_key=properties.reply_to,
            body=json.dumps(response_data),
            properties=pika.BasicProperties(
                correlation_id=properties.correlation_id,
                content_type='application/json'
            )
        )

        self.logger.info(f"Published response to {properties.reply_to}")

    except Exception as e:
        self.logger.error(f"Failed to publish response: {e}")
```

---

## Configuration Requirements

### sical_config.py

**Required configurations:**

```python
# Operation type configuration
OPERATION_TYPE_CONFIG = {
    'pmp450': {
        'name': 'PMP450',
        'description': 'Operación de Gasto PMP',
        'operation_code': '450',
        'requires_tesoreria': True,
        'can_finalize': True,
        'supports_duplicates_check': True,
    }
}

# Default values
DEFAULT_OPERATION_VALUES = {
    'expediente': 'rbt-apunte-ADO',
    'fpago': '10',
    'tpago': '10',
    'texto': 'ADO....',
    'caja': '200',
}

# Economic to PGP account mapping
PARTIDAS_GASTO_CUENTA_PGP: Dict[str, str] = {
    '224': '625',
    '16205': '644',
    '311': '669',
    '241': '629',
    '467': '6501',
    '20104': '561',
    '30012': '554',
    '30016': '554',
}

DEFAULT_CUENTA_PGP = '000'
```

### sical_constants.py

**Required constants:**

```python
# Window patterns
SICAL_WINDOWS = {
    'pmp450': 'regex:.*SICAL II 4.2 new30',
}

# Menu navigation paths
SICAL_MENU_PATHS = {
    'pmp450': ('GASTOS', 'OPERACIONES DE PRESUPUESTO CORRIENTE'),
}

# Operation codes
OPERATION_CODES = {
    'pmp450': '450',
}

# Form element paths (UI Automation selectors)
PMP450_FORM_PATHS = {
    'cod_operacion': 'class:"TComboBox" and path:"3|5|1"',
    'fecha': 'class:"TDBDateEdit" and path:"3|5|4|8"',
    'expediente': 'class:"TDBEdit" and path:"3|5|4|7"',
    'tercero': 'class:"TDBEdit" and path:"3|5|4|5"',
    'tesoreria_check': 'class:"TDBCheckBox" and name:"Tesorería" and path:"3|5|4|3"',
    'forma_pago_primary': 'class:"TDBEdit" and path:"3|5|4|9|3"',
    'tipo_pago_primary': 'class:"TDBEdit" and path:"3|5|4|9|2"',
    'caja_primary': 'class:"TDBEdit" and path:"3|5|4|9|1"',
    'texto': 'path:"3|1|1" and class:"TDBMemo"',
    'aplicaciones_grid': 'path:"3|2|1|1"',
    'new_line_button': 'class:"TBitBtn" and path:"3|3|3"',
    'nuevo_button': 'path:"2|3"',
    'validar_button': 'name:"Validar" and path:"2|5"',
    'num_operacion': 'class:"TEdit" and path:"3|5|3"',
}

# Timing configuration
DEFAULT_TIMING = {
    'window_open_wait': 2.0,
    'field_entry_delay': 0.5,
    'validation_wait': 3.0,
    'search_wait': 2.0,
    'print_wait': 2.0,
}
```

---

## Testing Guidelines

### Unit Testing

**Test file:** `tests/test_pmp450_processor.py`

```python
import pytest
from processors.pmp450_processor import PMP450Processor

class TestPMP450Processor:
    """Test PMP450 processor functionality."""

    def test_validate_input_success(self):
        """Test successful input validation."""
        processor = PMP450Processor(logger=mock_logger)

        valid_data = {
            'fecha': '17/09/2025',
            'tercero': 'P4001500D',
            'caja': '200_CAIXABNK - 2064',
            'texto_sical': [{'texto_ado': 'PAGO'}],
            'aplicaciones': [
                {
                    'year': '2025',
                    'funcional': '1234',
                    'economica': '220',
                    'importe': 150.00
                }
            ]
        }

        # Should not raise
        processor.validate_input(valid_data)

    def test_validate_input_missing_field(self):
        """Test validation with missing required field."""
        processor = PMP450Processor(logger=mock_logger)

        invalid_data = {
            'fecha': '17/09/2025',
            # Missing 'tercero'
            'caja': '200_CAIXABNK - 2064',
            'texto_sical': [{'texto_ado': 'PAGO'}],
            'aplicaciones': []
        }

        with pytest.raises(ValueError, match="Missing required field: tercero"):
            processor.validate_input(invalid_data)

    def test_create_operation_data_transformation(self):
        """Test data transformation from v2 to SICAL format."""
        processor = PMP450Processor(logger=mock_logger)

        input_data = {
            'fecha': '17/09/2025',
            'tercero': 'P4001500D',
            'caja': '200_CAIXABNK - 2064',
            'texto_sical': [{'texto_ado': 'PAGO PROVEEDOR _FIN'}],
            'aplicaciones': [
                {
                    'year': '2025',
                    'funcional': '1234',
                    'economica': '220',
                    'proyecto': 'GFA-001',
                    'importe': 150.00
                }
            ]
        }

        result = processor.create_operation_data(input_data)

        assert result['fecha'] == '17092025'  # Transformed
        assert result['caja'] == '200'  # Extracted
        assert result['texto'] == 'PAGO PROVEEDOR'  # _FIN removed
        assert result['finalizar_operacion'] is True  # _FIN detected
        assert len(result['aplicaciones']) == 1
        assert result['aplicaciones'][0]['gfa'] == 'GFA-001'
```

### Integration Testing

```python
class TestPMP450Integration:
    """Integration tests for PMP450 workflow."""

    @pytest.mark.integration
    def test_complete_workflow_success(self):
        """Test complete PMP450 workflow end-to-end."""
        processor = PMP450Processor(logger=logger, gui_callback=None)

        operation_data = {
            'tipo': 'pmp450',
            'detalle': {
                'fecha': '17/09/2025',
                'tercero': 'P4001500D',
                'caja': '200_CAIXABNK - 2064',
                'texto_sical': [{'texto_ado': 'TEST OPERATION'}],
                'aplicaciones': [
                    {
                        'year': '2025',
                        'funcional': '1234',
                        'economica': '220',
                        'importe': 100.00,
                        'cuenta_pgp': '629'
                    }
                ]
            }
        }

        result = processor.execute(operation_data)

        assert result.status == OperationStatus.COMPLETED
        assert result.num_operacion is not None
        assert result.error is None
        assert 'validation' in [p['phase'] for p in result.completed_phases]
```

### Manual Testing Checklist

- [ ] Valid message with single aplicación
- [ ] Valid message with multiple aplicaciones
- [ ] Message with _FIN flag (auto-finalize)
- [ ] Message missing required field (should fail)
- [ ] Message with invalid date format (should fail)
- [ ] Message with invalid tercero (should fail)
- [ ] Duplicate detection (abort_on_duplicate)
- [ ] Duplicate detection (check_only)
- [ ] Force create with valid token
- [ ] Force create with expired token (should fail)
- [ ] Force create exceeding rate limit (should fail)
- [ ] Auto-mapping of cuenta_pgp
- [ ] Explicit cuenta_pgp override

---

## Troubleshooting

### Common Issues

#### Issue: "Failed to open SICAL window"

**Cause:** SICAL application not running or window pattern incorrect

**Solution:**
1. Check SICAL is running
2. Verify window pattern in `sical_constants.py:SICAL_WINDOWS['pmp450']`
3. Update pattern if SICAL version changed

#### Issue: "Element not found: fecha"

**Cause:** Form element path incorrect or window structure changed

**Solution:**
1. Use UI Automation inspector to find correct path
2. Update path in `sical_constants.py:PMP450_FORM_PATHS['fecha']`
3. Test with fallback paths in `sical_utils.py:find_element_with_fallback()`

#### Issue: "Validation failed: Missing required field 'funcional'"

**Cause:** Producer sending incomplete aplicación data

**Solution:**
1. Check producer message format
2. Ensure all required aplicación fields present
3. Refer producer to `PMP_TASK_FORMAT_GUIDE.md`

#### Issue: "Duplicate confirmation token expired"

**Cause:** Token expired (15 minute TTL) before force_create

**Solution:**
1. Producer should retry with new check_only operation
2. Get fresh token before force_create
3. Consider increasing token TTL in `sical_security.py` if needed

#### Issue: "Rate limit exceeded for force_create"

**Cause:** Too many force_create operations for same tercero

**Solution:**
1. Check rate limits: 15/hour, 30/day per tercero
2. Use `abort_on_duplicate` policy instead
3. Review if operations are truly necessary

### Logging and Debugging

**Enable debug logging:**

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

**Key log points:**

```python
# Phase transitions
self.logger.info("Phase: Data Creation")
self.logger.debug(f"Transformed data: {validated_data}")

# Duplicate detection
self.logger.info(f"Duplicate check found {count} similar records")
self.logger.debug(f"Duplicate details: {duplicate_details}")

# Form entry
self.logger.debug(f"Filling field 'fecha' with value '{fecha}'")

# Validation
self.logger.info(f"Operation validated: {num_operacion}")

# Errors
self.logger.error(f"Failed to fill field: {e}", exc_info=True)
```

### Performance Monitoring

**Track operation duration:**

```python
result.init_time = datetime.now().isoformat()
# ... processing ...
result.end_time = datetime.now().isoformat()
result.duration = str(datetime.fromisoformat(result.end_time) -
                      datetime.fromisoformat(result.init_time))
```

**Expected durations:**
- Data creation: < 1 second
- Duplicate check: 3-5 seconds
- Window setup: 2-4 seconds
- Form entry: 5-10 seconds (single aplicación)
- Form entry: 10-30 seconds (multiple aplicaciones)
- Validation: 3-5 seconds
- Printing: 2-4 seconds
- Payment ordering: 10-15 seconds

**Total expected duration:**
- Without _FIN: 30-60 seconds
- With _FIN: 60-120 seconds

---

## Best Practices

### 1. Always Validate Early

Validate all input data before opening SICAL windows to avoid wasting resources:

```python
# ✅ Good: Validate before window operations
self.validate_input(operation_data)
validated_data = self.create_operation_data(operation_data)
self.window_manager.open_window(...)

# ❌ Bad: Open window before validation
self.window_manager.open_window(...)
self.validate_input(operation_data)  # Too late!
```

### 2. Use Phase Tracking

Track completed phases for debugging and resumability:

```python
result.completed_phases.append({
    'phase': 'validation',
    'timestamp': datetime.now().isoformat(),
    'details': {'num_operacion': num_operacion}
})
```

### 3. Implement Proper Cleanup

Always clean up SICAL windows on errors:

```python
try:
    # Processing...
except Exception as e:
    handle_error_cleanup(self.window_manager)
    raise
```

### 4. Log Extensively

Log all important operations for debugging:

```python
self.logger.info(f"Processing PMP450 operation for tercero {tercero}")
self.logger.debug(f"Filling {len(aplicaciones)} aplicaciones")
self.logger.error(f"Validation failed: {e}", exc_info=True)
```

### 5. Handle Timeouts Gracefully

Use appropriate timeouts for all operations:

```python
time.sleep(DEFAULT_TIMING['validation_wait'])
window.wait_until_visible(timeout=DEFAULT_TIMING['window_open_wait'])
```

### 6. Respect Rate Limits

Enforce rate limits for force_create operations:

```python
rate_limiter = get_rate_limiter()
if not rate_limiter.check_limit(tercero):
    raise ValueError("Rate limit exceeded")
```

### 7. Generate Meaningful Error Messages

Provide actionable error messages:

```python
# ✅ Good
raise ValueError(f"Invalid fecha format: '{fecha}'. Expected DD/MM/YYYY")

# ❌ Bad
raise ValueError("Invalid date")
```

---

## Reference Files

### Core Implementation Files

- `gasto_task_consumer.py` - Main consumer entry point
- `processors/pmp450_processor.py` - PMP450 workflow implementation
- `sical_base.py` - Base processor and window manager
- `sical_config.py` - Configuration and defaults
- `sical_constants.py` - Window paths and element locators
- `sical_utils.py` - Helper functions
- `sical_security.py` - Security and duplicate handling

### Documentation Files

- `PMP_TASK_FORMAT_GUIDE.md` - Producer message format guide
- `PRODUCER_INTEGRATION_GUIDE.md` - Duplicate handling and security
- `legacy/MESSAGE_FORMAT_MIGRATION.md` - Format specifications
- `REFACTORING_GUIDE.md` - Architecture overview

---

**Document Version:** 1.0
**Last Updated:** 2025-01-28
**Target Version:** SICAL Gastos Robot v2.0
