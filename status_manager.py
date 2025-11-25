"""
Status Manager for Gastos Robot GUI

Manages the current state of the robot service, including:
- Service and RabbitMQ connection status
- Task statistics and current task info
- Activity logs
"""

import threading
import time
from datetime import datetime
from collections import deque
from typing import Optional, Dict, Any


class StatusManager:
    """Thread-safe status manager for the Gastos Robot GUI."""

    def __init__(self, max_logs=500):
        """Initialize the status manager."""
        self.lock = threading.Lock()

        # Service status
        self.service_running = False
        self.rabbitmq_connected = False
        self.start_time: Optional[float] = None

        # Statistics
        self.stats = {
            'pending': 0,
            'processing': 0,
            'completed': 0,
            'failed': 0
        }

        # Current task
        self.current_task: Optional[Dict[str, Any]] = None

        # Last completed task (for displaying token info after completion)
        self.last_completed_task: Optional[Dict[str, Any]] = None

        # Logs (using deque for efficient append/pop)
        self.logs = deque(maxlen=max_logs)

    def update_service_status(self, running: bool):
        """Update service running status."""
        with self.lock:
            self.service_running = running
            if running:
                self.start_time = time.time()
            else:
                self.start_time = None

    def update_rabbitmq_status(self, connected: bool):
        """Update RabbitMQ connection status."""
        with self.lock:
            self.rabbitmq_connected = connected

    def task_received(self, task_id: str):
        """Mark a task as received (pending)."""
        with self.lock:
            self.stats['pending'] += 1
        self.add_log(f"Task received: {task_id[:16]}...", "INFO")

    def task_started(self, task_id: str, operation_type: str = None,
                    operation_number: str = None, amount: float = None, **kwargs):
        """Mark a task as started (processing)."""
        with self.lock:
            self.stats['pending'] = max(0, self.stats['pending'] - 1)
            self.stats['processing'] += 1

            # Clear last completed task when starting a new one
            self.last_completed_task = None

            # Create current task info
            self.current_task = {
                'task_id': task_id,
                'operation_type': operation_type or 'unknown',
                'operation_number': operation_number or 'N/A',
                'amount': amount,
                'start_time': time.time(),
                'duration': 0,
                'current_step': 'Starting...',
                # Additional expense-specific fields
                'date': kwargs.get('date'),
                'third_party': kwargs.get('third_party'),
                'nature': kwargs.get('nature'),
                'nature_display': self._format_nature(kwargs.get('nature')),
                'description': kwargs.get('description'),
                'cash_register': kwargs.get('cash_register'),
                'total_line_items': kwargs.get('total_line_items', 0),
                'current_line_item': 0,
                'line_item_details': None,
                # Policy and token information
                'duplicate_policy': kwargs.get('duplicate_policy'),
                'duplicate_confirmation_token': kwargs.get('duplicate_confirmation_token'),
                'token_status': 'received' if kwargs.get('duplicate_confirmation_token') else None
            }

        op_type_display = operation_type.upper() if operation_type else 'UNKNOWN'
        self.add_log(f"Processing task {task_id[:16]}... (Type: {op_type_display})", "INFO")

    def _format_nature(self, nature: str) -> str:
        """Format nature code to display name."""
        if not nature:
            return '--'
        if nature in ('1', '2', '3', '4'):
            return 'Presupuestary'
        elif nature == '5':
            return 'Non-presupuestary'
        return nature

    def task_progress(self, step: str, **kwargs):
        """Update current task progress with detailed info."""
        with self.lock:
            if self.current_task:
                self.current_task['current_step'] = step

                # Update current line item if provided
                if 'current_line_item' in kwargs:
                    self.current_task['current_line_item'] = kwargs['current_line_item']

                # Update line item details if provided
                if 'line_item_details' in kwargs:
                    self.current_task['line_item_details'] = kwargs['line_item_details']

                # Update total line items if provided
                if 'total_line_items' in kwargs:
                    self.current_task['total_line_items'] = kwargs['total_line_items']

                # Calculate duration
                self.current_task['duration'] = time.time() - self.current_task['start_time']

    def update_token_status(self, status: str):
        """Update the token status for the current task.

        Args:
            status: Token status ('received', 'validated', 'processing', 'finalized')
        """
        with self.lock:
            if self.current_task:
                self.current_task['token_status'] = status

    def task_completed(self, task_id: str, success: bool = True):
        """Mark a task as completed or failed."""
        with self.lock:
            self.stats['processing'] = max(0, self.stats['processing'] - 1)

            if success:
                self.stats['completed'] += 1
                status_text = "SUCCESS"
                log_level = "INFO"
            else:
                self.stats['failed'] += 1
                status_text = "FAILED"
                log_level = "ERROR"

            # Save current task as last completed (for token retention)
            if self.current_task:
                self.last_completed_task = self.current_task.copy()
                # Update token status to finalized
                if self.last_completed_task.get('duplicate_confirmation_token'):
                    self.last_completed_task['token_status'] = 'finalized'
                self.last_completed_task['completion_status'] = status_text

            # Clear current task
            self.current_task = None

        self.add_log(f"Task completed: {task_id[:16]}... - {status_text}", log_level)

    def reset_stats(self):
        """Reset all statistics."""
        with self.lock:
            self.stats = {
                'pending': 0,
                'processing': 0,
                'completed': 0,
                'failed': 0
            }
            self.current_task = None
        self.add_log("Statistics reset", "INFO")

    def add_log(self, message: str, level: str = "INFO"):
        """Add a log message."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"

        with self.lock:
            self.logs.append(log_entry)

    def get_status(self) -> Dict[str, Any]:
        """
        Get current status snapshot.

        Returns a dictionary with all current status information.
        """
        with self.lock:
            # Calculate uptime
            uptime = None
            if self.start_time:
                uptime = time.time() - self.start_time

            # Calculate success rate
            total_tasks = self.stats['completed'] + self.stats['failed']
            success_rate = 0.0
            if total_tasks > 0:
                success_rate = (self.stats['completed'] / total_tasks) * 100

            # Update current task duration if exists
            current_task_copy = None
            if self.current_task:
                current_task_copy = self.current_task.copy()
                current_task_copy['duration'] = time.time() - current_task_copy['start_time']

            return {
                'service_running': self.service_running,
                'rabbitmq_connected': self.rabbitmq_connected,
                'uptime': uptime,
                'stats': self.stats.copy(),
                'success_rate': success_rate,
                'current_task': current_task_copy,
                'last_completed_task': self.last_completed_task.copy() if self.last_completed_task else None,
                'recent_logs': list(self.logs)
            }


# Global instance
status_manager = StatusManager()
