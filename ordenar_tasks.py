import datetime
from robocorp.tasks import task
from robocorp import windows
import time, os, json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import logging
from robocorp import windows
from robocorp.tasks import task
from gasto_tasks import OperationEncoder, OperationResult, OperationStatus

###########
### ORDENAR Y PAGAR
###########

ROBOT_DIR = Path(__file__).parent.absolute()
DATA_FOLDER_NAME = 'data'
DATA_DIR = os.path.join(ROBOT_DIR, DATA_FOLDER_NAME)
PENDING_DIR = os.path.join(DATA_DIR, 'pending')
PROCESSED_DIR = os.path.join(DATA_DIR, 'processed')
FAILED_DIR = os.path.join(DATA_DIR, 'z_failed')


# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Get logger instance
gasto_logger = logging.getLogger(__name__)



class TesoreriaPagosSicalWindowManager:
    def __init__(self):
        self.ventana_proceso = None
        
    def find_proceso_window(self):
        nombre_ventana_tesoreriapagos = 'regex:.*SICAL II 4.2 TesPagos'
        return windows.find_window(f'{nombre_ventana_tesoreriapagos}', raise_error=False)
    
    def close_window(self):
        if self.ventana_proceso:
            try:
                boton_cerrar = self.ventana_proceso.find('name:"Cerrar"', search_depth=8, raise_error=False)
                if boton_cerrar:
                    boton_cerrar.click()
                    self.ventana_proceso.find('class:"TButton" and name:"No"').click()
            except Exception as e:
                gasto_logger.exception("Error closing window: %s", str(e))

@task()
def prueba_pago():
    operation_data =  {
        'num_operacion' : '225102320',
        'num_lista': None,
        'fecha_ordenamiento': '01012025',
        'fecha_pago': None,
    }
    result = ordenarypagar_gasto(operation_data)
    print(result)


def ordenarypagar_gasto(operation_data: Dict[str, Any]) -> OperationResult:
    """
    Process an order and pay process based on received message data.
    
    Args:
        operation_data: Dictionary containing the operation details from RabbitMQ message
    
    Returns:
        OperationResult: Object containing the operation results and status
    """

    print('Entry Ordenar y Pagar: ', operation_data)
    init_time = datetime.now()
    result = OperationResult(
        status=OperationStatus.PENDING,
        init_time=str(init_time),
        sical_is_open=False
    )
    
    window_manager = TesoreriaPagosSicalWindowManager()
    
    try:
        # Prepare operation data
        datos_pago = create_pago_data(operation_data)

        print('Created TESORERIA PAGOS data: ', datos_pago)
        # Setup SICAL window
        if not setup_sical_window(window_manager):
            result.status = OperationStatus.FAILED
            result.error = "Failed to open SICAL window"
            return result
        else: 
            result.sical_is_open = True
            result.status = OperationStatus.IN_PROGRESS
        
        # Process operation
        result = ordenar_y_pagar_operacion_gasto(window_manager.ventana_proceso, datos_pago, result)
        
        if result.status == OperationStatus.COMPLETED:
            # Validate and finalize
            ##result = validate_operation(window_manager.ventana_arqueo, result)
            pass
            if result.status == OperationStatus.COMPLETED:
                ## result = print_operation_document(window_manager.ventana_arqueo, result)
                pass

        
    except Exception as e:
        gasto_logger.exception("Error in tesorería pagos operation")
        result.status = OperationStatus.FAILED
        result.error = str(e)
        
        if result.sical_is_open:
            handle_error_cleanup(window_manager.ventana_arqueo)
    
    finally:
        # Cleanup
        gasto_logger.info("Finalize manually until develop is complete")
        #window_manager.close_window()
        
        # Calculate duration
        end_time = datetime.now()
        result.end_time = str(end_time)
        result.duration = str(end_time - init_time)
    
    return result

def create_pago_data(operation_data: Dict[str, Any]) -> Dict[str, Any]:
    """Transform operation data from message into SICAL-compatible format"""
    """If not fecha_pago, same date as fecha_ordenamiento"""
    fecha_orden = operation_data.get('fecha_ordenamiento', operation_data.get('fecha'))
    return {
        'num_operacion': operation_data.get('num_operacion'),
        'num_lista': operation_data.get('num_lista', None),
        'fecha_ordenamiento': fecha_orden,
        'fecha_pago': operation_data.get('fecha_pago', fecha_orden),
        
    }

def setup_sical_window(window_manager: TesoreriaPagosSicalWindowManager) -> bool:
    """Setup SICAL window for operation"""
    rama_tesoreria_pagos = ('TESORERIA', 'GESTION DE PAGOS', 'PROCESO DE ORDENACION Y PAGO')
    if not abrir_ventana_opcion_en_menu(rama_tesoreria_pagos):
        return False
    
    window_manager.ventana_proceso = window_manager.find_proceso_window()
    gasto_logger.debug(f"VENTANA proceso {window_manager.ventana_proceso}")
    return bool(window_manager.ventana_proceso)


def ordenar_y_pagar_operacion_gasto(ventana_proceso, datos_pago: Dict[str, Any], 
                           result: OperationResult) -> OperationResult:
    
    try:
        fecha_ordenpago_el = ventana_proceso.find('class:"TMaskEdit" and path:"2|1|1"')
        fecha_ordenpago_el.send_keys(datos_pago['fecha_ordenamiento'], interval=0.1, wait_time=0.5, send_enter=True)
        modal_cambio_fecha_ok = ventana_proceso.find('class:"TButton" and name:"OK" and path:"1|1"', raise_error=False)
        if modal_cambio_fecha_ok:
            modal_cambio_fecha_ok.click(wait_time=0.5)

        boton_ordenar = ventana_proceso.find('name:"Ordenar" and path:"2|7"').click(wait_time=0.8)

        if not datos_pago['num_lista']:
            option_operation_el = ventana_proceso.find('name:"Nº Operación" and class:"TGroupButton"')
            option_operation_el.click(wait_time=0.5)
            num_operation_el = ventana_proceso.find('class:"TEdit" and path:"1|1|4"').click(wait_time=0.2)
            num_operation_el.send_keys(datos_pago['num_operacion'], interval=0.1, wait_time=0.5, send_enter=True)

            #Si al introducir la operacion ya está pagada aparece error
            modal_error_ya_ordenado = ventana_proceso.find('class:"TMessageForm" and name:"Error"', timeout=1.0, raise_error=False)
            if not modal_error_ya_ordenado: #si no está ordenada la operación
                time.sleep(0.1)
                boton_validar_op = ventana_proceso.find('class:"TBitBtn" and path:"1|1|1"')
                boton_validar_op.click(wait_time=0.1)
                boton_validar_orden = ventana_proceso.find('class:"TBitBtn" and path:"2|1|3|12" and name:"Validar"')
                boton_validar_orden.click(wait_time=0.1)
                boton_modal_info_ok = ventana_proceso.find('class:"TButton" and name:"OK" and path:"1|1"')
                boton_modal_info_ok.click(wait_time=1.0)
                #imprimir mto de pago
                check_mto_pago = ventana_proceso.find('class:"TCheckBox" and name:"Mandamientos de Pagos"')
                check_mto_pago.click(wait_time=0.2)
                btn_validad_mto_pago = ventana_proceso.find('class:"TBitBtn" and path:"1|1|9"')
                btn_validad_mto_pago.click(wait_time=0.2)

                #aparecen varios cuadros de dialogo que tendremos que confirmar
                btn_modal_confirm_yes = ventana_proceso.find('class:"TButton" and name:"Yes" and path:"1|2"')
                btn_modal_confirm_yes.click(wait_time=0.2)

                btn_modal_confirm_yes2 = ventana_proceso.find('class:"TButton" and name:"Yes" and path:"1|2"')
                btn_modal_confirm_yes2.click(wait_time=0.2)

                btn_modal_confirm_firmantes = ventana_proceso.find('class:"TButton" and name:"Yes" and path:"1|2"')
                btn_modal_confirm_firmantes.click(wait_time=0.2)

                ventana_imprimir = windows.find_window('regex:.*Imprimir')
                ventana_imprimir.find('class:"Button" and name:"Aceptar" and path:"26"').click(wait_time=1.0)

                btn_final_ok = ventana_proceso.find('class:"TButton" and name:"OK" and path:"1|1"')
                btn_final_ok.click(wait_time=0.5)
            
            else:
                ventana_proceso.find('class:"TButton" and name:"OK"').click(wait_time=0.8)
                ventana_proceso.find('class:"TButton" and name:"OK"').click(wait_time=0.8)
                ventana_proceso.find('class:"TBitBtn" and path:"1|1|2"').click(wait_time=0.8)
            

            btn_pagar_mto_pago = ventana_proceso.find('class:"TBitBtn" and name:"Pagar" and path:"2|5"')
            btn_pagar_mto_pago.click(wait_time=0.4)

            option_operation_el = ventana_proceso.find('name:"Nº Operación" and class:"TGroupButton"')
            option_operation_el.click(wait_time=0.5)

            num_operation_el = ventana_proceso.find('class:"TEdit" and path:"1|1|4"').click(wait_time=0.2)
            num_operation_el.send_keys(datos_pago['num_operacion'], interval=0.1, wait_time=0.5, send_enter=True)

            boton_validar_op = ventana_proceso.find('class:"TBitBtn" and path:"1|1|1"')
            boton_validar_op.click(wait_time=1.0)

            boton_validar_orden = ventana_proceso.find('class:"TBitBtn" and path:"2|1|3|12" and name:"Validar"')
            boton_validar_orden.click(wait_time=1.0)
            
            boton_modal_info_ok = ventana_proceso.find('class:"TButton" and name:"OK" and path:"1|1"')
            boton_modal_info_ok.click(wait_time=1.0)

            btn_salir_impresion = ventana_proceso.find('class:"TBitBtn" and path:"1|1|10"')
            btn_salir_impresion.click()
            time.sleep(0.5)
            btn_salir_tes_pagos = ventana_proceso.find('class:"TBitBtn" and name:"Salir" and path:"2|8"')
            btn_salir_tes_pagos.click()
        else:
            #pagar_lista
            pass

    except Exception as e:
        result.status = OperationStatus.FAILED
        result.error = f"Validation error: {str(e)}"
    
    return result

def abrir_ventana_opcion_en_menu(menu_a_buscar):
    '''Selecciona la opción de menu elegida, desplegando cada elemento de
    la rama correspondiente definida mediante una tupla y haciendo doble click 
    en el último de la tupla, que correspondería dicha opción'''

    rama_ado = ('GASTOS', 'OPERACIONES DE PRESUPUESTO CORRIENTE')
    rama_arqueo = ('TESORERIA', 'GESTION DE COBROS', 'ARQUEOS. APLICACION DIRECTA', 
                'TRATAMIENTO INDIVIDUALIZADO/RESUMEN')
    rama_tesoreria_pagos = ('TESORERIA', 'GESTION DE PAGOS', 'PROCESO DE ORDENACION Y PAGO')

    app = windows.find_window('regex:.*FMenuSical', raise_error=False)
    if not app:
        print('¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡', 'SICAL CLOSED?????')
        return False

    if not menu_a_buscar:
        menu_a_buscar = rama_arqueo

    retraer_todos_elementos_del_menu()
    
    for element in menu_a_buscar[:-1]:
        element = app.find(f'control:"TreeItemControl" and name:"{element}"', timeout=0.05)
        element.send_keys(keys='{ADD}', wait_time=0.01)

    last_element = menu_a_buscar[-1]
    app.find(f'control:"TreeItemControl" and name:"{last_element}"').double_click()
    return True

@task
def retraer_todos_elementos_del_menu():
    '''Repliega todos los elementos del menu'''
    tree_elements = ['GASTOS', 'INGRESOS', 'OPERACIONES NO PRESUPUESTARIAS', 'TESORERIA',
                    'CONTABILIDAD GENERAL', 'TERCEROS', 'GASTOS CON FINANCIACION AFECTADA \ PROYECTO',
                    'PAGOS A JUSTIFICAR Y ANTICIPOS DE CAJA FIJA', 'ADMINISTRACION DEL SISTEMA',
                    'TRANSACCIONES ESPECIALES', 'CONSULTAS AVANZADAS', 'FACTURAS', 
                    'OFICINA DE PRESUPUESTO', 'INVENTARIO CONTABLE']
    
    app = windows.find_window('regex:.*FMenuSical')
    for element in tree_elements:
        element = app.find(f'control:"TreeItemControl" and name:"{element}"',
                        search_depth=2, timeout=0.01)
        #element.send_keys(keys='{ADD}')
        element.send_keys(keys='{SUBTRACT}', wait_time=0.01)

def handle_error_cleanup():
    """Clean up SICAL windows in case of error"""
    try:
        modal_dialog = windows.find_window("regex:.*mtec40")
        if modal_dialog:
            modal_dialog.find('class:"TButton" and name:"OK"').click()
        
        # Additional cleanup as needed
    except Exception as e:
        gasto_logger.exception("Error during cleanup: %s", str(e))