#!/usr/bin/env python3
"""
Test script for rate limiting functionality.
"""

import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

# Set test secret key
os.environ['SICAL_CONFIG_SECRET_KEY'] = 'test-secret-key-12345678901234567890123456789012'

from sical_security import (
    RateLimitConfig,
    RateLimitWindow,
    BusinessHours,
    MultiWindowRateLimiter,
    save_rate_limit_config,
    load_rate_limit_config,
    SecureConfigLoader
)

def test_config_save_load():
    """Test saving and loading configuration."""
    print("=" * 70)
    print("Test 1: Save and Load Configuration")
    print("=" * 70)

    # Create test configuration
    config = RateLimitConfig(
        windows=[
            RateLimitWindow(15, 3600, 'hourly_limit'),
            RateLimitWindow(30, 86400, 'daily_limit')
        ],
        business_hours=BusinessHours(7, 19, 'Europe/Madrid')
    )

    # Save configuration
    test_file = 'test_rate_config.json'
    save_rate_limit_config(config, test_file)
    print(f"✓ Configuration saved to {test_file}")

    # Load configuration
    loaded_config = load_rate_limit_config(test_file)
    print(f"✓ Configuration loaded from {test_file}")

    # Verify
    assert len(loaded_config.windows) == 2, "Wrong number of windows"
    assert loaded_config.windows[0].max_operations == 15, "Wrong hourly limit"
    assert loaded_config.windows[1].max_operations == 30, "Wrong daily limit"
    assert loaded_config.business_hours.start_hour == 7, "Wrong start hour"
    assert loaded_config.business_hours.end_hour == 19, "Wrong end hour"

    print("✓ All configuration values verified")

    # Clean up
    os.remove(test_file)
    print(f"✓ Test file removed")
    print()


def test_tamper_detection():
    """Test that tampering is detected."""
    print("=" * 70)
    print("Test 2: Tamper Detection")
    print("=" * 70)

    # Create and save valid config
    config = RateLimitConfig(
        windows=[RateLimitWindow(10, 3600, 'test_limit')],
        business_hours=None
    )

    test_file = 'test_tamper.json'
    save_rate_limit_config(config, test_file)
    print(f"✓ Valid configuration saved")

    # Tamper with the file
    import json
    with open(test_file, 'r') as f:
        data = json.load(f)

    # Change max_operations
    data['config']['windows'][0]['max_operations'] = 10000

    with open(test_file, 'w') as f:
        json.dump(data, f)

    print("✓ Configuration tampered (changed 10 to 10000)")

    # Try to load - should fail and use defaults
    try:
        loaded_config = load_rate_limit_config(test_file)
        # Should get defaults, not tampered values
        if any(w.max_operations == 10000 for w in loaded_config.windows):
            print("✗ SECURITY FAILURE: Tampered config was accepted!")
            os.remove(test_file)
            sys.exit(1)
        else:
            print("✓ Tampered config rejected, defaults used")
    except ValueError as e:
        print(f"✓ Tampered config rejected with error: {e}")

    # Clean up
    os.remove(test_file)
    print(f"✓ Test file removed")
    print()


def test_multi_window_rate_limiter():
    """Test multi-window rate limiting."""
    print("=" * 70)
    print("Test 3: Multi-Window Rate Limiting")
    print("=" * 70)

    # Create rate limiter with tight limits for testing
    config = RateLimitConfig(
        windows=[
            RateLimitWindow(3, 10, 'short_limit'),  # 3 ops per 10 seconds
            RateLimitWindow(5, 20, 'medium_limit'),  # 5 ops per 20 seconds
        ],
        business_hours=None  # Disable for testing
    )

    limiter = MultiWindowRateLimiter(config)
    print("✓ Rate limiter created")

    tercero = "TEST-TERCERO"

    # Should allow first 3 operations
    for i in range(3):
        allowed, error = limiter.check_rate_limit(tercero)
        assert allowed, f"Operation {i+1} should be allowed: {error}"
        print(f"✓ Operation {i+1}/3 allowed")

    # 4th operation should be blocked by short_limit
    allowed, error = limiter.check_rate_limit(tercero)
    assert not allowed, "4th operation should be blocked"
    assert "short_limit" in error, f"Wrong error message: {error}"
    print(f"✓ Operation 4 blocked by short_limit: {error}")

    print()


def test_business_hours():
    """Test business hours enforcement."""
    print("=" * 70)
    print("Test 4: Business Hours Enforcement")
    print("=" * 70)

    # Create rate limiter with business hours
    config = RateLimitConfig(
        windows=[RateLimitWindow(100, 3600, 'test_limit')],
        business_hours=BusinessHours(9, 17, 'Europe/Madrid')  # 9 AM - 5 PM
    )

    limiter = MultiWindowRateLimiter(config)
    print("✓ Rate limiter with business hours created (9 AM - 5 PM Madrid)")

    # Get current time in Madrid
    madrid_tz = ZoneInfo('Europe/Madrid')
    now = datetime.now(madrid_tz)
    current_hour = now.hour

    print(f"Current time in Madrid: {now.strftime('%H:%M')}")

    # Test current time
    allowed, error = limiter.check_rate_limit("TEST")

    if 9 <= current_hour < 17:
        if allowed:
            print("✓ Operation allowed during business hours")
        else:
            print(f"✗ Operation should be allowed during business hours! Error: {error}")
    else:
        if not allowed:
            print(f"✓ Operation blocked outside business hours: {error}")
        else:
            print("✗ Operation should be blocked outside business hours!")

    print()


def test_default_config():
    """Test default configuration."""
    print("=" * 70)
    print("Test 5: Default Configuration")
    print("=" * 70)

    # Load config when file doesn't exist
    config = load_rate_limit_config('nonexistent_file.json')

    # Should get defaults
    assert len(config.windows) == 2, "Should have 2 windows"
    assert config.windows[0].max_operations == 15, "Default hourly should be 15"
    assert config.windows[1].max_operations == 30, "Default daily should be 30"
    assert config.business_hours is not None, "Should have business hours"
    assert config.business_hours.start_hour == 7, "Should start at 7 AM"
    assert config.business_hours.end_hour == 19, "Should end at 7 PM"
    assert config.business_hours.timezone == 'Europe/Madrid', "Should use Madrid timezone"

    print("✓ Default configuration loaded correctly")
    print(f"  - Hourly limit: {config.windows[0].max_operations} ops/hour")
    print(f"  - Daily limit: {config.windows[1].max_operations} ops/day")
    print(f"  - Business hours: {config.business_hours.start_hour}:00 - {config.business_hours.end_hour}:00 {config.business_hours.timezone}")
    print()


def main():
    """Run all tests."""
    print()
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "RATE LIMITING TEST SUITE" + " " * 29 + "║")
    print("╚" + "═" * 68 + "╝")
    print()

    try:
        test_default_config()
        test_config_save_load()
        test_tamper_detection()
        test_multi_window_rate_limiter()
        test_business_hours()

        print("=" * 70)
        print("✓ ALL TESTS PASSED")
        print("=" * 70)
        print()
        return 0

    except AssertionError as e:
        print()
        print("=" * 70)
        print(f"✗ TEST FAILED: {e}")
        print("=" * 70)
        print()
        return 1
    except Exception as e:
        print()
        print("=" * 70)
        print(f"✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 70)
        print()
        return 1


if __name__ == '__main__':
    sys.exit(main())
