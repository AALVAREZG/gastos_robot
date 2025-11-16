"""
SICAL Gasto Task Consumer - RabbitMQ message consumer for SICAL operations.

This is the backwards-compatible wrapper that maintains the original interface
while using the new refactored processor system internally.

For new implementations, use gasto_task_consumer_new.py directly.
"""

# Re-export from the new module for backwards compatibility
from gasto_task_consumer_new import GastoConsumer, OPERATION_PROCESSORS

# Also re-export from sical_base for backwards compatibility with old imports
from sical_base import OperationEncoder, OperationResult, OperationStatus

# Import legacy function signatures for compatibility
from processors.ado220_processor import ADO220Processor


def operacion_gastoADO220(operation_data, gasto_logger):
    """
    Backwards compatible wrapper for ADO220 operations.

    This function maintains the old signature while using the new processor.

    Args:
        operation_data: Operation data dictionary
        gasto_logger: Logger instance

    Returns:
        OperationResult from the processor
    """
    processor = ADO220Processor(gasto_logger)
    return processor.execute(operation_data)


def operacion_gastoPMP450(operation_data, gasto_logger):
    """
    New PMP450 operation handler.

    Args:
        operation_data: Operation data dictionary
        gasto_logger: Logger instance

    Returns:
        OperationResult from the processor
    """
    from processors.pmp450_processor import PMP450Processor
    processor = PMP450Processor(gasto_logger)
    return processor.execute(operation_data)


__all__ = [
    'GastoConsumer',
    'OPERATION_PROCESSORS',
    'OperationEncoder',
    'OperationResult',
    'OperationStatus',
    'operacion_gastoADO220',
    'operacion_gastoPMP450',
]
