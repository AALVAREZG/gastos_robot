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
        fecha_ordenamiento          DD/MM/YYYY o DDMMYYYY
        fecha_pago                  por defecto, la de ordenacion

    tipo: 'listas_pendientes_pago'  devuelve las listas pendientes
    detalle:
        fecha                       DD/MM/YYYY; por defecto, hoy. Se teclea antes
                                    de pulsar «Pagar», como en un pago

El resultado lleva en `result.pago` hasta donde llego cada paso (ver
`tesoreria_pagos.nuevo_estado`). Con num_operacion, `result.num_operacion` es
la operacion sobre la que se actuo; con lista va vacio, y el productor no puede
juzgar el resultado por ese campo.
"""

from datetime import date, datetime
from typing import Any, Dict, Optional

from sical_base import (
    SicalOperationProcessor,
    SicalWindowManager,
    OperationResult,
    OperationStatus,
)
from sical_utils import transform_date_to_sical_format
from . import tesoreria_pagos
from .tesoreria_pagos import TesoreriaPagosWindowManager


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

        ordenar = _booleano(operation_data.get('ordenar'),
                            por_defecto=modo == tesoreria_pagos.MODO_OPERACION)
        pagar = _booleano(operation_data.get('pagar'), por_defecto=True)
        if modo == tesoreria_pagos.MODO_LISTA and ordenar:
            raise ValueError('ordenarypagar: una lista ya esta ordenada; con num_lista solo se puede pagar')
        if not (ordenar or pagar):
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
            if modo == tesoreria_pagos.MODO_LISTA:
                tesoreria_pagos.pagar_lista_y_salir(ventana, estado, self.logger, avisar=self.notify_step)
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
