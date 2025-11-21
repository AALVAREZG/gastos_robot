"""
SICAL Gasto Task Consumer - RabbitMQ message consumer for SICAL operations.

This module consumes messages from RabbitMQ and routes them to the appropriate
operation processor. It maintains bidirectional communication with the GUI
through callbacks.
"""

import pika
import json
import dataclasses
import logging
import time
import comtypes
from datetime import datetime
from typing import Optional, Dict, Any, Callable

from config import RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASS
from sical_base import OperationEncoder, OperationResult, OperationStatus
from sical_logging import setup_logging, get_consumer_logger
from sical_config import GUI_EVENTS

# Import processors
from processors import ADO220Processor, PMP450Processor

# Import legacy ordenarypagar (to be refactored later)
from processors.ordenar_tasks import ordenar_y_pagar_operacion_gasto as legacy_ordenar_pagar


# Registry of available operation processors
OPERATION_PROCESSORS: Dict[str, type] = {
    'ado220': ADO220Processor,
    'pmp450': PMP450Processor,
}


class GastoConsumer:
    """
    RabbitMQ consumer for SICAL gasto (expense) operations.

    This consumer:
    - Connects to RabbitMQ queue
    - Parses incoming messages
    - Routes to appropriate processor
    - Maintains GUI callbacks for status updates
    - Sends responses back via RabbitMQ
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the consumer.

        Args:
            logger: Optional logger instance (creates one if not provided)
        """
        self.connection: Optional[pika.BlockingConnection] = None
        self.channel: Optional[pika.channel.Channel] = None
        self.queue_name = 'sical_queue.gasto'
        self.logger = logger or get_consumer_logger()

        # GUI callbacks
        self.status_callback: Optional[Callable] = None
        self.task_callback: Optional[Callable] = None

        # Connection state
        self.is_connected = False

        # Setup connection
        self.setup_connection()

    def setup_connection(self) -> None:
        """Establish connection to RabbitMQ."""
        try:
            credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
            self.connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    port=RABBITMQ_PORT,
                    credentials=credentials,
                    heartbeat=600,
                    retry_delay=2.0,
                    socket_timeout=5.0
                )
            )
            self.channel = self.connection.channel()

            # Declare the queue
            self.channel.queue_declare(
                queue=self.queue_name,
                durable=True
            )

            # Set QoS to handle one message at a time
            self.channel.basic_qos(prefetch_count=1)

            self.logger.info('RabbitMQ connection established successfully')
            self.is_connected = True

            # Notify callback of connection
            if self.status_callback:
                self.status_callback(GUI_EVENTS['connected'])

        except Exception as e:
            self.logger.error(f'Failed to connect to RabbitMQ: {e}')
            self.is_connected = False
            if self.status_callback:
                self.status_callback(GUI_EVENTS['disconnected'])
            raise

    def set_status_callback(self, callback: Callable) -> None:
        """
        Set the status callback function for GUI updates.

        Args:
            callback: Function to call for status updates
        """
        self.status_callback = callback

        # Emit current connection state
        if callback and self.is_connected:
            callback(GUI_EVENTS['connected'])

    def set_task_callback(self, callback: Callable) -> None:
        """
        Set the task callback function for detailed progress updates.

        Args:
            callback: Function to call for task progress
        """
        self.task_callback = callback

    def callback(self, ch, method, properties, body) -> None:
        """
        Process incoming messages from RabbitMQ.

        This is called automatically by pika for each message received.

        Args:
            ch: Channel
            method: Delivery method
            properties: Message properties
            body: Message body
        """
        self.logger.info(f'Received message with correlation_id: {properties.correlation_id}')

        try:
            # Parse incoming message
            data = json.loads(body)
            self.logger.debug(f'Message content: {data}')

            # Extract operation details
            task_id = data.get('task_id', properties.correlation_id)
            operation_type, operation_data = self._extract_operation_data(data)

            # Notify GUI of task received
            if self.status_callback:
                self.status_callback(GUI_EVENTS['task_received'], task_id=task_id)

            # Build task details for GUI
            task_details = self._build_task_details(task_id, operation_type, operation_data)
            started_at = task_details['started_at']
            start_time = time.time()

            # Notify GUI of task started
            if self.status_callback:
                self.status_callback(GUI_EVENTS['task_started'], **task_details)

            # Add tipo to operation_data for compatibility
            operation_data['tipo'] = operation_type

            self.logger.info(f'Processing {operation_type} operation')

            # Route to appropriate processor
            result = self._process_operation(operation_type, operation_data)

            self.logger.info(f'Operation completed: {operation_type} - '
                           f'Status: {result.status.value}, '
                           f'Error: {result.error if result.error else "None"}')

            # Prepare and send response
            response = {
                'status': result.status.value,
                'operation_id': task_id,
                'result': dataclasses.asdict(result)
            }

            ch.basic_publish(
                exchange='',
                routing_key=properties.reply_to,
                properties=pika.BasicProperties(
                    correlation_id=properties.correlation_id
                ),
                body=json.dumps(response, cls=OperationEncoder)
            )

            # Acknowledge message
            ch.basic_ack(delivery_tag=method.delivery_tag)
            self.logger.info(f'Successfully processed message {properties.correlation_id}')

            # Notify GUI of completion
            self._notify_task_completion(task_details, result, start_time)

        except Exception as e:
            self.logger.exception(f'Error processing message: {e}')

            # Notify GUI of failure
            if self.status_callback:
                if 'task_details' in locals() and 'start_time' in locals():
                    failure_details = task_details.copy()
                    failure_details['duration_seconds'] = time.time() - start_time
                    failure_details['error_message'] = str(e)
                    self.status_callback(GUI_EVENTS['task_failed'], **failure_details)
                else:
                    self.status_callback(
                        GUI_EVENTS['task_failed'],
                        task_id=properties.correlation_id,
                        error_message=str(e)
                    )

            # Negative acknowledgment - message will be requeued
            ch.basic_nack(delivery_tag=method.delivery_tag)

    def _extract_operation_data(self, data: Dict[str, Any]) -> tuple:
        """
        Extract operation type and data from message.

        Supports both wrapped and direct message formats.

        Args:
            data: Raw message data

        Returns:
            Tuple of (operation_type, operation_data)

        Raises:
            ValueError: If message format is invalid
        """
        if 'operation_data' in data and 'operation' in data.get('operation_data', {}):
            # Wrapped format from producer
            self.logger.debug('Processing wrapped message format')
            operation_wrapper = data.get('operation_data', {}).get('operation', {})
            operation_type = operation_wrapper.get('tipo', 'unknown')
            operation_data = operation_wrapper.get('detalle', {})
        elif 'tipo' in data and 'detalle' in data:
            # Direct v2 format
            self.logger.debug('Processing direct v2 message format')
            operation_type = data.get('tipo')
            operation_data = data.get('detalle', {})
        else:
            raise ValueError(
                'Invalid message format - must contain either '
                '"operation_data.operation" or "tipo" and "detalle" fields'
            )

        return operation_type, operation_data

    def _build_task_details(
        self,
        task_id: str,
        operation_type: str,
        operation_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build task details dictionary for GUI callbacks.

        Args:
            task_id: Task identifier
            operation_type: Type of operation
            operation_data: Operation data

        Returns:
            Dictionary with task details
        """
        # Calculate total amount from aplicaciones
        aplicaciones = operation_data.get('aplicaciones', [])
        total_amount = sum(
            float(app.get('importe', 0)) for app in aplicaciones
        ) if aplicaciones else None

        # Build description from texto_sical
        texto_sical_list = operation_data.get('texto_sical', [])
        description = texto_sical_list[0].get('texto_ado', '') if texto_sical_list else None

        return {
            'task_id': task_id,
            'operation_type': operation_type,
            'operation_number': operation_data.get('num_operacion'),
            'amount': total_amount,
            'date': operation_data.get('fecha'),
            'cash_register': operation_data.get('caja'),
            'third_party': operation_data.get('tercero'),
            'nature': operation_data.get('naturaleza'),
            'description': description,
            'total_line_items': len(aplicaciones),
            'started_at': datetime.now().isoformat()
        }

    def _process_operation(
        self,
        operation_type: str,
        operation_data: Dict[str, Any]
    ) -> OperationResult:
        """
        Route operation to appropriate processor.

        Args:
            operation_type: Type of operation
            operation_data: Operation data

        Returns:
            OperationResult from processor
        """
        if operation_type in OPERATION_PROCESSORS:
            # Use new processor system
            processor_class = OPERATION_PROCESSORS[operation_type]
            processor = processor_class(self.logger)

            # Set callbacks for GUI communication
            processor.set_callbacks(self.status_callback, self.task_callback)

            # Execute operation
            return processor.execute(operation_data)

        elif operation_type == 'ordenarypagar':
            # Use legacy ordenarypagar (to be refactored)
            self.logger.info('Using legacy ordenarypagar handler')
            return legacy_ordenar_pagar(operation_data)

        else:
            # Unknown operation type
            self.logger.warning(f'Unknown operation type: {operation_type}')
            return OperationResult(
                status=OperationStatus.PENDING,
                init_time=datetime.now().isoformat(),
                sical_is_open=False,
                error=f'Unknown operation type: {operation_type}'
            )

    def _notify_task_completion(
        self,
        task_details: Dict[str, Any],
        result: OperationResult,
        start_time: float
    ) -> None:
        """
        Notify GUI of task completion.

        Args:
            task_details: Original task details
            result: Operation result
            start_time: Unix timestamp when task started
        """
        if not self.status_callback:
            return

        # Calculate duration
        duration_seconds = time.time() - start_time

        # Build completion details
        completion_details = task_details.copy()
        completion_details['duration_seconds'] = duration_seconds
        completion_details['error_message'] = result.error if result.error else None

        # Update operation number if assigned
        if result.num_operacion:
            completion_details['operation_number'] = result.num_operacion

        # Determine success/failure
        success_statuses = (
            OperationStatus.COMPLETED,
            OperationStatus.IN_PROGRESS
        )

        if result.status in success_statuses:
            self.status_callback(GUI_EVENTS['task_completed'], **completion_details)
        else:
            self.status_callback(GUI_EVENTS['task_failed'], **completion_details)

    def start_consuming(self) -> None:
        """Start consuming messages from the queue."""
        try:
            # Initialize COM for this thread
            # This ensures COM stays initialized across all task executions
            # and avoids COM state issues between successive tasks
            try:
                comtypes.CoInitialize()
                self.logger.info('COM initialized for consumer thread')
            except Exception as e:
                self.logger.warning(f'COM initialization warning (may already be initialized): {e}')

            self.logger.info(f'Starting to consume messages from {self.queue_name}')

            # Register callback
            self.channel.basic_consume(
                queue=self.queue_name,
                on_message_callback=self.callback
            )

            # Start consuming (blocks until stop_consuming is called)
            self.channel.start_consuming()

        except KeyboardInterrupt:
            self.logger.info('Received interrupt signal, shutting down...')
            self.stop_consuming()
        except Exception as e:
            self.logger.error(f'Error while consuming messages: {e}')
            self.stop_consuming()
            raise
        finally:
            # Uninitialize COM for this thread
            try:
                comtypes.CoUninitialize()
                self.logger.info('COM uninitialized for consumer thread')
            except Exception as e:
                self.logger.warning(f'Error uninitializing COM: {e}')

    def stop_consuming(self) -> None:
        """Stop consuming messages and close connections."""
        try:
            if self.channel:
                self.channel.stop_consuming()
            if self.connection and not self.connection.is_closed:
                self.connection.close()
            self.logger.info('Successfully shut down consumer')

            # Update connection state
            self.is_connected = False

            # Notify GUI
            if self.status_callback:
                self.status_callback(GUI_EVENTS['disconnected'])

        except Exception as e:
            self.logger.error(f'Error while shutting down: {e}')


# Main entry point for standalone execution
if __name__ == '__main__':
    # Setup logging
    setup_logging(level=logging.INFO)

    # Create and start consumer
    logger = get_consumer_logger()
    consumer = GastoConsumer(logger)

    try:
        consumer.start_consuming()
    except KeyboardInterrupt:
        logger.info('Consumer stopped by user')
    finally:
        consumer.stop_consuming()
