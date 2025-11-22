"""
SICAL Base Classes - Abstract base classes and common data structures.

This module defines the core abstractions for SICAL operation processors,
window managers, and result data structures.
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Callable

from robocorp import windows

from sical_constants import SICAL_WINDOWS, DEFAULT_TIMING
from sical_config import GUI_EVENTS


# =============================================================================
# ENUMS - Operation status definitions
# =============================================================================

class OperationStatus(Enum):
    """Status states for SICAL operations."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    P_DUPLICATED = "P_DUPLICATED"  # Possibly duplicated
    COMPLETED = "COMPLETED"
    INCOMPLETED = "INCOMPLETED"
    FAILED = "FAILED"

    def to_json(self):
        """Convert enum to string for JSON serialization."""
        return self.value


# =============================================================================
# DATA STRUCTURES - Common result and data classes
# =============================================================================

@dataclass
class OperationResult:
    """
    Result object for SICAL operations.

    This dataclass contains all information about an operation's execution,
    including status, timing, errors, and metadata.
    """
    status: OperationStatus
    init_time: str
    end_time: Optional[str] = None
    duration: Optional[str] = None
    error: Optional[str] = None
    num_operacion: Optional[str] = None
    total_operacion: Optional[float] = None
    suma_aplicaciones: Optional[float] = None
    sical_is_open: bool = False
    completed_phases: Optional[list] = field(default_factory=list)
    similiar_records_encountered: int = -1
    # Duplicate detection details
    duplicate_details: Optional[list] = field(default_factory=list)
    duplicate_check_metadata: Optional[dict] = field(default_factory=dict)
    # Security: Confirmation tokens for force_create
    duplicate_confirmation_token: Optional[str] = None
    duplicate_token_expires_at: Optional[float] = None


class OperationEncoder(json.JSONEncoder):
    """Custom JSON encoder for SICAL operation objects."""

    def default(self, obj):
        if isinstance(obj, OperationStatus):
            return obj.value
        if isinstance(obj, OperationResult):
            return {
                'status': obj.status.value,
                'init_time': obj.init_time,
                'end_time': obj.end_time,
                'duration': obj.duration,
                'error': obj.error,
                'num_operacion': obj.num_operacion,
                'total_operacion': obj.total_operacion,
                'suma_aplicaciones': obj.suma_aplicaciones,
                'sical_is_open': obj.sical_is_open,
                'completed_phases': obj.completed_phases,
                'similiar_records_encountered': obj.similiar_records_encountered,
                'duplicate_details': obj.duplicate_details,
                'duplicate_check_metadata': obj.duplicate_check_metadata,
                'duplicate_confirmation_token': obj.duplicate_confirmation_token,
                'duplicate_token_expires_at': obj.duplicate_token_expires_at,
            }
        return super().default(obj)


# =============================================================================
# WINDOW MANAGERS - Base class for SICAL window management
# =============================================================================

class SicalWindowManager(ABC):
    """
    Abstract base class for SICAL window managers.

    Each operation type has its own window manager that knows how to find,
    interact with, and close its specific SICAL window.
    """

    def __init__(self, logger: logging.Logger):
        """
        Initialize the window manager.

        Args:
            logger: Logger instance for this window manager
        """
        self.ventana_proceso = None
        self.logger = logger

    @property
    @abstractmethod
    def window_pattern(self) -> str:
        """Return the regex pattern for finding this window."""
        pass

    def find_proceso_window(self):
        """
        Find and return the process window.

        Returns:
            Window object if found, None otherwise
        """
        return windows.find_window(self.window_pattern, raise_error=False)

    def close_window(self) -> None:
        """Close the managed window safely."""
        if self.ventana_proceso:
            try:
                boton_cerrar = self.ventana_proceso.find(
                    'name:"Cerrar"',
                    search_depth=8,
                    raise_error=False
                )
                if boton_cerrar:
                    boton_cerrar.click()
                    self.ventana_proceso.find('class:"TButton" and name:"No"').click()
            except Exception as e:
                self.logger.warning(f'Error closing window: {e}')

    def is_window_open(self) -> bool:
        """Check if the managed window is currently open."""
        return self.ventana_proceso is not None


# =============================================================================
# OPERATION PROCESSORS - Abstract base class for operation processing
# =============================================================================

class SicalOperationProcessor(ABC):
    """
    Abstract base class for SICAL operation processors.

    Each operation type (ADO220, PMP450, etc.) extends this class and
    implements its specific processing logic while inheriting common
    workflow patterns.
    """

    def __init__(self, logger: logging.Logger):
        """
        Initialize the processor.

        Args:
            logger: Logger instance for this processor
        """
        self.logger = logger
        self.status_callback: Optional[Callable] = None
        self.task_callback: Optional[Callable] = None
        self.window_manager: Optional[SicalWindowManager] = None

    def set_callbacks(
        self,
        status_callback: Optional[Callable] = None,
        task_callback: Optional[Callable] = None
    ) -> None:
        """
        Set callback functions for GUI communication.

        Args:
            status_callback: Callback for status updates
            task_callback: Callback for task progress updates
        """
        self.status_callback = status_callback
        self.task_callback = task_callback

    def notify_step(self, step_message: str, **kwargs) -> None:
        """
        Notify GUI of current processing step.

        Args:
            step_message: Description of current step
            **kwargs: Additional data to pass to callback
        """
        if self.task_callback:
            self.task_callback(GUI_EVENTS['step'], step=step_message, **kwargs)

    @property
    @abstractmethod
    def operation_type(self) -> str:
        """Return the operation type identifier (e.g., 'ado220')."""
        pass

    @property
    @abstractmethod
    def operation_name(self) -> str:
        """Return the human-readable operation name."""
        pass

    @abstractmethod
    def create_window_manager(self) -> SicalWindowManager:
        """Create and return the appropriate window manager for this operation."""
        pass

    @abstractmethod
    def create_operation_data(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform incoming message data to SICAL-compatible format.

        Args:
            operation_data: Raw operation data from message

        Returns:
            Transformed data for SICAL processing
        """
        pass

    @abstractmethod
    def setup_operation_window(self) -> bool:
        """
        Open and setup the SICAL window for this operation.

        Returns:
            bool: True if window was opened successfully
        """
        pass

    @abstractmethod
    def process_operation_form(
        self,
        operation_data: Dict[str, Any],
        result: OperationResult
    ) -> OperationResult:
        """
        Process the operation by filling the SICAL form.

        Args:
            operation_data: Prepared operation data
            result: Current operation result object

        Returns:
            Updated operation result
        """
        pass

    def execute(self, operation_data: Dict[str, Any]) -> OperationResult:
        """
        Execute the complete operation workflow.

        This is the main entry point for processing an operation.
        It orchestrates the complete flow: data preparation, window setup,
        form processing, validation, and cleanup.

        Args:
            operation_data: Operation data from RabbitMQ message

        Returns:
            OperationResult: Final result of the operation
        """
        self.logger.info('=' * 60)
        self.logger.info(f'Starting {self.operation_name} operation')

        init_time = datetime.now()
        result = OperationResult(
            status=OperationStatus.PENDING,
            init_time=str(init_time),
            sical_is_open=False,
            completed_phases=[],
            similiar_records_encountered=-1,
        )

        # Create window manager
        self.window_manager = self.create_window_manager()

        try:
            # Phase 1: Transform operation data
            self.notify_step(f'Preparing {self.operation_name} data')
            sical_data = self.create_operation_data(operation_data)
            self.logger.info(f'{self.operation_name} data prepared')
            result.completed_phases.append({'phase': 'data_creation', 'description': 'Created operation data'})

            # Phase 2: Setup SICAL window
            self.notify_step(f'Opening {self.operation_name} window')
            if not self.setup_operation_window():
                result.status = OperationStatus.FAILED
                result.error = f'Failed to open {self.operation_name} window'
                return result
            else:
                result.sical_is_open = True
                result.status = OperationStatus.IN_PROGRESS
                result.completed_phases.append({'phase': 'window_setup', 'description': 'Opened SICAL window'})

            # Phase 3: Process the operation form
            self.notify_step(f'Processing {self.operation_name} form')
            result = self.process_operation_form(sical_data, result)

            self.logger.info(f'Operation processing complete - Status: {result.status.value}')

        except Exception as e:
            self.logger.error(f'Error in {self.operation_name} operation: {e}')
            result.status = OperationStatus.FAILED
            result.error = str(e)

            if result.sical_is_open:
                from sical_utils import handle_error_cleanup
                handle_error_cleanup(self.window_manager.ventana_proceso if self.window_manager else None)

        finally:
            # Calculate duration
            end_time = datetime.now()
            result.end_time = str(end_time)
            result.duration = str(end_time - init_time)

            self.logger.info(f'Final result - Status: {result.status.value}, '
                           f'Op #: {result.num_operacion}, '
                           f'Error: {result.error if result.error else "None"}')

        return result

    def validate_operation(self, result: OperationResult) -> OperationResult:
        """
        Validate the operation in SICAL.

        This default implementation can be overridden by specific processors.

        Args:
            result: Current operation result

        Returns:
            Updated operation result with validation status
        """
        # Default implementation - override in subclasses
        return result

    def print_operation_document(self, result: OperationResult) -> OperationResult:
        """
        Print the operation document.

        This default implementation can be overridden by specific processors.

        Args:
            result: Current operation result

        Returns:
            Updated operation result
        """
        # Default implementation - override in subclasses
        return result


# =============================================================================
# CALLBACK HELPERS - Helper functions for GUI communication
# =============================================================================

class GUICallbackHelper:
    """Helper class for managing GUI callbacks consistently."""

    def __init__(
        self,
        status_callback: Optional[Callable] = None,
        task_callback: Optional[Callable] = None
    ):
        """
        Initialize the callback helper.

        Args:
            status_callback: Callback for status updates
            task_callback: Callback for task progress updates
        """
        self.status_callback = status_callback
        self.task_callback = task_callback

    def notify_task_received(self, task_id: str) -> None:
        """Notify that a task was received."""
        if self.status_callback:
            self.status_callback(GUI_EVENTS['task_received'], task_id=task_id)

    def notify_task_started(self, **task_details) -> None:
        """Notify that task processing has started."""
        if self.status_callback:
            self.status_callback(GUI_EVENTS['task_started'], **task_details)

    def notify_task_completed(self, **completion_details) -> None:
        """Notify that task completed successfully."""
        if self.status_callback:
            self.status_callback(GUI_EVENTS['task_completed'], **completion_details)

    def notify_task_failed(self, **failure_details) -> None:
        """Notify that task processing failed."""
        if self.status_callback:
            self.status_callback(GUI_EVENTS['task_failed'], **failure_details)

    def notify_step(self, step_message: str, **kwargs) -> None:
        """Notify current processing step."""
        if self.task_callback:
            self.task_callback(GUI_EVENTS['step'], step=step_message, **kwargs)

    def notify_line_item_progress(
        self,
        current_item: int,
        total_items: int,
        item_details: str = ''
    ) -> None:
        """Notify progress on line items."""
        if self.task_callback:
            self.task_callback(
                GUI_EVENTS['step'],
                step=f'Processing line item {current_item} of {total_items}',
                current_line_item=current_item,
                total_line_items=total_items,
                line_item_details=item_details
            )
