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
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime
import secrets

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


class RateLimiter:
    """
    Rate limiter to prevent mass duplicate creation.

    Limits the number of operations that can be created per tercero
    within a configurable time window.
    """

    def __init__(self, max_operations: int = 10, time_window: int = 3600):
        """
        Initialize the rate limiter.

        Args:
            max_operations: Maximum operations allowed per time window
            time_window: Time window in seconds (default 1 hour)
        """
        self.max_operations = max_operations
        self.time_window = time_window
        self.operations: Dict[str, list] = defaultdict(list)

        logger.info(
            f'RateLimiter initialized: max {max_operations} operations '
            f'per {time_window}s per tercero'
        )

    def check_rate_limit(self, tercero: str) -> Tuple[bool, str]:
        """
        Check if operation exceeds rate limit.

        Args:
            tercero: Third party identifier

        Returns:
            Tuple of (allowed, error_message)
        """
        now = time.time()

        # Clean old operations outside the time window
        self.operations[tercero] = [
            ts for ts in self.operations[tercero]
            if now - ts < self.time_window
        ]

        # Check limit
        current_count = len(self.operations[tercero])
        if current_count >= self.max_operations:
            logger.warning(
                f'RATE LIMIT: Tercero {tercero} exceeded limit: '
                f'{current_count}/{self.max_operations} operations in last {self.time_window}s'
            )
            return False, (
                f"Rate limit exceeded: maximum {self.max_operations} operations "
                f"per {self.time_window // 3600} hour(s) for tercero {tercero}"
            )

        # Record operation
        self.operations[tercero].append(now)

        logger.debug(
            f'Rate limit check passed for {tercero}: '
            f'{current_count + 1}/{self.max_operations} operations'
        )

        return True, ""


# Global instances (one per consumer process)
_confirmation_manager: Optional[DuplicateConfirmationManager] = None
_rate_limiter: Optional[RateLimiter] = None


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


def get_rate_limiter() -> RateLimiter:
    """
    Get the global rate limiter instance.

    Creates a new instance on first call, then returns the same instance.

    Returns:
        RateLimiter instance
    """
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
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
