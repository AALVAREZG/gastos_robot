from robocorp.tasks import task
from robocorp import windows
from robocorp import log
import time, os, json


###########
### ADO_GASTO
# v1.3
# In this-version ado data loads from file ado220.json
###########


@task
def load_json_data():
    # Open the JSON file
    with open('ado220.json') as file:
        # Load the JSON data into a Python data structure
        data = json.load(file)

    # Now you can access the data as a Python dictionary
    log.debug(data)

    

@task
def imprimir_ADO():
    resultado = {}
    resultado['num_operacion'] = '224100870'
    imprimir_ADO_by_ventana_consulta(resultado)

@task
def ordenar_y_pagar_operacion():
    lista_operaciones = [
        {'num_op' : '325100062', 'fecha': '11032025'},
        
    ]
    for op in lista_operaciones:
        ordenar_y_pagar_operacion_gastoADO(num_operacion=op['num_op'], 
                                           num_lista=None, 
                                           fecha_ordenamiento=op['fecha'],
                                           fecha_pago=op['fecha'])
        


@task
def ordenar_y_pagar_lista():
    lista_operaciones = [
        {'num_op' : '224102741', 'fecha': '10102024'},
        {'num_op' : '224102740', 'fecha': '10102024'},
        {'num_op' : '224102748', 'fecha': '23102024'},
        {'num_op' : '224102749', 'fecha': '24102024'},
        {'num_op' : '224102750', 'fecha': '24102024'},
    ]

    for op in lista_operaciones:
        ordenar_y_pagar_operacion_gastoADO(num_operacion=op['num_op'], 
                                           num_lista=None, 
                                           fecha_ordenamiento=op['fecha'],
                                           fecha_pago=op['fecha'])
        
cuenta_contable_economica =  {
    '224' : '625',      #PRIMAS DE SEGUROS
    '16205' : '644',    #GASTOS SOCIALES. SEGUROS
    '311'   : '669',    #932-311 COMISIONES BANCARIAS, GASTOS
    '241'   : '629',    #241-629 GASTOS DIVERSOS, 629 COMUNICACIONES Y OTROS GASTOS
}
# 920 - 224 Adminitracion General - Seguros


@task
def temp():
    ordenar_y_pagar_operacion_gastoADO('224101811', 
                                           num_lista=None, 
                                           fecha_ordenamiento='03082024',
                                           fecha_pago='03082024')
    

@task   
def operacion_220ADO():
    
    pagar = True
    resultado_ADO = {}
    datos_220ADO_PLANTILLA_NOUSADO =  {
        'fecha':'23042024', 'expediente':'rbt-apunte-ADO', 'tercero' :'A28141935',
        'fpago': '10', 'tpago': '10', 'caja': '200', 
        'texto':'RECIBO POLIZA 0960270022271 23042024 - 23072024 RESP. CIVIL', 
        'aplicaciones': [{'funcional':'920', 'economica':'224', 'gfa':None, 'importe':'1745.06', 'cuenta':'625'},]
                    }
    

    # Open the JSON file
    with open('ado220.json', 'r') as file:
        # Load the JSON data into a Python data structure
        data_from_json = json.load(file)

    # Now you can access the data as a Python dictionary
    print(data_from_json)

    #ventana_ADO = abrir_ventana_operaciones_gasto()
    rama_ado = ('GASTOS', 'OPERACIONES DE PRESUPUESTO CORRIENTE')
    nombre_ventana_ado = 'regex:.*SICAL II 4.2 new30'

    #Si está abierta la ventana de operaciones de gasto, cerrarla
    ventana_ADO_is_open = windows.find_window(f'{nombre_ventana_ado}', raise_error=False)
    if ventana_ADO_is_open:
        ventana_ADO_is_open.find('control:"ButtonControl" and name:"Cerrar" and path:"5|4"').click()
    
    abrir_ventana_opcion_en_menu(rama_ado)
    ventana_ADO = windows.find_window(f'{nombre_ventana_ado}', raise_error=False)
    
    resultado = introducir_datos_220ADO(app=ventana_ADO, 
                                        datos_ADO=data_from_json,
                                        resultado=resultado_ADO)
    
    
    ###DESACTIVAR EN PRODUCCIÓN.
    '''
    time.sleep(3)
    ventana_ADO.find('control:"ButtonControl" and name:"Cerrar" and path:"5|4"').click()
    confirm = windows.find_window('regex:.*Confirm')
    confirm.find('class:"TButton" and name:"Yes"').click()
    
    '''
    resultado = validar_operacion_ADO(app = ventana_ADO, resultado= resultado_ADO)
    
    resultado = imprimir_ADO_by_ventana_consulta(resultado_ADO)
    
    num_operacion = resultado.get('num_operacion', '000error')
    fecha_orden = data_from_json.get('fecha', '00error')
    fecha_pago = data_from_json.get('fecha', '00error')
    
    if pagar:
        ordenar_y_pagar_operacion_gastoADO(num_operacion, 
                                           num_lista=None, 
                                           fecha_ordenamiento=fecha_orden,
                                           fecha_pago=fecha_pago)

    filename = 'resultado.json'
    with open(filename, 'w') as json_file:
        json.dump(resultado, json_file, indent=4)
    
    return resultado

   
    
    

def ordenar_y_pagar_operacion_gastoADO(num_operacion, num_lista, fecha_ordenamiento, fecha_pago):
    

    rama_tesoreria_pagos = ('TESORERIA', 'GESTION DE PAGOS', 'PROCESO DE ORDENACION Y PAGO')
    nombre_ventana_tespagos = 'regex:.*SICAL II 4.2 TesPagos'

    ventana_tesoreria_pagos_is_open = windows.find_window(f'{nombre_ventana_tespagos}', timeout=1.0, raise_error=False)
    if ventana_tesoreria_pagos_is_open:
        ventana_tesoreria_pagos = ventana_tesoreria_pagos_is_open
    else:
        abrir_ventana_opcion_en_menu(rama_tesoreria_pagos)
        ventana_tesoreria_pagos = windows.find_window(f'{nombre_ventana_tespagos}', raise_error=False)

      
    if ventana_tesoreria_pagos:
        fecha_ordenpago_el = ventana_tesoreria_pagos.find('class:"TMaskEdit" and path:"2|1|1"')
        fecha_ordenpago_el.send_keys(fecha_ordenamiento, interval=0.1, wait_time=0.5, send_enter=True)
        modal_cambio_fecha_ok = ventana_tesoreria_pagos.find('class:"TButton" and name:"OK" and path:"1|1"', raise_error=False)
        if modal_cambio_fecha_ok:
            modal_cambio_fecha_ok.click(wait_time=0.5)

        boton_ordenar = ventana_tesoreria_pagos.find('name:"Ordenar" and path:"2|7"').click(wait_time=0.8)

        if not num_lista:
            option_operation_el = ventana_tesoreria_pagos.find('name:"Nº Operación" and class:"TGroupButton"')
            option_operation_el.click(wait_time=0.5)
            num_operation_el = ventana_tesoreria_pagos.find('class:"TEdit" and path:"1|1|4"').click(wait_time=0.2)
            num_operation_el.send_keys(num_operacion, interval=0.1, wait_time=0.5, send_enter=True)

            #Si al introducir la operacion ya está pagada aparece error
            modal_error_ya_ordenado = ventana_tesoreria_pagos.find('class:"TMessageForm" and name:"Error"', timeout=1.0, raise_error=False)
            if not modal_error_ya_ordenado: #si no está ordenada la operación
                time.sleep(0.1)
                boton_validar_op = ventana_tesoreria_pagos.find('class:"TBitBtn" and path:"1|1|1"')
                boton_validar_op.click(wait_time=0.1)
                boton_validar_orden = ventana_tesoreria_pagos.find('class:"TBitBtn" and path:"2|1|3|12" and name:"Validar"')
                boton_validar_orden.click(wait_time=0.1)
                boton_modal_info_ok = ventana_tesoreria_pagos.find('class:"TButton" and name:"OK" and path:"1|1"')
                boton_modal_info_ok.click(wait_time=1.0)
                #imprimir mto de pago
                check_mto_pago = ventana_tesoreria_pagos.find('class:"TCheckBox" and name:"Mandamientos de Pagos"')
                check_mto_pago.click(wait_time=0.2)
                btn_validad_mto_pago = ventana_tesoreria_pagos.find('class:"TBitBtn" and path:"1|1|9"')
                btn_validad_mto_pago.click(wait_time=0.8)

                #aparecen varios cuadros de dialogo que tendremos que confirmar
                btn_modal_confirm_yes = ventana_tesoreria_pagos.find('class:"TButton" and name:"Yes" and path:"1|2"')
                btn_modal_confirm_yes.click(wait_time=0.5)

                btn_modal_confirm_yes2 = ventana_tesoreria_pagos.find('class:"TButton" and name:"Yes" and path:"1|2"')
                btn_modal_confirm_yes2.click(wait_time=0.5)

                btn_modal_confirm_firmantes = ventana_tesoreria_pagos.find('class:"TButton" and name:"Yes" and path:"1|2"')
                btn_modal_confirm_firmantes.click(wait_time=0.5)

                ventana_imprimir = windows.find_window('regex:.*Imprimir')
                ventana_imprimir.find('class:"Button" and name:"Aceptar" and path:"26"').click(wait_time=1.0)

                btn_final_ok = ventana_tesoreria_pagos.find('class:"TButton" and name:"OK" and path:"1|1"')
                btn_final_ok.click(wait_time=0.5)
            
            else:
                ventana_tesoreria_pagos.find('class:"TButton" and name:"OK"').click(wait_time=0.8)
                ventana_tesoreria_pagos.find('class:"TButton" and name:"OK"').click(wait_time=0.8)
                ventana_tesoreria_pagos.find('class:"TBitBtn" and path:"1|1|2"').click(wait_time=0.8)
            

            btn_pagar_mto_pago = ventana_tesoreria_pagos.find('class:"TBitBtn" and name:"Pagar" and path:"2|5"')
            btn_pagar_mto_pago.click(wait_time=0.4)

            option_operation_el = ventana_tesoreria_pagos.find('name:"Nº Operación" and class:"TGroupButton"')
            option_operation_el.click(wait_time=0.5)

            num_operation_el = ventana_tesoreria_pagos.find('class:"TEdit" and path:"1|1|4"').click(wait_time=0.2)
            num_operation_el.send_keys(num_operacion, interval=0.1, wait_time=0.5, send_enter=True)

            boton_validar_op = ventana_tesoreria_pagos.find('class:"TBitBtn" and path:"1|1|1"')
            boton_validar_op.click(wait_time=1.0)

            boton_validar_orden = ventana_tesoreria_pagos.find('class:"TBitBtn" and path:"2|1|3|12" and name:"Validar"')
            boton_validar_orden.click(wait_time=1.0)
            
            boton_modal_info_ok = ventana_tesoreria_pagos.find('class:"TButton" and name:"OK" and path:"1|1"')
            boton_modal_info_ok.click(wait_time=1.0)

            btn_salir_impresion = ventana_tesoreria_pagos.find('class:"TBitBtn" and path:"1|1|10"')
            btn_salir_impresion.click()
            time.sleep(0.5)
            btn_salir_tes_pagos = ventana_tesoreria_pagos.find('class:"TBitBtn" and name:"Salir" and path:"2|8"')
            btn_salir_tes_pagos.click()



def introducir_datos_220ADO(app, datos_ADO, resultado):
        
    ## HACER CLICK EN BOTON NUEVO PARA INICIALIZAR EL FORMULARIO
    boton_nuevo = app.find('path:"2|2"').click()
    
    modal_confirm = windows.find_window('regex:.*Confirm', raise_error=True)
    boton_confirm = modal_confirm.find('name:"OK" and path:"2"').click()
    
    
    #boton_confirm = app.find('path:"1|2" > name:"Confirm"').click()
    #modal_confirm = windows.find_window('regex:.*Confirm')
    #boton_confirm = modal_confirm.find('path:"2"').click(wait_time=1.0)

    cod_operacion_element = app.find('class:"TComboBox" and path:"3|5|1"').click(wait_time=0.3)
    cod_operacion_element.send_keys(keys='220', interval=0.05, wait_time=0.1)
    cod_operacion_element.send_keys(keys='{Enter}', wait_time=0.1)

    ## INTRODUCIR DATOS PANEL PRINCIPAL
    fecha_element = app.find('class:"TDBDateEdit" and path:"3|5|4|8"').double_click()
    fecha_element.send_keys(datos_ADO['fecha'], interval=0.03, wait_time=0.1)

    expediente_element = app.find('class:"TDBEdit" and path:"3|5|4|7"').double_click()
    expediente_element.send_keys(datos_ADO['expediente'], wait_time=0.1)

    tercero_element = app.find('class:"TDBEdit" and path:"3|5|4|5"').double_click()
    tercero_element.send_keys(datos_ADO['tercero'], interval=0.05, wait_time=0.1)

    tesoreria_check_el = app.find('class:"TDBCheckBox" and name:"Tesorería" and path:"3|5|4|3"').click(wait_time=1.0)

    forma_pago_element = app.find('class:"TDBEdit" and path:"3|5|4|9|3"').double_click(wait_time=0.1)
    #forma_pago_element = app.find('class:"TDBEdit" and path:"3|5|5|9|3"').double_click(wait_time=0.1)

    
    forma_pago_element.send_keys(keys=datos_ADO['fpago'], interval=0.01, wait_time=0.1)
    forma_pago_element.send_keys(keys='{Enter}', wait_time=0.1)

    tipo_pago_element = app.find('class:"TDBEdit" and path:"3|5|4|9|2"').double_click(wait_time=0.1)
    #tipo_pago_element = app.find('class:"TDBEdit" and path:"3|5|5|9|2"').double_click(wait_time=0.1)
    tipo_pago_element.send_keys(keys=datos_ADO['tpago'], interval=0.01, wait_time=0.1)
    tipo_pago_element.send_keys(keys='{Enter}', wait_time=0.1)

    caja_element = app.find('class:"TDBEdit" and path:"3|5|4|9|1"').click(wait_time=0.1)
    #caja_element = app.find('class:"TDBEdit" and path:"3|5|5|9|1"').click(wait_time=0.1)
    caja_element.send_keys(keys=datos_ADO['caja'], interval=0.1, wait_time=0.1)

    texto_element = app.find('path:"3|1|1" and class:"TDBMemo"').double_click()
    texto_element.send_keys(keys='{Ctrl}{A}', wait_time=0.1)
    texto_element.send_keys(datos_ADO['texto'], wait_time=0.2)
    texto_element.send_keys(keys='{Enter}', wait_time=0.1)

    #aplicaciones_element = app.find('path:"3|2|1|1"').double_click()
    grid_element = app.find('path:"3|2|1|1|1"')
    suma_aplicaciones = 0
    
    for i, aplicacion in enumerate(datos_ADO['aplicaciones']):
        log.debug(f"APLICACION: {i} _ {aplicacion['funcional']}-{aplicacion['economica']}")
        new_button_element = app.find('class:"TBitBtn" and path:"3|3|3"').click()
        app.send_keys(keys='{Tab}', interval=0.05, wait_time=0.1, send_enter=False)
        app.send_keys(keys=aplicacion['funcional'], interval=0.1, wait_time=0.1, send_enter=True)
        app.send_keys(keys=aplicacion['economica'], interval=0.1, wait_time=0.0, send_enter=True)
        if aplicacion.get('gfa', None): #SI TIENE GFA/PROGRAMA
            app.send_keys(keys=aplicacion['gfa'], interval=0.1, wait_time=0.1, send_enter=True)
          
        app.send_keys(keys='{Tab}', wait_time=0.05, interval=0.1)
        app.send_keys(keys=aplicacion['importe'], interval=0.05, wait_time=0.1, send_enter=False)
        app.send_keys(keys='{Enter}', wait_time=0.1)
        app.send_keys(keys=aplicacion['cuenta'], interval=0.1, wait_time=0.2)
        ckeck_button_element = app.find('class:"TBitBtn" and path:"3|3|5"').click()
        
        suma_aplicaciones = suma_aplicaciones + float(aplicacion['importe'].replace(',', '.'))
    
    
    total_operacion = app.find('class:"TCurrencyEdit" and path:"3|6|6"').get_value().replace(',', '.')
    
    resultado['total_operacion'] = total_operacion
    resultado['suma_aplicaciones'] = suma_aplicaciones
    
    if (float(suma_aplicaciones) != float(total_operacion)):
        log.debug(f'suma partidas: {suma_aplicaciones}  --> total_operacion: {total_operacion}')
        log.debug(float(suma_aplicaciones) == float(total_operacion))
        raise ValueError('Suma partidas no coincide con total operación.')
    
    return resultado

def validar_operacion_ADO(app, resultado):
    try:
        app.find('name:"Validar" and path:"2|5"').click(wait_time=0.2)

    except Exception as inst:
        log.exception("Exception al validar la operacion ... ")
        log.exception(type(inst))    # the exception type
    else:
        modal_confirm = windows.find_window('regex:.*Confirm')
        modal_confirm.find('class:"TButton" and name:"Yes" and path:"2"').click()
        time.sleep(1)
        modal_information = windows.find_window('regex:.*Information')
        modal_information.find('class:"TButton" and name:"OK" and path:"1"').click()
        
        time.sleep(1)
        try: 
            num_operacion = app.find('class:"TEdit" and path:"3|5|3"').get_value()
            resultado['num_operacion'] = num_operacion
            salir_click = app.find('class:"TBitBtn" and name:"Salir"').click(wait_time=0.5)
            return resultado

        except Exception as inst:
            log.exception("Exception al recuperar el núm de operacion ... ")
            log.exception(type(inst))    # the exception type
        

def imprimir_ADO_by_ventana_consulta(resultado_ADO):
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
        abrir_ventana_opcion_en_menu(rama_consulta_operaciones)
        ventana_consulta = windows.find_window(f'{nombre_ventana_consulta_op}', raise_error=False)
    
    num_operacion = resultado_ADO['num_operacion']
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
    #REPLEGAR LA RAMA CONSULTAS AVANZADAS
    try:
        f_menu_sical.find('control:"TreeItemControl" and name:"CONSULTAS AVANZADAS"').double_click(wait_time=1.0)
    except windows.ActionNotPossible:
        rama_consultas_avanzadas = f_menu_sical.find('control:"TreeItemControl" and name:"CONSULTAS AVANZADAS"').double_click(wait_time=1.0)
    
    return resultado_ADO


def saveop_as_pdf_ventana(num_operacion, save_as_window):
    pdf_path = os.path.join('U:\\usuarios\\secretaria\\AAlvarez\\Tesoreria', 'rbt-apuntes')
    pdf_name = os.path.join(pdf_path, num_operacion + '.pdf')
    save_as_window = windows.find_window('regex:.*Guardar como') 
    time.sleep(2)
    #save_as_window.find('path:"6|1|3|1|1|1"').set_value(pdf_path)
    save_as_window.find('control:"EditControl" and name:"Nombre:"').set_value(pdf_name)
    time.sleep(2)
    save_as_window.find('class:"Button" and name:"Guardar"').click()
   


def saveop_as_pdf(num_operacion):
    pdf_path = os.path.join('U:\\usuarios\\secretaria\\AAlvarez\\Tesoreria', 'rbt-apuntes')
    pdf_name = os.path.join(pdf_path, num_operacion + '.pdf')
    save_as_window = windows.find_window('regex:.*Guardar como') 
    path_field = save_as_window.find('class:"ToolbarWindow32" and path:"6|1|3|1|1|1"')
    time.sleep(2)
    #save_as_window.find('path:"6|1|3|1|1|1"').set_value(pdf_path)
    save_as_window.find('control:"EditControl" and name:"Nombre:" and path:"1|1|6|3|2|1"').set_value(pdf_name)
    time.sleep(5)
    save_as_window.find('class:"Button" and name:"Guardar" and path:"3"').click()


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


#@task
def abrir_ventana_opcion_en_menu(menu_a_buscar):
    '''Selecciona la opción de menu elegida, desplegando cada elemento de
    la rama correspondiente definida mediante una tupla y haciendo doble click 
    en el último de la tupla, que correspondería dicha opción'''

    rama_ado = ('GASTOS', 'OPERACIONES DE PRESUPUESTO CORRIENTE')
    rama_arqueo = ('TESORERIA', 'GESTION DE COBROS', 'ARQUEOS. APLICACION DIRECTA', 
                   'TRATAMIENTO INDIVIDUALIZADO/RESUMEN')
    rama_tesoreria_pagos = ('TESORERIA', 'GESTION DE PAGOS', 'PROCESO DE ORDENACION Y PAGO')

    #menu_a_buscar = rama_arqueo
    retraer_todos_elementos_del_menu()
    app = windows.find_window('regex:.*FMenuSical')

    
    for element in menu_a_buscar[:-1]:
        element = app.find(f'control:"TreeItemControl" and name:"{element}"', timeout=0.1)
        element.send_keys(keys='{ADD}', wait_time=0.01)

    last_element = menu_a_buscar[-1]
    app.find(f'control:"TreeItemControl" and name:"{last_element}"').double_click()