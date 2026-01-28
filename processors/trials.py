from typing import Any, Optional
from robocorp.tasks import task
from robocorp import windows

PMP450_FORM_PATHS = {
    # Main panel elements - TODO: Update with actual paths

    'ejercicio_field':'control:"ComboBoxControl" and os.path:"4|3|3|1"',
    'cod_operacion': 'class:"TComboBox" and path:"4|3|2|1"',
    'fecha': 'class:"TDBDateEdit" and path:"4|3|5|6|1"',
    'expediente': 'class:"TDBEdit" and path:"4|3|5|5|1"',
    'tercero': 'class:"TDBEdit" and path:"4|3|5|4|1"',
    'tesoreria_check': 'class:"TDBCheckBox" and name:"Tesorería"',

    # Payment form elements
    'forma_pago_primary': 'class:"TDBEdit" and path:"4|3|5|3|1|4"',
    'forma_pago_alternate': 'class:"TDBEdit" and path:"3|5|5|9|3"',
    'tipo_pago_primary': 'class:"TDBEdit" and path:"4|3|5|3|1|2"',
    'tipo_pago_alternate': 'class:"TDBEdit" and path:"3|5|5|9|2"',
    'caja_primary': 'class:"TDBEdit" and path:"4|3|5|3|1|1"',
    'caja_alternate': 'class:"TDBEdit" and path:"3|5|5|9|1"',

    # Text and aplicaciones
    'texto': 'class:"TDBMemo" and path:"4|3|1|1"',
    'aplicaciones_grid': 'path:"4|1|1|1"',
    'new_line_button': 'class:"TBitBtn" and path:"4|2|1"',
    'confirm_line_button': 'class:"TBitBtn" and path:"4|2|3"',

    # Action buttons
    'nuevo_button': 'path:"3|4"',
    'validar_button': 'class:"TBitBtn" and name:"Validar"',
    'salir_button': 'class:"TBitBtn" and name:"Salir"',
    'cerrar_button': 'name:"Cerrar"',
    'nuevo_ok_button': 'class:"TButton" and name:"OK"',


    # Result fields
    'num_operacion': 'class:"TEdit" and path:"4|2|6|1"',
    'total_operacion': 'class:"TCurrencyEdit" and path:"1|4"',
    'liquido_operacion': 'class:"TCurrencyEdit" and path:"1|2"',
}
 
@task
def probar_elementos():
    app = windows.find_window('regex:.*SICAL II 4.2 TesPagos')
    year_box = app.find('class:"TComboBox" and path:"2|1|2"', raise_error=False)
    if year_box:
        print("ComboBox encontrado")
        print("Click elemento : ", year_box.click())
        print("Contenido del ComboBox:", year_box.get_value())
        year_box.select('2026')
        print("Contenido del ComboBox:", year_box.get_value())
        #year_box.set_value('2026')
        #year_box.click()

    continuar = True
    if continuar:
        fecha_ordenpago_el = app.find('class:"TMaskEdit" and path:"2|1|1"').click(wait_time=0.1)
        fecha_ordenpago_el.send_keys('{HOME}')
        fecha_ordenpago_el.send_keys('01012026', interval=0.1, wait_time=0.5, send_enter=True)
        modal_cambio_fecha_ok = app.find('class:"TButton" and name:"OK" and path:"1|1"', raise_error=False)
        if modal_cambio_fecha_ok:
            modal_cambio_fecha_ok.click(wait_time=0.5)

        boton_ordenar = app.find('name:"Ordenar" and path:"2|7"').click(wait_time=0.8)

        option_operation_el = app.find('name:"Nº Operación" and class:"TGroupButton"')
        option_operation_el.click(wait_time=0.5)

@task
def _fill_PMP450_main_panel():
        """
        Fill the main panel fields in the PMP450 form.

        TODO: Verify these paths are correct for PMP450.
        """
        
        wait_time = 0.1
        # Fecha

        ventana = windows.find_window('regex:.*SICAL II 4.2 mona30')
        
        # Check for select anuality on year-start
        anuanity_select = ventana.find('class:"TDBComboBox" and path:"4|3|3|1"', timeout=0.3, raise_error=False)

        if anuanity_select:
            anuanity_select.click(wait_time=wait_time)
            anuanity_select.send_keys(keys='2025', wait_time=wait_time)
            anuanity_select.send_keys(keys='{Enter}', wait_time=wait_time)

        cod_op_element = ventana.find(PMP450_FORM_PATHS['cod_operacion']).click(wait_time=wait_time)
        cod_op_element.send_keys(keys='450', interval=0.05, wait_time=wait_time)
        cod_op_element.send_keys(keys='{Enter}', wait_time=wait_time)
        
        fecha_element = ventana.find(PMP450_FORM_PATHS['fecha']).double_click()
        fecha_element.send_keys('01012025', interval=0.03, wait_time=wait_time)

        # Expediente
        expediente_element = ventana.find(PMP450_FORM_PATHS['expediente']).double_click()
        expediente_element.send_keys('12345', wait_time=wait_time)

        # Tercero
        tercero_element = ventana.find(PMP450_FORM_PATHS['tercero']).double_click()
        tercero_element.send_keys('43000000M', interval=0.05, wait_time=wait_time)

        # Tesoreria checkbox
        tesoreria_check = ventana.find(PMP450_FORM_PATHS['tesoreria_check'])
        tesoreria_check.click(wait_time=1.0)
        tesoreria_check.send_keys(keys='{Space}', wait_time=wait_time)


        # Forma de pago
        forma_pago = ventana.find(PMP450_FORM_PATHS['forma_pago_primary'],
                        raise_error=False
        )
        forma_pago.double_click(wait_time=wait_time)
        forma_pago.send_keys(keys='10', interval=0.01, wait_time=wait_time)
        forma_pago.send_keys(keys='{Enter}', wait_time=wait_time)

        # Tipo de pago
        tipo_pago = ventana.find(
            PMP450_FORM_PATHS['tipo_pago_primary'],
            raise_error=False
        )
        tipo_pago.double_click(wait_time=wait_time)
        tipo_pago.send_keys(keys='10', interval=0.01, wait_time=wait_time)
        tipo_pago.send_keys(keys='{Enter}', wait_time=wait_time)

        # Caja
        caja_element = find_element_with_fallback(
            ventana,
            PMP450_FORM_PATHS['caja_primary'],
            PMP450_FORM_PATHS['caja_alternate'],
            raise_error=True
        )
        caja_element.click(wait_time=wait_time)
        caja_element.send_keys(keys='101', interval=wait_time, wait_time=wait_time)

        # Texto
        texto_element = ventana.find(PMP450_FORM_PATHS['texto']).double_click()
        texto_element.send_keys(keys='{Ctrl}{A}', wait_time=wait_time)
        texto_element.send_keys('PRUEBABABSBSBS', wait_time=wait_time)
        texto_element.send_keys(keys='{Enter}', wait_time=wait_time)


        ventana.find(PMP450_FORM_PATHS['aplicaciones_grid']).double_click()

        ventana.find(PMP450_FORM_PATHS['new_line_button']).click()

        #ventana.send_keys(keys='{Tab}', interval=0.05, wait_time=wait_time, send_enter=False)
        ventana.send_keys(keys='30013', interval=wait_time, wait_time=0.0, send_enter=True)
        _contraido = '2500001'
        if _contraido:
            ventana.send_keys(keys=_contraido, interval=wait_time, wait_time=wait_time, send_enter=True)
        else:
            ventana.send_keys(keys='{Tab}', wait_time=0.05, interval=wait_time)

        ventana.send_keys(keys='1000', interval=0.05, wait_time=wait_time, send_enter=False)
        ventana.send_keys(keys='{Enter}', wait_time=wait_time)

        ventana.send_keys(keys='554', interval=wait_time, wait_time=wait_time)

        ventana.find(PMP450_FORM_PATHS['confirm_line_button']).click()



def find_element_with_fallback(
    window: Any,
    primary_path: str,
    fallback_path: str,
    raise_error: bool = True
) -> Optional[Any]:
    """
    Find an element using primary path, falling back to alternate path if not found.

    Args:
        window: Window to search in
        primary_path: Primary element path
        fallback_path: Fallback element path
        raise_error: Whether to raise error if neither path found

    Returns:
        Element if found, None otherwise (or raises if raise_error=True)
    """
    element = window.find(primary_path, raise_error=False)
    if element:
        return element

    element = window.find(fallback_path, raise_error=raise_error)
    return element