"""
SICAL Logging Configuration - Centralized logging setup for the entire application.

This module provides a consistent logging configuration that:
- Logs only relevant, actionable information
- Uses structured log messages
- Supports multiple output formats (console, file)
- Integrates with GUI status updates
"""

import logging
import sys
from typing import Optional
from datetime import datetime


def setup_logging(
    level: int = logging.INFO,
    log_to_file: bool = False,
    log_file: Optional[str] = None,
    enable_console: bool = True
) -> None:
    """
    Configure logging for the SICAL automation system.

    Args:
        level: Logging level (INFO by default for production)
        log_to_file: Whether to also log to file
        log_file: Path to log file (if log_to_file is True)
        enable_console: Whether to enable console logging
    """
    # Clear any existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers = []

    # Set root logger level
    root_logger.setLevel(level)

    # Create formatter - concise but informative
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # Console handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_to_file and log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)  # More verbose in file
        file_formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # Configure specific logger levels to reduce noise
    _configure_third_party_loggers()


def _configure_third_party_loggers() -> None:
    """Configure logging levels for third-party libraries to reduce noise."""
    # Suppress verbose pika logs
    logging.getLogger('pika').setLevel(logging.WARNING)

    # Suppress robocorp internal logs (keep only warnings/errors)
    logging.getLogger('robocorp').setLevel(logging.WARNING)

    # Suppress urllib3 connection pool logs
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def get_operation_logger(operation_type: str) -> logging.Logger:
    """
    Get a logger configured for a specific operation type.

    Args:
        operation_type: The operation type (e.g., 'ado220', 'pmp450')

    Returns:
        Logger instance for the operation
    """
    logger_name = f'sical.{operation_type}'
    return logging.getLogger(logger_name)


def get_consumer_logger() -> logging.Logger:
    """
    Get a logger for the RabbitMQ consumer.

    Returns:
        Logger instance for the consumer
    """
    return logging.getLogger('sical.consumer')


def get_gui_logger() -> logging.Logger:
    """
    Get a logger for GUI components.

    Returns:
        Logger instance for GUI
    """
    return logging.getLogger('sical.gui')


class OperationLoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that adds operation context to log messages.

    This adapter automatically includes operation-specific information
    in every log message without cluttering the code.
    """

    def process(self, msg, kwargs):
        """Add operation context to the log message."""
        operation_info = self.extra.get('operation_info', {})

        if operation_info:
            context_parts = []
            if 'tercero' in operation_info:
                context_parts.append(f"Tercero: {operation_info['tercero']}")
            if 'num_operacion' in operation_info:
                context_parts.append(f"Op#: {operation_info['num_operacion']}")
            if 'amount' in operation_info:
                context_parts.append(f"Amount: {operation_info['amount']:.2f}")

            if context_parts:
                context_str = ' | '.join(context_parts)
                msg = f"[{context_str}] {msg}"

        return msg, kwargs


def create_operation_logger(
    operation_type: str,
    tercero: Optional[str] = None,
    num_operacion: Optional[str] = None,
    amount: Optional[float] = None
) -> OperationLoggerAdapter:
    """
    Create a logger adapter with operation context.

    Args:
        operation_type: The operation type
        tercero: Third party ID (optional)
        num_operacion: Operation number (optional)
        amount: Operation amount (optional)

    Returns:
        Logger adapter with operation context
    """
    base_logger = get_operation_logger(operation_type)

    operation_info = {}
    if tercero:
        operation_info['tercero'] = tercero
    if num_operacion:
        operation_info['num_operacion'] = num_operacion
    if amount is not None:
        operation_info['amount'] = amount

    return OperationLoggerAdapter(base_logger, {'operation_info': operation_info})


class SummarizedLogger:
    """
    A logger wrapper that summarizes repetitive operations.

    Instead of logging every UI interaction, this logger accumulates
    similar events and logs them in summary form.
    """

    def __init__(self, base_logger: logging.Logger):
        """
        Initialize the summarized logger.

        Args:
            base_logger: The base logger to use
        """
        self.logger = base_logger
        self._accumulated = {}

    def log_ui_action(self, action_type: str, details: str = '') -> None:
        """
        Log a UI action, accumulating similar actions.

        Args:
            action_type: Type of action (e.g., 'click', 'send_keys')
            details: Additional details
        """
        key = action_type
        if key not in self._accumulated:
            self._accumulated[key] = []
        self._accumulated[key].append(details)

    def flush(self, phase_name: str) -> None:
        """
        Flush accumulated logs as a summary.

        Args:
            phase_name: Name of the phase being summarized
        """
        if not self._accumulated:
            return

        summary_parts = []
        for action_type, details_list in self._accumulated.items():
            count = len(details_list)
            if count > 1:
                summary_parts.append(f"{action_type}: {count} operations")
            else:
                summary_parts.append(f"{action_type}: {details_list[0]}")

        summary = ', '.join(summary_parts)
        self.logger.info(f"{phase_name} - {summary}")

        self._accumulated = {}


# Logging decorators for common patterns

def log_phase(phase_name: str):
    """
    Decorator to log the start and end of a processing phase.

    Args:
        phase_name: Name of the phase being executed
    """
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            logger = getattr(self, 'logger', logging.getLogger(__name__))
            logger.info(f'Starting phase: {phase_name}')
            try:
                result = func(self, *args, **kwargs)
                logger.info(f'Completed phase: {phase_name}')
                return result
            except Exception as e:
                logger.error(f'Phase {phase_name} failed: {e}')
                raise
        return wrapper
    return decorator


def log_operation_boundary(func):
    """
    Decorator to log operation start and end with timing.

    This decorator should be applied to main operation methods.
    """
    def wrapper(self, *args, **kwargs):
        logger = getattr(self, 'logger', logging.getLogger(__name__))
        operation_name = getattr(self, 'operation_name', 'Unknown')

        start_time = datetime.now()
        logger.info(f'{"=" * 60}')
        logger.info(f'Starting {operation_name} operation at {start_time.strftime("%H:%M:%S")}')

        try:
            result = func(self, *args, **kwargs)

            end_time = datetime.now()
            duration = end_time - start_time
            logger.info(f'Completed {operation_name} operation')
            logger.info(f'Duration: {duration}')
            logger.info(f'{"=" * 60}')

            return result

        except Exception as e:
            end_time = datetime.now()
            duration = end_time - start_time
            logger.error(f'{operation_name} operation failed after {duration}')
            logger.error(f'Error: {e}')
            logger.info(f'{"=" * 60}')
            raise

    return wrapper
