# PMP450 Task Format Guide for Producers

This guide describes the correct format for generating PMP450 (Operación de Gasto PMP) tasks that can be consumed by the SICAL Gastos Robot.

## Table of Contents
- [Message Structure](#message-structure)
- [Field Definitions](#field-definitions)
- [Aplicaciones (Line Items)](#aplicaciones-line-items)
- [Special Features](#special-features)
- [Duplicate Handling](#duplicate-handling)
- [Complete Examples](#complete-examples)
- [Validation Rules](#validation-rules)

---

## Message Structure

### Basic Format (v2)

All PMP450 tasks must use the following JSON structure:

```json
{
  "tipo": "pmp450",
  "detalle": {
    "fecha": "DD/MM/YYYY",
    "tercero": "STRING(9)",
    "caja": "CODE_BANKNAME - NUMBER",
    "caja_tercero": "STRING",
    "expediente": "STRING",
    "fpago": "STRING",
    "tpago": "STRING",
    "texto_sical": [
      {
        "texto_ado": "STRING"
      }
    ],
    "aplicaciones": [],
    "descuentos": [],
    "aux_data": {},
    "metadata": {}
  }
}
```

### Message Wrapper (Optional)

If your system uses RabbitMQ with reply-to semantics, wrap the message:

```json
{
  "task_id": "unique-task-identifier",
  "operation_data": {
    "tipo": "pmp450",
    "detalle": { ... }
  },
  "reply_to": "your_response_queue_name"
}
```

---

## Field Definitions

### Root Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tipo` | String | **Yes** | Must be `"pmp450"` for PMP450 operations |
| `detalle` | Object | **Yes** | Contains all operation details |

### Detalle Object Fields

| Field | Type | Required | Default | Description | Example |
|-------|------|----------|---------|-------------|---------|
| `fecha` | String | **Yes** | - | Operation date in DD/MM/YYYY format | `"17/09/2025"` |
| `tercero` | String | **Yes** | - | Third party ID (9 characters) | `"P4001500D"` |
| `caja` | String | **Yes** | - | Cash register with bank name | `"200_CAIXABNK - 2064"` |
| `caja_tercero` | String | No | `null` | Third party cash register | `"001"` |
| `expediente` | String | No | `"rbt-apunte-ADO"` | Expense file reference | `"EXP-2025-001"` |
| `fpago` | String | No | `"10"` | Payment form code | `"10"` |
| `tpago` | String | No | `"10"` | Payment type code | `"10"` |
| `texto_sical` | Array | **Yes** | - | Operation description array | See below |
| `aplicaciones` | Array | **Yes** | - | Budget line items (must have at least one) | See below |
| `descuentos` | Array | No | `[]` | Discounts array (currently unused) | `[]` |
| `aux_data` | Object | No | `{}` | Auxiliary data for custom fields | `{}` |
| `metadata` | Object | No | `{}` | Operation metadata | See below |
| `duplicate_policy` | String | No | `"abort_on_duplicate"` | Duplicate handling policy | See [Duplicate Handling](#duplicate-handling) |
| `duplicate_confirmation_token` | String | Conditional | - | Token for force_create policy | From Phase 1 response |
| `duplicate_check_id` | String | Conditional | - | Check ID for tracking | `"CHECK-20250117-001"` |

### texto_sical Array

Array with one object containing the operation description:

```json
"texto_sical": [
  {
    "texto_ado": "PAGO A PROVEEDOR"
  }
]
```

**Special Flag:** Add `_FIN` suffix to automatically finalize and order payment:

```json
"texto_sical": [
  {
    "texto_ado": "PAGO A PROVEEDOR _FIN"
  }
]
```

### metadata Object (Optional)

```json
"metadata": {
  "generation_datetime": "2025-01-13T10:30:00.000Z",
  "source_system": "your-system-name",
  "user_id": "user@example.com"
}
```

---

## Aplicaciones (Line Items)

Each PMP450 operation must have **at least one** aplicación (budget line item).

### Aplicación Object Structure

```json
{
  "year": "2025",
  "funcional": "1234",
  "economica": "220",
  "proyecto": "GFA-001",
  "contraido": false,
  "base_imponible": 0.0,
  "tipo": 0.0,
  "importe": 150.00,
  "cuenta_pgp": "629",
  "aux": ""
}
```

### Aplicación Field Definitions

| Field | Type | Required | Default | Description | Example |
|-------|------|----------|---------|-------------|---------|
| `year` | String | **Yes** | - | Budget year | `"2025"` |
| `funcional` | String | **Yes** | - | Functional classification code | `"1234"` |
| `economica` | String | **Yes** | - | Economic budget code | `"220"`, `"224"`, `"311"` |
| `proyecto` | String | No | `null` | Project or GFA code | `"GFA-001"` |
| `contraido` | Boolean | No | `false` | Whether amount is contracted | `true` or `false` |
| `base_imponible` | Float | No | `0.0` | Taxable base amount | `130.43` |
| `tipo` | Float | No | `0.0` | Tax percentage | `21.0` |
| `importe` | Float | **Yes** | - | Line item total amount | `150.00` |
| `cuenta_pgp` | String | No | Auto-mapped | PGP account code | `"629"`, `"625"` |
| `aux` | String | No | `""` | Auxiliary information | Any string |

### cuenta_pgp Auto-Mapping

If `cuenta_pgp` is not provided, it's automatically mapped based on `economica`:

| economica | cuenta_pgp | Description |
|-----------|------------|-------------|
| `"224"` | `"625"` | Primas de seguros |
| `"16205"` | `"644"` | Gastos sociales seguros |
| `"311"` | `"669"` | Comisiones bancarias |
| `"241"` | `"629"` | Gastos diversos |
| `"467"` | `"6501"` | Transferencias a consorcios |
| `"20104"` | `"561"` | Fianza obras |
| `"30012"` | `"554"` | Ingresos ctas op pend aplicación |
| `"30016"` | `"554"` | Ingresos agentes recaudadores |
| Other | `"000"` | Default account |

**Recommendation:** Always provide `cuenta_pgp` explicitly to avoid mapping issues.

---

## Special Features

### 1. Automatic Finalization (_FIN Flag)

Add `_FIN` to the `texto_ado` field to automatically:
1. Create the operation
2. Validate the operation
3. Print the operation document
4. Order payment
5. Complete payment process

```json
"texto_sical": [
  {
    "texto_ado": "PAGO A PROVEEDOR XYZ _FIN"
  }
]
```

**Without _FIN:** Operation is created and validated only. Payment ordering must be done manually.

### 2. Caja (Cash Register) Format

The `caja` field must include the bank name and account number:

**Correct format:**
```json
"caja": "200_CAIXABNK - 2064"
```

**Format pattern:** `CODE_BANKNAME - NUMBER`
- `CODE`: Cash register code (e.g., "200")
- `BANKNAME`: Bank identifier (e.g., "CAIXABNK")
- `NUMBER`: Account number (e.g., "2064")

### 3. Tercero (Third Party) Validation

The `tercero` field must be exactly 9 characters and follow one of these patterns:
- Letter followed by 8 digits: `P40015001` → becomes `P4001500D` (with check digit)
- 8 digits followed by letter: `40015001P`

**Valid examples:**
- `"P4001500D"`
- `"A1234567B"`
- `"12345678Z"`

---

## Duplicate Handling

PMP450 supports three duplicate handling policies to prevent accidental duplicate operations.

### Policy 1: abort_on_duplicate (Default - Recommended)

**Use case:** Production systems requiring maximum safety

```json
{
  "tipo": "pmp450",
  "detalle": {
    "fecha": "17/09/2025",
    "tercero": "P4001500D",
    "caja": "200_CAIXABNK - 2064",
    "duplicate_policy": "abort_on_duplicate",
    ...
  }
}
```

**Behavior:**
- Checks for duplicates BEFORE opening SICAL window
- If duplicates found: Returns `P_DUPLICATED` status with duplicate details
- If no duplicates: Proceeds with operation creation
- **Most secure option**

**Response on duplicate:**
```json
{
  "status": "P_DUPLICATED",
  "similiar_records_encountered": 2,
  "duplicate_details": [
    {
      "num_operacion": "2025000123",
      "fecha": "17/09/2025",
      "tercero": "P4001500D",
      "importe": 150.00
    }
  ],
  "duplicate_confirmation_token": "TOKEN_abc123...",
  "duplicate_token_expires_at": 1737198765.5
}
```

### Policy 2: check_only (Two-Phase Approach)

**Use case:** User review workflow before creating operation

#### Phase 1: Check for Duplicates

```json
{
  "tipo": "pmp450",
  "detalle": {
    "fecha": "17/09/2025",
    "tercero": "P4001500D",
    "caja": "200_CAIXABNK - 2064",
    "duplicate_policy": "check_only",
    "duplicate_check_id": "CHECK-20250117-001",
    ...
  }
}
```

**Behavior:**
- Checks for duplicates without opening SICAL
- Does NOT create operation
- Returns confirmation token if duplicates found
- User can review duplicates before proceeding

**Response:**
```json
{
  "status": "P_DUPLICATED",
  "similiar_records_encountered": 1,
  "duplicate_details": [...],
  "duplicate_confirmation_token": "TOKEN_xyz789...",
  "duplicate_token_expires_at": 1737198765.5,
  "duplicate_check_id": "CHECK-20250117-001"
}
```

#### Phase 2: Force Create (If User Confirms)

```json
{
  "tipo": "pmp450",
  "detalle": {
    "fecha": "17/09/2025",
    "tercero": "P4001500D",
    "caja": "200_CAIXABNK - 2064",
    "duplicate_policy": "force_create",
    "duplicate_confirmation_token": "TOKEN_xyz789...",
    "duplicate_check_id": "CHECK-20250117-001",
    ...
  }
}
```

**Requirements:**
- Must include valid `duplicate_confirmation_token` from Phase 1
- Token must not be expired (15 minute expiration)
- Must include same `duplicate_check_id` from Phase 1

**Rate Limits:**
- 15 operations per hour
- 30 operations per day per tercero

**Security:**
- Full audit trail logged
- Token single-use only
- Expired tokens rejected

---

## Complete Examples

### Example 1: Simple PMP450 Operation (No Finalization)

```json
{
  "tipo": "pmp450",
  "detalle": {
    "fecha": "17/09/2025",
    "tercero": "P4001500D",
    "caja": "200_CAIXABNK - 2064",
    "caja_tercero": "001",
    "expediente": "EXP-2025-001",
    "fpago": "10",
    "tpago": "10",
    "texto_sical": [
      {
        "texto_ado": "PAGO FACTURA 2025-001 PROVEEDOR ABC"
      }
    ],
    "aplicaciones": [
      {
        "year": "2025",
        "funcional": "1234",
        "economica": "220",
        "proyecto": "GFA-001",
        "contraido": false,
        "base_imponible": 123.97,
        "tipo": 21.0,
        "importe": 150.00,
        "cuenta_pgp": "629",
        "aux": ""
      }
    ],
    "descuentos": [],
    "aux_data": {},
    "metadata": {
      "generation_datetime": "2025-01-13T10:30:00.000Z",
      "source_system": "invoice-processor"
    }
  }
}
```

### Example 2: PMP450 with Multiple Line Items and Auto-Finalization

```json
{
  "tipo": "pmp450",
  "detalle": {
    "fecha": "20/09/2025",
    "tercero": "A9876543B",
    "caja": "200_CAIXABNK - 2064",
    "expediente": "EXP-2025-042",
    "fpago": "10",
    "tpago": "10",
    "texto_sical": [
      {
        "texto_ado": "PAGO MULTIPLE PARTIDAS PRESUPUESTARIAS _FIN"
      }
    ],
    "aplicaciones": [
      {
        "year": "2025",
        "funcional": "1234",
        "economica": "220",
        "proyecto": "GFA-001",
        "importe": 500.00,
        "cuenta_pgp": "629"
      },
      {
        "year": "2025",
        "funcional": "5678",
        "economica": "224",
        "proyecto": "GFA-002",
        "importe": 300.00,
        "cuenta_pgp": "625"
      },
      {
        "year": "2025",
        "funcional": "9012",
        "economica": "311",
        "importe": 50.00,
        "cuenta_pgp": "669"
      }
    ],
    "duplicate_policy": "abort_on_duplicate",
    "metadata": {
      "generation_datetime": "2025-01-20T14:22:00.000Z",
      "total_amount": 850.00
    }
  }
}
```

### Example 3: With Duplicate Check (Two-Phase)

#### Phase 1: Check Only

```json
{
  "tipo": "pmp450",
  "detalle": {
    "fecha": "17/09/2025",
    "tercero": "P4001500D",
    "caja": "200_CAIXABNK - 2064",
    "expediente": "EXP-2025-100",
    "fpago": "10",
    "tpago": "10",
    "texto_sical": [
      {
        "texto_ado": "PAGO SERVICIO MENSUAL OCTUBRE"
      }
    ],
    "aplicaciones": [
      {
        "year": "2025",
        "funcional": "2000",
        "economica": "241",
        "importe": 1200.00,
        "cuenta_pgp": "629"
      }
    ],
    "duplicate_policy": "check_only",
    "duplicate_check_id": "CHECK-20250917-UUID-12345"
  }
}
```

#### Phase 2: Force Create (After User Review)

```json
{
  "tipo": "pmp450",
  "detalle": {
    "fecha": "17/09/2025",
    "tercero": "P4001500D",
    "caja": "200_CAIXABNK - 2064",
    "expediente": "EXP-2025-100",
    "fpago": "10",
    "tpago": "10",
    "texto_sical": [
      {
        "texto_ado": "PAGO SERVICIO MENSUAL OCTUBRE"
      }
    ],
    "aplicaciones": [
      {
        "year": "2025",
        "funcional": "2000",
        "economica": "241",
        "importe": 1200.00,
        "cuenta_pgp": "629"
      }
    ],
    "duplicate_policy": "force_create",
    "duplicate_confirmation_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "duplicate_check_id": "CHECK-20250917-UUID-12345"
  }
}
```

---

## Validation Rules

### Required Field Validation

The consumer will reject messages missing required fields:

✅ **Must have:**
- `tipo` = `"pmp450"`
- `detalle.fecha` (DD/MM/YYYY format)
- `detalle.tercero` (9 characters)
- `detalle.caja` (CODE_BANKNAME - NUMBER format)
- `detalle.texto_sical` (array with at least one object)
- `detalle.aplicaciones` (array with at least one object)

Each aplicación must have:
- `year`
- `funcional`
- `economica`
- `importe`

### Date Format Validation

**Accepted:** `DD/MM/YYYY`
- ✅ `"17/09/2025"`
- ✅ `"01/01/2025"`
- ❌ `"2025-09-17"` (ISO format not accepted)
- ❌ `"17092025"` (No separators - legacy format, auto-converted)

### Amount Format Validation

Amounts must be valid numbers:
- ✅ `150.00` (Float)
- ✅ `150` (Integer)
- ✅ `"150.00"` (String - auto-converted)
- ❌ `"150,00"` (Comma decimal separator)

### Tercero Format Validation

Must be exactly 9 characters matching pattern:
- Letter + 8 digits: `^[A-Z][0-9]{8}$`
- 8 digits + Letter: `^[0-9]{8}[A-Z]$`

Examples:
- ✅ `"P4001500D"`
- ✅ `"A1234567B"`
- ❌ `"P400150"` (Too short)
- ❌ `"P40015000"` (Wrong pattern)

---

## Operation Result Response

After processing, the consumer publishes an `OperationResult` to the `reply_to` queue (if specified):

### Success Response

```json
{
  "status": "COMPLETED",
  "init_time": "2025-01-13T10:30:00.123Z",
  "end_time": "2025-01-13T10:32:45.678Z",
  "duration": "0:02:45.555000",
  "num_operacion": "2025000456",
  "total_operacion": 150.00,
  "suma_aplicaciones": 150.00,
  "sical_is_open": true,
  "completed_phases": [
    {"phase": "data_creation", "timestamp": "..."},
    {"phase": "duplicate_check", "timestamp": "..."},
    {"phase": "window_setup", "timestamp": "..."},
    {"phase": "form_entry", "timestamp": "..."},
    {"phase": "validation", "timestamp": "..."},
    {"phase": "printing", "timestamp": "..."},
    {"phase": "payment_ordering", "timestamp": "..."}
  ],
  "similiar_records_encountered": 0,
  "duplicate_details": [],
  "error": null
}
```

### Failure Response

```json
{
  "status": "FAILED",
  "init_time": "2025-01-13T10:30:00.123Z",
  "end_time": "2025-01-13T10:31:15.678Z",
  "duration": "0:01:15.555000",
  "error": "Failed to validate operation: Missing required field 'funcional'",
  "num_operacion": null,
  "total_operacion": null,
  "sical_is_open": false,
  "completed_phases": [
    {"phase": "data_creation", "timestamp": "..."}
  ]
}
```

### Duplicate Detected Response

```json
{
  "status": "P_DUPLICATED",
  "init_time": "2025-01-13T10:30:00.123Z",
  "end_time": "2025-01-13T10:30:05.678Z",
  "duration": "0:00:05.555000",
  "similiar_records_encountered": 2,
  "duplicate_details": [
    {
      "num_operacion": "2025000123",
      "fecha": "17/09/2025",
      "tercero": "P4001500D",
      "importe": 150.00,
      "expediente": "EXP-2025-001"
    },
    {
      "num_operacion": "2025000124",
      "fecha": "17/09/2025",
      "tercero": "P4001500D",
      "importe": 150.00,
      "expediente": "EXP-2025-002"
    }
  ],
  "duplicate_confirmation_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "duplicate_token_expires_at": 1737198765.5,
  "duplicate_check_metadata": {
    "search_criteria": {
      "tercero": "P4001500D",
      "fecha": "17/09/2025"
    },
    "search_date_range": 7,
    "policy": "abort_on_duplicate"
  },
  "sical_is_open": false,
  "error": null
}
```

### Status Values

| Status | Description |
|--------|-------------|
| `PENDING` | Task queued, not yet processed |
| `IN_PROGRESS` | Task currently being processed |
| `COMPLETED` | Task completed successfully |
| `INCOMPLETED` | Task partially completed (rare) |
| `P_DUPLICATED` | Possible duplicate detected |
| `FAILED` | Task failed with error |

---

## Best Practices

### 1. Always Include Metadata

Add generation metadata for debugging and auditing:

```json
"metadata": {
  "generation_datetime": "2025-01-13T10:30:00.000Z",
  "source_system": "your-app-name",
  "user_id": "user@example.com",
  "invoice_number": "INV-2025-001"
}
```

### 2. Use Explicit cuenta_pgp

Don't rely on auto-mapping. Always specify:

```json
{
  "economica": "220",
  "cuenta_pgp": "629"  // Explicit mapping
}
```

### 3. Use abort_on_duplicate in Production

For production systems, always use the safest policy:

```json
"duplicate_policy": "abort_on_duplicate"
```

### 4. Validate Data Before Sending

Check your data before submitting:
- ✅ Date format is DD/MM/YYYY
- ✅ Tercero is exactly 9 characters
- ✅ Caja includes bank name and number
- ✅ At least one aplicación exists
- ✅ All amounts are valid numbers
- ✅ All required fields are present

### 5. Handle Duplicate Responses

Always handle `P_DUPLICATED` status:

```python
if result['status'] == 'P_DUPLICATED':
    # Show duplicates to user
    duplicates = result['duplicate_details']

    # Let user decide:
    # - Cancel operation
    # - Force create with token
```

### 6. Use _FIN Flag Carefully

Only use `_FIN` when you want immediate payment:
- ✅ Regular monthly payments
- ✅ Automated recurring operations
- ❌ Operations requiring manual review
- ❌ High-value operations needing approval

### 7. Set Appropriate Timeouts

PMP450 operations can take time:
- Typical operation: 30-90 seconds
- With _FIN flag: 2-4 minutes
- Set RabbitMQ timeout accordingly (5 minutes recommended)

---

## Troubleshooting

### Common Errors

**Error:** `"Missing required field 'tercero'"`
- **Solution:** Ensure `detalle.tercero` is present and exactly 9 characters

**Error:** `"Invalid date format"`
- **Solution:** Use DD/MM/YYYY format, not YYYY-MM-DD or DDMMYYYY

**Error:** `"No aplicaciones provided"`
- **Solution:** Include at least one item in `detalle.aplicaciones` array

**Error:** `"Invalid caja format"`
- **Solution:** Use format `CODE_BANKNAME - NUMBER`, e.g., `"200_CAIXABNK - 2064"`

**Error:** `"Duplicate confirmation token expired"`
- **Solution:** Tokens expire after 15 minutes. Request new check_only operation

**Error:** `"Rate limit exceeded for force_create"`
- **Solution:** Respect rate limits (15/hour, 30/day). Use abort_on_duplicate policy instead

---

## Migration from Legacy Format (v1)

If you're migrating from the old format, here are the key changes:

| Old (v1) | New (v2) | Notes |
|----------|----------|-------|
| `operation.fecha: "17092025"` | `detalle.fecha: "17/09/2025"` | Add slashes |
| `operation.texto: "STRING"` | `detalle.texto_sical: [{"texto_ado": "STRING"}]` | Now an array |
| `operation.caja: "200"` | `detalle.caja: "200_CAIXABNK - 2064"` | Include bank info |
| `aplicacion.gfa` | `aplicacion.proyecto` | Field renamed |
| `aplicacion.importe: "150.00"` | `aplicacion.importe: 150.00` | Use number, not string |

The consumer auto-converts v1 to v2, but v2 is recommended for new implementations.

---

## Support and Resources

- **Message Format Specification:** `/legacy/MESSAGE_FORMAT_MIGRATION.md`
- **Duplicate Handling Guide:** `/PRODUCER_INTEGRATION_GUIDE.md`
- **Configuration Reference:** `/sical_config.py`
- **Example Messages:** `/legacy/example_message_v2_ado220.json`

---

## Quick Reference

### Minimal Valid Message

```json
{
  "tipo": "pmp450",
  "detalle": {
    "fecha": "17/09/2025",
    "tercero": "P4001500D",
    "caja": "200_CAIXABNK - 2064",
    "texto_sical": [{"texto_ado": "PAGO"}],
    "aplicaciones": [
      {
        "year": "2025",
        "funcional": "1234",
        "economica": "220",
        "importe": 100.00
      }
    ]
  }
}
```

### Production-Ready Message Template

```json
{
  "tipo": "pmp450",
  "detalle": {
    "fecha": "DD/MM/YYYY",
    "tercero": "XXXXXXXXX",
    "caja": "CODE_BANKNAME - NUMBER",
    "caja_tercero": "001",
    "expediente": "EXP-YYYY-NNN",
    "fpago": "10",
    "tpago": "10",
    "texto_sical": [
      {
        "texto_ado": "DESCRIPTION _FIN"
      }
    ],
    "aplicaciones": [
      {
        "year": "YYYY",
        "funcional": "XXXX",
        "economica": "XXX",
        "proyecto": "GFA-XXX",
        "contraido": false,
        "base_imponible": 0.0,
        "tipo": 0.0,
        "importe": 0.00,
        "cuenta_pgp": "XXX",
        "aux": ""
      }
    ],
    "descuentos": [],
    "duplicate_policy": "abort_on_duplicate",
    "aux_data": {},
    "metadata": {
      "generation_datetime": "ISO-8601-DATETIME",
      "source_system": "your-system"
    }
  }
}
```

---

**Document Version:** 1.0
**Last Updated:** 2025-01-28
**Format Version:** v2
