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
import socket
import time
import comtypes
from datetime import datetime
from typing import Optional, Dict, Any, Callable

import document_mode as document_mode_mod
from rabbit_heartbeat import HeartbeatPublisher
import run_trace

from config_loader import RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASS
from sical_base import OperationEncoder, OperationResult, OperationStatus
from sical_logging import setup_logging, get_consumer_logger
from sical_config import GUI_EVENTS

# Import processors
from processors import (
    ADO220Processor,
    PMP450Processor,
    OrdenarPagarProcessor,
    ListasPendientesPagoProcessor,
)


# Registry of available operation processors
OPERATION_PROCESSORS: Dict[str, type] = {
    'ado220': ADO220Processor,
    'pmp450': PMP450Processor,
    'ordenarypagar': OrdenarPagarProcessor,
    'listas_pendientes_pago': ListasPendientesPagoProcessor,
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

        # Latido a RabbitMQ (spec §6.3). Los pasos ya se generaban; hasta ahora
        # solo iban a la GUI local y se perdian.
        self.heartbeat: Optional[HeartbeatPublisher] = None
        self.hostname = socket.gethostname()

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

            self.heartbeat = HeartbeatPublisher(self.channel, 'gasto', self.logger)
            self.heartbeat.declare()

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

            # Modo de documento: una decision, tomada por el productor, que
            # viaja en el mensaje (spec §4). El consumidor deja de tener
            # interruptor; CONTABLE_CAPTURE_ENABLED queda como reserva para
            # mensajes que no traigan el campo, lo que permite desplegar el
            # productor primero.
            doc_mode = document_mode_mod.document_mode_from_message(data)
            if doc_mode:
                self.logger.info(f'document_mode={doc_mode} (del mensaje)')
            else:
                self.logger.info(
                    'El mensaje no trae document_mode; se usa la reserva '
                    'CONTABLE_CAPTURE_ENABLED')

            # Rastro: el mensaje entero tal como llego. Es lo primero que hay
            # que poder mirar cuando el resultado no cuadra.
            run_trace.bind(task_id)
            run_trace.event('message_in',
                            correlation_id=properties.correlation_id,
                            operation_type=operation_type,
                            document_mode=doc_mode,
                            schema_version=data.get('schema_version'),
                            duplicate_policy=operation_data.get('duplicate_policy'),
                            detalle=operation_data)

            # A partir de aqui cada paso del robot sale tambien a RabbitMQ.
            if self.heartbeat:
                self.heartbeat.bind(properties.correlation_id, task_id=task_id)
                self.heartbeat.beat('Task received')

            # BUGFIX: Merge duplicate policy fields from top-level message if present
            # Producer may send these at message root level
            for policy_field in ('duplicate_policy', 'duplicate_confirmation_token', 'duplicate_check_id'):
                if policy_field in data and policy_field not in operation_data:
                    operation_data[policy_field] = data[policy_field]
                    self.logger.info(f'Merged {policy_field} from message root: {data[policy_field]}')

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
            result = self._process_operation(operation_type, operation_data,
                                             document_mode=doc_mode)

            self.logger.info(f'Operation completed: {operation_type} - '
                           f'Status: {result.status.value}, '
                           f'Error: {result.error if result.error else "None"}')

            # Prepare and send response.
            #
            # `hostname` es como el productor descubre el mapa de asientos
            # (spec §3): un asiento ES una maquina, y el asiento se descubre,
            # no se configura -mover este consumidor a una VM nueva no exige
            # tocar ningun JSON-.
            response = {
                'status': result.status.value,
                'operation_id': task_id,
                'result': dataclasses.asdict(result),
                'hostname': self.hostname,
                'document_mode': doc_mode,
            }

            # Spec v2 (Phase B′): return the captured contable PDF(s) as a
            # top-level, phase-tagged array so sical-robot can merge/stage
            # each phase. Only present when capture ran (flag ON + finalized).
            contables = getattr(result, '_contable_documents', None)
            if contables:
                response['contable_documents'] = contables
                captured = [c for c in contables if c.get('capture_status') == 'CAPTURED']
                self.logger.info(
                    f'Returning {len(captured)}/{len(contables)} contable '
                    f'document(s) to producer '
                    f'(phases: {[c.get("phase") for c in contables]})')

            # Las fases con sus marcas de tiempo (Fase 1a) van al rastro tal
            # cual: es de donde salen los tres numeros que la spec deja por
            # medir en §9.
            run_trace.event('result_out',
                            status=result.status.value,
                            num_operacion=result.num_operacion,
                            total_operacion=result.total_operacion,
                            duration=result.duration,
                            error=result.error,
                            document_mode=doc_mode,
                            capture_status=result.capture_status,
                            capture_error=result.capture_error,
                            pago=result.pago,
                            fases=result.completed_phases,
                            contables=[{k: v for k, v in c.items() if k != 'data'}
                                       for c in (contables or [])])

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
            if self.heartbeat:
                self.heartbeat.unbind()
            run_trace.unbind()
            self.logger.info(f'Successfully processed message {properties.correlation_id}')

            # Notify GUI of completion
            self._notify_task_completion(task_details, result, start_time)

        except Exception as e:
            run_trace.exception('consumer_error', e)
            self.logger.exception(f'Error processing message: {e}')
            if self.heartbeat:
                self.heartbeat.unbind()

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

            # BUGFIX: Merge duplicate policy fields from wrapper level if present
            # Some producers may send these at operation_data level instead of detalle
            wrapper_data = data.get('operation_data', {})
            for policy_field in ('duplicate_policy', 'duplicate_confirmation_token', 'duplicate_check_id'):
                if policy_field in wrapper_data and policy_field not in operation_data:
                    operation_data[policy_field] = wrapper_data[policy_field]
                    self.logger.debug(f'Merged {policy_field} from wrapper level: {wrapper_data[policy_field]}')
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

        # Ordenar/pagar no trae texto ni aplicaciones: se describe por lo que hace
        if operation_type == 'ordenarypagar':
            if operation_data.get('num_lista'):
                description = f'Pagar lista {operation_data["num_lista"]}'
            else:
                description = f'Ordenar/pagar operacion {operation_data.get("num_operacion")}'
        elif operation_type == 'listas_pendientes_pago':
            description = 'Consultar listas pendientes de pago'

        return {
            'task_id': task_id,
            'operation_type': operation_type,
            'operation_number': operation_data.get('num_operacion'),
            'amount': total_amount,
            'date': (operation_data.get('fecha') or operation_data.get('fecha_pago')
                     or operation_data.get('fecha_ordenamiento')),
            'cash_register': operation_data.get('caja'),
            'third_party': operation_data.get('tercero'),
            'nature': operation_data.get('naturaleza'),
            'description': description,
            'total_line_items': len(aplicaciones),
            'started_at': datetime.now().isoformat(),
            # Policy and token information
            'duplicate_policy': operation_data.get('duplicate_policy'),
            'duplicate_confirmation_token': operation_data.get('duplicate_confirmation_token')
        }

    def _process_operation(
        self,
        operation_type: str,
        operation_data: Dict[str, Any],
        document_mode: Optional[str] = None
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

            # Set callbacks for GUI communication. El envoltorio publica el
            # paso a RabbitMQ ademas de mandarlo a la GUI: es literalmente
            # enganchar un callback que ya estaba definido (spec §6.3).
            processor.set_callbacks(self.status_callback, self._task_callback_with_heartbeat)
            processor.set_document_mode(document_mode)

            # Execute operation
            return processor.execute(operation_data)

        else:
            # Unknown operation type
            self.logger.warning(f'Unknown operation type: {operation_type}')
            return OperationResult(
                status=OperationStatus.PENDING,
                init_time=datetime.now().isoformat(),
                sical_is_open=False,
                error=f'Unknown operation type: {operation_type}'
            )

    def _task_callback_with_heartbeat(self, event, **kwargs):
        """
        Publica el paso a RabbitMQ y lo reenvia a la GUI.

        Cada paso rearma la ventana de silencio del productor (§6.4): pasa de
        preguntar «¿han pasado 75 s desde que publique?» -que mata tareas
        vivas, porque la `duration` p90 de un gasto es 3m43s- a «¿han pasado
        75 s sin noticias de esta tarea?».
        """
        try:
            if self.heartbeat and kwargs.get('step'):
                self.heartbeat.beat(kwargs['step'])
        except Exception as exc:  # noqa: BLE001 - un latido no tumba nada
            self.logger.debug(f'heartbeat failed: {exc}')
        if self.task_callback:
            self.task_callback(event, **kwargs)

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
