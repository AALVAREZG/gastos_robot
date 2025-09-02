import datetime
from robocorp.tasks import task
from robocorp import windows
import time, os, json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import logging
import ctypes



###########
### GASTO 1.5
## se pretende hacer uso de rabbitMq para la comunicación entre los procesos
###########

partidas_gasto_cuentaPG = {
    '224' : '625',      #920 -224 PRIMAS DE SEGUROS
    '16205' : '644',    #GASTOS SOCIALES. SEGUROS
    '311'   : '669',    #932-311 COMISIONES BANCARIAS, GASTOS
    '241'   : '629',    #241-629 GASTOS DIVERSOS, 629 COMUNICACIONES Y OTROS GASTOS
    '467'   : '6501',   #162-467 Transferencias a consorcios.
    '20104' : '561', #FIANZA OBRAS
    '30012' : '554', #INGRESOS CTAS OP PEND APLICACION
    '30016' : '554', #INGRESOS AGENTES RECAUDADORES PEND APLICACION
}

ROBOT_DIR = Path(__file__).parent.absolute()
DATA_FOLDER_NAME = 'data'
DATA_DIR = os.path.join(ROBOT_DIR, DATA_FOLDER_NAME)
PENDING_DIR = os.path.join(DATA_DIR, 'pending')
PROCESSED_DIR = os.path.join(DATA_DIR, 'processed')
FAILED_DIR = os.path.join(DATA_DIR, 'z_failed')


# Configure logging
logging.basicConfig(
    level=logging.CRITICAL,
    format='%(filename)s:%(lineno)d:%(funcName)s - %(name)s - %(levelname)s - %(message)s'
)
robocorp_logger = logging.getLogger('robocorp')

# Get logger instance
# Enable just the logger you want to see
#gasto_logger = logging.getLogger('robocorp').setLevel(logging.INFO)
# Specifically disable the logger you want to hide
#pika_logger = logging.getLogger('pika').setLevel(logging.CRITICAL)  # or logging.ERROR


# 1. First, make the Enum JSON-serializable
class OperationStatus(Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    P_DUPLICATED = "P_DUPLICATED" #POSIBLY DUPLICATED
    COMPLETED = "COMPLETED"
    INCOMPLETED = "INCOMPLETED"
    FAILED = "FAILED"

    def to_json(self):
        """Convert enum to string for JSON serialization"""
        return self.value

# 2. Create a custom JSON encoder
class OperationEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, OperationStatus):
            return obj.value
        if isinstance(obj, OperationResult):
            return {
                'status': obj.status.value,
                'init_time': obj.init_time,
                'end_time': obj.end_time,
                'duration': obj.duration,
                'error': obj.error,
                'num_operacion': obj.num_operacion,
                'total_operacion': obj.total_operacion,
                'suma_aplicaciones': obj.suma_aplicaciones,
                'sical_is_open': obj.sical_is_open
            }
        return super().default(obj)

@dataclass
class OperationResult:
    status: OperationStatus
    init_time: str
    end_time: Optional[str] = None
    duration: Optional[str] = None
    error: Optional[str] = None
    num_operacion: Optional[str] = None
    total_operacion: Optional[float] = None
    suma_aplicaciones: Optional[float] = None
    sical_is_open: bool = False
    completed_phases: Optional[list] = field(default_factory=list)  # Creates empty list
    similiar_records_encountered: int = -1

class Ado220SicalWindowManager:
    def __init__(self, logger):
        self.ventana_proceso = None
        self.logger = logger
        
        
    def find_proceso_window(self):
        nombre_ventana_ado = 'regex:.*SICAL II 4.2 new30'
        return windows.find_window(f'{nombre_ventana_ado}', raise_error=False)
    
    def close_window(self):
        if self.ventana_proceso:
            try:
                boton_cerrar = self.ventana_proceso.find('name:"Cerrar"', search_depth=8, raise_error=False)
                if boton_cerrar:
                    boton_cerrar.click()
                    self.ventana_proceso.find('class:"TButton" and name:"No"').click()
            except Exception as e:
                self.logger.exception("Error closing window: %s", str(e))

class ConsultaOpSicalWindowManager:
    def __init__(self, logger):
        self.ventana_proceso = None
        self.logger = logger
        
        
    def find_proceso_window(self):
        
        nombre_ventana_consulta_op = 'regex:.*SICAL II 4.2 ConOpera'
        return windows.find_window(f'{nombre_ventana_consulta_op}', raise_error=False)
    
    def close_window(self):
        if self.ventana_proceso:
            try:
                boton_cerrar = self.ventana_proceso.find('name:"Cerrar"', search_depth=8, raise_error=False)
                if boton_cerrar:
                    boton_cerrar.click()
                    self.ventana_proceso.find('class:"TButton" and name:"No"').click()
            except Exception as e:
                self.logger.exception("Error closing window: %s", str(e))

                

class TesoreriaPagosSicalWindowManager:
    def __init__(self, logger):
        self.ventana_proceso = None
        self.logger = logger
        
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
                self.logger.exception("Error closing window: %s", str(e))

def setup_consulta_op_window(window_manager: ConsultaOpSicalWindowManager, logger) -> bool:
    """Setup SICAL window for consulta operation"""
    rama_consulta_operaciones = ('CONSULTAS AVANZADAS', 'CONSULTA DE OPERACIONES')
    
    if not abrir_ventana_opcion_en_menu(rama_consulta_operaciones, logger):
        #si no está abierta la ventana gasto esperar un poco más 
        #DEVUELVE FALSE SOLO SI FMENUSICAL ESTA CERRADO
        time.sleep(3)
        if not abrir_ventana_opcion_en_menu(rama_consulta_operaciones, logger):
            logger.critical(f"Imposible abrir ventana: {rama_consulta_operaciones}")
            return False
        
    # ESPERAMOS UN POCO A QUE SE ABRA LA VENTANA CONSULTA
    time.sleep(2)
    window_manager.ventana_proceso = window_manager.find_proceso_window()
    window_manager.logger.debug(f"VENTANA proceso {window_manager.ventana_proceso}")

    return bool(window_manager.ventana_proceso)

def operacion_gastoADO220(operation_data: Dict[str, Any], gasto_logger) -> OperationResult:
    """
    Process an GASTO operation in SICAL system based on received message data.
    
    Args:
        operation_data: Dictionary containing the operation details from RabbitMQ message
    
    Returns:
        OperationResult: Object containing the operation results and status
    """
    gasto_logger.critical('||||||||||||||||||  --1--  ||||||||||||||')
    gasto_logger.critical(f'Entry Operación gasto: {operation_data}')
    init_time = datetime.now()
    result = OperationResult(
        status=OperationStatus.PENDING,
        init_time=str(init_time),
        sical_is_open=False,
        completed_phases = [],
        similiar_records_encountered = -1,
    )

    
    window_manager = Ado220SicalWindowManager(logger=gasto_logger)
    consulta_op_window_manager = ConsultaOpSicalWindowManager(logger=gasto_logger)
    # Prepare operation data
    try:
        datos_ado = create_ado_data(operation_data)
        gasto_logger.critical('||||||||||||||||||  --2--  ||||||||||||||')
        gasto_logger.critical(f'Created ADO data: {datos_ado}')
        result.completed_phases.append({'0':'Created ADO data'})
    except Exception as e:
        gasto_logger.critical(f'Exception creating ado data {e}')
        result.status = OperationStatus.COMPLETED

    finalizar_operacion = datos_ado.get('finalizar_operacion', False)
    if finalizar_operacion:
        try:
            # Setup SICAL window
            if not setup_consulta_op_window(consulta_op_window_manager, gasto_logger):
                result.status = OperationStatus.FAILED
                result.error = "Failed to open CONSULTA OP window"
                return result
            else: 
                result.sical_is_open = True
                result.status = OperationStatus.IN_PROGRESS
            
            
            
            result = consultar_operacion_en_SICAL(consulta_op_window_manager.ventana_proceso, datos_ado, result)
            
            if result.status == OperationStatus.FAILED:
                return result
            elif result.status == OperationStatus.P_DUPLICATED:
                txt_message = f"Posiblidad de operacion duplicada, registros simimares: {result.similiar_records_encountered}"
                gasto_logger.critical(txt_message)
                show_windows_message_box(txt_message=txt_message, txt_title="Proceso abortado")
                return result
            elif result.status == OperationStatus.IN_PROGRESS:
                pass
            else:
                gasto_logger.critical(f"Estado desconocido tras consultar operación {result}")

            
        except Exception as e:
            gasto_logger.critical(f'Exception consulting ado operation previous data {e}')
            return result
    else:
        gasto_logger.critical("NO FINALIZAR OPERACION")
        pass
                
    

    try:
        
        # Setup SICAL window
        if not setup_ado_window(window_manager, gasto_logger):
            result.status = OperationStatus.FAILED
            result.error = "Failed to open SICAL window"
            return result
        else: 
            result.sical_is_open = True
            result.status = OperationStatus.IN_PROGRESS
        
        # Process operation
        result = process_ado220_operation(window_manager.ventana_proceso, datos_ado, result)
        finalizar_operacion = datos_ado.get('finalizar_operacion', False)
        gasto_logger.critical(f"result of input data on ado220 {result}")
        gasto_logger.info(f"finalizar operacion :? {finalizar_operacion}")  # Fixed
        if result.status == OperationStatus.COMPLETED and finalizar_operacion:
            # PEDIR CONFIRMACIÓN ANTES DE VALIDAR
            # FLAG PARA EVITAR DUPLICAR REGISTROS
            red_flag = result.similiar_records_encountered > 0
            if not red_flag: 
                result = validar_operacion_ADO(window_manager.ventana_proceso, result)
                num_operacion = result.num_operacion
                gasto_logger.critical(f"result of validar operacion {result}")
                gasto_logger.critical(f"numero operacion :? {num_operacion}")
                
                if result.status == OperationStatus.COMPLETED and num_operacion:
                    #handle_error_cleanup()  # Fixed - removed parameter
                    datos_ado['num_operacion'] = num_operacion
                    imprimir_ADO_by_ventana_consulta(result, gasto_logger)
                    
                    # Fixed - added proper parameters
                    datos_pago = {
                        'num_operacion': num_operacion,
                        'fecha_ordenamiento': operation_data.get('fecha_ordenamiento', datos_ado['fecha']),
                        'fecha_pago': operation_data.get('fecha_pago', operation_data.get('fecha_ordenamiento', datos_ado['fecha']))
                    }
                    pagos_window_manager = TesoreriaPagosSicalWindowManager(logger=gasto_logger)
    
                    try:
                        print('Created TESORERIA PAGOS data: ', datos_pago)
                        # Setup SICAL window
                        if not setup_tesoreria_pago_window(pagos_window_manager, gasto_logger):
                            result.status = OperationStatus.FAILED
                            result.error = "Failed to open TESORERIA PAGOS window"
                            return result
                        else: 
                            result.sical_is_open = True
                            result.status = OperationStatus.IN_PROGRESS

                        result = ordenar_y_pagar_operacion_gasto(
                            pagos_window_manager.ventana_proceso, 
                            datos_pago, 
                            result
                        )


                    except Exception as e:
                        gasto_logger.critital("Error in tesorería pagos operation")
                        result.error = str(e)
                        
                        if result.sical_is_open:
                            handle_error_cleanup(window_manager.ventana_proceso)
        
        
    except Exception as e:
        gasto_logger.critical(f"Error in GASTO operation {e}")
        result.status = OperationStatus.FAILED
        result.error = str(e)
        
        if result.sical_is_open:
            handle_error_cleanup()  # Fixed - removed parameter
    
    finally:
        # Cleanup
        gasto_logger.critical(f"FINALIZAR OPERACION?? {datos_ado.get('finalizar_operacion', 'n/d')}")
        gasto_logger.critical(result)  # Fixed typo
        #window_manager.close_window()
        
        # Calculate duration
        end_time = datetime.now()
        result.end_time = str(end_time)
        result.duration = str(end_time - init_time)
        return result

# Also fix the handle_error_cleanup function to accept an optional parameter
def handle_error_cleanup(ventana_proceso=None):
    """Clean up SICAL windows in case of error"""
    try:
        modal_dialog = windows.find_window("regex:.*mtec40", raise_error=False)
        if modal_dialog:
            modal_dialog.find('class:"TButton" and name:"OK"').click()
        
        # Additional cleanup as needed
        if ventana_proceso:
            # Add any window-specific cleanup here if needed
            pass
            
    except Exception as e:
        robocorp_logger.exception("Error during cleanup: %s", str(e))


def create_ado_data(operation_data: Dict[str, Any]) -> Dict[str, Any]:
    """Transform operation data from message into SICAL-compatible format"""
    datos_220ADO_PLANTILLA_NOUSADO =  {
        'fecha':'23042024', 'expediente':'rbt-apunte-ADO', 'tercero' :'A28141935',
        'fpago': '10', 'tpago': '10', 'caja': '200', 
        'texto':'RECIBO POLIZA 0960270022271 23042024 - 23072024 RESP. CIVIL', 
        'aplicaciones': [{'funcional':'920', 'economica':'224', 'gfa':None, 'importe':'1745.06', 'cuenta':'625'},]
        }
    
    texto_operacion = str(operation_data.get('texto', 'ADO....'))
    
    ## TEMPORALMENTE, USAMOS ESTE TRUCO PARA FINALIZAR OPERACIÓN
    ## COMPROBAMOS SI EL TEXTO DE LA OPERACIÓN ACABA EN _FIN

    if texto_operacion.endswith('_FIN'):
        finalizar_operacion = True
        texto_operacion = texto_operacion.rstrip('_FIN')
    else:
        finalizar_operacion = False

    return {
        'fecha': operation_data.get('fecha'),
        'expediente': operation_data.get('expediente', 'rbt-apunte-ADO'),
        'tercero': operation_data.get('tercero'),
        'fpago': operation_data.get('fpago', '10'),
        'tpago': operation_data.get('tpago', '10'),
        'caja': operation_data.get('caja'),
        'texto': texto_operacion,
        'aplicaciones': create_aplicaciones(operation_data.get('aplicaciones', [])),
        'finalizar_operacion': finalizar_operacion
    }

def clean_value(value):
    print("value passed", value, type(value))
    if isinstance(value, bool):
        return value  # Return boolean values as-is
    elif isinstance(value, str) and value.lower() == 'false':
        return False
    elif isinstance(value, str) and value.lower() == 'true':
        return True
    elif isinstance(value, str):
        return value.lower()
    elif isinstance(value, int):
        return str(value)
    # Return the original value if it's not a string or int
    return bool(value)


def create_aplicaciones(final_data: list) -> list:
    """Transform aplicaciones data into SICAL-compatible format"""
    aplicaciones = []
    for aplicacion in final_data:  # Exclude last item (total)
        aplicaciones.append({
            'funcional': str(aplicacion['funcional']),
            'economica': str(aplicacion['economica']),
            'gfa': aplicacion.get('gfa', None),
            'importe': str(aplicacion['importe']),
            'cuenta': partidas_gasto_cuentaPG.get(str(aplicacion['economica']), '000'),
            'otro': False,
        })
    return aplicaciones


def setup_ado_window(window_manager: Ado220SicalWindowManager, logger) -> bool:
    """Setup SICAL window for operation"""
    rama_ado = ('GASTOS', 'OPERACIONES DE PRESUPUESTO CORRIENTE')
    time.sleep(0.5)
    if not abrir_ventana_opcion_en_menu(rama_ado, logger):
        #si no está abierta la ventana gasto esperar un poco más
        time.sleep(2)
        if not abrir_ventana_opcion_en_menu(rama_ado, logger):
            return False
    
    window_manager.ventana_proceso = window_manager.find_proceso_window()
    window_manager.logger.debug(f"VENTANA proceso {window_manager.ventana_proceso}")
    return bool(window_manager.ventana_proceso)


def process_ado220_operation(ventana_proceso, datos_ado: Dict[str, Any], 
                           result: OperationResult) -> OperationResult:
    """Process the ado operation in SICAL"""
    print('Processing ADO operation...')
    try:
        # Initialize form
        boton_nuevo_click = ventana_proceso.find('path:"2|2"').click()
        modal_confirm = windows.find_window('regex:.*Confirm', raise_error=True)
        boton_confirm_click = modal_confirm.find('name:"OK" and path:"2"').click()
        # Fill main data
        fill_main_panel_data(ventana_proceso, datos_ado, result)
        
        # Process aplicaciones. Not implemented yet, implemented in fill_main_panel_data
        # result = process_aplicaciones(ventana_arqueo, datos_arqueo['aplicaciones'], result)
        
        if result.status != OperationStatus.FAILED:
            result.status = OperationStatus.COMPLETED
            
    except Exception as e:
        result.status = OperationStatus.FAILED
        result.error = str(e)
    
    return result

def abrir_ventana_opcion_en_menu(menu_a_buscar, logger):
    '''Selecciona la opción de menu elegida, desplegando cada elemento de
    la rama correspondiente definida mediante una tupla y haciendo doble click 
    en el último de la tupla, que correspondería dicha opción'''
    logger.info('||||||||||||||||||  --3--  ||||||||||||||')
    logger.info(f'Trying to open.... {menu_a_buscar}')
    rama_ado = ('GASTOS', 'OPERACIONES DE PRESUPUESTO CORRIENTE')
    rama_arqueo = ('TESORERIA', 'GESTION DE COBROS', 'ARQUEOS. APLICACION DIRECTA', 
                   'TRATAMIENTO INDIVIDUALIZADO/RESUMEN')
    rama_tesoreria_pagos = ('TESORERIA', 'GESTION DE PAGOS', 'PROCESO DE ORDENACION Y PAGO')
    

    app = windows.find_window('regex:.*FMenuSical', raise_error=False)
    if not app:
        logger.error('¡¡¡¡¡¡¡¡¡¡¡¡¡¡¡', 'SICAL CLOSED?????')
        return False

    if not menu_a_buscar:
        menu_a_buscar = rama_arqueo

    retraer_todos_elementos_del_menu(logger)
    
    for element in menu_a_buscar[:-1]:
        element = app.find(f'control:"TreeItemControl" and name:"{element}"', timeout=0.05)
        element.send_keys(keys='{ADD}', wait_time=0.01)

    last_element = menu_a_buscar[-1]
    app.find(f'control:"TreeItemControl" and name:"{last_element}"').double_click()
    return True

def retraer_todos_elementos_del_menu(logger):
    #logger = robocorp_logger
    '''Repliega todos los elementos del menu'''
    tree_elements = ['GASTOS', 'INGRESOS', 'OPERACIONES NO PRESUPUESTARIAS', 'TESORERIA',
                     'CONTABILIDAD GENERAL', 'TERCEROS', 'GASTOS CON FINANCIACION AFECTADA \ PROYECTO',
                     'PAGOS A JUSTIFICAR Y ANTICIPOS DE CAJA FIJA', 'ADMINISTRACION DEL SISTEMA',
                     'TRANSACCIONES ESPECIALES', 'CONSULTAS AVANZADAS', 'FACTURAS', 
                     'OFICINA DE PRESUPUESTO', 'INVENTARIO CONTABLE']
    tree_elements_RED = ['TERCEROS', 'GASTOS CON FINANCIACION AFECTADA \ PROYECTO',
                     'PAGOS A JUSTIFICAR Y ANTICIPOS DE CAJA FIJA', 'ADMINISTRACION DEL SISTEMA',
                     'TRANSACCIONES ESPECIALES', 'CONSULTAS AVANZADAS', 'FACTURAS', 
                     'OFICINA DE PRESUPUESTO', 'INVENTARIO CONTABLE']
    
    app = windows.find_window('regex:.*FMenuSical')
    logger.info('||||||||||||||||||  --4--  ||||||||||||||')
    logger.info(f'Minimizando elementos')
    for element in tree_elements_RED:
        logger.info(f'{element}')
        element = app.find(f'control:"TreeItemControl" and name:"{element}"',
                           search_depth=2, timeout=0.01)
        #element.send_keys(keys='{ADD}')
        element.send_keys(keys='{SUBTRACT}', wait_time=0.01)
  

    
def fill_main_panel_data(ventana_proceso, datos_ado: Dict[str, Any], result: OperationResult) -> OperationResult:
    """Fill the main panel data in SICAL form"""
    # Implementation of filling main panel data
    # (Keeping existing logic but with improved error handling)
    # Open the JSON file
    

    try:
        print("fill main panel data with: ", ventana_proceso, datos_ado)
        default_wait_time = 0.2

        cod_operacion_element = ventana_proceso.find('class:"TComboBox" and path:"3|5|1"').click(wait_time=default_wait_time)
        cod_operacion_element.send_keys(keys='220', interval=0.05, wait_time=default_wait_time)
        cod_operacion_element.send_keys(keys='{Enter}', wait_time=default_wait_time)

        ## INTRODUCIR DATOS PANEL PRINCIPAL
        #fecha_element = ventana_proceso.find('class:"TDBDateEdit" and path:"3|5|4|8"').set_value(datos_ado['fecha'])
        fecha_element = ventana_proceso.find('class:"TDBDateEdit" and path:"3|5|4|8"').double_click()
        fecha_element.send_keys(datos_ado['fecha'], interval=0.03, wait_time=default_wait_time)

        expediente_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|4|7"').double_click()
        expediente_element.send_keys(datos_ado['expediente'], wait_time=default_wait_time)

        tercero_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|4|5"').double_click()
        tercero_element.send_keys(datos_ado['tercero'], interval=0.05, wait_time=default_wait_time)

        tesoreria_check_el = ventana_proceso.find('class:"TDBCheckBox" and name:"Tesorería" and path:"3|5|4|3"').click(wait_time=default_wait_time)

        ## SOMETIMES path of elements of forma de pago and tipo pago changes 
        # between 3|5|4 and 3|5|5
        # Define logic for manage this incident

        forma_pago_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|4|9|3"', raise_error = False)
        print(forma_pago_element)
        robocorp_logger.error(f"FORMA PAGO ELEMENT:  {forma_pago_element} ")
        if forma_pago_element:
            forma_pago_element.double_click(wait_time=default_wait_time)
        else:
            forma_pago_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|5|9|3"')
            forma_pago_element.double_click(wait_time=default_wait_time)

        #forma_pago_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|4|9|3"').double_click(wait_time=default_wait_time)
        #forma_pago_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|5|9|3"').double_click(wait_time=default_wait_time)
        
        forma_pago_element.send_keys(keys=datos_ado['fpago'], interval=0.01, wait_time=default_wait_time)
        forma_pago_element.send_keys(keys='{Enter}', wait_time=default_wait_time)

        tipo_pago_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|4|9|2"', raise_error=False)
        if tipo_pago_element:
            tipo_pago_element.double_click(wait_time=default_wait_time)
        else:
            tipo_pago_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|5|9|2"')
            tipo_pago_element.double_click(wait_time=default_wait_time)
        #tipo_pago_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|4|9|2"').double_click(wait_time=default_wait_time)
        #tipo_pago_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|5|9|2"').double_click(wait_time=default_wait_time)
        tipo_pago_element.send_keys(keys=datos_ado['tpago'], interval=0.01, wait_time=default_wait_time)
        tipo_pago_element.send_keys(keys='{Enter}', wait_time=default_wait_time)

        caja_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|4|9|1"', raise_error=False)
        if caja_element:
            caja_element.click(wait_time=default_wait_time)
            caja_element.send_keys(keys=datos_ado['caja'], interval=default_wait_time, wait_time=default_wait_time)
        else:
            caja_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|5|9|1"').click(wait_time=default_wait_time)
            caja_element.send_keys(keys=datos_ado['caja'], interval=default_wait_time, wait_time=default_wait_time)

        #caja_element = ventana_proceso.find('class:"TDBEdit" and path:"3|5|4|9|1"').click(wait_time=default_wait_time)
        
        texto_element = ventana_proceso.find('path:"3|1|1" and class:"TDBMemo"').double_click()
        texto_element.send_keys(keys='{Ctrl}{A}', wait_time=default_wait_time)
        texto_element.send_keys(datos_ado['texto'], wait_time=0.2)
        texto_element.send_keys(keys='{Enter}', wait_time=default_wait_time)

        aplicaciones_element = ventana_proceso.find('path:"3|2|1|1"').double_click()
        #grid_element = ventana_proceso.find('path:"3|2|1|1|1"')
        suma_aplicaciones = 0
        
        for i, aplicacion in enumerate(datos_ado['aplicaciones']):
            robocorp_logger.debug(f"APLICACION: {i} _ {aplicacion}")
            new_button_element = ventana_proceso.find('class:"TBitBtn" and path:"3|3|3"').click()
            ventana_proceso.send_keys(keys='{Tab}', interval=0.05, wait_time=default_wait_time, send_enter=False)
            ventana_proceso.send_keys(keys=aplicacion['funcional'], interval=default_wait_time, wait_time=default_wait_time, send_enter=True)
            ventana_proceso.send_keys(keys=aplicacion['economica'], interval=default_wait_time, wait_time=0.0, send_enter=True)
            if aplicacion.get('gfa', None): #SI TIENE GFA/PROGRAMA
                ventana_proceso.send_keys(keys=aplicacion['gfa'], interval=default_wait_time, wait_time=default_wait_time, send_enter=True)
            
            ventana_proceso.send_keys(keys='{Tab}', wait_time=0.05, interval=default_wait_time)
            ventana_proceso.send_keys(keys=aplicacion['importe'], interval=0.05, wait_time=default_wait_time, send_enter=False)
            ventana_proceso.send_keys(keys='{Enter}', wait_time=default_wait_time)
            ventana_proceso.send_keys(keys=aplicacion['cuenta'], interval=default_wait_time, wait_time=0.2)
            ckeck_button_element = ventana_proceso.find('class:"TBitBtn" and path:"3|3|5"').click()
            
            #suma_aplicaciones = suma_aplicaciones + float(aplicacion['importe'].replace(',', '.'))
        
        
        #total_operacion = ventana_proceso.find('class:"TCurrencyEdit" and path:"3|6|6"').get_value().replace(',', '.')
        total_operacion = 0
      
        
        if (float(suma_aplicaciones) != float(total_operacion)):
            robocorp_logger.debug(f'suma partidas: {suma_aplicaciones}  --> total_operacion: {total_operacion}')
            robocorp_logger.debug(float(suma_aplicaciones) == float(total_operacion))
            raise ValueError('Suma partidas no coincide con total operación.')
        result.total_operacion = total_operacion
        result.suma_aplicaciones = suma_aplicaciones
        result.completed_phases.append({2: 'Fill main panel data'})

        
    except Exception as e:
        result.status = OperationStatus.FAILED
        result.error = f"Validation error: {str(e)}"
    
    return result

def validar_operacion_ADO(ventana_proceso, result):
    result.status = OperationStatus.PENDING
    try:
        robocorp_logger.critical(f"Try to validate ADO in ...{ventana_proceso} ")
        ventana_proceso.find('name:"Validar" and path:"2|5"').click(wait_time=0.2)
    except Exception as inst:
        robocorp_logger.critical("Exception al validar la operacion ... ")
        robocorp_logger.exception("Exception al validar la operacion ... ")
        robocorp_logger.exception(type(inst))    # the exception type
    else:
        modal_confirm = windows.find_window('regex:.*Confirm')
        modal_confirm.find('class:"TButton" and name:"Yes" and path:"2"').click()
        time.sleep(1)
        modal_information = windows.find_window('regex:.*Information')
        modal_information.find('class:"TButton" and name:"OK" and path:"1"').click()
        
        time.sleep(1)
        try: 
            num_operacion_field = ventana_proceso.find('class:"TEdit" and path:"3|5|3"', raise_error = False).get_value()
            print("///////// NUMERO DE OPERACION: ", num_operacion_field)
            if num_operacion_field:
                result.num_operacion = num_operacion_field
            salir_click = ventana_proceso.find('class:"TBitBtn" and name:"Salir"').click(wait_time=0.5)
            result.status = OperationStatus.COMPLETED
            result.completed_phases.append({3: f'Operation validated: {num_operacion_field}'})

        except Exception as e:
            result.status = OperationStatus.FAILED
            result.error = f"Validation error: {str(e)}"
        
        return result

@task
def imprimir_ADO_by_ventana_consulta(result, logger):
    #logger = robocorp_logger
    #num_operacion = '225101450'
    '''
    result = OperationResult(
        status=OperationStatus.PENDING,
        init_time=str(datetime.now()),
        sical_is_open=False
    )
    '''
    num_operacion = result.num_operacion
    #IMPRIMIR MEDIANTE FORMULARIO CONSULTA
    #la opción de imprimir una vez creada la operación no funciona
    #porque no se detecta el dialogo confirmar
    rama_consulta_operaciones = ('CONSULTAS AVANZADAS', 'CONSULTA DE OPERACIONES')
    nombre_ventana_consulta_op = 'regex:.*SICAL II 4.2 ConOpera'

    ventana_consulta_op_is_open = windows.find_window(f'{nombre_ventana_consulta_op}',
                                                      timeout=1.5,
                                                      raise_error=False)
    if ventana_consulta_op_is_open:
        ventana_consulta = ventana_consulta_op_is_open
    else:
        abrir_ventana_opcion_en_menu(rama_consulta_operaciones, logger)
        ventana_consulta = windows.find_window(f'{nombre_ventana_consulta_op}', raise_error=False)
    
    
    campo_id_operacion = ventana_consulta.find('class:"TEdit" and path:"1|38"')
    campo_id_operacion.send_keys(num_operacion, interval=0.1, wait_time=0.2, send_enter=True)
    btn_imprimir_click = ventana_consulta.find('class:"TBitBtn" and name:"Imprimir"').click()
    #Si la operacion ya esta ordenada, aparece ventana para seleccion estado documento
    campo_estado_documento = ventana_consulta.find('class:"TEdit" and path:"1|3"', raise_error=False)
    if campo_estado_documento: #si no está ordenada la operación, imprime directamente
        campo_estado_documento.send_keys(keys='I', interval=0.1, send_enter=True, wait_time=3.0)
    
    ventana_visual_documentos = windows.find_window('regex:.*Visualizador de Documentos de SICAL v2')
    btn_impresora = ventana_visual_documentos.find('class:"TBitBtn" and path:"2|2|7"').click()
    #btn_guardar_pdf = ventana_visual_documentos.find('class:"TBitBtn" and path:"2|2|3"').click()
    '''
    #NO GUARDAR COMO PDF PARA EVITAR PROCESO
    save_as_window = windows.find_window('regex:.*Guardar como', timeout=1.5, raise_error=False) 
    if save_as_window:
        saveop_as_pdf_ventana(resultado_ADO['num_operacion'], save_as_window)
    
    #si existe el documento, sobreescribir
    modal_doc_exist_yesbutt = ventana_visual_documentos.find('class:"TButton" and name:"Yes" and path:"1|2"', raise_error=False)
    if modal_doc_exist_yesbutt:
        modal_doc_exist_yesbutt.click(wait_time=0.5)
        #el proceso devuelve a veces runtime error. Hacer click en Aceptar para cerrar.
        modal_runtime_error = ventana_visual_documentos.find('class:"TButton" and name:"Aceptar"', raise_error=False)
        if modal_runtime_error:
            modal_runtime_error.click(wait_time=0.5)
    
    #el proceso devuelve a veces runtime error. Hacer click en OK para cerrar.
    modal_runtime_error = ventana_visual_documentos.find('class:"TButton" and name:"OK"', raise_error=False)
    if modal_runtime_error:
        modal_runtime_error.click(wait_time=0.5)
    '''
       
    btn_salir_ventana_visual_doc = ventana_visual_documentos.find('class:"TBitBtn" and path:"2|2|6"').click()
    btn_salir_ventana_consulta =  ventana_consulta.find('class:"TBitBtn" and name:"Salir"').click()
    f_menu_sical = windows.find_window('regex:.*FMenuSical')
    result.completed_phases.append({4: f'Print operation document ID: {num_operacion}'})
    #REPLEGAR LA RAMA CONSULTAS AVANZADAS
    try:
        f_menu_sical.find('control:"TreeItemControl" and name:"CONSULTAS AVANZADAS"').double_click(wait_time=1.0)
    except windows.ActionNotPossible:
        rama_consultas_avanzadas = f_menu_sical.find('control:"TreeItemControl" and name:"CONSULTAS AVANZADAS"').double_click(wait_time=1.0)
    
    return result

def handle_error_cleanup_old():
    """Clean up SICAL windows in case of error"""
    try:
        modal_dialog = windows.find_window("regex:.*mtec40")
        if modal_dialog:
            modal_dialog.find('class:"TButton" and name:"OK"').click()
        
        # Additional cleanup as needed
    except Exception as e:
        robocorp_logger.exception("Error during cleanup: %s", str(e))


#def ordenarypagar_gasto(operation_data: Dict[str, Any], logger) -> OperationResult:
@task
def ordenar_y_pagar_prueba():
    """
    Process an order and pay process based on received message data.
    
    Args:
        operation_data: Dictionary containing the operation details from RabbitMQ message
    
    Returns:
        OperationResult: Object containing the operation results and status
    """
    logger = robocorp_logger
    operation_data = {
        'num_operacion' : '225101454',
        'fecha_ordenamiento': '03062025',
        'fecha_pago': '03062025'
    }
    
    print('Entry Ordenar y Pagar: ', operation_data)
    init_time = datetime.now()
    result = OperationResult(
        status=OperationStatus.PENDING,
        init_time=str(init_time),
        sical_is_open=False
    )
    
    window_manager = TesoreriaPagosSicalWindowManager(logger=logger)
    
    try:
        # Prepare operation data
        datos_pago = create_pago_data(operation_data)

        print('Created TESORERIA PAGOS data: ', datos_pago)
        # Setup SICAL window
        if not setup_tesoreria_pago_window(window_manager, logger):
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
        logger.exception("Error in tesorería pagos operation")
        result.status = OperationStatus.FAILED
        result.error = str(e)
        
        if result.sical_is_open:
            handle_error_cleanup(window_manager.ventana_proceso)
    
    finally:
        # Cleanup
        logger.info("Finalize manually until develop is complete")
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

def setup_tesoreria_pago_window(window_manager: TesoreriaPagosSicalWindowManager, logger) -> bool:
    """Setup SICAL window for operation"""
    rama_tesoreria_pagos = ('TESORERIA', 'GESTION DE PAGOS', 'PROCESO DE ORDENACION Y PAGO')
    if not abrir_ventana_opcion_en_menu(rama_tesoreria_pagos, logger):
        return False
    window_manager.ventana_proceso = window_manager.find_proceso_window()
    window_manager.logger.critical(f"VENTANA proceso {window_manager.ventana_proceso}")
    return bool(window_manager.ventana_proceso)


def ordenar_y_pagar_operacion_gasto(ventana_proceso, datos_pago: Dict[str, Any], 
                           result: OperationResult) -> OperationResult:
    logger = robocorp_logger
    logger.info('||||||||||||||||||  --5--  ||||||||||||||')
    logger.critical(f'Trying to order and pay .... {datos_pago}')
    logger.critical(f'With window manager .... {ventana_proceso}')
    try:
        fecha_ordenpago_el = ventana_proceso.find('class:"TMaskEdit" and path:"2|1|1"')
        fecha_ordenpago_el.send_keys(datos_pago['fecha_ordenamiento'], interval=0.1, wait_time=0.5, send_enter=True)
        modal_cambio_fecha_ok = ventana_proceso.find('class:"TButton" and name:"OK" and path:"1|1"', raise_error=False)
        if modal_cambio_fecha_ok:
            modal_cambio_fecha_ok.click(wait_time=0.5)

        boton_ordenar = ventana_proceso.find('name:"Ordenar" and path:"2|7"').click(wait_time=0.8)

        if not datos_pago.get('num_lista', False):
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
            result.completed_phases.append({5: f"Operacion ordenada y pagada: {datos_pago['num_operacion']}"})
        else:
            #pagar_lista
            pass

    except Exception as e:
        logger.exception(f'excepcion order and pay: {e} ')
        result.status = OperationStatus.FAILED
        result.error = f"Error al ordenar o pagar operacion: {datos_pago['num_operacion']} - {str(e)}"
    
    return result

def consultar_operacion_en_SICAL(ventana_proceso, datos_ado: Dict[str, Any], result: OperationResult) -> OperationResult:

    logger = robocorp_logger
    
    #IMPRIMIR MEDIANTE FORMULARIO CONSULTA
    #la opción de imprimir una vez creada la operación no funciona
    #porque no se detecta el dialogo confirmar
    
    
    filtros_button = ventana_proceso.find('class:"TBitBtn" and name:"Filtros"')
    filtros_button.click()

    nombre_ventana_filtros_op = 'regex:.*SICAL II 4.2 FilOpera'
    try:
        ventana_filtros_op = windows.find_window(f'{nombre_ventana_filtros_op}',
                                                      timeout=1.5,
                                                        raise_error=False)
        
        tercero_field = ventana_filtros_op.find('class:"TEdit" and path:"2|34"')
        tercero_field.double_click()
        tercero_field.send_keys(datos_ado['tercero'],interval=0.1, wait_time=0.1, send_enter=True )
        
        from_date_field = ventana_filtros_op.find('control:"EditControl" and path:"2|29"')
        from_date_field.double_click()
        from_date_field.send_keys(datos_ado['fecha'],interval=0.01, wait_time=0.1, send_enter=True)
        
        to_date_field = ventana_filtros_op.find('control:"EditControl" and path:"2|18"')
        to_date_field.double_click()
        to_date_field.send_keys(datos_ado['fecha'],interval=0.01, wait_time=0.1, send_enter=True)

        aplicacion_funcional = ventana_filtros_op.find('class:"TEdit" and path:"2|39"')
        aplicacion_funcional.double_click()
        aplicacion_funcional.send_keys(datos_ado['aplicaciones'][0]['funcional'],interval=0.01, wait_time=0.1, send_enter=True)

        aplicacion_economica = ventana_filtros_op.find('class:"TEdit" and path:"2|38"')
        aplicacion_economica.double_click()
        aplicacion_economica.send_keys(datos_ado['aplicaciones'][0]['economica'],interval=0.01, wait_time=0.1, send_enter=True)

        importe_desde = ventana_filtros_op.find('class:"TEdit" and path:"2|5"')
        importe_desde.double_click()
        importe_desde.send_keys(datos_ado['aplicaciones'][0]['importe'],interval=0.01, wait_time=0.1, send_enter=True)

        importe_hasta = ventana_filtros_op.find('class:"TEdit" and path:"2|4"')
        importe_hasta.double_click()
        importe_hasta.send_keys(datos_ado['aplicaciones'][0]['importe'],interval=0.01, wait_time=0.1, send_enter=True)

        caja_field = ventana_filtros_op.find('class:"Edit" and path:"2|16|1"')
        caja_field.click()
        caja_field.send_keys(datos_ado['caja'],interval=0.01, wait_time=0.1, send_enter=True)

        consultar_button_click = ventana_filtros_op.find('class:"TBitBtn" and name:"Consultar"').click()
        #Si no existen operaciones aparece un modal con error "no se ha encontrado registros"
        modal_error_sin_registros = ventana_filtros_op.find('class:"TMessageForm" and name:"Error"', timeout=1.0, raise_error=False)
        
        if not modal_error_sin_registros: #si no aparece modal error, existen registros
            #consultar número de registros encontrados
            num_registros = ventana_filtros_op.find('class:"TEdit" and path:"1|1|2"').get_value()
            print("numero de registros, ", num_registros)
            result.similiar_records_encountered = num_registros
            result.status = OperationStatus.P_DUPLICATED
           
        else:
            result.similiar_records_encountered = 0
            logger.critical("No existen registros similares")
            click_ok_button = ventana_filtros_op.find('class:"TButton" and name:"OK"').click()
            close_filtros = ventana_filtros_op.find('control:"ButtonControl" and name:"Cerrar"').click()
            # No cerramos la ventana consulta, luego la necesitamos para imprimir y nos ahorramos abrirla
            # close_consulta_op = ventana_proceso.find('class:"TBitBtn" and name:"Salir"').click()
            time.sleep(0.1)

        result.completed_phases.append({1: f'Registros similares consultados: {result.similiar_records_encountered} encontrados'})
        
    except windows.ElementNotFound:
        logger.critical(f"Not found {nombre_ventana_filtros_op}")
        result.status = OperationStatus.FAILED
      
   
    return result

def show_windows_message_box(txt_message, txt_title):
    # Constantes de MessageBox
    MB_OK = 0x0
    MB_OKCANCEL = 0x1
    MB_ICONINFORMATION = 0x40
    MB_ICONWARNING = 0x30
    MB_ICONERROR = 0x10
    MB_SYSTEMMODAL = 0x1000
    # Define the MessageBoxW function
    MessageBox = ctypes.windll.user32.MessageBoxW
    # 0x40 is the icon type for information, 0x0 for no options, "Message text" is your message, "Title" is the message box title
    MessageBox(None, txt_message, txt_title, MB_SYSTEMMODAL | MB_ICONINFORMATION )



@task
def consultar_operacion_en_SICAL_TASK():

#def fill_main_panel_data(ventana_proceso, datos_ado: Dict[str, Any], result: OperationResult) -> OperationResult:
    datos_ado =  {
        'fecha':'01012025', 'expediente':'rbt-apunte-ADO', 'tercero' :'A08663619',
        'fpago': '10', 'tpago': '10', 'caja': '204', 
        'texto':'//', 
        'aplicaciones': [{'funcional':'932', 'economica':'311', 'gfa':None, 'importe':'30.00', 'cuenta':'625'},]
        }
    logger = robocorp_logger
    result = False
    #IMPRIMIR MEDIANTE FORMULARIO CONSULTA
    #la opción de imprimir una vez creada la operación no funciona
    #porque no se detecta el dialogo confirmar
    rama_consulta_operaciones = ('CONSULTAS AVANZADAS', 'CONSULTA DE OPERACIONES')
    nombre_ventana_consulta_op = 'regex:.*SICAL II 4.2 ConOpera'

    ventana_consulta_op_is_open = windows.find_window(f'{nombre_ventana_consulta_op}',
                                                      timeout=1.5,
                                                      raise_error=False)
    if ventana_consulta_op_is_open:
        ventana_consulta = ventana_consulta_op_is_open
    else:
        abrir_ventana_opcion_en_menu(rama_consulta_operaciones, logger)
        ventana_consulta = windows.find_window(f'{nombre_ventana_consulta_op}', raise_error=False)
    
    filtros_button = ventana_consulta.find('class:"TBitBtn" and name:"Filtros"')
    filtros_button.click()

    nombre_ventana_filtros_op = 'regex:.*SICAL II 4.2 FilOpera'
    try:
        ventana_filtros_op = windows.find_window(f'{nombre_ventana_filtros_op}',
                                                      timeout=1.5,
                                                        raise_error=False)
        
        tercero_field = ventana_filtros_op.find('class:"TEdit" and path:"2|34"')
        tercero_field.double_click()
        tercero_field.send_keys(datos_ado['tercero'],interval=0.1, wait_time=0.1, send_enter=True )
        
        from_date_field = ventana_filtros_op.find('control:"EditControl" and path:"2|29"')
        from_date_field.double_click()
        from_date_field.send_keys(datos_ado['fecha'],interval=0.01, wait_time=0.1, send_enter=True)
        
        to_date_field = ventana_filtros_op.find('control:"EditControl" and path:"2|18"')
        to_date_field.double_click()
        to_date_field.send_keys(datos_ado['fecha'],interval=0.01, wait_time=0.1, send_enter=True)

        aplicacion_funcional = ventana_filtros_op.find('class:"TEdit" and path:"2|39"')
        aplicacion_funcional.double_click()
        aplicacion_funcional.send_keys(datos_ado['aplicaciones'][0]['funcional'],interval=0.01, wait_time=0.1, send_enter=True)

        aplicacion_economica = ventana_filtros_op.find('class:"TEdit" and path:"2|38"')
        aplicacion_economica.double_click()
        aplicacion_economica.send_keys(datos_ado['aplicaciones'][0]['economica'],interval=0.01, wait_time=0.1, send_enter=True)

        importe_desde = ventana_filtros_op.find('class:"TEdit" and path:"2|5"')
        importe_desde.double_click()
        importe_desde.send_keys(datos_ado['aplicaciones'][0]['importe'],interval=0.01, wait_time=0.1, send_enter=True)

        importe_hasta = ventana_filtros_op.find('class:"TEdit" and path:"2|4"')
        importe_hasta.double_click()
        importe_hasta.send_keys(datos_ado['aplicaciones'][0]['importe'],interval=0.01, wait_time=0.1, send_enter=True)

        caja_field = ventana_filtros_op.find('class:"Edit" and path:"2|16|1"')
        caja_field.click()
        caja_field.send_keys(datos_ado['caja'],interval=0.01, wait_time=0.1, send_enter=True)

        consultar_button_click = ventana_filtros_op.find('class:"TBitBtn" and name:"Consultar"').click()
        #Si no existen operaciones aparece un modal con error "no se ha encontrado registros"
        modal_error_sin_registros = ventana_filtros_op.find('class:"TMessageForm" and name:"Error"', timeout=1.0, raise_error=False)
        
        if not modal_error_sin_registros: #si no aparece modal error, existen registros
            #consultar número de registros encontrados
            num_registros = ventana_filtros_op.find('class:"TEdit" and path:"1|1|2"').get_value()
            print("numero de registros, ", num_registros)
            result = True
           
        else:
            result = False
            print("no existen registros")
            time.sleep(0.1)


    except windows.ElementNotFound:
        logger.critical(f"Not found {nombre_ventana_filtros_op}")
      
   
    return result

