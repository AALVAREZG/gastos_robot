"""
SICAL Security Module - Token-based duplicate confirmation system.

This module provides cryptographic security for duplicate override operations,
preventing malicious users from bypassing duplicate checks.

Security Features:
- Confirmation tokens for force_create operations
- Token expiration (5 minutes by default)
- One-time token usage (prevents replay attacks)
- Operation data validation (prevents tampering)
- HMAC-based cryptographic verification
- Rate limiting per tercero
- Comprehensive audit logging
"""

import hashlib
import hmac
import json
import time
import logging
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import secrets
import os

# Get logger
logger = logging.getLogger(__name__)


@dataclass
class ConfirmationToken:
    """
    Token for confirming duplicate override.

    Attributes:
        token_id: Unique token identifier
        operation_hash: HMAC hash of operation data
        created_at: Unix timestamp of creation
        expires_at: Unix timestamp of expiration
        used: Whether the token has been consumed
        tercero: Third party identifier (for rate limiting)
    """
    token_id: str
    operation_hash: str
    created_at: float
    expires_at: float
    used: bool = False
    tercero: Optional[str] = None


class DuplicateConfirmationManager:
    """
    Manages confirmation tokens for duplicate override operations.

    This class implements a secure token system to ensure that force_create
    operations can only be performed after a valid duplicate check has been
    completed and the user has acknowledged the duplicates.

    Security Guarantees:
    - Tokens expire after configurable lifetime (default 5 minutes)
    - Tokens can only be used once (prevents replay attacks)
    - Tokens are cryptographically tied to specific operation data
    - Token validation prevents data tampering
    - All force_create attempts are logged for auditing
    """

    def __init__(
        self,
        token_lifetime_seconds: int = 300,
        secret_key: Optional[str] = None
    ):
        """
        Initialize the confirmation manager.

        Args:
            token_lifetime_seconds: Token validity period (default 5 minutes)
            secret_key: Secret key for HMAC (generated if not provided)
        """
        self.token_lifetime = token_lifetime_seconds
        self.secret_key = secret_key or secrets.token_hex(32)
        self.tokens: Dict[str, ConfirmationToken] = {}
        self._cleanup_interval = 60  # Clean up expired tokens every minute
        self._last_cleanup = time.time()

        logger.info(f'DuplicateConfirmationManager initialized with {token_lifetime_seconds}s token lifetime')

    def generate_token(self, operation_data: Dict[str, Any]) -> Tuple[str, float]:
        """
        Generate a confirmation token for the given operation.

        This method creates a cryptographically secure token that is tied
        to the specific operation data. The token can only be used once
        and expires after the configured lifetime.

        Args:
            operation_data: The operation data to be protected

        Returns:
            Tuple of (token_id, expires_at_timestamp)
        """
        # Create operation hash (deterministic representation)
        operation_hash = self._hash_operation_data(operation_data)

        # Generate unique token ID
        token_id = secrets.token_urlsafe(32)

        # Create token
        now = time.time()
        expires_at = now + self.token_lifetime

        token = ConfirmationToken(
            token_id=token_id,
            operation_hash=operation_hash,
            created_at=now,
            expires_at=expires_at,
            used=False,
            tercero=operation_data.get('tercero')
        )

        # Store token
        self.tokens[token_id] = token

        logger.info(
            f'Generated confirmation token: {token_id[:16]}... '
            f'for tercero: {token.tercero}, expires in {self.token_lifetime}s'
        )

        # Cleanup old tokens periodically
        self._cleanup_expired_tokens()

        return token_id, expires_at

    def validate_token(
        self,
        token_id: Optional[str],
        operation_data: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Validate a confirmation token.

        This method performs comprehensive validation:
        1. Token exists
        2. Token not expired
        3. Token not already used
        4. Operation data matches token hash

        Args:
            token_id: The token to validate
            operation_data: The operation data to verify against

        Returns:
            Tuple of (is_valid, error_message)
            If is_valid is True, error_message is empty string
        """
        # Check token exists
        if not token_id:
            logger.warning('SECURITY: Missing confirmation token for force_create')
            return False, "Missing confirmation token - force_create requires valid token from duplicate check"

        if token_id not in self.tokens:
            logger.warning(f'SECURITY: Invalid confirmation token: {token_id[:16]}...')
            return False, "Invalid confirmation token - token not found or already expired"

        token = self.tokens[token_id]

        # Check not already used
        if token.used:
            logger.warning(
                f'SECURITY: Replay attack detected - token already used: {token_id[:16]}... '
                f'for tercero: {token.tercero}'
            )
            return False, "Confirmation token already used - each token can only be used once"

        # Check not expired
        now = time.time()
        if now > token.expires_at:
            age_seconds = now - token.created_at
            logger.warning(
                f'SECURITY: Expired token used: {token_id[:16]}... '
                f'age: {age_seconds:.0f}s, max: {self.token_lifetime}s'
            )
            return False, f"Confirmation token expired - tokens are valid for {self.token_lifetime} seconds"

        # Verify operation data matches
        operation_hash = self._hash_operation_data(operation_data)
        if operation_hash != token.operation_hash:
            logger.error(
                f'SECURITY: Data tampering detected! Token hash mismatch for {token_id[:16]}... '
                f'Expected: {token.operation_hash[:16]}..., Got: {operation_hash[:16]}...'
            )
            return False, "Confirmation token does not match operation data - possible tampering detected"

        # Mark as used (consume the token)
        token.used = True
        time_remaining = token.expires_at - now

        logger.info(
            f'Token validated successfully: {token_id[:16]}... '
            f'for tercero: {token.tercero}, {time_remaining:.0f}s remaining'
        )

        return True, ""

    def _hash_operation_data(self, operation_data: Dict[str, Any]) -> str:
        """
        Create a cryptographic hash of operation data.

        This creates a deterministic HMAC hash that will be the same for
        identical operations but different if any key field changes.

        The hash includes all fields that identify a unique operation:
        - tercero (third party)
        - fecha (date)
        - caja (cash register)
        - aplicaciones (line items with funcional, economica, importe)

        Args:
            operation_data: Operation data to hash

        Returns:
            Hex-encoded HMAC-SHA256 hash
        """
        # Extract key fields for hashing (fields that identify the operation)
        key_fields = {
            'tercero': operation_data.get('tercero'),
            'fecha': operation_data.get('fecha'),
            'caja': operation_data.get('caja'),
            'aplicaciones': [
                {
                    'funcional': app.get('funcional'),
                    'economica': app.get('economica'),
                    'importe': str(app.get('importe')),  # Convert to string for consistency
                }
                for app in operation_data.get('aplicaciones', [])
            ]
        }

        # Create deterministic JSON string (sorted keys for consistency)
        json_str = json.dumps(key_fields, sort_keys=True, separators=(',', ':'))

        # Create HMAC-SHA256 hash
        hash_obj = hmac.new(
            self.secret_key.encode(),
            json_str.encode(),
            hashlib.sha256
        )

        return hash_obj.hexdigest()

    def _cleanup_expired_tokens(self) -> None:
        """
        Remove expired tokens from memory.

        This runs periodically (based on cleanup_interval) to prevent
        memory buildup from expired tokens.
        """
        now = time.time()

        # Only cleanup periodically
        if now - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = now

        # Find expired tokens
        expired_tokens = [
            token_id
            for token_id, token in self.tokens.items()
            if now > token.expires_at
        ]

        # Remove expired tokens
        for token_id in expired_tokens:
            del self.tokens[token_id]

        if expired_tokens:
            logger.debug(f'Cleaned up {len(expired_tokens)} expired tokens')

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about token usage.

        Returns:
            Dictionary with token statistics
        """
        now = time.time()
        active_tokens = sum(1 for t in self.tokens.values() if not t.used and now <= t.expires_at)
        used_tokens = sum(1 for t in self.tokens.values() if t.used)
        expired_tokens = sum(1 for t in self.tokens.values() if not t.used and now > t.expires_at)

        return {
            'total_tokens': len(self.tokens),
            'active_tokens': active_tokens,
            'used_tokens': used_tokens,
            'expired_tokens': expired_tokens,
            'token_lifetime_seconds': self.token_lifetime
        }


@dataclass
class RateLimitWindow:
    """Configuration for a single rate limit window."""
    max_operations: int
    time_window_seconds: int
    name: str


@dataclass
class BusinessHours:
    """Configuration for business hours restrictions."""
    start_hour: int  # 0-23
    end_hour: int    # 0-23
    timezone: str    # e.g., "Europe/Madrid"


@dataclass
class RateLimitConfig:
    """Complete rate limiting configuration."""
    windows: List[RateLimitWindow]
    business_hours: Optional[BusinessHours] = None


class SecureConfigLoader:
    """
    Loads and validates cryptographically signed configuration files.

    This prevents malicious users from tampering with security settings.
    Configuration files are JSON with HMAC-SHA256 signatures.
    """

    def __init__(self, secret_key: Optional[str] = None):
        """
        Initialize the secure config loader.

        Args:
            secret_key: Secret key for HMAC verification (from environment or generated)
        """
        # Use environment variable or generate a persistent key
        self.secret_key = secret_key or os.environ.get('SICAL_CONFIG_SECRET_KEY')

        if not self.secret_key:
            # Generate and warn (should be set in production)
            self.secret_key = secrets.token_hex(32)
            logger.warning(
                'SECURITY WARNING: No SICAL_CONFIG_SECRET_KEY found in environment. '
                'Generated temporary key. Configuration signatures will not persist across restarts. '
                'Set SICAL_CONFIG_SECRET_KEY environment variable for production use.'
            )

    def load_config(self, config_path: str) -> Dict[str, Any]:
        """
        Load and validate a signed configuration file.

        Args:
            config_path: Path to the configuration file

        Returns:
            Configuration dictionary

        Raises:
            ValueError: If signature is invalid or file is corrupted
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.warning(f'Config file not found: {config_path}, using defaults')
            return {}
        except json.JSONDecodeError as e:
            logger.error(f'Invalid JSON in config file {config_path}: {e}')
            raise ValueError(f'Corrupted configuration file: {e}')

        # Extract signature and config
        signature = data.get('signature')
        config = data.get('config')

        if not signature or not config:
            raise ValueError('Configuration file missing signature or config section')

        # Verify signature
        expected_signature = self._sign_config(config)
        if not hmac.compare_digest(signature, expected_signature):
            logger.error(
                f'SECURITY: Invalid configuration signature in {config_path}! '
                'Configuration may have been tampered with.'
            )
            raise ValueError('Configuration signature verification failed - possible tampering')

        logger.info(f'Configuration loaded and verified from {config_path}')
        return config

    def save_config(self, config: Dict[str, Any], config_path: str) -> None:
        """
        Save a signed configuration file.

        Args:
            config: Configuration dictionary
            config_path: Path to save the configuration
        """
        signature = self._sign_config(config)

        data = {
            'signature': signature,
            'config': config,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'note': 'This file is cryptographically signed. Manual edits will be rejected.'
        }

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        logger.info(f'Signed configuration saved to {config_path}')

    def _sign_config(self, config: Dict[str, Any]) -> str:
        """Create HMAC signature for configuration."""
        config_str = json.dumps(config, sort_keys=True, separators=(',', ':'))
        signature = hmac.new(
            self.secret_key.encode(),
            config_str.encode(),
            hashlib.sha256
        )
        return signature.hexdigest()


class MultiWindowRateLimiter:
    """
    Advanced rate limiter with multiple time windows and business hours enforcement.

    Supports:
    - Multiple concurrent time windows (e.g., 15/hour AND 30/day)
    - Business hours restrictions
    - Global tracking (across all terceros)
    - Secure configuration loading
    """

    def __init__(self, config: RateLimitConfig):
        """
        Initialize the multi-window rate limiter.

        Args:
            config: Rate limit configuration with windows and business hours
        """
        self.config = config
        self.operations: List[float] = []  # Global operation tracking

        # Log configuration
        window_info = ', '.join([
            f'{w.max_operations} ops per {w.time_window_seconds}s ({w.name})'
            for w in config.windows
        ])
        logger.info(f'MultiWindowRateLimiter initialized (GLOBAL): {window_info}')

        if config.business_hours:
            logger.info(
                f'Business hours enforced: {config.business_hours.start_hour}:00 - '
                f'{config.business_hours.end_hour}:00 {config.business_hours.timezone}'
            )

    def check_rate_limit(self, tercero: str) -> Tuple[bool, str]:
        """
        Check if operation exceeds any rate limit window or business hours.

        Note: Rate limits are GLOBAL (across all terceros), not per-tercero.

        Args:
            tercero: Third party identifier (logged for audit purposes only)

        Returns:
            Tuple of (allowed, error_message)
        """
        now = time.time()

        # Check business hours first
        if self.config.business_hours:
            allowed, error = self._check_business_hours(now)
            if not allowed:
                return False, error

        # Clean old operations for all windows
        max_window = max(w.time_window_seconds for w in self.config.windows)
        self.operations = [
            ts for ts in self.operations
            if now - ts < max_window
        ]

        # Check each window (globally)
        for window in self.config.windows:
            recent_ops = [
                ts for ts in self.operations
                if now - ts < window.time_window_seconds
            ]

            if len(recent_ops) >= window.max_operations:
                logger.warning(
                    f'RATE LIMIT (GLOBAL): {window.name} limit exceeded: '
                    f'{len(recent_ops)}/{window.max_operations} operations '
                    f'in last {window.time_window_seconds}s '
                    f'(attempted by tercero {tercero})'
                )
                return False, (
                    f"Rate limit exceeded: {window.name} allows maximum "
                    f"{window.max_operations} operations per "
                    f"{self._format_time_window(window.time_window_seconds)} globally"
                )

        # Record operation
        self.operations.append(now)

        logger.debug(
            f'Rate limit check passed (tercero {tercero}): '
            f'global counts: {[len([ts for ts in self.operations if now - ts < w.time_window_seconds]) for w in self.config.windows]}'
        )

        return True, ""

    def _check_business_hours(self, timestamp: float) -> Tuple[bool, str]:
        """
        Check if timestamp falls within configured business hours.

        Args:
            timestamp: Unix timestamp to check

        Returns:
            Tuple of (allowed, error_message)
        """
        if not self.config.business_hours:
            return True, ""

        bh = self.config.business_hours

        try:
            tz = ZoneInfo(bh.timezone)
        except Exception as e:
            logger.error(f'Invalid timezone {bh.timezone}: {e}')
            return True, ""  # Fail open if timezone is invalid

        dt = datetime.fromtimestamp(timestamp, tz=tz)
        current_hour = dt.hour

        # Check if within business hours
        if current_hour < bh.start_hour or current_hour >= bh.end_hour:
            logger.warning(
                f'BUSINESS HOURS: Operation attempted at {dt.strftime("%H:%M")} '
                f'{bh.timezone}, outside allowed hours '
                f'{bh.start_hour}:00-{bh.end_hour}:00'
            )
            return False, (
                f"Operations only allowed during business hours: "
                f"{bh.start_hour}:00 - {bh.end_hour}:00 {bh.timezone}. "
                f"Current time: {dt.strftime('%H:%M')} {bh.timezone}"
            )

        return True, ""

    def _format_time_window(self, seconds: int) -> str:
        """Format time window in human-readable form."""
        if seconds < 3600:
            return f"{seconds // 60} minutes"
        elif seconds < 86400:
            return f"{seconds // 3600} hour(s)"
        else:
            return f"{seconds // 86400} day(s)"


class RateLimiter:
    """
    DEPRECATED: Simple single-window rate limiter.

    Use MultiWindowRateLimiter for new implementations.
    This class is kept for backward compatibility.
    """

    def __init__(self, max_operations: int = 10, time_window: int = 3600):
        """
        Initialize the rate limiter.

        Args:
            max_operations: Maximum operations allowed per time window (globally)
            time_window: Time window in seconds (default 1 hour)
        """
        logger.warning(
            'RateLimiter is deprecated. Use MultiWindowRateLimiter for new implementations.'
        )
        self.max_operations = max_operations
        self.time_window = time_window
        self.operations: list = []  # Global operation tracking

        logger.info(
            f'RateLimiter initialized (GLOBAL): max {max_operations} operations '
            f'per {time_window}s'
        )

    def check_rate_limit(self, tercero: str) -> Tuple[bool, str]:
        """
        Check if operation exceeds rate limit.

        Note: Rate limits are GLOBAL (across all terceros), not per-tercero.

        Args:
            tercero: Third party identifier (logged for audit purposes only)

        Returns:
            Tuple of (allowed, error_message)
        """
        now = time.time()

        # Clean old operations outside the time window
        self.operations = [
            ts for ts in self.operations
            if now - ts < self.time_window
        ]

        # Check limit (globally)
        current_count = len(self.operations)
        if current_count >= self.max_operations:
            logger.warning(
                f'RATE LIMIT (GLOBAL): Limit exceeded: '
                f'{current_count}/{self.max_operations} operations in last {self.time_window}s '
                f'(attempted by tercero {tercero})'
            )
            return False, (
                f"Rate limit exceeded: maximum {self.max_operations} operations "
                f"per {self.time_window // 3600} hour(s) globally"
            )

        # Record operation
        self.operations.append(now)

        logger.debug(
            f'Rate limit check passed (tercero {tercero}): '
            f'{current_count + 1}/{self.max_operations} operations globally'
        )

        return True, ""


# Global instances (one per consumer process)
_confirmation_manager: Optional[DuplicateConfirmationManager] = None
_rate_limiter: Optional[MultiWindowRateLimiter] = None
_config_loader: Optional[SecureConfigLoader] = None


def get_confirmation_manager() -> DuplicateConfirmationManager:
    """
    Get the global confirmation manager instance.

    Creates a new instance on first call, then returns the same instance.

    Returns:
        DuplicateConfirmationManager instance
    """
    global _confirmation_manager
    if _confirmation_manager is None:
        _confirmation_manager = DuplicateConfirmationManager()
    return _confirmation_manager


def load_rate_limit_config(config_path: str = 'rate_limit_config.json') -> RateLimitConfig:
    """
    Load rate limit configuration from secure signed config file.

    If config file doesn't exist, returns default configuration:
    - 15 operations per 60 minutes
    - 30 operations per day
    - Business hours: 7am-7pm Europe/Madrid

    Args:
        config_path: Path to configuration file

    Returns:
        RateLimitConfig instance
    """
    global _config_loader

    if _config_loader is None:
        _config_loader = SecureConfigLoader()

    try:
        config_dict = _config_loader.load_config(config_path)

        if not config_dict:
            # Use defaults
            logger.info('Using default rate limit configuration')
            return _get_default_rate_limit_config()

        # Parse configuration
        windows = [
            RateLimitWindow(
                max_operations=w['max_operations'],
                time_window_seconds=w['time_window_seconds'],
                name=w['name']
            )
            for w in config_dict.get('windows', [])
        ]

        business_hours = None
        if 'business_hours' in config_dict:
            bh = config_dict['business_hours']
            business_hours = BusinessHours(
                start_hour=bh['start_hour'],
                end_hour=bh['end_hour'],
                timezone=bh['timezone']
            )

        return RateLimitConfig(windows=windows, business_hours=business_hours)

    except Exception as e:
        logger.error(f'Failed to load rate limit config: {e}, using defaults')
        return _get_default_rate_limit_config()


def _get_default_rate_limit_config() -> RateLimitConfig:
    """Get default rate limit configuration."""
    return RateLimitConfig(
        windows=[
            RateLimitWindow(
                max_operations=15,
                time_window_seconds=3600,  # 60 minutes
                name='hourly_limit'
            ),
            RateLimitWindow(
                max_operations=30,
                time_window_seconds=86400,  # 24 hours
                name='daily_limit'
            )
        ],
        business_hours=BusinessHours(
            start_hour=7,
            end_hour=19,  # 7pm (exclusive, so operations allowed until 18:59)
            timezone='Europe/Madrid'
        )
    )


def save_rate_limit_config(
    config: RateLimitConfig,
    config_path: str = 'rate_limit_config.json'
) -> None:
    """
    Save rate limit configuration to a secure signed file.

    This is used to generate initial configuration or update it.
    Only authorized administrators should use this function.

    Args:
        config: Rate limit configuration to save
        config_path: Path to save configuration

    Example:
        config = RateLimitConfig(
            windows=[
                RateLimitWindow(15, 3600, 'hourly_limit'),
                RateLimitWindow(30, 86400, 'daily_limit')
            ],
            business_hours=BusinessHours(7, 19, 'Europe/Madrid')
        )
        save_rate_limit_config(config)
    """
    global _config_loader

    if _config_loader is None:
        _config_loader = SecureConfigLoader()

    config_dict = {
        'windows': [
            {
                'max_operations': w.max_operations,
                'time_window_seconds': w.time_window_seconds,
                'name': w.name
            }
            for w in config.windows
        ]
    }

    if config.business_hours:
        config_dict['business_hours'] = {
            'start_hour': config.business_hours.start_hour,
            'end_hour': config.business_hours.end_hour,
            'timezone': config.business_hours.timezone
        }

    _config_loader.save_config(config_dict, config_path)
    logger.info(f'Rate limit configuration saved to {config_path}')


def get_rate_limiter() -> MultiWindowRateLimiter:
    """
    Get the global rate limiter instance.

    Creates a new instance on first call with configuration loaded from
    rate_limit_config.json (or defaults if not found).

    Returns:
        MultiWindowRateLimiter instance
    """
    global _rate_limiter
    if _rate_limiter is None:
        config = load_rate_limit_config()
        _rate_limiter = MultiWindowRateLimiter(config)
    return _rate_limiter


def audit_log_force_create(
    operation_data: Dict[str, Any],
    token_valid: bool,
    error_message: str = ""
) -> None:
    """
    Log force_create attempts for security auditing.

    All attempts to use force_create are logged, whether successful or not,
    to provide an audit trail for security review.

    Args:
        operation_data: The operation data
        token_valid: Whether the token validation succeeded
        error_message: Error message if validation failed
    """
    audit_entry = {
        'timestamp': datetime.now().isoformat(),
        'action': 'force_create_attempt',
        'token_valid': token_valid,
        'tercero': operation_data.get('tercero'),
        'fecha': operation_data.get('fecha'),
        'total_importe': sum(
            float(app.get('importe', 0))
            for app in operation_data.get('aplicaciones', [])
        ),
        'token': operation_data.get('duplicate_confirmation_token', 'MISSING')[:16] + '...',
        'error': error_message if not token_valid else None
    }

    # Log to application logger
    if token_valid:
        logger.info(f"AUDIT: force_create approved - {audit_entry}")
    else:
        logger.warning(f"AUDIT: force_create REJECTED - {audit_entry}")

    # Optionally write to dedicated audit file
    try:
        with open('security_audit.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(audit_entry) + '\n')
    except Exception as e:
        logger.error(f'Failed to write to audit log file: {e}')
