"""
Envia una tarea de prueba a la cola de gastos y espera la respuesta.

Sirve para probar `ordenarypagar` en SICAL sin el productor. Todos los
comandos son inocuos salvo `pagar-lista`, que PAGA DE VERDAD:

    python enviar_tarea_prueba.py pagar-lista 20260103 --fecha 30/09/2026 --confirmo-pago
        Paga la lista. Exige --fecha (sin valor por defecto) y --confirmo-pago,
        y antes consulta las pendientes: si la lista no esta, no envia nada.
        Pide `inline_capture`: con la lista pagada, se trae su relacion en PDF.

    python enviar_tarea_prueba.py relacion 20260111 [--guardar relacion.pdf]
        Saca la relacion de operaciones de la lista en PDF por la via de
        impresion de Tesoreria Pagos. No paga nada: vale cualquier lista del
        desplegable, tambien las ya pagadas. Con --guardar escribe el PDF que
        devuelve el robot.

    python enviar_tarea_prueba.py listas
        Lee las listas pendientes de pago del desplegable de «Pagar».

    python enviar_tarea_prueba.py lista 57 [--fecha 02/10/2026]
        Intenta pagar la lista 57. Mientras tesoreria_pagos.PAGO_LISTA_DISPONIBLE
        sea False el robot abre «Pagar», comprueba la lista y CANCELA ANTES DE
        TECLEARLA:
          - si ya esta pagada  -> FAILED con ListaNoPendiente  (el fallo)
          - si esta pendiente  -> FAILED con PagoListaNoDisponible
        En los dos casos sale de Tesoreria Pagos sin haber tocado nada.

    python enviar_tarea_prueba.py comprobar 326100196 [--fecha 02/10/2026]
        Teclea la operacion en el dialogo de «Pagar», lee el aviso de SICAL si
        sale y CANCELA SIN VALIDAR. No ordena ni paga. Con una operacion ya
        pagada ensena el aviso que da SICAL en ese caso.

Antes de lanzarlo:

- El consumidor tiene que ser el de esta rama (`python run_gui.py`), no el
  GastosRobot.exe instalado. Ese no conoce `listas_pendientes_pago` -contesta
  «Unknown operation type»- y con `ordenarypagar` entra en bucle: la ruta
  antigua estaba rota. Por eso `lista` manda antes `listas`, y si el
  consumidor no lo conoce se para ahi.
- Que ningun otro robot este usando SICAL en esa maquina: esta prueba no pasa
  por el productor, que es quien reparte los asientos.
- La cola tiene que estar vacia: si hay tareas del productor esperando, se para.
"""

import argparse
import json
import logging
import sys
import time
import uuid
from datetime import date

import pika

# Las importaciones del robot dejan el registro en DEBUG; aqui sobra.
logging.disable(logging.WARNING)

from config_loader import RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASS
from processors import tesoreria_pagos

COLA = 'sical_queue.gasto'
ESPERA_MAXIMA_S = 300


def _conectar():
    credenciales = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    conexion = pika.BlockingConnection(pika.ConnectionParameters(
        host=RABBITMQ_HOST, port=RABBITMQ_PORT, credentials=credenciales,
        heartbeat=600, socket_timeout=5.0))
    return conexion, conexion.channel()


def _comprobar_cola(canal) -> bool:
    """La cola existe, tiene un consumidor escuchando y no tiene nada esperando."""
    try:
        estado = canal.queue_declare(queue=COLA, passive=True).method
    except pika.exceptions.ChannelClosedByBroker:
        print(f'La cola {COLA} no existe: arranca antes el consumidor.')
        return False
    if estado.consumer_count == 0:
        print(f'No hay ningun consumidor escuchando en {COLA}. Arranca el de esta rama '
              f'(python run_gui.py): un mensaje que se quede en la cola lo cogeria el '
              f'primero que se conecte, aunque sea el GastosRobot.exe antiguo.')
        return False
    if estado.message_count > 0:
        print(f'Hay {estado.message_count} tarea(s) esperando en {COLA}. Espera a que se '
              f'vacie: esta prueba iria detras y no pasa por el productor.')
        return False
    return True


def _enviar(conexion, canal, cola_respuesta, tipo, detalle, document_mode='deferred'):
    task_id = f'prueba_{tipo}_{time.strftime("%Y%m%d_%H%M%S")}'
    correlation_id = f'{task_id}-{uuid.uuid4().hex}'
    cuerpo = {
        'task_id': task_id,
        'task_type': 'gasto',
        'schema_version': 3,
        'operation_data': {'operation': {'tipo': tipo, 'detalle': detalle}},
        'parameters': {'priority': 'normal', 'retry_count': 1, 'document_mode': document_mode},
        'timestamp': int(time.time() * 1000),
    }
    canal.basic_publish(
        exchange='', routing_key=COLA, body=json.dumps(cuerpo),
        properties=pika.BasicProperties(correlation_id=correlation_id,
                                        reply_to=cola_respuesta,
                                        content_type='application/json'))
    print(f'\n>> {tipo} {json.dumps(detalle, ensure_ascii=False)}  (task_id {task_id})')
    print('   esperando respuesta', end='', flush=True)

    inicio = time.monotonic()
    while time.monotonic() - inicio < ESPERA_MAXIMA_S:
        metodo, propiedades, body = canal.basic_get(cola_respuesta, auto_ack=True)
        if metodo and propiedades.correlation_id == correlation_id:
            print(f' ({time.monotonic() - inicio:.0f} s)')
            return json.loads(body)
        conexion.process_data_events(time_limit=2)
        print('.', end='', flush=True)

    print(f'\n   Sin respuesta en {ESPERA_MAXIMA_S} s. La tarea puede seguir en marcha: '
          f'mira la ventana del robot y su registro en logs/.')
    return None


def _mostrar(respuesta):
    resultado = respuesta.get('result') or {}
    print(f'   status: {respuesta.get("status")}')
    if resultado.get('error'):
        print(f'   error:  {resultado["error"]}')
    if resultado.get('num_operacion'):
        print(f'   num_operacion: {resultado["num_operacion"]}')
    if resultado.get('pago') is not None:
        print('   pago:   ' + json.dumps(resultado['pago'], ensure_ascii=False, indent=2)
              .replace('\n', '\n           '))
    for fase in resultado.get('completed_phases') or []:
        print(f'   fase:   {fase.get("phase")} ({fase.get("duration_seconds")} s) '
              f'{fase.get("description")}')
    for doc in respuesta.get('contable_documents') or []:
        print(f'   documento {doc.get("phase")}: {doc.get("capture_status")} {doc.get("filename")} '
              f'{doc.get("size_bytes")} B, {doc.get("page_count")} pag.'
              + (f'  error: {doc["capture_error"]}' if doc.get('capture_error') else ''))
    print(f'   duracion: {resultado.get("duration")}   maquina: {respuesta.get("hostname")}')


def _guardar_documento(respuesta, ruta):
    """Escribe en `ruta` el PDF que vuelve en la respuesta, comprobando su sha256."""
    import base64
    import hashlib
    for doc in respuesta.get('contable_documents') or []:
        if doc.get('capture_status') == 'CAPTURED' and doc.get('data'):
            datos = base64.b64decode(doc['data'])
            if hashlib.sha256(datos).hexdigest() != doc.get('sha256'):
                print('   El PDF recibido no casa con su sha256: no se guarda.')
                return False
            with open(ruta, 'wb') as fh:
                fh.write(datos)
            print(f'   PDF guardado en {ruta}')
            return True
    print('   La respuesta no trae ningun PDF capturado.')
    return False


def _consumidor_antiguo(respuesta) -> bool:
    error = ((respuesta or {}).get('result') or {}).get('error') or ''
    return error.startswith('Unknown operation type')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='prueba', required=True)
    p_listas = sub.add_parser('listas', help='leer las listas pendientes de pago')
    p_lista = sub.add_parser('lista', help='intentar pagar una lista (cancela antes de teclearla)')
    p_lista.add_argument('num_lista')
    p_comprobar = sub.add_parser('comprobar', help='teclear una operacion en Pagar y cancelar sin validar')
    p_comprobar.add_argument('num_operacion')
    p_pagar = sub.add_parser('pagar-lista', help='PAGAR DE VERDAD una lista pendiente')
    p_pagar.add_argument('num_lista')
    p_pagar.add_argument('--fecha', required=True, help='fecha de pago DD/MM/YYYY (obligatoria)')
    p_pagar.add_argument('--confirmo-pago', action='store_true',
                         help='sin esto no se envia nada: el pago no se puede deshacer')
    p_relacion = sub.add_parser('relacion', help='sacar la relacion de una lista en PDF (no paga nada)')
    p_relacion.add_argument('num_lista')
    p_relacion.add_argument('--fecha', default=date.today().strftime('%d/%m/%Y'),
                            help='fecha que se teclea para activar «Imprimir», DD/MM/YYYY (por defecto, hoy)')
    for p in (p_pagar, p_relacion):
        p.add_argument('--guardar', help='donde escribir el PDF de la relacion que devuelve el robot')
    for p in (p_lista, p_comprobar):
        p.add_argument('--sin-consulta', action='store_true',
                       help='no mandar antes la consulta de listas (solo si el consumidor ya es el de esta rama)')
    for p in (p_listas, p_lista, p_comprobar):
        p.add_argument('--fecha', default=date.today().strftime('%d/%m/%Y'),
                       help='fecha que se teclea en Tesoreria Pagos, DD/MM/YYYY (por defecto, hoy)')
    args = parser.parse_args()

    if args.prueba == 'pagar-lista' and not args.confirmo_pago:
        print('pagar-lista paga de verdad y no se puede deshacer: repite con --confirmo-pago.')
        return 2

    if args.prueba == 'lista' and tesoreria_pagos.PAGO_LISTA_DISPONIBLE:
        # Con el paso de seleccionar ya montado, una lista pendiente se pagaria
        # de verdad. Este script es para las pruebas que no pagan.
        print('PAGO_LISTA_DISPONIBLE es True: una lista pendiente se pagaria de verdad. '
              'Este script solo hace pruebas que no pagan; no se envia nada.')
        return 2

    conexion, canal = _conectar()
    try:
        if not _comprobar_cola(canal):
            return 1
        cola_respuesta = canal.queue_declare(queue='', exclusive=True, auto_delete=True).method.queue

        # La relacion no necesita la consulta: no paga, y vale con cualquier
        # lista del desplegable, pendiente o no. Un consumidor antiguo
        # contesta «Unknown operation type» sin tocar SICAL.
        if args.prueba == 'relacion':
            respuesta = _enviar(conexion, canal, cola_respuesta, 'relacion_lista',
                                {'num_lista': args.num_lista, 'fecha': args.fecha})
            if respuesta is None:
                return 1
            _mostrar(respuesta)
            if args.guardar:
                _guardar_documento(respuesta, args.guardar)
            return 0 if respuesta.get('status') == 'COMPLETED' else 1

        # Primero la consulta: es inocua, dice que listas hay y delata a un
        # consumidor antiguo antes de mandarle un ordenarypagar. Es tambien una
        # segunda apertura de Tesoreria Pagos; con --sin-consulta se omite.
        if args.prueba != 'listas' and getattr(args, 'sin_consulta', False):
            return _siguiente(conexion, canal, cola_respuesta, args, None)
        respuesta = _enviar(conexion, canal, cola_respuesta, 'listas_pendientes_pago',
                            {'fecha': args.fecha})
        if respuesta is None:
            return 1
        _mostrar(respuesta)
        if _consumidor_antiguo(respuesta):
            print('\nEl consumidor no conoce los tipos nuevos: es el GastosRobot.exe antiguo. '
                  'Cierralo, arranca el de esta rama (python run_gui.py) y repite.')
            return 1
        if args.prueba == 'listas':
            return 0 if respuesta.get('status') == 'COMPLETED' else 1

        pendientes = ((respuesta.get('result') or {}).get('pago') or {}).get('listas_pendientes')
        return _siguiente(conexion, canal, cola_respuesta, args, pendientes)
    finally:
        conexion.close()


def _siguiente(conexion, canal, cola_respuesta, args, pendientes):
    if args.prueba == 'pagar-lista':
        if pendientes is None or not any(
                tesoreria_pagos.numero_de_lista(l) == tesoreria_pagos.numero_de_lista(args.num_lista)
                for l in pendientes):
            print(f'\nLa lista {args.num_lista} no esta entre las pendientes ({pendientes}): no se envia nada.')
            return 1
        print(f'\nPAGANDO la lista {args.num_lista} con fecha {args.fecha}...')
        respuesta = _enviar(conexion, canal, cola_respuesta, 'ordenarypagar',
                            {'num_lista': args.num_lista, 'pagar': True, 'fecha_pago': args.fecha},
                            document_mode='inline_capture')
        if respuesta is None:
            return 1
        _mostrar(respuesta)
        if args.guardar:
            _guardar_documento(respuesta, args.guardar)
        return 0 if respuesta.get('status') == 'COMPLETED' else 1
    if args.prueba == 'comprobar':
        respuesta = _enviar(conexion, canal, cola_respuesta, 'ordenarypagar',
                            {'num_operacion': args.num_operacion, 'comprobar': True,
                             'fecha_pago': args.fecha})
        if respuesta is None:
            return 1
        _mostrar(respuesta)
        return 0
    return _intentar_lista(conexion, canal, cola_respuesta, args, pendientes)


def _intentar_lista(conexion, canal, cola_respuesta, args, pendientes):
    if pendientes is not None:
        if any(tesoreria_pagos.numero_de_lista(l) == tesoreria_pagos.numero_de_lista(args.num_lista)
               for l in pendientes):
            print(f'\nAviso: la lista {args.num_lista} esta PENDIENTE. Con el pago por lista '
                  f'desactivado el robot cancelara antes de teclearla (PagoListaNoDisponible).')
        else:
            print(f'\nLa lista {args.num_lista} no esta entre las pendientes: '
                  f'se espera ListaNoPendiente.')

    respuesta = _enviar(conexion, canal, cola_respuesta, 'ordenarypagar',
                        {'num_lista': args.num_lista, 'pagar': True, 'fecha_pago': args.fecha})
    if respuesta is None:
        return 1
    _mostrar(respuesta)
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    sys.exit(main())
