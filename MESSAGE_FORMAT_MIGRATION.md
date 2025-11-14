# Message Format Migration Guide

## Overview
The RabbitMQ message format has been updated from v1 to v2. The consumer now supports **both formats** for backwards compatibility.

## Message Format Comparison

### Version 2 (New Format) - CURRENT

#### Structure
```json
{
  "tipo": "ado220|pmp450|ordenarypagar",
  "detalle": {
    // operation-specific fields
  }
}
```

#### ADO220 Operation Example
```json
{
  "tipo": "ado220",
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
        "texto_ado": "PAGO A PROVEEDOR _FIN"
      }
    ],
    "aplicaciones": [
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
    ],
    "descuentos": [],
    "aux_data": {},
    "metadata": {
      "generation_datetime": "2025-01-13T10:30:00.000Z"
    }
  }
}
```

#### Order & Pay Operation Example
```json
{
  "tipo": "ordenarypagar",
  "detalle": {
    "num_operacion": "225101450",
    "num_lista": null,
    "fecha_ordenamiento": "17/09/2025",
    "fecha_pago": "20/09/2025"
  }
}
```

---

### Version 1 (Legacy Format) - DEPRECATED

#### Structure
```json
{
  "task_id": "unique-task-id",
  "operation_data": {
    "operation": {
      "tipo": "ado220|pmp450|ordenarypagar",
      // operation-specific fields
    }
  }
}
```

#### ADO220 Operation Example
```json
{
  "task_id": "task-12345",
  "operation_data": {
    "operation": {
      "tipo": "ado220",
      "fecha": "17092025",
      "tercero": "P4001500D",
      "caja": "200",
      "expediente": "EXP-2025-001",
      "fpago": "10",
      "tpago": "10",
      "texto": "PAGO A PROVEEDOR _FIN",
      "aplicaciones": [
        {
          "funcional": "1234",
          "economica": "220",
          "gfa": "GFA-001",
          "importe": "150.00"
        }
      ]
    }
  }
}
```

---

## Key Differences

| Field | v1 (Legacy) | v2 (New) | Notes |
|-------|-------------|----------|-------|
| **Structure** | `operation_data.operation` | Root level `tipo` + `detalle` | Flattened structure |
| **Date Format** | `DDMMYYYY` | `DD/MM/YYYY` | Slashes added |
| **Text Field** | `texto` (string) | `texto_sical` (array) | Array of text objects |
| **Caja Field** | `"200"` | `"200_CAIXABNK - 2064"` | Includes bank name |
| **Caja Tercero** | N/A | `caja_tercero` | New field |
| **Aplicaciones - Project** | `gfa` | `proyecto` | Renamed |
| **Aplicaciones - Year** | N/A | `year` | New field |
| **Aplicaciones - Contraído** | N/A | `contraido` | New field |
| **Aplicaciones - Base Imponible** | N/A | `base_imponible` | New field |
| **Aplicaciones - Tipo** | N/A | `tipo` | New field |
| **Aplicaciones - Cuenta** | Auto-calculated | `cuenta_pgp` | Can be provided |
| **Aplicaciones - Aux** | N/A | `aux` | New field |
| **Aplicaciones - Importe** | String | Float | Type changed |
| **Descuentos** | N/A | `descuentos` | New array |
| **Aux Data** | N/A | `aux_data` | New object |
| **Metadata** | N/A | `metadata` | New object |

---

## Transformation Logic

### Date Normalization
```python
# v2 format: "17/09/2025" → "17092025"
# v1 format: "17092025" → "17092025" (no change)
if '/' in date_value:
    normalized = date_value.replace('/', '')
```

### Caja Code Extraction
```python
# v2 format: "200_CAIXABNK - 2064" → "200"
# v1 format: "200" → "200" (no change)
if '_' in caja_value:
    caja = caja_value.split('_')[0]
```

### Text Field Extraction
```python
# v2 format: texto_sical[0].texto_ado
# v1 format: texto
if 'texto_sical' in data and data['texto_sical']:
    text = data['texto_sical'][0].get('texto_ado', 'ADO....')
else:
    text = data.get('texto', 'ADO....')
```

### Aplicaciones Project Field
```python
# v2 format: proyecto
# v1 format: gfa
gfa_proyecto = aplicacion.get('proyecto') or aplicacion.get('gfa', None)
```

### Cuenta Determination
```python
# v2 format: prefer cuenta_pgp from message
# v1 format: always use mapping table
if 'cuenta_pgp' in aplicacion and aplicacion['cuenta_pgp']:
    cuenta = str(aplicacion['cuenta_pgp'])
else:
    cuenta = partidas_gasto_cuentaPG.get(economica, '000')
```

---

## Code Changes

### Files Modified

1. **gasto_task_consumer.py**
   - Updated `callback()` method to detect message format
   - Added support for both v1 and v2 structures
   - Improved logging to show which format is being processed

2. **gasto_tasks.py**
   - Updated `create_ado_data()` to handle both formats
   - Updated `create_aplicaciones()` to handle new fields
   - Added date normalization logic
   - Added caja code extraction logic
   - Added text field extraction logic

3. **ordenar_tasks.py**
   - Updated `create_pago_data()` to handle both date formats
   - Added date normalization helper function

### New Files Created

- `example_message_v2_ado220.json` - Example v2 ADO operation message
- `example_message_v2_ordenarypagar.json` - Example v2 payment operation message
- `MESSAGE_FORMAT_MIGRATION.md` - This migration guide

---

## Testing

### Test with v2 Format
```python
# Load example v2 message
with open('example_message_v2_ado220.json', 'r') as f:
    message_v2 = json.load(f)

# Send to RabbitMQ queue
channel.basic_publish(
    exchange='',
    routing_key='sical_queue.gasto',
    body=json.dumps(message_v2),
    properties=pika.BasicProperties(
        correlation_id='test-v2-001',
        reply_to='test.response.queue'
    )
)
```

### Test with v1 Format (Legacy)
```python
# Load legacy v1 message
message_v1 = {
    "task_id": "test-v1-001",
    "operation_data": {
        "operation": {
            "tipo": "ado220",
            "fecha": "17092025",
            "tercero": "P4001500D",
            "caja": "200",
            "expediente": "EXP-2025-001",
            "fpago": "10",
            "tpago": "10",
            "texto": "PAGO A PROVEEDOR _FIN",
            "aplicaciones": [
                {
                    "funcional": "1234",
                    "economica": "220",
                    "gfa": "GFA-001",
                    "importe": "150.00"
                }
            ]
        }
    }
}

# Send to RabbitMQ queue (same as above)
```

---

## Migration Timeline

- **Phase 1 (Current):** Both formats supported, v1 deprecated
- **Phase 2 (Future):** v1 support removed after all producers migrated
- **Recommendation:** Migrate all producers to v2 format as soon as possible

---

## Special Flags

### _FIN Flag
Both formats support the `_FIN` flag to indicate operation should be finalized (validated, printed, and paid):

- **v1:** `"texto": "PAGO A PROVEEDOR _FIN"`
- **v2:** `"texto_sical": [{"texto_ado": "PAGO A PROVEEDOR _FIN"}]`

When the text ends with `_FIN`, the consumer will:
1. Create and fill the operation
2. Validate the operation
3. Print the operation document
4. Order and pay the operation

---

## Notes

- The consumer automatically detects which format is being used
- No configuration changes needed - the code handles both formats transparently
- All new fields from v2 are preserved in the internal data structure
- Legacy v1 messages will continue to work without modification
- Logging shows which format version is being processed for debugging

---

## Support

For questions or issues, check the logs which will indicate:
- `Processing new format (v2) message: tipo=...`
- `Processing legacy format (v1) message: tipo=...`
