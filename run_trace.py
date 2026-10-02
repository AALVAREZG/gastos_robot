"""
Rastro de ejecución: lo que queda en disco cuando el robot termina.

Hasta ahora los robots escribían **solo en consola y en la ventana**. En cuanto
se cierra la GUI no queda nada: si una ejecución real sale rara, no hay qué
mirar. Esto lo arregla con dos ficheros por día, en `logs/` junto al ejecutable:

    logs/<robot>-YYYYMMDD.log     texto, para leerlo
    logs/<robot>-YYYYMMDD.jsonl   un objeto JSON por linea, para reconstruirlo

**Por que dos y no uno.** El texto es lo que se lee cuando quieres entender una
ejecución; el JSONL es lo que se lee cuando quieres *medirla* o comparar dos
ejecuciones — sacar cuanto tardo cada fase, que documento fallo, con que
mensaje entro la tarea— sin escarbar prosa con expresiones regulares. Son
publicos distintos y formatos distintos.

**El fichero de texto va a DEBUG aunque la consola vaya a INFO.** Es el punto:
la ventana se mantiene limpia (ver gui_log_filter) y el disco se queda con
todo, incluido lo que solo importa cuando algo se ha roto. Las bibliotecas de
terceros siguen ancladas a WARNING —sus DEBUG son decenas de miles de lineas
inservibles—, pero sus avisos y errores si entran, que es lo que hace falta
cuando falla un selector. Con `SICAL_TRACE_VERBOSE=1` se desanclan para una
ejecución de diagnostico profundo.

**Nunca lanza.** Un fallo al escribir el rastro no puede tumbar una operación
contable: todo va en try/except y, como mucho, se pierde una linea.
"""

import json
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta

# Terceros que inundan; anclados a WARNING salvo SICAL_TRACE_VERBOSE=1.
_NOISY = (
    'pika', 'comtypes', 'urllib3', 'PIL', 'robocorp', 'RPA', 'asyncio',
    'charset_normalizer', 'fontTools', 'RobotFramework', 'WDM', 'uiautomation',
    'selenium', 'websockets', 'requests',
)

_DIAS_QUE_SE_GUARDAN = 30

# RLock y no Lock: `init` emite su propio evento de arranque, y `event` vuelve a
# pedir el candado. Con un Lock normal eso es un interbloqueo -y el robot se
# queda colgado en el arranque, antes de hacer nada-. Costo: una ejecucion de
# prueba que no termino nunca.
_lock = threading.RLock()
_state = {'path_jsonl': None, 'path_log': None, 'task_id': None, 'run_id': None}


def _app_dir():
    """Directorio de la aplicación: junto al .exe cuando esta empaquetado."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _prune(logs_dir):
    """Borra rastros de mas de _DIAS_QUE_SE_GUARDAN dias."""
    limite = time.time() - _DIAS_QUE_SE_GUARDAN * 86400
    try:
        for nombre in os.listdir(logs_dir):
            if not (nombre.endswith('.log') or nombre.endswith('.jsonl')):
                continue
            p = os.path.join(logs_dir, nombre)
            if os.path.isfile(p) and os.path.getmtime(p) < limite:
                os.remove(p)
    except Exception:  # noqa: BLE001
        pass


def init(prefix, formatter=None, extra=None):
    """
    Instala el fichero de texto y abre el de eventos. Idempotente.

    `formatter` permite al robot conservar su propio formato (arqueos tiene uno
    orientado a fases, con task= y PHASE); si no se pasa, se usa uno generico
    que incluye el nombre del logger, que es lo que hace falta para saber quien
    dijo que.

    Devuelve la ruta de la carpeta de rastros, o None si no se pudo crear.
    """
    with _lock:
        if _state['path_log']:
            return os.path.dirname(_state['path_log'])
        try:
            logs_dir = os.path.join(_app_dir(), 'logs')
            os.makedirs(logs_dir, exist_ok=True)
            _prune(logs_dir)

            dia = datetime.now().strftime('%Y%m%d')
            _state['path_log'] = os.path.join(logs_dir, f'{prefix}-{dia}.log')
            _state['path_jsonl'] = os.path.join(logs_dir, f'{prefix}-{dia}.jsonl')
            _state['run_id'] = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"

            handler = logging.handlers.RotatingFileHandler(
                _state['path_log'], maxBytes=8 * 1024 * 1024, backupCount=5,
                encoding='utf-8')
            handler.setLevel(logging.DEBUG)
            handler.set_name('sical_trace_file')
            handler.setFormatter(formatter or logging.Formatter(
                '%(asctime)s.%(msecs)03d %(levelname)-7s %(name)-28s %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'))

            root = logging.getLogger()
            if not any(getattr(h, 'name', '') == 'sical_trace_file'
                       for h in root.handlers):
                root.addHandler(handler)
            # Gatean los manejadores; el raiz tiene que dejar pasar DEBUG o el
            # fichero nunca lo vera.
            root.setLevel(logging.DEBUG)

            verbose = str(os.getenv('SICAL_TRACE_VERBOSE', '')).strip().lower() \
                in ('1', 'true', 'yes', 'on')
            for noisy in _NOISY:
                logging.getLogger(noisy).setLevel(
                    logging.DEBUG if verbose else logging.WARNING)

            event('run_start',
                  robot=prefix,
                  hostname=socket.gethostname(),
                  pid=os.getpid(),
                  frozen=bool(getattr(sys, 'frozen', False)),
                  python=sys.version.split()[0],
                  cwd=os.getcwd(),
                  verbose=verbose,
                  **(extra or {}))
            logging.getLogger('run_trace').info(
                'Rastro de esta ejecucion en %s', logs_dir)
            return logs_dir
        except Exception:  # noqa: BLE001 - el rastro nunca tumba el robot
            _state['path_log'] = None
            _state['path_jsonl'] = None
            return None


def bind(task_id):
    """Ata los siguientes eventos a una tarea o lote."""
    _state['task_id'] = task_id


def unbind():
    _state['task_id'] = None


def event(name, **campos):
    """Escribe un evento. Nunca lanza."""
    path = _state.get('path_jsonl')
    if not path:
        return
    try:
        registro = {
            'ts': datetime.now().isoformat(timespec='milliseconds'),
            'run': _state.get('run_id'),
            'event': name,
        }
        if _state.get('task_id'):
            registro['task_id'] = _state['task_id']
        registro.update(campos)
        linea = json.dumps(registro, ensure_ascii=False, default=str)
        with _lock:
            with open(path, 'a', encoding='utf-8') as fh:
                fh.write(linea + '\n')
    except Exception:  # noqa: BLE001
        pass


def exception(name, exc, **campos):
    """Un evento de error con su traza completa."""
    event(name,
          error=f'{type(exc).__name__}: {exc}',
          traceback=''.join(traceback.format_exception(
              type(exc), exc, exc.__traceback__)),
          **campos)


def paths():
    """Rutas de los dos ficheros, para poder decirle al operador donde estan."""
    return {'log': _state.get('path_log'), 'jsonl': _state.get('path_jsonl')}
