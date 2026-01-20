from robocorp.tasks import task
from robocorp import windows

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

