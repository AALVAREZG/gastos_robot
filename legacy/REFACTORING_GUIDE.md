# SICAL Gastos Robot - Refactoring Guide

## Overview

This document describes the major refactoring of the SICAL Gastos Robot codebase to introduce modular processor support for different operation types (ADO220, PMP450).

## New Architecture

### File Structure

```
gastos_robot/
├── sical_constants.py       # All UI paths and configuration constants
├── sical_config.py          # Account mappings and operation configs
├── sical_utils.py           # Shared utility functions
├── sical_base.py            # Abstract base classes and data structures
├── sical_logging.py         # Centralized logging configuration
├── processors/              # Operation-specific processors
│   ├── __init__.py
│   ├── ado220_processor.py  # ADO220 expense operation
│   └── pmp450_processor.py  # PMP450 expense operation
├── gasto_task_consumer.py   # Backwards-compatible wrapper
├── gasto_task_consumer_new.py # New refactored consumer
└── gastos_gui.py            # GUI (unchanged interface)
```

## Key Benefits

1. **Centralized Constants** - All UI paths in `sical_constants.py`
2. **Modular Processors** - Each operation type is self-contained
3. **Easy Configuration** - Just update constants for new operations
4. **Optimized Logging** - Only relevant information logged
5. **GUI Integration Preserved** - Same callback interface
6. **Backwards Compatibility** - Old imports still work

## Configuring PMP450 Paths

When you have SICAL access, update `sical_constants.py`:

```python
# Update PMP450 window pattern if different
SICAL_WINDOWS = {
    'pmp450': 'regex:.*SICAL II 4.2 <actual_pattern>',
    ...
}

# Update menu path
SICAL_MENU_PATHS = {
    'pmp450': ('ACTUAL', 'MENU', 'PATH'),
    ...
}

# Update form paths
PMP450_FORM_PATHS = {
    'cod_operacion': 'actual path',
    'fecha': 'actual path',
    ...
}

# Update operation code
OPERATION_CODES = {
    'pmp450': '450',  # or actual code
}
```

## GUI Integration

The GUI integration is fully preserved. The processors communicate with the GUI through:

1. **status_callback** - Task lifecycle events
2. **task_callback** - Detailed progress updates (line items, phases)

Enhanced features:
- Line item progress tracking
- Phase completion notifications
- Detailed error reporting

## Adding New Operation Types

1. Create new processor in `processors/`:
   ```python
   from sical_base import SicalOperationProcessor

   class NewOperationProcessor(SicalOperationProcessor):
       @property
       def operation_type(self): return 'new_type'

       @property
       def operation_name(self): return 'New Operation'

       def create_window_manager(self): ...
       def create_operation_data(self, data): ...
       def setup_operation_window(self): ...
       def process_operation_form(self, data, result): ...
   ```

2. Add constants to `sical_constants.py`
3. Register in `gasto_task_consumer_new.py`:
   ```python
   OPERATION_PROCESSORS = {
       'new_type': NewOperationProcessor,
       ...
   }
   ```

## Migration from Old Code

- `gasto_tasks.py` - Legacy, kept for reference only
- `tasks.py` - Can be removed (duplicate code)
- Old imports work via backwards-compatible wrapper

## Testing

Run the consumer:
```bash
python gasto_task_consumer_new.py
```

Or use with GUI (unchanged):
```bash
python gastos_gui.py
```
