"""
Modo de documento: una decisión, tomada por el productor, que viaja en el
mensaje.

Ver `sical-robot/docs/document-robot-split-spec.md`, §4.

Antes esta decisión vivía repartida en tres ficheros que nada ataba:

    gastos_robot/config.py    CONTABLE_CAPTURE_ENABLED = false
    arqueos_robot/config.py   CONTABLE_CAPTURE_ENABLED = true
    sical-robot               contableAssemblyEnabled  = false

El propio código lo admitía -«Must be ON in tandem with sical-robot's
contableAssemblyEnabled»- y el CLAUDE.md del productor lo remataba: «Never
leave a consumer's flag split from the producer». Una regla que sólo se
sostiene porque alguien se acuerda; con tres VMs y tres `.env` en tres
máquinas se rompe sola.

El consumidor deja de tener interruptor: hace lo que dice el mensaje.
`CONTABLE_CAPTURE_ENABLED` se degrada a **reserva** para mensajes que no traigan
el campo -consumidor nuevo contra productor viejo-, y se retira cuando los tres
lo entiendan. Eso es lo que permite desplegar el productor primero.
"""

LEGACY_PRINT = 'legacy_print'
INLINE_CAPTURE = 'inline_capture'
DEFERRED = 'deferred'

VALID_MODES = (LEGACY_PRINT, INLINE_CAPTURE, DEFERRED)


def document_mode_from_message(data):
    """
    Extrae `parameters.document_mode` del mensaje.

    Devuelve None cuando el campo no viene o trae un valor desconocido: en
    ambos casos el consumidor cae a su reserva. Un modo inventado NO se
    interpreta a medias — se ignora y se avisa por el registro, porque
    adivinarlo es exactamente el fallo silencioso que este campo viene a
    eliminar.
    """
    if not isinstance(data, dict):
        return None
    params = data.get('parameters')
    if not isinstance(params, dict):
        return None
    mode = params.get('document_mode')
    if mode in VALID_MODES:
        return mode
    return None


def should_capture(mode, fallback_enabled):
    """¿Hay que capturar el PDF y devolverlo con el resultado?"""
    if mode is None:
        return bool(fallback_enabled)
    return mode == INLINE_CAPTURE


def should_print(mode, fallback_enabled):
    """¿Hay que imprimir en SICAL como siempre (camino heredado)?"""
    if mode is None:
        return not bool(fallback_enabled)
    return mode == LEGACY_PRINT


def touches_documents(mode, fallback_enabled):
    """
    False sólo en `deferred`: el robot de operaciones no hace nada de
    documentos y ni siquiera abre ConOpera. Es de donde sale el ahorro.
    """
    return should_capture(mode, fallback_enabled) or should_print(mode, fallback_enabled)
