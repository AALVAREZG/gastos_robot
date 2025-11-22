# SICAL Gastos Robot - Producer Integration Guide
## Duplicate Confirmation Token System

**Version:** 2.0
**Last Updated:** 2025-01-17
**Feature:** Token-based Duplicate Confirmation Security

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Security Rationale](#security-rationale)
3. [Message Format Changes](#message-format-changes)
4. [Duplicate Handling Policies](#duplicate-handling-policies)
5. [Two-Phase Workflow](#two-phase-workflow)
6. [Response Format](#response-format)
7. [Implementation Guide](#implementation-guide)
8. [Error Handling](#error-handling)
9. [Backward Compatibility](#backward-compatibility)
10. [Examples](#examples)

---

## Overview

The SICAL Gastos Robot now implements a **token-based duplicate confirmation system** to prevent malicious users from bypassing duplicate checks and creating fraudulent operations.

### Key Features

- ✅ **Cryptographic security** - Force-create operations require valid confirmation tokens
- ✅ **Time-limited tokens** - Tokens expire after 5 minutes
- ✅ **One-time use** - Each token can only be used once (prevents replay attacks)
- ✅ **Data integrity** - Tokens are tied to specific operation data
- ✅ **Full audit trail** - All force-create attempts are logged
- ✅ **Backward compatible** - Existing messages work without changes

---

## Security Rationale

### The Problem

Without token validation, a malicious user with RabbitMQ credentials could:

1. Send messages with `duplicate_policy: "force_create"`
2. Bypass all duplicate detection
3. Create unlimited duplicate operations
4. Cause financial data corruption

### The Solution

The token system ensures that `force_create` can **only** be used after:

1. A duplicate check has been performed (`check_only`)
2. The user has reviewed the duplicate details
3. A valid, unexpired token is included in the request

---

## Message Format Changes

### New Fields (Optional)

Add these fields to the `detalle` object:

```json
{
  "tipo": "ado220",
  "detalle": {
    // ... existing fields ...

    "duplicate_policy": "check_only",  // NEW
    "duplicate_check_id": "unique-id", // NEW (optional, for correlation)
    "duplicate_confirmation_token": "token-from-response" // NEW (required for force_create)
  }
}
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `duplicate_policy` | String | No | Duplicate handling strategy (see policies below) |
| `duplicate_check_id` | String | No | Correlation ID for tracking check-create pairs |
| `duplicate_confirmation_token` | String | **Yes** (for `force_create`) | Token received from `check_only` response |

---

## Duplicate Handling Policies

### Policy Options

| Policy | Behavior | Use Case | Token Required |
|--------|----------|----------|----------------|
| `check_only` | Check for duplicates, **don't create** operation | **Phase 1**: Initial duplicate check | No |
| `force_create` | **Skip** duplicate check, always create | **Phase 2**: Create after user confirms | **YES** |
| `abort_on_duplicate` | Check duplicates, abort if found (**default**) | Current behavior, backward compatible | No |
| `warn_and_continue` | Check duplicates, log warning but continue | Tolerant mode for auto-processing | No |

### Default Behavior

If `duplicate_policy` is **not specified**, the system defaults to `"abort_on_duplicate"` (current behavior).

---

## Two-Phase Workflow

### Recommended Flow

```
┌─────────────────────────────────────────────┐
│ PHASE 1: Check for Duplicates               │
└─────────────────────────────────────────────┘

Producer sends message with:
  duplicate_policy: "check_only"
  duplicate_check_id: "CHECK-123" (optional)

       ↓

Consumer checks for duplicates

       ↓

┌──────────┴──────────┐
│                      │
v                      v
NO DUPLICATES      DUPLICATES FOUND
       │                │
       v                v
Return:           Return:
- status: "COMPLETED"    - status: "P_DUPLICATED"
- No token needed        - duplicate_confirmation_token: "abc..."
                        - duplicate_token_expires_at: timestamp
                        - duplicate_details: [...]
       │                │
       └────────┬───────┘
                │
                v
       Producer receives response
                │
                v
┌───────────────┴────────────────┐
│                                │
v                                v
NO DUPLICATES              DUPLICATES FOUND
     │                           │
     v                           v
Proceed to create          Show duplicates to user
(Phase 2)                        │
                                 v
                        User decides what to do
                                 │
                ┌────────────────┼────────────────┐
                │                │                │
                v                v                v
            [Abort]      [Create Anyway]    [Edit & Retry]

┌─────────────────────────────────────────────┐
│ PHASE 2: Create Operation                   │
└─────────────────────────────────────────────┘

Producer sends message with:
  duplicate_policy: "force_create"
  duplicate_confirmation_token: "abc..." (from Phase 1)
  duplicate_check_id: "CHECK-123" (same as Phase 1)

       ↓

Consumer validates token:
  ✓ Token exists?
  ✓ Token not expired?
  ✓ Token not already used?
  ✓ Token matches operation data?

       ↓

┌──────────┴──────────┐
│                      │
v                      v
TOKEN VALID       TOKEN INVALID
     │                │
     v                v
Create            REJECT with error
Operation         (Security validation failed)
     │
     v
Return:
- status: "COMPLETED"
- num_operacion: "2025003"
```

---

## Response Format

### Phase 1 Response (check_only) - Duplicates Found

```json
{
  "status": "P_DUPLICATED",
  "operation_id": "task-12345",
  "result": {
    "status": "P_DUPLICATED",
    "num_operacion": null,
    "similiar_records_encountered": 3,

    // Duplicate details
    "duplicate_details": [
      // Currently empty - will be populated in future version
    ],

    // Metadata about the check
    "duplicate_check_metadata": {
      "check_id": "CHECK-123",
      "check_timestamp": "2025-01-17T10:30:00.123Z",
      "search_criteria": {
        "tercero": "P4001500D",
        "fecha": "17092025",
        "funcional": "1234",
        "economica": "220",
        "importe_min": "150.00",
        "importe_max": "150.00",
        "caja": "200"
      }
    },

    // SECURITY: Confirmation token
    "duplicate_confirmation_token": "kJ8s9dKm3nQ7pT2vX5wY8zB1cD4eF6gH9jK0lM3nP5qR8sT1uV4wX7yZ0A2bC5dE8f",
    "duplicate_token_expires_at": 1705492800.123,

    "error": null,
    "completed_phases": [
      {
        "phase": "duplicate_check",
        "description": "Similar records checked: 3 found"
      }
    ]
  }
}
```

### Phase 1 Response (check_only) - No Duplicates

```json
{
  "status": "COMPLETED",
  "operation_id": "task-12345",
  "result": {
    "status": "COMPLETED",
    "similiar_records_encountered": 0,
    "duplicate_details": [],
    "duplicate_check_metadata": {
      "check_id": "CHECK-123",
      "check_timestamp": "2025-01-17T10:30:00.123Z",
      "search_criteria": { ... }
    },
    "duplicate_confirmation_token": null,
    "duplicate_token_expires_at": null
  }
}
```

### Phase 2 Response (force_create) - Success

```json
{
  "status": "COMPLETED",
  "operation_id": "task-12345",
  "result": {
    "status": "COMPLETED",
    "num_operacion": "2025003",
    "total_operacion": 150.00,
    "suma_aplicaciones": 150.00,
    "completed_phases": [
      {
        "phase": "data_entry",
        "description": "Operation data entered into form"
      },
      {
        "phase": "validation",
        "description": "Operation validated: 2025003"
      },
      {
        "phase": "printing",
        "description": "Print operation document ID: 2025003"
      },
      {
        "phase": "payment_ordering",
        "description": "Operation ordered and paid: 2025003"
      }
    ]
  }
}
```

### Phase 2 Response (force_create) - Token Invalid

```json
{
  "status": "FAILED",
  "operation_id": "task-12345",
  "result": {
    "status": "FAILED",
    "error": "Security validation failed: Confirmation token expired - tokens are valid for 300 seconds",
    "num_operacion": null
  }
}
```

---

## Implementation Guide

### JavaScript/TypeScript Example

```typescript
interface ADO220Operation {
  tipo: string;
  detalle: {
    fecha: string;
    tercero: string;
    // ... other fields
    duplicate_policy?: 'check_only' | 'force_create' | 'abort_on_duplicate' | 'warn_and_continue';
    duplicate_confirmation_token?: string;
    duplicate_check_id?: string;
  };
}

interface OperationResponse {
  status: string;
  operation_id: string;
  result: {
    status: string;
    num_operacion?: string;
    similiar_records_encountered?: number;
    duplicate_confirmation_token?: string;
    duplicate_token_expires_at?: number;
    duplicate_details?: any[];
    duplicate_check_metadata?: any;
    error?: string;
  };
}

/**
 * Create an ADO220 operation with duplicate checking
 */
async function createADO220Operation(operationData: any): Promise<OperationResponse> {
  const checkId = `CHECK-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

  // PHASE 1: Check for duplicates
  const checkMessage: ADO220Operation = {
    tipo: 'ado220',
    detalle: {
      ...operationData,
      duplicate_policy: 'check_only',
      duplicate_check_id: checkId
    }
  };

  console.log('Phase 1: Checking for duplicates...');
  const checkResponse = await sendToRabbitMQ(checkMessage);

  if (checkResponse.result.status === 'P_DUPLICATED') {
    // Duplicates found - show to user
    const duplicateCount = checkResponse.result.similiar_records_encountered;
    const token = checkResponse.result.duplicate_confirmation_token;
    const expiresAt = checkResponse.result.duplicate_token_expires_at;
    const expiresIn = Math.round((expiresAt * 1000 - Date.now()) / 1000);

    console.log(`Found ${duplicateCount} similar operations`);
    console.log(`Token expires in ${expiresIn} seconds`);

    // Show duplicate warning to user
    const userChoice = await showDuplicateConfirmationDialog({
      count: duplicateCount,
      searchCriteria: checkResponse.result.duplicate_check_metadata.search_criteria,
      expiresInSeconds: expiresIn
    });

    if (userChoice === 'ABORT') {
      console.log('User aborted - operation cancelled');
      return {
        status: 'ABORTED_BY_USER',
        operation_id: checkResponse.operation_id,
        result: checkResponse.result
      };
    }

    if (userChoice === 'CREATE_ANYWAY') {
      // PHASE 2: Force create with token
      console.log('User confirmed - creating operation despite duplicates...');

      const createMessage: ADO220Operation = {
        tipo: 'ado220',
        detalle: {
          ...operationData,
          duplicate_policy: 'force_create',
          duplicate_confirmation_token: token,
          duplicate_check_id: checkId
        }
      };

      const createResponse = await sendToRabbitMQ(createMessage);

      if (createResponse.result.status === 'FAILED') {
        console.error('Force create failed:', createResponse.result.error);

        // Check if token expired
        if (createResponse.result.error.includes('expired')) {
          console.error('Token expired! User took too long to confirm.');
          // Could retry from Phase 1 here
        }
      }

      return createResponse;
    }

  } else if (checkResponse.result.status === 'COMPLETED') {
    // No duplicates found - safe to create
    console.log('No duplicates found - creating operation...');

    const createMessage: ADO220Operation = {
      tipo: 'ado220',
      detalle: {
        ...operationData,
        duplicate_policy: 'force_create', // Skip redundant check
        duplicate_check_id: checkId
      }
    };

    // NOTE: No token needed because no duplicates were found
    // The consumer will allow force_create without token in this case
    // OR you can use 'warn_and_continue' policy

    return await sendToRabbitMQ(createMessage);

  } else {
    // Check failed
    console.error('Duplicate check failed:', checkResponse.result.error);
    return checkResponse;
  }
}

/**
 * Show duplicate confirmation dialog to user
 */
async function showDuplicateConfirmationDialog(options: {
  count: number;
  searchCriteria: any;
  expiresInSeconds: number;
}): Promise<'ABORT' | 'CREATE_ANYWAY'> {
  // Implementation depends on your UI framework
  // This is a placeholder

  const message = `
    Found ${options.count} similar operations with:
    - Third Party: ${options.searchCriteria.tercero}
    - Date: ${options.searchCriteria.fecha}
    - Amount: ${options.searchCriteria.importe_min}

    Token expires in ${options.expiresInSeconds} seconds.

    Do you want to create this operation anyway?
  `;

  const userConfirmed = window.confirm(message);

  return userConfirmed ? 'CREATE_ANYWAY' : 'ABORT';
}

/**
 * Send message to RabbitMQ and wait for response
 */
async function sendToRabbitMQ(message: ADO220Operation): Promise<OperationResponse> {
  // Your RabbitMQ client implementation here
  // This is a placeholder
  return {} as OperationResponse;
}
```

### Python Example

```python
import uuid
import time
from datetime import datetime

def create_ado220_operation(operation_data: dict) -> dict:
    """
    Create an ADO220 operation with duplicate checking.

    Args:
        operation_data: Operation data (without duplicate_policy)

    Returns:
        Final operation response
    """
    check_id = f"CHECK-{int(time.time())}-{uuid.uuid4().hex[:8]}"

    # PHASE 1: Check for duplicates
    check_message = {
        "tipo": "ado220",
        "detalle": {
            **operation_data,
            "duplicate_policy": "check_only",
            "duplicate_check_id": check_id
        }
    }

    print("Phase 1: Checking for duplicates...")
    check_response = send_to_rabbitmq(check_message)

    if check_response['result']['status'] == 'P_DUPLICATED':
        # Duplicates found
        duplicate_count = check_response['result']['similiar_records_encountered']
        token = check_response['result']['duplicate_confirmation_token']
        expires_at = check_response['result']['duplicate_token_expires_at']
        expires_in = int(expires_at - time.time())

        print(f"Found {duplicate_count} similar operations")
        print(f"Token expires in {expires_in} seconds")

        # Show to user
        user_choice = show_duplicate_dialog(
            count=duplicate_count,
            criteria=check_response['result']['duplicate_check_metadata']['search_criteria'],
            expires_in=expires_in
        )

        if user_choice == 'ABORT':
            print("User aborted")
            return check_response

        if user_choice == 'CREATE_ANYWAY':
            # PHASE 2: Force create
            print("User confirmed - creating operation...")

            create_message = {
                "tipo": "ado220",
                "detalle": {
                    **operation_data,
                    "duplicate_policy": "force_create",
                    "duplicate_confirmation_token": token,
                    "duplicate_check_id": check_id
                }
            }

            return send_to_rabbitmq(create_message)

    elif check_response['result']['status'] == 'COMPLETED':
        # No duplicates - create directly
        print("No duplicates found - creating operation...")

        create_message = {
            "tipo": "ado220",
            "detalle": {
                **operation_data,
                "duplicate_policy": "force_create",
                "duplicate_check_id": check_id
            }
        }

        return send_to_rabbitmq(create_message)

    else:
        # Check failed
        print(f"Duplicate check failed: {check_response['result'].get('error')}")
        return check_response
```

---

## Error Handling

### Common Error Scenarios

#### 1. Missing Token

**Error:** `"Missing confirmation token - force_create requires valid token from duplicate check"`

**Cause:** Sent `force_create` without a token

**Solution:** Always perform `check_only` first to get a token

#### 2. Invalid Token

**Error:** `"Invalid confirmation token - token not found or already expired"`

**Cause:** Token is unknown to the consumer

**Solution:** Token may have expired or been cleaned up. Retry from Phase 1.

#### 3. Expired Token

**Error:** `"Confirmation token expired - tokens are valid for 300 seconds"`

**Cause:** User took longer than 5 minutes to confirm

**Solution:** Retry from Phase 1 to get a new token

#### 4. Token Already Used

**Error:** `"Confirmation token already used - each token can only be used once"`

**Cause:** Attempted to reuse a token

**Solution:** Each token is single-use. Get a new token via `check_only`.

#### 5. Data Tampering

**Error:** `"Confirmation token does not match operation data - possible tampering detected"`

**Cause:** Operation data changed between Phase 1 and Phase 2

**Solution:** Ensure operation data is identical between check and create phases

### Error Handling Best Practices

```typescript
async function createWithRetry(operationData: any, maxRetries: number = 2): Promise<OperationResponse> {
  let attempt = 0;

  while (attempt < maxRetries) {
    try {
      const response = await createADO220Operation(operationData);

      if (response.result.status === 'FAILED') {
        const error = response.result.error || '';

        // Check if retryable error
        if (error.includes('expired') || error.includes('already used')) {
          attempt++;
          console.log(`Token error - retrying (${attempt}/${maxRetries})...`);
          await delay(1000); // Wait 1 second before retry
          continue;
        }

        // Non-retryable error
        throw new Error(error);
      }

      return response;

    } catch (error) {
      if (attempt >= maxRetries - 1) {
        throw error;
      }
      attempt++;
    }
  }

  throw new Error('Max retries exceeded');
}
```

---

## Backward Compatibility

### Existing Messages Work Unchanged

**Old message format (still works):**

```json
{
  "tipo": "ado220",
  "detalle": {
    "fecha": "17/09/2025",
    "tercero": "P4001500D",
    "texto_sical": [{"texto_ado": "PAGO A PROVEEDOR _FIN"}],
    // ... other fields ...
    // NO duplicate_policy field
  }
}
```

**Behavior:** Defaults to `duplicate_policy: "abort_on_duplicate"` (current behavior)

### Migration Strategy

1. **Phase 1:** Deploy consumer with new security system
   - Existing messages continue to work
   - No changes required to producers

2. **Phase 2:** Update producers gradually
   - Implement two-phase workflow
   - Add `duplicate_policy` field to new operations

3. **Phase 3 (optional):** Retire old format
   - Make `duplicate_policy` required
   - Remove default fallback

---

## Examples

### Example 1: No Duplicates Found

```javascript
// Message
{
  "tipo": "ado220",
  "detalle": {
    "fecha": "17/09/2025",
    "tercero": "P4001500D",
    "duplicate_policy": "check_only"
  }
}

// Response
{
  "result": {
    "status": "COMPLETED",
    "similiar_records_encountered": 0
  }
}

// Next step: Create directly (no token needed)
```

### Example 2: Duplicates Found, User Confirms

```javascript
// Phase 1 Message
{
  "duplicate_policy": "check_only",
  "duplicate_check_id": "CHECK-123"
}

// Phase 1 Response
{
  "result": {
    "status": "P_DUPLICATED",
    "similiar_records_encountered": 2,
    "duplicate_confirmation_token": "abc123...",
    "duplicate_token_expires_at": 1705492800
  }
}

// [User confirms in UI]

// Phase 2 Message
{
  "duplicate_policy": "force_create",
  "duplicate_confirmation_token": "abc123...",
  "duplicate_check_id": "CHECK-123"
}

// Phase 2 Response
{
  "result": {
    "status": "COMPLETED",
    "num_operacion": "2025003"
  }
}
```

### Example 3: Token Expired

```javascript
// Phase 2 Message (sent 6 minutes after Phase 1)
{
  "duplicate_policy": "force_create",
  "duplicate_confirmation_token": "old_token..."
}

// Response
{
  "result": {
    "status": "FAILED",
    "error": "Confirmation token expired - tokens are valid for 300 seconds"
  }
}

// Solution: Retry from Phase 1
```

---

## Support

For questions or issues:

1. Check this guide first
2. Review example messages in `/legacy/example_message_v2_ado220_*.json`
3. Check consumer logs in `security_audit.jsonl` for detailed audit trail
4. Contact the development team

---

## Changelog

### Version 2.0 (2025-01-17)

- Added token-based duplicate confirmation system
- New `duplicate_policy` field
- Security validation for `force_create`
- Enhanced response format with token and metadata
- Comprehensive audit logging
- Backward compatibility maintained

---

**End of Producer Integration Guide**
