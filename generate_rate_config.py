#!/usr/bin/env python3
"""
Utility script to generate secure rate limit configuration file.

This script creates a cryptographically signed configuration file for rate limiting.
Only authorized administrators should use this script.

Usage:
    python generate_rate_config.py

The generated file will be digitally signed to prevent tampering.
Set SICAL_CONFIG_SECRET_KEY environment variable for production use.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sical_security import (
    RateLimitConfig,
    RateLimitWindow,
    BusinessHours,
    save_rate_limit_config
)


def main():
    """Generate default rate limit configuration."""
    print("=" * 70)
    print("SICAL Rate Limit Configuration Generator")
    print("=" * 70)
    print()

    # Check if SICAL_CONFIG_SECRET_KEY is set
    secret_key = os.environ.get('SICAL_CONFIG_SECRET_KEY')
    if not secret_key:
        print("⚠️  WARNING: SICAL_CONFIG_SECRET_KEY environment variable not set!")
        print("   A temporary key will be generated, but signatures will not persist")
        print("   across restarts. Set this variable in production for security.")
        print()
        response = input("Continue anyway? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            return
        print()

    # Create configuration with user's requirements:
    # - 15 operations per 60 minutes
    # - 30 operations per day
    # - Business hours: 7am-7pm Europe/Madrid
    config = RateLimitConfig(
        windows=[
            RateLimitWindow(
                max_operations=15,
                time_window_seconds=3600,  # 60 minutes
                name='hourly_limit'
            ),
            RateLimitWindow(
                max_operations=30,
                time_window_seconds=86400,  # 24 hours (1 day)
                name='daily_limit'
            )
        ],
        business_hours=BusinessHours(
            start_hour=7,
            end_hour=19,  # 7pm (exclusive, so operations allowed until 18:59)
            timezone='Europe/Madrid'
        )
    )

    # Display configuration
    print("Configuration to be saved:")
    print("-" * 70)
    print(f"Rate Limits:")
    for window in config.windows:
        hours = window.time_window_seconds / 3600
        print(f"  • {window.name}: {window.max_operations} operations per {hours:.1f} hour(s)")

    if config.business_hours:
        bh = config.business_hours
        print(f"\nBusiness Hours:")
        print(f"  • Time: {bh.start_hour}:00 - {bh.end_hour}:00")
        print(f"  • Timezone: {bh.timezone}")
        print(f"  • Note: Operations outside these hours will be rejected")

    print("-" * 70)
    print()

    # Confirm
    response = input("Save this configuration? (yes/no): ")
    if response.lower() != 'yes':
        print("Aborted.")
        return

    # Save configuration
    config_path = 'rate_limit_config.json'
    try:
        save_rate_limit_config(config, config_path)
        print()
        print(f"✓ Configuration saved to: {config_path}")
        print()
        print("IMPORTANT SECURITY NOTES:")
        print("=" * 70)
        print("1. This file is cryptographically signed with HMAC-SHA256")
        print("2. Manual edits will be REJECTED by the consumer")
        print("3. To update configuration, run this script again")
        print("4. Protect the SICAL_CONFIG_SECRET_KEY environment variable")
        print("5. Only authorized administrators should modify this file")
        print()
        print("The configuration will be loaded automatically by the consumer.")
        print("=" * 70)

    except Exception as e:
        print(f"✗ Error saving configuration: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
