# Rate Limiting Configuration Guide
## SICAL Gastos Robot - Administrator Documentation

**Version:** 1.0
**Last Updated:** 2025-01-17

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Default Configuration](#default-configuration)
3. [Security Model](#security-model)
4. [Managing Configuration](#managing-configuration)
5. [Configuration File Format](#configuration-file-format)
6. [Environment Variables](#environment-variables)
7. [Monitoring](#monitoring)
8. [Troubleshooting](#troubleshooting)

---

## Overview

The SICAL Gastos Robot implements **multi-window rate limiting** with **business hours enforcement** to prevent abuse of the `force_create` duplicate override functionality.

### Protection Layers

1. **Token-based confirmation** - Only valid tokens from duplicate checks can authorize force_create
2. **Multi-window rate limiting** - Multiple time windows enforce different limits
3. **Business hours** - Operations restricted to working hours
4. **Cryptographic signatures** - Configuration files are tamper-proof

---

## Default Configuration

The system uses these defaults if no configuration file is present:

### Rate Limit Windows

| Window | Limit | Time Period | Purpose |
|--------|-------|-------------|---------|
| **Hourly Limit** | 15 operations | 60 minutes | Prevent short-term abuse |
| **Daily Limit** | 30 operations | 24 hours | Prevent long-term abuse |

### Business Hours

- **Start Time:** 7:00 AM
- **End Time:** 7:00 PM (19:00)
- **Timezone:** Europe/Madrid (Spanish time)
- **Enforcement:** Operations outside these hours are rejected

### Per-Tercero Tracking

All rate limits are enforced **per tercero** (third party identifier). Each tercero has independent limits.

---

## Security Model

### Why Cryptographic Signatures?

Configuration files are signed with HMAC-SHA256 to prevent unauthorized modification:

```
✅ Valid signature   → Configuration loaded
❌ Invalid signature → Configuration REJECTED, defaults used
❌ Missing config    → Defaults used
```

### Threat Model

**Without signatures:**
- Malicious user modifies `rate_limit_config.json`
- Changes 15 ops/hour to 10000 ops/hour
- Bypasses rate limiting entirely

**With signatures:**
- Malicious user modifies configuration
- Signature verification fails
- System rejects tampered config and uses secure defaults
- Security audit log records tampering attempt

---

## Managing Configuration

### Initial Setup

1. **Set the secret key (REQUIRED for production):**

```bash
export SICAL_CONFIG_SECRET_KEY="your-secure-random-key-here"
```

⚠️ **Important:** Use a strong random key and keep it secret!

```bash
# Generate a secure key
python3 -c "import secrets; print(secrets.token_hex(32))"
```

2. **Generate the default configuration:**

```bash
python3 generate_rate_config.py
```

This creates `rate_limit_config.json` with default values.

### Modifying Configuration

**⚠️ DO NOT manually edit `rate_limit_config.json`!**

Manual edits will be rejected due to signature validation.

**Correct procedure:**

1. Edit `generate_rate_config.py` to modify the configuration
2. Run the script to regenerate the signed configuration file
3. Restart the consumer to load new configuration

### Example: Custom Configuration

Edit `generate_rate_config.py`:

```python
# Change this section in generate_rate_config.py
config = RateLimitConfig(
    windows=[
        RateLimitWindow(
            max_operations=20,      # Changed from 15
            time_window_seconds=3600,
            name='hourly_limit'
        ),
        RateLimitWindow(
            max_operations=50,      # Changed from 30
            time_window_seconds=86400,
            name='daily_limit'
        ),
        # Add new window - weekly limit
        RateLimitWindow(
            max_operations=150,
            time_window_seconds=604800,  # 7 days
            name='weekly_limit'
        )
    ],
    business_hours=BusinessHours(
        start_hour=8,           # Changed from 7
        end_hour=20,            # Changed from 19
        timezone='Europe/Madrid'
    )
)
```

Then regenerate:

```bash
python3 generate_rate_config.py
# Restart consumer to apply changes
```

### Disabling Business Hours

To allow operations 24/7, edit `generate_rate_config.py`:

```python
config = RateLimitConfig(
    windows=[
        # ... your windows ...
    ],
    business_hours=None  # Disable business hours enforcement
)
```

---

## Configuration File Format

### File Structure

```json
{
  "signature": "a1b2c3d4e5f6...",
  "config": {
    "windows": [
      {
        "max_operations": 15,
        "time_window_seconds": 3600,
        "name": "hourly_limit"
      },
      {
        "max_operations": 30,
        "time_window_seconds": 86400,
        "name": "daily_limit"
      }
    ],
    "business_hours": {
      "start_hour": 7,
      "end_hour": 19,
      "timezone": "Europe/Madrid"
    }
  },
  "generated_at": "2025-01-17T10:30:00.000Z",
  "note": "This file is cryptographically signed. Manual edits will be rejected."
}
```

### Field Descriptions

#### Windows

| Field | Type | Description |
|-------|------|-------------|
| `max_operations` | Integer | Maximum operations allowed in time window |
| `time_window_seconds` | Integer | Time window in seconds |
| `name` | String | Descriptive name for logging |

**Common time windows:**
- 60 seconds = 1 minute
- 3600 seconds = 1 hour
- 86400 seconds = 1 day
- 604800 seconds = 1 week

#### Business Hours

| Field | Type | Description |
|-------|------|-------------|
| `start_hour` | Integer (0-23) | Hour when operations allowed (inclusive) |
| `end_hour` | Integer (0-23) | Hour when operations stop (exclusive) |
| `timezone` | String | IANA timezone name |

**Valid timezones:**
- `Europe/Madrid` (Spanish time)
- `Europe/London` (UK time)
- `America/New_York` (US Eastern)
- See [IANA timezone database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

---

## Environment Variables

### SICAL_CONFIG_SECRET_KEY

**Purpose:** Secret key for HMAC signature verification

**Security:**
- ✅ Set in environment or secure secret management system
- ✅ Use minimum 32-byte random key
- ❌ Do NOT commit to git
- ❌ Do NOT share with unauthorized users
- ❌ Do NOT store in code or .env file (in production)

**Setting the variable:**

```bash
# Linux/Mac (temporary)
export SICAL_CONFIG_SECRET_KEY="your-key-here"

# Linux/Mac (permanent - add to ~/.bashrc or ~/.profile)
echo 'export SICAL_CONFIG_SECRET_KEY="your-key-here"' >> ~/.bashrc

# Windows (temporary)
set SICAL_CONFIG_SECRET_KEY=your-key-here

# Windows (permanent)
setx SICAL_CONFIG_SECRET_KEY "your-key-here"

# Docker
docker run -e SICAL_CONFIG_SECRET_KEY="your-key-here" ...

# Systemd service
Environment="SICAL_CONFIG_SECRET_KEY=your-key-here"
```

---

## Monitoring

### Checking Current Configuration

```python
from sical_security import get_rate_limiter

limiter = get_rate_limiter()
config = limiter.config

# Display configuration
print(f"Rate limit windows:")
for window in config.windows:
    print(f"  {window.name}: {window.max_operations} ops per {window.time_window_seconds}s")

if config.business_hours:
    bh = config.business_hours
    print(f"Business hours: {bh.start_hour}:00 - {bh.end_hour}:00 {bh.timezone}")
```

### Log Messages

Rate limiting events are logged with these patterns:

**Initialization:**
```
INFO: MultiWindowRateLimiter initialized: 15 ops per 3600s (hourly_limit), 30 ops per 86400s (daily_limit)
INFO: Business hours enforced: 7:00 - 19:00 Europe/Madrid
```

**Rate limit exceeded:**
```
WARNING: RATE LIMIT: Tercero P4001500D exceeded hourly_limit limit: 15/15 operations in last 3600s
```

**Business hours violation:**
```
WARNING: BUSINESS HOURS: Operation attempted at 21:30 Europe/Madrid, outside allowed hours 7:00-19:00
```

**Configuration issues:**
```
WARNING: Config file not found: rate_limit_config.json, using defaults
ERROR: SECURITY: Invalid configuration signature in rate_limit_config.json! Configuration may have been tampered with.
```

### Security Audit Log

All `force_create` attempts (successful or rejected) are logged to:

**File:** `security_audit.jsonl`

**Format:** JSON Lines (one JSON object per line)

```json
{"timestamp": "2025-01-17T14:30:00", "action": "force_create_attempt", "token_valid": false, "tercero": "P4001500D", "error": "Rate limit exceeded: hourly_limit allows maximum 15 operations per 60 minutes"}
```

**Monitoring script example:**

```bash
# Show recent rate limit violations
grep "Rate limit exceeded" security_audit.jsonl | tail -20

# Count failed force_create attempts by tercero
jq -r 'select(.token_valid == false) | .tercero' security_audit.jsonl | sort | uniq -c | sort -rn
```

---

## Troubleshooting

### Configuration Not Loading

**Symptom:** Logs show "using defaults" despite having config file

**Possible causes:**

1. **Signature mismatch**
   - Check: Look for "Invalid configuration signature" in logs
   - Solution: Regenerate config with `generate_rate_config.py`

2. **Different secret key**
   - Check: `SICAL_CONFIG_SECRET_KEY` changed since config generation
   - Solution: Use same key OR regenerate config with new key

3. **File corruption**
   - Check: Is `rate_limit_config.json` valid JSON?
   - Solution: Regenerate config

### Rate Limits Too Strict

**Symptom:** Legitimate operations being rejected

**Solutions:**

1. Increase rate limits in `generate_rate_config.py`
2. Add additional time windows (e.g., weekly limit)
3. Temporarily disable business hours if needed
4. Check if operations should use `check_only` instead

### Business Hours Timezone Issues

**Symptom:** Operations rejected at wrong times

**Check:**
```python
from datetime import datetime
from zoneinfo import ZoneInfo

# Check current time in configured timezone
tz = ZoneInfo('Europe/Madrid')
now = datetime.now(tz)
print(f"Current time in Madrid: {now.strftime('%H:%M')}")
```

**Solution:** Verify timezone string is correct IANA format

### Secret Key Not Persisting

**Symptom:** "temporary key will be generated" warning on each restart

**Solution:** Set `SICAL_CONFIG_SECRET_KEY` in environment permanently (see Environment Variables section)

---

## Best Practices

### Security

1. ✅ Always set `SICAL_CONFIG_SECRET_KEY` in production
2. ✅ Rotate secret key periodically (requires config regeneration)
3. ✅ Monitor `security_audit.jsonl` for suspicious patterns
4. ✅ Protect configuration files with appropriate file permissions
5. ✅ Use version control for `generate_rate_config.py` (NOT the JSON file)

### Operations

1. ✅ Test configuration changes in development first
2. ✅ Document reason for rate limit changes
3. ✅ Monitor logs after configuration updates
4. ✅ Keep backup of working configuration
5. ✅ Plan configuration changes during low-traffic periods

### Monitoring

1. ✅ Set up alerts for repeated rate limit violations
2. ✅ Review audit logs weekly
3. ✅ Track rate limit hit rates over time
4. ✅ Adjust limits based on actual usage patterns

---

## Support

For issues or questions:

1. Check consumer logs for detailed error messages
2. Review `security_audit.jsonl` for pattern analysis
3. Verify configuration with monitoring scripts
4. Contact development team with log excerpts

---

## Appendix: Quick Reference

### Generate New Configuration
```bash
python3 generate_rate_config.py
```

### Check Current Config
```bash
cat rate_limit_config.json | jq '.config'
```

### Monitor Rate Limit Events
```bash
tail -f consumer.log | grep "RATE LIMIT"
```

### Analyze Audit Log
```bash
tail -100 security_audit.jsonl | jq 'select(.error != null)'
```

### Test Configuration Loading
```python
from sical_security import load_rate_limit_config
config = load_rate_limit_config()
print(f"Loaded {len(config.windows)} rate limit windows")
```
