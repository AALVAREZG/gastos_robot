# Force Create Task Sending Process - Complete Analysis

**Date:** 2025-12-02
**Version:** 1.0
**System:** SICAL Gastos Robot

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Architecture Components](#architecture-components)
3. [Two-Phase Workflow](#two-phase-workflow)
4. [Security Mechanisms](#security-mechanisms)
5. [Code Flow Analysis](#code-flow-analysis)
6. [Key Optimizations](#key-optimizations)
7. [Error Handling](#error-handling)
8. [Rate Limiting](#rate-limiting)
9. [Sequence Diagrams](#sequence-diagrams)

---

## Overview

The **force_create** process allows users to create operations in SICAL even when duplicate records are detected. This is a security-critical feature because it bypasses normal duplicate prevention mechanisms, requiring a token-based confirmation system to prevent abuse.

### Key Principles

1. **Two-Phase Operation**: Separate duplicate checking from operation creation
2. **Token-Based Security**: Cryptographic tokens prevent unauthorized force_create attempts
3. **Early Validation**: Security checks happen BEFORE opening SICAL windows (efficiency)
4. **Rate Limiting**: Global rate limits prevent abuse
5. **Comprehensive Audit Trail**: All force_create attempts are logged

---

## Architecture Components

### 1. Base Classes (`sical_base.py`)

#### `SicalOperationProcessor`
The abstract base class that orchestrates the complete workflow:

```python
def execute(self, operation_data: Dict[str, Any]) -> OperationResult:
    # Phase 1: Transform data
    sical_data = self.create_operation_data(operation_data)

    # Phase 1.5: Check for duplicates BEFORE opening window
    duplicate_policy = sical_data.get('duplicate_policy', 'abort_on_duplicate')

    if duplicate_policy in ('check_only', 'abort_on_duplicate'):
        result = self.check_for_duplicates_pre_window(sical_data, result)

        # Early exit if check-only mode
        if duplicate_policy == 'check_only':
            return result  # No window opened!

        # Early exit if duplicates found in abort mode
        if result.status == OperationStatus.P_DUPLICATED:
            return result  # No window opened!

    elif duplicate_policy == 'force_create':
        # Validate token BEFORE opening window
        result = self._validate_force_create_token(sical_data, result)

        if result.status == OperationStatus.FAILED:
            return result  # Token invalid - no window opened!

    # Phase 2: Setup SICAL window (only if validation passed)
    if not self.setup_operation_window():
        result.status = OperationStatus.FAILED
        return result

    # Phase 3: Process the operation form
    result = self.process_operation_form(sical_data, result)

    return result
```

**Key Insight**: The base class implements the workflow orchestration, ensuring security checks happen BEFORE expensive window operations.

### 2. Security Module (`sical_security.py`)

#### `DuplicateConfirmationManager`
Manages confirmation tokens with cryptographic security:

- **Token Generation**: Creates cryptographically secure tokens tied to operation data
- **Token Validation**: Comprehensive validation with multiple security checks
- **Token Expiration**: 5-minute lifetime (configurable)
- **One-Time Use**: Prevents replay attacks
- **Data Integrity**: HMAC-SHA256 hash ensures operation data hasn't been tampered with

```python
def validate_token(token_id: str, operation_data: Dict) -> Tuple[bool, str]:
    # Check 1: Token exists
    # Check 2: Token not already used
    # Check 3: Token not expired
    # Check 4: Operation data matches token hash (prevents tampering)

    if all_checks_pass:
        token.used = True  # Consume token (one-time use)
        return True, ""
    else:
        return False, "specific_error_message"
```

#### `MultiWindowRateLimiter`
Implements global rate limiting with multiple time windows:

- **Hourly Limit**: 15 operations per 60 minutes (default)
- **Daily Limit**: 30 operations per 24 hours (default)
- **Business Hours**: 7:00 AM - 7:00 PM Europe/Madrid timezone
- **Global Enforcement**: Rate limits apply across ALL terceros (not per-tercero)

### 3. Processor Implementation (`processors/ado220_processor.py`)

#### `ADO220Processor`
Implements the ADO220-specific duplicate checking:

- **Consulta Window**: Opens SICAL's search window to find duplicates
- **Search Criteria**: Searches by tercero, fecha, caja, funcional, economica, importe
- **Token Generation**: Creates tokens when duplicates are found
- **Metadata Collection**: Records search criteria and results

---

## Two-Phase Workflow

### Phase 1: Duplicate Check (`check_only` policy)

```
┌─────────────────────────────────────────────┐
│ PRODUCER: Send check_only message          │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ CONSUMER: Receive message                   │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ sical_base.py: execute()                    │
│ - Transform data                            │
│ - Detect duplicate_policy = "check_only"   │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ Call: check_for_duplicates_pre_window()    │
│ IMPORTANT: No ADO220 window opened yet!    │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ ado220_processor.py: _check_for_duplicates()│
│                                             │
│ 1. Open Consulta window                    │
│ 2. Fill search filters:                    │
│    - Tercero                                │
│    - Fecha range                            │
│    - Funcional, Economica                   │
│    - Importe range                          │
│    - Caja                                   │
│ 3. Execute search                           │
└─────────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌──────────────┐        ┌──────────────────┐
│ No Duplicates│        │ Duplicates Found │
└──────────────┘        └──────────────────┘
        │                       │
        ▼                       ▼
   similiar = 0           similiar = N
   status = COMPLETED     status = P_DUPLICATED
   token = null           │
                          ▼
                    ┌──────────────────────────┐
                    │ Generate Security Token: │
                    │                          │
                    │ 1. Hash operation data   │
                    │    (HMAC-SHA256)         │
                    │ 2. Generate token ID     │
                    │    (32 bytes secure)     │
                    │ 3. Set expiration        │
                    │    (now + 300 seconds)   │
                    │ 4. Store in memory       │
                    └──────────────────────────┘
                          │
                          ▼
               duplicate_confirmation_token
               duplicate_token_expires_at
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
        ▼                                   ▼
┌─────────────────┐              ┌─────────────────────┐
│ Close Consulta  │              │ Close Consulta      │
│ Return COMPLETED│              │ Return P_DUPLICATED │
└─────────────────┘              └─────────────────────┘
        │                                   │
        └───────────────┬───────────────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │ EARLY EXIT from       │
            │ execute() method      │
            │                       │
            │ ADO220 window was     │
            │ NEVER opened!         │
            └───────────────────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │ Return result to      │
            │ consumer              │
            └───────────────────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │ Consumer sends        │
            │ response to producer  │
            └───────────────────────┘
```

**Key Efficiency**: The Consulta window is used for searching, but the ADO220 window is NEVER opened during Phase 1. This saves significant time and resources.

### Phase 2: Force Create (`force_create` policy)

```
┌─────────────────────────────────────────────┐
│ PRODUCER: Send force_create message         │
│ - Includes duplicate_confirmation_token     │
│ - Same operation data as Phase 1            │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ CONSUMER: Receive message                   │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ sical_base.py: execute()                    │
│ - Transform data                            │
│ - Detect duplicate_policy = "force_create" │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ Call: _validate_force_create_token()        │
│ IMPORTANT: Still no window opened!          │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ sical_security.py: Token Validation         │
│                                             │
│ Security Check 1: Token exists?             │
│   ✗ FAIL → Return "Missing token"          │
│   ✓ PASS → Continue                         │
│                                             │
│ Security Check 2: Token already used?       │
│   ✗ FAIL → Return "Token already used"     │
│   ✓ PASS → Continue                         │
│                                             │
│ Security Check 3: Token expired?            │
│   ✗ FAIL → Return "Token expired"          │
│   ✓ PASS → Continue                         │
│                                             │
│ Security Check 4: Data tampered?            │
│   - Hash current operation data             │
│   - Compare with token's operation_hash     │
│   ✗ FAIL → Return "Data tampering detected"│
│   ✓ PASS → Continue                         │
│                                             │
│ Security Check 5: Rate limit OK?            │
│   - Check hourly limit (15 ops/60 min)     │
│   - Check daily limit (30 ops/24 hrs)      │
│   - Check business hours (7am-7pm Spain)   │
│   ✗ FAIL → Return "Rate limit exceeded"    │
│   ✓ PASS → Continue                         │
└─────────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌────────────────┐      ┌────────────────┐
│ Validation     │      │ Validation     │
│ FAILED         │      │ PASSED         │
└────────────────┘      └────────────────┘
        │                       │
        ▼                       ▼
 status = FAILED          Mark token as used
 EARLY EXIT!              (prevents replay)
 (No window opened)               │
                                  ▼
                    ┌──────────────────────────┐
                    │ Audit log force_create   │
                    │ (security_audit.jsonl)   │
                    └──────────────────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────┐
                    │ NOW open ADO220 window   │
                    │ setup_operation_window() │
                    └──────────────────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────┐
                    │ process_operation_form() │
                    │                          │
                    │ 1. Enter operation data  │
                    │ 2. Validate              │
                    │ 3. Print document        │
                    │ 4. Order payment         │
                    └──────────────────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────┐
                    │ Close ADO220 window      │
                    │ Return COMPLETED         │
                    │ num_operacion = "2025XXX"│
                    └──────────────────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────┐
                    │ Consumer sends response  │
                    └──────────────────────────┘
```

**Critical Security Point**: ALL security validation happens BEFORE opening the ADO220 window. If any check fails, the operation is rejected immediately without consuming resources.

---

## Security Mechanisms

### 1. Token Generation (Phase 1)

**Location**: `sical_security.py:91-135` (`DuplicateConfirmationManager.generate_token()`)

```python
def generate_token(self, operation_data: Dict[str, Any]) -> Tuple[str, float]:
    # Step 1: Create deterministic hash of operation data
    operation_hash = self._hash_operation_data(operation_data)
    # Uses HMAC-SHA256 with secret key
    # Includes: tercero, fecha, caja, aplicaciones (funcional, economica, importe)

    # Step 2: Generate cryptographically secure token ID
    token_id = secrets.token_urlsafe(32)  # 256 bits of entropy

    # Step 3: Set expiration
    now = time.time()
    expires_at = now + self.token_lifetime  # Default: 300 seconds (5 minutes)

    # Step 4: Create and store token
    token = ConfirmationToken(
        token_id=token_id,
        operation_hash=operation_hash,
        created_at=now,
        expires_at=expires_at,
        used=False,
        tercero=operation_data.get('tercero')
    )

    self.tokens[token_id] = token  # In-memory storage

    return token_id, expires_at
```

### 2. Token Validation (Phase 2)

**Location**: `sical_security.py:137-206` (`DuplicateConfirmationManager.validate_token()`)

```python
def validate_token(self, token_id: str, operation_data: Dict) -> Tuple[bool, str]:
    # CHECK 1: Token provided?
    if not token_id:
        return False, "Missing confirmation token"

    # CHECK 2: Token exists in memory?
    if token_id not in self.tokens:
        return False, "Invalid confirmation token - token not found or already expired"

    token = self.tokens[token_id]

    # CHECK 3: Token not already used? (prevents replay attacks)
    if token.used:
        return False, "Confirmation token already used - each token can only be used once"

    # CHECK 4: Token not expired?
    now = time.time()
    if now > token.expires_at:
        return False, f"Confirmation token expired - tokens are valid for {self.token_lifetime} seconds"

    # CHECK 5: Operation data matches token hash? (prevents tampering)
    operation_hash = self._hash_operation_data(operation_data)
    if operation_hash != token.operation_hash:
        return False, "Confirmation token does not match operation data - possible tampering detected"

    # ALL CHECKS PASSED
    token.used = True  # Mark as consumed
    return True, ""
```

### 3. Rate Limiting

**Location**: `sical_security.py:463-518` (`MultiWindowRateLimiter.check_rate_limit()`)

**Configuration** (default):
- **Hourly window**: 15 operations per 3600 seconds
- **Daily window**: 30 operations per 86400 seconds
- **Business hours**: 7:00 - 19:00 Europe/Madrid timezone
- **Scope**: GLOBAL (all terceros share the same limit pool)

```python
def check_rate_limit(self, tercero: str) -> Tuple[bool, str]:
    now = time.time()

    # Check 1: Business hours
    if self.config.business_hours:
        allowed, error = self._check_business_hours(now)
        if not allowed:
            return False, error  # Outside business hours

    # Check 2: Multiple time windows
    for window in self.config.windows:
        recent_ops = [ts for ts in self.operations
                      if now - ts < window.time_window_seconds]

        if len(recent_ops) >= window.max_operations:
            return False, f"Rate limit exceeded: {window.name}"

    # ALL CHECKS PASSED
    self.operations.append(now)  # Record this operation
    return True, ""
```

### 4. Data Integrity Hashing

**Location**: `sical_security.py:208-252` (`DuplicateConfirmationManager._hash_operation_data()`)

The hash includes all fields that uniquely identify an operation:

```python
def _hash_operation_data(self, operation_data: Dict) -> str:
    key_fields = {
        'tercero': operation_data.get('tercero'),
        'fecha': operation_data.get('fecha'),
        'caja': operation_data.get('caja'),
        'aplicaciones': [
            {
                'funcional': app.get('funcional'),
                'economica': app.get('economica'),
                'importe': str(app.get('importe')),
            }
            for app in operation_data.get('aplicaciones', [])
        ]
    }

    # Deterministic JSON (sorted keys)
    json_str = json.dumps(key_fields, sort_keys=True, separators=(',', ':'))

    # HMAC-SHA256 with secret key
    hash_obj = hmac.new(
        self.secret_key.encode(),
        json_str.encode(),
        hashlib.sha256
    )

    return hash_obj.hexdigest()
```

---

## Code Flow Analysis

### File: `sical_base.py`

**Method**: `SicalOperationProcessor.execute()` (lines 349-454)

This is the **orchestration method** that implements the complete workflow:

```python
def execute(self, operation_data: Dict[str, Any]) -> OperationResult:
    # Initialize result
    result = OperationResult(
        status=OperationStatus.PENDING,
        init_time=str(datetime.now()),
        ...
    )

    # PHASE 1: Transform data (lines 380-383)
    sical_data = self.create_operation_data(operation_data)

    # PHASE 1.5: Duplicate checking and security validation (lines 385-416)
    duplicate_policy = sical_data.get('duplicate_policy', 'abort_on_duplicate')

    # Branch 1: check_only or abort_on_duplicate
    if duplicate_policy in ('check_only', 'abort_on_duplicate'):
        result = self.check_for_duplicates_pre_window(sical_data, result)

        # Early exit for check_only mode
        if duplicate_policy == 'check_only':
            return result  # Line 396 - EARLY EXIT!

        # Early exit if duplicates found in abort mode
        if result.status == OperationStatus.P_DUPLICATED:
            return result  # Line 401 - EARLY EXIT!

    # Branch 2: force_create
    elif duplicate_policy == 'force_create':
        # Validate token BEFORE opening window
        result = self._validate_force_create_token(sical_data, result)

        if result.status == OperationStatus.FAILED:
            return result  # Line 413 - EARLY EXIT!

    # PHASE 2: Open SICAL window (lines 418-427)
    # NOTE: We only reach here if:
    # - check_only: Not possible (early exit at line 396)
    # - abort_on_duplicate: No duplicates found
    # - force_create: Token validated successfully

    if not self.setup_operation_window():
        result.status = OperationStatus.FAILED
        return result

    result.sical_is_open = True
    result.status = OperationStatus.IN_PROGRESS

    # PHASE 3: Process the form (lines 430-431)
    result = self.process_operation_form(sical_data, result)

    return result
```

**Key Insight**: The method has THREE early exit points (lines 396, 401, 413) that prevent window opening if:
1. Policy is check_only (we only want to check, not create)
2. Duplicates found with abort_on_duplicate policy
3. Token validation fails

### File: `processors/ado220_processor.py`

**Method**: `ADO220Processor._check_for_duplicates()` (lines 284-413)

This implements the actual duplicate detection logic:

```python
def _check_for_duplicates(self, operation_data: Dict, result: OperationResult) -> OperationResult:
    # Step 1: Open Consulta window (lines 310-313)
    if not self._setup_consulta_window(consulta_manager):
        result.status = OperationStatus.FAILED
        return result

    # Step 2: Open filters dialog (lines 318-330)
    consulta_manager.ventana_proceso.find('filtros_button').click()
    filtros_window = windows.find_window('Filtros')

    # Step 3: Fill search criteria (line 333)
    search_criteria = self._fill_duplicate_check_filters(filtros_window, operation_data)
    # Searches by: tercero, fecha, caja, funcional, economica, importe

    # Step 4: Execute search (lines 336-337)
    filtros_window.find('consultar_button').click()

    # Step 5: Check for results (lines 340-402)
    modal_error = filtros_window.find('TMessageForm:Error')

    if not modal_error:
        # DUPLICATES FOUND (lines 347-378)
        num_registros = filtros_window.find('num_registros').get_value()
        result.similiar_records_encountered = int(num_registros)

        # Generate confirmation token (lines 359-363)
        confirmation_manager = get_confirmation_manager()
        token_id, expires_at = confirmation_manager.generate_token(operation_data)

        result.duplicate_confirmation_token = token_id
        result.duplicate_token_expires_at = expires_at
        result.status = OperationStatus.P_DUPLICATED

        # Close windows (line 378)
        filtros_window.find('cerrar_button').click()

    else:
        # NO DUPLICATES (lines 381-397)
        result.similiar_records_encountered = 0
        result.status = OperationStatus.COMPLETED  # Implicitly set

        # Close windows (lines 391-396)
        filtros_window.find('ok_button').click()
        filtros_window.find('cerrar_button').click()
        consulta_manager.close_window()

    return result
```

---

## Key Optimizations

### 1. **Pre-Window Validation**

**Problem**: Opening SICAL windows is expensive (time-consuming)

**Solution**: All validation happens BEFORE opening windows

**Impact**:
- `check_only`: Consulta window only, ADO220 never opened → **Saves ~5-10 seconds**
- `force_create` (invalid token): No windows opened → **Saves ~10-15 seconds**
- `abort_on_duplicate`: Consulta window only if duplicates found → **Saves ~5-10 seconds**

**Code Location**: `sical_base.py:385-416`

### 2. **Token-Based Security**

**Problem**: Users could abuse `force_create` to bypass duplicate protection

**Solution**: Cryptographic tokens that:
- Expire after 5 minutes
- Can only be used once
- Are tied to specific operation data

**Impact**:
- Prevents replay attacks
- Prevents data tampering
- Requires legitimate two-phase workflow

**Code Location**: `sical_security.py:55-302`

### 3. **Global Rate Limiting**

**Problem**: Malicious users could create thousands of duplicate operations

**Solution**: Multi-window rate limiting:
- 15 operations per hour (global)
- 30 operations per day (global)
- Business hours enforcement

**Impact**:
- Prevents abuse
- Defense-in-depth security
- Maintains system stability

**Code Location**: `sical_security.py:429-567`

### 4. **In-Memory Token Storage**

**Problem**: Persistent storage could be tampered with

**Solution**: Tokens stored in memory with periodic cleanup

**Impact**:
- Tokens automatically cleared on service restart
- No persistence attack surface
- Automatic cleanup of expired tokens

**Code Location**: `sical_security.py:86-87, 254-281`

---

## Error Handling

### Token Validation Errors

| Error | Cause | Solution | Code Location |
|-------|-------|----------|---------------|
| `"Missing confirmation token"` | No token provided with force_create | Always perform check_only first | `sical_security.py:161-162` |
| `"Invalid confirmation token"` | Token not found in memory | Token expired/cleaned up, retry from Phase 1 | `sical_security.py:164-166` |
| `"Token already used"` | Replay attack attempt | Get new token via check_only | `sical_security.py:171-176` |
| `"Token expired"` | User took > 5 minutes to confirm | Retry from Phase 1 | `sical_security.py:179-186` |
| `"Data tampering detected"` | Operation data changed between phases | Ensure data consistency | `sical_security.py:189-195` |

### Rate Limit Errors

| Error | Cause | Solution | Code Location |
|-------|-------|----------|---------------|
| `"Rate limit exceeded: hourly_limit"` | > 15 force_create ops in last hour (globally) | Wait or coordinate with other users | `sical_security.py:497-508` |
| `"Rate limit exceeded: daily_limit"` | > 30 force_create ops in last 24 hours (globally) | Wait until tomorrow or contact admin | `sical_security.py:497-508` |
| `"Operations only allowed during business hours"` | Attempt outside 7am-7pm Spanish time | Schedule during business hours | `sical_security.py:550-555` |

### Window Operation Errors

| Error | Cause | Solution | Code Location |
|-------|-------|----------|---------------|
| `"Failed to open Consulta window"` | SICAL menu navigation failed | Retry operation | `ado220_processor.py:312-313` |
| `"Failed to open Filters window"` | Dialog didn't appear | Retry operation | `ado220_processor.py:328-330` |
| `"Failed to open ADO220 window"` | SICAL menu navigation failed | Retry operation | `ado220_processor.py:421-423` |

---

## Rate Limiting

### Configuration

**Default Configuration** (`sical_security.py:716-736`):

```python
RateLimitConfig(
    windows=[
        # Hourly window
        RateLimitWindow(
            max_operations=15,
            time_window_seconds=3600,  # 60 minutes
            name='hourly_limit'
        ),
        # Daily window
        RateLimitWindow(
            max_operations=30,
            time_window_seconds=86400,  # 24 hours
            name='daily_limit'
        )
    ],
    business_hours=BusinessHours(
        start_hour=7,     # 7:00 AM
        end_hour=19,      # 7:00 PM (exclusive, so until 18:59)
        timezone='Europe/Madrid'
    )
)
```

### Scope: Global vs Per-Tercero

**IMPORTANT**: Rate limits are **GLOBAL**, not per-tercero. All force_create operations from all users and all terceros count toward the same shared limit.

**Example**:
- User A creates 10 operations for tercero "P4001500D"
- User B creates 6 operations for tercero "P5002000X"
- **Total**: 16 operations globally → Hourly limit exceeded!

**Rationale**: Prevents system abuse and maintains stability regardless of how users distribute operations across terceros.

### Business Hours Enforcement

**Location**: `sical_security.py:520-557`

```python
def _check_business_hours(self, timestamp: float) -> Tuple[bool, str]:
    tz = ZoneInfo('Europe/Madrid')
    dt = datetime.fromtimestamp(timestamp, tz=tz)
    current_hour = dt.hour

    if current_hour < 7 or current_hour >= 19:
        return False, (
            f"Operations only allowed during business hours: "
            f"7:00 - 19:00 Europe/Madrid. "
            f"Current time: {dt.strftime('%H:%M')} Europe/Madrid"
        )

    return True, ""
```

**Example Times** (Europe/Madrid timezone):
- ✅ 07:00 - Allowed
- ✅ 12:30 - Allowed
- ✅ 18:59 - Allowed
- ❌ 19:00 - Blocked (outside business hours)
- ❌ 21:00 - Blocked
- ❌ 02:00 - Blocked

---

## Sequence Diagrams

### Complete Two-Phase Flow

```
Producer                 Consumer                Security Module           SICAL System
   │                        │                          │                       │
   │─────check_only────────>│                          │                       │
   │                        │                          │                       │
   │                        │──validate_data──>        │                       │
   │                        │<─────ok──────────        │                       │
   │                        │                          │                       │
   │                        │──────────────────────────────open Consulta────>│
   │                        │<─────────────────────────────window opened──────│
   │                        │                          │                       │
   │                        │──────────────────────────────search────────────>│
   │                        │<─────────────────────────────results: 3─────────│
   │                        │                          │                       │
   │                        │──generate_token──────────>│                       │
   │                        │<─token_id, expires_at────│                       │
   │                        │                          │                       │
   │<────P_DUPLICATED──────│                          │                       │
   │  (token included)     │                          │                       │
   │                        │                          │                       │
   │  [User reviews         │                          │                       │
   │   duplicates and      │                          │                       │
   │   confirms]           │                          │                       │
   │                        │                          │                       │
   │──force_create─────────>│                          │                       │
   │  (with token)         │                          │                       │
   │                        │                          │                       │
   │                        │──validate_token──────────>│                       │
   │                        │  Check: exists?          │                       │
   │                        │  Check: not used?        │                       │
   │                        │  Check: not expired?     │                       │
   │                        │  Check: data match?      │                       │
   │                        │<────valid────────────────│                       │
   │                        │                          │                       │
   │                        │──check_rate_limit────────>│                       │
   │                        │<────allowed──────────────│                       │
   │                        │                          │                       │
   │                        │──────────────────────────────open ADO220──────>│
   │                        │<─────────────────────────────window opened──────│
   │                        │                          │                       │
   │                        │──────────────────────────────enter data────────>│
   │                        │──────────────────────────────validate──────────>│
   │                        │<─────────────────────────────num_op: 2025003───│
   │                        │──────────────────────────────print────────────>│
   │                        │──────────────────────────────order payment────>│
   │                        │<─────────────────────────────completed─────────│
   │                        │                          │                       │
   │<────COMPLETED─────────│                          │                       │
   │  (num_op: 2025003)    │                          │                       │
   │                        │                          │                       │
```

### Security Validation Flow (force_create)

```
┌────────────────────────────────────────────────────────────┐
│ _validate_force_create_token()                             │
│ (sical_base.py:297-347)                                    │
└────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────────┐
│ get_confirmation_manager().validate_token()                │
│ (sical_security.py:137-206)                                │
└────────────────────────────────────────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        │                               │
        ▼                               ▼
┌──────────────┐                ┌──────────────┐
│ Token Checks │                │ Rate Limit   │
└──────────────┘                └──────────────┘
        │                               │
        │ 1. Exists?                    │ 1. Hourly OK?
        │ 2. Not used?                  │ 2. Daily OK?
        │ 3. Not expired?               │ 3. Business hours?
        │ 4. Data match?                │
        │                               │
        ▼                               ▼
┌──────────────┐                ┌──────────────┐
│ Mark as used │                │ Record op    │
└──────────────┘                └──────────────┘
        │                               │
        └───────────────┬───────────────┘
                        │
                        ▼
                ┌───────────────┐
                │ audit_log()   │
                └───────────────┘
                        │
                        ▼
                ┌───────────────┐
                │ Return valid  │
                └───────────────┘
```

---

## Summary

The force_create process is a **secure, efficient, two-phase workflow** that:

1. **Phase 1 (check_only)**: Detects duplicates without committing to create
   - Opens Consulta window for searching
   - Generates security token if duplicates found
   - Returns immediately without opening ADO220 window

2. **Phase 2 (force_create)**: Creates operation after validation
   - Validates token BEFORE opening any windows
   - Enforces rate limits and business hours
   - Only opens ADO220 window if all security checks pass
   - Comprehensive audit logging

**Key Security Features**:
- Cryptographic tokens prevent unauthorized force_create
- Token expiration limits time window for abuse
- One-time token use prevents replay attacks
- Data integrity hash prevents tampering
- Global rate limiting prevents system abuse
- Business hours enforcement adds operational control

**Key Efficiency Features**:
- Early validation prevents wasteful window operations
- Token validation happens before window opening
- Duplicate checking reuses efficient Consulta window
- In-memory token storage for fast validation

**Code Quality**:
- Clear separation of concerns (base class orchestration, processor implementation, security module)
- Comprehensive error handling and logging
- Backward compatible (existing messages without duplicate_policy work)
- Well-documented with examples and integration guide

This design represents a **defense-in-depth security approach** while maintaining operational efficiency.

---

**End of Analysis**
