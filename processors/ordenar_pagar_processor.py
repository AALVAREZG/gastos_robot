"""
Ordenar y/o pagar operaciones que ya estan contabilizadas.

Dos usos:

- terminar una operacion contabilizada que no llego a ordenarse o pagarse -el
  robot fallo a mitad y hay numero de operacion-, u ordenar/pagar una
  contabilizada por otros medios;
- pagar una lista: el numero de lista agrupa operaciones ya contabilizadas y
  ordenadas, y es lo que corresponde a un cargo bancario de transferencias.

Va en este robot y en su cola (`sical_queue.gasto`) como un `tipo` mas: un
consumidor aparte compartiria asiento con este -un asiento es una maquina- y
no ganaria nada, salvo otro proceso que vigilar.

Mensaje (`operation_data.operation`)::

    tipo: 'ordenarypagar'
    detalle:
        num_operacion | num_lista   exactamente uno de los dos
        ordenar                     por defecto true con num_operacion; con lista no cabe
        pagar                       por defecto true
        comprobar                   solo con num_operacion: teclea el numero en
                                    «Pagar», lee el aviso de SICAL si sale y
                                    cancela sin validar. No ordena ni paga
        fecha_ordenamiento          DD/MM/YYYY o DDMMYYYY
        fecha_pago                  por defecto, la de ordenacion

    tipo: 'listas_pendientes_pago'  devuelve las listas pendientes
    detalle:
        fecha                       DD/MM/YYYY; por defecto, hoy. Se teclea antes
                                    de pulsar «Pagar», como en un pago

    tipo: 'relacion_lista'          saca la relacion de una lista, sin pagar nada
    detalle:
        num_lista
        fecha                       DD/MM/YYYY; por defecto, hoy. Solo activa
                                    «Imprimir»: la relacion no depende de ella

El resultado lleva en `result.pago` hasta donde llego cada paso (ver
`tesoreria_pagos.nuevo_estado`). Con num_operacion, `result.num_operacion` es
la operacion sobre la que se actuo; con lista va vacio, y el productor no puede
juzgar el resultado por ese campo.

El documento del pago por lista -la relacion de sus operaciones- va en
`contable_documents` con la fase `P` cuando el mensaje pide `inline_capture`.
Lo saca este robot y no el de documentos: ConOpera trabaja por operacion, y
la relacion sale de Tesoreria Pagos, que ya esta abierta al pagar.
"""

import os
from datetime import date, datetime
from typing import Any, Callable, Dict, Optional

from sical_base import (
    SicalOperationProcessor,
    SicalWindowManager,
    OperationResult,
    OperationStatus,
    attach_contable_document,
)
from sical_utils import transform_date_to_sical_format
from doc_pipeline import capture_and_return as car
from . import tesoreria_pagos
from .tesoreria_pagos import TesoreriaPagosWindowManager

# La relacion de una lista viaja como el documento de la fase de Pago: es el
# justificante del pago de la tarea, como lo sera la fase P de ConOpera en el
# pago por operacion. sical-robot la guarda en task_contable_documents
# (task_id, 'P') sin cambiar el esquema.
FASE_PAGO = 'P'


def capturar_relacion(ventana, num_lista: str, logger,
                      avisar: Optional[Callable[[str], None]] = None, cfg=None) -> dict:
    """
    Saca la relacion de la lista en PDF y devuelve su sobre `contable_document`.

    Nunca lanza: corre con la lista ya pagada, y un documento que falla no
    puede tumbar un pago hecho. El fallo va en el sobre (FAILED +
    capture_error), y la relacion se puede volver a pedir con `relacion_lista`.
    """
    if cfg is None:
        import config as cfg
    sobre = car.sobre_vacio(FASE_PAGO, f'lista_{num_lista}.pdf')
    destino = os.path.join(cfg.SICAL_PDF_WORKDIR, f'lista_{num_lista}_sical.pdf')
    try:
        ruta = tesoreria_pagos.relacion_lista_pdf(ventana, num_lista, destino, logger, avisar)
    except Exception as e:
        sobre['capture_error'] = f'relacion de la lista: {e}'
        logger.warning(f'CONTABLE {FASE_PAGO}: {sobre["capture_error"]}')
        return sobre
    return car.completar_sobre(sobre, ruta, num_lista, cfg, que='lista')


def _texto(valor: Any) -> Optional[str]:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _booleano(valor: Any, por_defecto: bool) -> bool:
    if valor is None or valor == '':
        return por_defecto
    if isinstance(valor, bool):
        return valor
    texto = str(valor).strip().lower()
    if texto in ('true', '1', 'si', 'sí', 'yes'):
        return True
    if texto in ('false', '0', 'no'):
        return False
    raise ValueError(f'valor booleano no valido: {valor!r}')


def _fecha(valor: Any, campo: str) -> Optional[str]:
    """DD/MM/YYYY o DDMMYYYY -> DDMMYYYY, comprobando que es una fecha."""
    texto = _texto(valor)
    if not texto:
        return None
    fecha = transform_date_to_sical_format(texto)
    try:
        datetime.strptime(fecha, '%d%m%Y')
    except ValueError:
        raise ValueError(f'{campo} no es una fecha DD/MM/YYYY: {valor!r}') from None
    return fecha


class _TesoreriaPagosProcessor(SicalOperationProcessor):
    """Lo comun a las operaciones que solo trabajan en Tesoreria Pagos."""

    def create_window_manager(self) -> SicalWindowManager:
        return TesoreriaPagosWindowManager(self.logger)

    def check_for_duplicates_pre_window(
        self,
        operation_data: Dict[str, Any],
        result: OperationResult,
        original_data: Optional[Dict[str, Any]] = None
    ) -> OperationResult:
        # No se crea nada en SICAL: no hay duplicados que buscar. Tampoco se
        # llega aqui, porque `duplicate_policy` va a None.
        return result

    def setup_operation_window(self) -> bool:
        return tesoreria_pagos.abrir_ventana(self.window_manager, self.logger)


class OrdenarPagarProcessor(_TesoreriaPagosProcessor):
    """Ordena y/o paga una operacion por su numero, o paga una lista."""

    @property
    def operation_type(self) -> str:
        return 'ordenarypagar'

    @property
    def operation_name(self) -> str:
        return 'Ordenar y pagar'

    def create_operation_data(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valida el mensaje. Todo lo que no cuadra se rechaza aqui, antes de
        abrir SICAL: un error en esta fase deja la tarea FAILED sin haber
        tocado nada.
        """
        num_operacion = _texto(operation_data.get('num_operacion'))
        num_lista = _texto(operation_data.get('num_lista'))
        if bool(num_operacion) == bool(num_lista):
            raise ValueError('ordenarypagar: hace falta num_operacion o num_lista, y solo uno de los dos')

        modo = tesoreria_pagos.MODO_LISTA if num_lista else tesoreria_pagos.MODO_OPERACION
        numero = num_lista or num_operacion
        if not numero.isdigit() or int(numero) == 0:
            raise ValueError(f'ordenarypagar: {modo} no es un numero valido: {numero!r}')

        comprobar = _booleano(operation_data.get('comprobar'), por_defecto=False)
        if comprobar and modo != tesoreria_pagos.MODO_OPERACION:
            raise ValueError('ordenarypagar: comprobar es solo para num_operacion '
                             '(para listas, listas_pendientes_pago)')
        ordenar = _booleano(operation_data.get('ordenar'),
                            por_defecto=modo == tesoreria_pagos.MODO_OPERACION and not comprobar)
        pagar = _booleano(operation_data.get('pagar'), por_defecto=not comprobar)
        if comprobar and (ordenar or pagar):
            raise ValueError('ordenarypagar: comprobar no ordena ni paga; '
                             'no se puede pedir a la vez que ordenar o pagar')
        if modo == tesoreria_pagos.MODO_LISTA and ordenar:
            raise ValueError('ordenarypagar: una lista ya esta ordenada; con num_lista solo se puede pagar')
        if not (ordenar or pagar or comprobar):
            raise ValueError('ordenarypagar: ordenar y pagar son false; no hay nada que hacer')
        # Mientras falte el paso de seleccionar las operaciones de la lista
        # (tesoreria_pagos.PAGO_LISTA_DISPONIBLE), el pago por lista abre SICAL
        # pero cancela antes de teclear la lista.

        fecha_ordenamiento = _fecha(operation_data.get('fecha_ordenamiento'), 'fecha_ordenamiento')
        fecha_pago = _fecha(operation_data.get('fecha_pago'), 'fecha_pago')
        fecha_ordenamiento = fecha_ordenamiento or fecha_pago
        fecha_pago = fecha_pago or fecha_ordenamiento
        if not fecha_ordenamiento:
            raise ValueError('ordenarypagar: falta la fecha (fecha_ordenamiento o fecha_pago)')

        return {
            'modo': modo,
            'numero': numero,
            'ordenar': ordenar,
            'pagar': pagar,
            'comprobar': comprobar,
            'fecha_ordenamiento': fecha_ordenamiento,
            'fecha_pago': fecha_pago,
            'duplicate_policy': None,
        }

    def process_operation_form(
        self,
        operation_data: Dict[str, Any],
        result: OperationResult
    ) -> OperationResult:
        modo = operation_data['modo']
        numero = operation_data['numero']
        estado = tesoreria_pagos.nuevo_estado(
            modo, numero,
            fecha_ordenamiento=operation_data['fecha_ordenamiento'],
            fecha_pago=operation_data['fecha_pago'],
            ordenar=operation_data['ordenar'],
            pagar=operation_data['pagar'])
        result.pago = estado
        if modo == tesoreria_pagos.MODO_OPERACION:
            # La operacion sobre la que se actua: es la que necesita el robot
            # de documentos para sacar el documento de Pago.
            result.num_operacion = numero

        ventana = self.window_manager.ventana_proceso
        self.logger.info(f'Ordenar y pagar - {modo}: {numero}, '
                         f'ordenar: {operation_data["ordenar"]}, pagar: {operation_data["pagar"]}, '
                         f'fechas: {operation_data["fecha_ordenamiento"]} / {operation_data["fecha_pago"]}')
        try:
            if operation_data.get('comprobar'):
                self.notify_step('Checking payment (no se valida)')
                tesoreria_pagos.comprobar_pago_y_salir(ventana, estado, self.logger)
            elif modo == tesoreria_pagos.MODO_LISTA:
                tesoreria_pagos.pagar_lista_y_salir(ventana, estado, self.logger, avisar=self.notify_step,
                                                    tras_pagar=self._documento_de_lista(result, numero))
            else:
                tesoreria_pagos.ordenar_y_pagar(ventana, estado, self.logger, avisar=self.notify_step)

            result.status = OperationStatus.COMPLETED
            self.phase_clock.mark(
                result, 'payment_ordering',
                f'{modo} {numero}: ordenacion {estado["ordenacion"]}, pago {estado["pago"]}')

        except Exception as e:
            self.logger.error(f'Error in order and pay: {e}')
            result.status = OperationStatus.FAILED
            result.error = f'Error ordering/paying {modo} {numero}: {str(e)}'

        return result

    def _documento_de_lista(self, result: OperationResult, num_lista: str):
        """
        Lo que hay que hacer con la lista ya pagada para traerse su relacion,
        o None si el mensaje no pide capturar.

        Solo `inline_capture`. En `deferred` nadie vendria despues a por ella
        -el robot de documentos no la sabe sacar-, asi que es el productor
        quien publica los pagos por lista en `inline_capture`. En
        `legacy_print` no se imprime: imprimirla desde el Visualizador no esta
        mapeado.
        """
        if not self.should_capture_contable():
            self.logger.info(f'document_mode={self.document_mode}: '
                             f'no se saca la relacion de la lista {num_lista}')
            return None

        def tras_pagar(ventana):
            self.notify_step('Capturing list document')
            attach_contable_document(
                result, capturar_relacion(ventana, num_lista, self.logger, avisar=self.notify_step))
            self.phase_clock.mark(result, 'list_document',
                                  f'Relacion de la lista {num_lista}: {result.capture_status}')
        return tras_pagar


class ListasPendientesPagoProcessor(_TesoreriaPagosProcessor):
    """Lee las listas pendientes de pago del desplegable de Pagar, sin pagar nada."""

    @property
    def operation_type(self) -> str:
        return 'listas_pendientes_pago'

    @property
    def operation_name(self) -> str:
        return 'Listas pendientes de pago'

    def create_operation_data(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        fecha = _fecha(operation_data.get('fecha'), 'fecha') or date.today().strftime('%d%m%Y')
        return {'fecha': fecha, 'duplicate_policy': None}

    def process_operation_form(
        self,
        operation_data: Dict[str, Any],
        result: OperationResult
    ) -> OperationResult:
        ventana = self.window_manager.ventana_proceso
        self.notify_step('Reading pending payment lists')
        try:
            listas = tesoreria_pagos.consultar_listas_pendientes(
                ventana, operation_data['fecha'], self.logger)
        except Exception as e:
            self.logger.error(f'Error reading pending lists: {e}')
            result.status = OperationStatus.FAILED
            result.error = f'Error reading pending payment lists: {str(e)}'
            return result

        result.pago = {'modo': 'consulta_listas', 'listas_pendientes': listas}
        if listas is None:
            result.status = OperationStatus.FAILED
            result.error = 'No se ha podido leer el desplegable de listas pendientes'
        else:
            result.status = OperationStatus.COMPLETED
            self.phase_clock.mark(result, 'payment_lists', f'{len(listas)} listas pendientes')
        return result


class RelacionListaProcessor(_TesoreriaPagosProcessor):
    """
    Saca la relacion de operaciones de una lista, sin pagar nada.

    Para repetir el documento de un pago por lista que fallo -la lista ya esta
    pagada y no se puede volver a pagar- y para probar la via de impresion
    contra SICAL con cualquier lista, sin pagar. El documento es el objeto de
    la tarea: se devuelve siempre, sea cual sea el `document_mode`.
    """

    @property
    def operation_type(self) -> str:
        return 'relacion_lista'

    @property
    def operation_name(self) -> str:
        return 'Relacion de lista'

    def create_operation_data(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        num_lista = _texto(operation_data.get('num_lista'))
        if not num_lista or not num_lista.isdigit() or int(num_lista) == 0:
            raise ValueError(f'relacion_lista: num_lista no es un numero valido: {num_lista!r}')
        fecha = _fecha(operation_data.get('fecha'), 'fecha') or date.today().strftime('%d%m%Y')
        return {'num_lista': num_lista, 'fecha': fecha, 'duplicate_policy': None}

    def process_operation_form(
        self,
        operation_data: Dict[str, Any],
        result: OperationResult
    ) -> OperationResult:
        ventana = self.window_manager.ventana_proceso
        num_lista = operation_data['num_lista']
        try:
            tesoreria_pagos.establecer_fecha(ventana, operation_data['fecha'])
        except Exception as e:
            self.logger.error(f'Error typing the date: {e}')
            result.status = OperationStatus.FAILED
            result.error = f'No se ha podido teclear la fecha: {e}'
            return result

        self.notify_step('Capturing list document')
        sobre = capturar_relacion(ventana, num_lista, self.logger, avisar=self.notify_step)
        attach_contable_document(result, sobre)
        try:
            tesoreria_pagos.salir(ventana, tras_pago=False)
        except Exception as e:
            self.logger.warning(f'No se pudo salir de Tesoreria Pagos: {e}')

        if sobre['capture_status'] == 'CAPTURED':
            result.status = OperationStatus.COMPLETED
            self.phase_clock.mark(result, 'list_document', f'Relacion de la lista {num_lista}')
        else:
            result.status = OperationStatus.FAILED
            result.error = sobre['capture_error']
        return result
