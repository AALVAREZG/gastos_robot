"""
Latido a RabbitMQ (spec §6.3).

Los robots ya generan eventos de progreso -`Preparing operation data`,
`Opening SICAL window`, `Validating operation`, `Capturing contable document`-
vía `notify_step` / `TASK_CALLBACK`. Hasta ahora iban **sólo a la GUI local** y
se perdían: el consumidor nunca registraba el callback. Publicarlos es enganchar
un callback que ya está definido.

Con eso se obtienen tres cosas de golpe:

  1. **El timeout por silencio** (§6.4). El productor pasa de preguntar «¿han
     pasado 75 s desde que publiqué?» -que mata tareas vivas, porque la
     `duration` p90 de un gasto es 3m43s- a «¿han pasado 75 s sin noticias de
     esta tarea?», que sólo mata tareas muertas.
  2. **Progreso real en el Task Monitor**, incluido el «documento 4 de 12» de
     un lote.
  3. **Los tiempos por fase en vivo.**

Nunca lanza: un latido perdido no puede tumbar una operación contable.
"""

import json
import logging
import socket
import time

import pika

logger = logging.getLogger(__name__)

HEARTBEAT_QUEUE = 'sical_heartbeat'

# Deben coincidir EXACTAMENTE con los del productor
# (sical-robot/src/services/rabbitmq/config.js, heartbeatQueueOptions): un
# `queue.declare` con argumentos distintos falla con PRECONDITION_FAILED y
# tumba el canal.
HEARTBEAT_QUEUE_ARGS = {
    'x-message-ttl': 300000,
    'x-max-length': 5000,
    'x-overflow': 'drop-head',
}


class HeartbeatPublisher:
    """
    Publica latidos en el canal que ya tiene abierto el consumidor.

    Se le pasa el canal de pika del propio consumidor en vez de abrir una
    conexión aparte: los latidos salen desde dentro del callback del mensaje,
    o sea, desde el mismo hilo, que es donde pika permite publicar sin
    sincronización adicional.
    """

    def __init__(self, channel, queue_name, logger_=None):
        self.channel = channel
        self.queue_name = queue_name          # cola de origen: 'gasto', 'arqueo', 'docs'
        self.logger = logger_ or logger
        self.hostname = socket.gethostname()
        self.correlation_id = None
        self.task_id = None
        self.job_id = None
        self._declared = False

    def declare(self):
        """Idempotente. Un fallo aquí sólo desactiva el latido."""
        if self._declared or self.channel is None:
            return
        try:
            self.channel.queue_declare(
                queue=HEARTBEAT_QUEUE, durable=True,
                arguments=HEARTBEAT_QUEUE_ARGS)
            self._declared = True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning('heartbeat queue unavailable: %s', exc)
            self.channel = None

    def bind(self, correlation_id, task_id=None, job_id=None):
        """Ata los siguientes latidos a una tarea o lote concretos."""
        self.correlation_id = correlation_id
        self.task_id = task_id
        self.job_id = job_id

    def unbind(self):
        self.correlation_id = None
        self.task_id = None
        self.job_id = None

    def beat(self, step, done=None, total=None, current=None):
        """
        Un latido. `done`/`total`/`current` sólo los usa el robot de documentos
        para el progreso del lote.
        """
        if self.channel is None or not self.correlation_id:
            return
        self.declare()
        if self.channel is None:
            return
        payload = {
            'message_type': 'heartbeat',
            'queue': self.queue_name,
            'hostname': self.hostname,
            'task_id': self.task_id,
            'job_id': self.job_id,
            'step': step,
            'timestamp': int(time.time() * 1000),
        }
        if done is not None:
            payload['done'] = done
        if total is not None:
            payload['total'] = total
        if current is not None:
            payload['current'] = current
        try:
            self.channel.basic_publish(
                exchange='',
                routing_key=HEARTBEAT_QUEUE,
                properties=pika.BasicProperties(
                    correlation_id=self.correlation_id,
                    content_type='application/json',
                    # No persistente a propósito: un latido de hace media hora
                    # no informa de nada, y no debe sobrevivir al broker.
                    delivery_mode=1,
                ),
                body=json.dumps(payload),
            )
        except Exception as exc:  # noqa: BLE001 - nunca tumba la operación
            self.logger.debug('heartbeat publish failed: %s', exc)
