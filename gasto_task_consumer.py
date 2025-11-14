# services/rabbitmq/consumer.py

import pika
import json
import dataclasses
import logging
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
            
        except Exception as e:
            self.logger.error(f"Failed to connect to RabbitMQ: {e}")
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
        self.logger.critical(f"Received message with correlation_id: {properties.correlation_id}")

        try:
            # Parse the incoming message
            data = json.loads(body)
            self.logger.info(f"Message content: {data}")

            test_result = OperationResult (
                status = OperationStatus.PENDING,
                init_time= None,
                sical_is_open=False
            )

            # Extract operation type and data from v2 format
            if "tipo" not in data or "detalle" not in data:
                self.logger.error(f"Invalid message format: {data}")
                raise ValueError("Invalid message format - must contain 'tipo' and 'detalle' fields")

            operation_type = data.get("tipo")
            operation_data = data.get("detalle", {})

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



            self.logger.critical(f"FINALIZADO: RESULTADO OPERACIÓN GASTO.......: {result}")
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
            
        except Exception as e:
            self.logger.exception(f"Error processing message: {e}")
            # Negative acknowledgment - message will be requeued
            ch.basic_nack(delivery_tag=method.delivery_tag)

    def start_consuming(self):
        """Start consuming messages from the queue"""
        try:
            self.logger.critical(f"Starting to consume messages from {self.queue_name}")
            
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
        except Exception as e:
            self.logger.error(f"Error while shutting down: {e}")