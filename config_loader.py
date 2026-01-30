"""
Configuration loader for SICAL Gastos Robot

This module handles loading configuration from config.py, supporting both:
- Normal Python script execution
- Frozen PyInstaller executable

When running as an executable, it looks for config.py in the same
directory as the .exe file, allowing users to edit credentials without
rebuilding the executable.

Usage:
    from config_loader import get_config, RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASS
"""

import sys
import os
import importlib.util


def get_application_path():
    """
    Get the directory where the application is running from.

    For frozen executables (PyInstaller), this returns the directory
    containing the .exe file.

    For normal Python scripts, this returns the script's directory.

    Returns:
        str: Absolute path to the application directory
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        # sys.executable is the path to the .exe file
        return os.path.dirname(sys.executable)
    else:
        # Running as script
        return os.path.dirname(os.path.abspath(__file__))


def get_config_path():
    """
    Get the path to config.py.

    Returns:
        str: Absolute path to config.py
    """
    return os.path.join(get_application_path(), 'config.py')


def config_exists():
    """
    Check if config.py exists.

    Returns:
        bool: True if config.py exists
    """
    return os.path.exists(get_config_path())


def load_config():
    """
    Load configuration from config.py.

    This dynamically loads config.py from the application directory,
    which allows the executable to use an external config file.

    Returns:
        module: The loaded config module

    Raises:
        FileNotFoundError: If config.py doesn't exist
        ImportError: If config.py can't be loaded
    """
    config_path = get_config_path()

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}\n"
            f"Please create a config.py file with your RabbitMQ settings.\n"
            f"You can use config.py.example as a template."
        )

    # Dynamically load the config module from the file path
    spec = importlib.util.spec_from_file_location("config", config_path)
    config_module = importlib.util.module_from_spec(spec)

    # Add to sys.modules so other imports of 'config' find this one
    sys.modules['config'] = config_module

    spec.loader.exec_module(config_module)

    return config_module


def get_config():
    """
    Get configuration values as a dictionary.

    Returns:
        dict: Configuration values

    Raises:
        FileNotFoundError: If config.py doesn't exist
    """
    config = load_config()

    return {
        'RABBITMQ_HOST': getattr(config, 'RABBITMQ_HOST', 'localhost'),
        'RABBITMQ_PORT': getattr(config, 'RABBITMQ_PORT', 5672),
        'RABBITMQ_USER': getattr(config, 'RABBITMQ_USER', 'guest'),
        'RABBITMQ_PASS': getattr(config, 'RABBITMQ_PASS', 'guest'),
    }


# Pre-load config and export variables for compatibility
# This allows: from config_loader import RABBITMQ_HOST
_config = None
RABBITMQ_HOST = 'localhost'
RABBITMQ_PORT = 5672
RABBITMQ_USER = 'guest'
RABBITMQ_PASS = 'guest'


def init_config():
    """
    Initialize configuration variables.

    Call this at application startup to load the config.

    Returns:
        bool: True if config was loaded successfully
    """
    global _config, RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASS

    try:
        _config = get_config()
        RABBITMQ_HOST = _config['RABBITMQ_HOST']
        RABBITMQ_PORT = _config['RABBITMQ_PORT']
        RABBITMQ_USER = _config['RABBITMQ_USER']
        RABBITMQ_PASS = _config['RABBITMQ_PASS']
        return True
    except FileNotFoundError:
        return False


# Try to initialize on import (for backward compatibility)
# This will fail silently if config.py doesn't exist yet
try:
    if config_exists():
        init_config()
except Exception:
    pass  # Config will be loaded later when explicitly initialized
