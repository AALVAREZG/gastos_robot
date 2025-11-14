# services/rabbitmq/consumer.py

import pika
import json
import dataclasses
import logging
import time
from datetime import datetime
from typing import Optional
from config import RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASS
from gasto_tasks import OperationEncoder, operacion_gastoADO220, OperationStatus, OperationResult
from ordenar_tasks import ordenar_y_pagar_operacion_gasto



class GastoConsumer:
    def __init__(self, logger):
        self.connection: Optional[pika.BlockingConnection] = None
        self.channel: Optional[pika.channel.Channel] = None
        self.queue_name = 'sical_queue.gasto'
        self.logger = logger
        self.status_callback = None
        self.task_callback = None
        self.is_connected = False  # Track connection state
        self.setup_connection()

    def setup_connection(self):
        """Establish connection to RabbitMQ"""
        try:
            credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
            self.connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    port=RABBITMQ_PORT,
                    credentials=credentials,
                    heartbeat=600,
                    retry_delay=2.0,  # Delay between connection attempts in seconds
                    socket_timeout=5.0  # Socket timeout in seconds
                )
            )
            self.channel = self.connection.channel()
            
            # Declare the queue we'll consume from
            self.channel.queue_declare(
                queue=self.queue_name,
                durable=True
            )
            
            # Set QoS to handle one message at a time
            self.channel.basic_qos(prefetch_count=1)
            self.logger.info("RabbitMQ connection established successfully")

            # Track connection state
            self.is_connected = True

            # Notify callback of connection (if already set)
            if self.status_callback:
                self.status_callback('connected')

        except Exception as e:
            self.logger.error(f"Failed to connect to RabbitMQ: {e}")
            self.is_connected = False
            if self.status_callback:
                self.status_callback('disconnected')
            raise

    def callback(self, ch, method, properties, body):
        """
        Process incoming messages from RabbitMQ.
        This is called automatically by pika for each message received.

        Message format (v2):
        {
            "tipo": "ado220|pmp450|ordenarypagar",
            "detalle": {...operation-specific fields...}
        }
        """
        self.logger.info(f"Received message with correlation_id: {properties.correlation_id}")

        try:
            # Parse the incoming message
            data = json.loads(body)
            self.logger.info(f"Message content: {data}")

            # Notify GUI of task received
            task_id = data.get('task_id', properties.correlation_id)
            if self.status_callback:
                self.status_callback('task_received', task_id=task_id)

            # Extract operation data from the message
            # Support both wrapped format (with operation_data.operation) and direct format
            if "operation_data" in data and "operation" in data.get("operation_data", {}):
                # New wrapped format from producer
                self.logger.info("Processing wrapped message format (operation_data.operation)")
                operation_wrapper = data.get("operation_data", {}).get("operation", {})
                operation_type = operation_wrapper.get("tipo", "Unknown")
                operation_data = operation_wrapper.get("detalle", {})
            elif "tipo" in data and "detalle" in data:
                # Direct v2 format
                self.logger.info("Processing direct v2 message format (tipo/detalle)")
                operation_type = data.get("tipo")
                operation_data = data.get("detalle", {})
            else:
                # Invalid format
                self.logger.error(f"Invalid message format: {data}")
                raise ValueError("Invalid message format - must contain either 'operation_data.operation' or 'tipo' and 'detalle' fields")

            # Notify GUI of task started with details
            # Map fields from the actual message format
            # Calculate total amount from aplicaciones if not present
            aplicaciones = operation_data.get('aplicaciones', [])
            total_amount = sum(float(app.get('importe', 0)) for app in aplicaciones) if aplicaciones else None

            # Build description from texto_sical if available
            texto_sical_list = operation_data.get('texto_sical', [])
            description = texto_sical_list[0].get('texto_ado', '') if texto_sical_list else None

            # Track task details and start time for completion callback
            started_at = datetime.now().isoformat()
            start_time = time.time()

            task_details = {
                'task_id': task_id,
                'operation_type': operation_type,
                'operation_number': operation_data.get('num_operacion'),  # Will be None initially, set after validation
                'amount': total_amount,
                'date': operation_data.get('fecha'),  # Changed from fecha_op
                'cash_register': operation_data.get('caja'),
                'third_party': operation_data.get('tercero'),
                'nature': operation_data.get('naturaleza'),  # May be None for some operations
                'description': description,
                'total_line_items': len(aplicaciones),
                'started_at': started_at
            }

            if self.status_callback:
                self.status_callback('task_started', **task_details)

            test_result = OperationResult (
                status = OperationStatus.PENDING,
                init_time= None,
                sical_is_open=False
            )

            # Add tipo to operation_data for handler functions
            operation_data["tipo"] = operation_type

            self.logger.info(f"Processing message: tipo={operation_type}")

            # Route to appropriate handler based on operation type
            if operation_type == "ado220":
                result = operacion_gastoADO220(operation_data, self.logger)
            elif operation_type == "pmp450":
                #result = operacion_gastoPMP450(operation_data)
                result = test_result
            elif operation_type == "ordenarypagar":
                result = ordenar_y_pagar_operacion_gasto(operation_data)
            else: # unknown type
                self.logger.warning(f"Unknown operation type: {operation_type}")
                result = test_result



            self.logger.info(f"Operation completed: {operation_type} - Status: {result.status.value}, Error: {result.error if result.error else 'None'}")
            # Prepare response
            response = {
                'status': result.status.value,
                'operation_id': data.get('task_id'),
                'result': dataclasses.asdict(result)
            }
            #self.logger.critical("RESPONSE:  ", response)
            # Send response back through RabbitMQ
            ch.basic_publish(
                exchange='',
                routing_key=properties.reply_to,
                properties=pika.BasicProperties(
                    correlation_id=properties.correlation_id
                ),
                
                body=json.dumps(response, cls=OperationEncoder)
            )
            
            # Acknowledge the message was processed successfully
            ch.basic_ack(delivery_tag=method.delivery_tag)
            self.logger.info(f"Successfully processed message {properties.correlation_id}")

            # Notify GUI of task completion with full details
            if self.status_callback:
                # Calculate duration
                duration_seconds = time.time() - start_time

                # Update task_details with completion info
                completion_details = task_details.copy()
                completion_details['duration_seconds'] = duration_seconds
                completion_details['error_message'] = result.error if result.error else None

                # Update operation_number if it was set during processing
                if result.num_operacion:
                    completion_details['operation_number'] = result.num_operacion

                success = result.status in (OperationStatus.COMPLETED, OperationStatus.IN_PROGRESS)
                if success:
                    self.status_callback('task_completed', **completion_details)
                else:
                    self.status_callback('task_failed', **completion_details)

        except Exception as e:
            self.logger.exception(f"Error processing message: {e}")

            # Notify GUI of task failure with details if available
            if self.status_callback:
                # Use task_details if defined, otherwise create minimal details
                if 'task_details' in locals() and 'start_time' in locals():
                    failure_details = task_details.copy()
                    failure_details['duration_seconds'] = time.time() - start_time
                    failure_details['error_message'] = str(e)
                    self.status_callback('task_failed', **failure_details)
                else:
                    # Minimal details if task_details not yet created
                    self.status_callback('task_failed',
                                       task_id=properties.correlation_id,
                                       error_message=str(e))

            # Negative acknowledgment - message will be requeued
            ch.basic_nack(delivery_tag=method.delivery_tag)

    def start_consuming(self):
        """Start consuming messages from the queue"""
        try:
            self.logger.info(f"Starting to consume messages from {self.queue_name}")
            
            # Register the callback function to be called when messages arrive
            self.channel.basic_consume(
                queue=self.queue_name,
                on_message_callback=self.callback
            )
            
            # Start consuming messages - this blocks until stop_consuming() is called
            self.channel.start_consuming()
            
        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal, shutting down...")
            self.stop_consuming()
        except Exception as e:
            self.logger.error(f"Error while consuming messages: {e}")
            self.stop_consuming()
            raise

    def stop_consuming(self):
        """Stop consuming messages and close connections"""
        try:
            if self.channel:
                self.channel.stop_consuming()
            if self.connection and not self.connection.is_closed:
                self.connection.close()
            self.logger.info("Successfully shut down consumer")

            # Update connection state
            self.is_connected = False

            # Notify GUI of disconnection
            if self.status_callback:
                self.status_callback('disconnected')

        except Exception as e:
            self.logger.error(f"Error while shutting down: {e}")

    def set_status_callback(self, callback):
        """Set the status callback function for GUI updates."""
        self.status_callback = callback

        # Emit current connection state when callback is first registered
        if callback and self.is_connected:
            callback('connected')

    def set_task_callback(self, callback):
        """Set the task callback function for detailed progress updates."""
        self.task_callback = callback