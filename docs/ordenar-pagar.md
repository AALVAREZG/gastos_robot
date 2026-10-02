# Ordenar y pagar operaciones ya contabilizadas

Dos tipos nuevos en la cola de siempre (`sical_queue.gasto`), atendidos por
este mismo robot. Un consumidor aparte compartiría asiento con este —un
asiento es una máquina— y no ganaría nada, salvo otro proceso que vigilar.

| `tipo` | Qué hace |
|---|---|
| `ordenarypagar` | Ordena y/o paga una operación por su número, o paga una lista |
| `listas_pendientes_pago` | Lee las listas pendientes de pago del desplegable de «Pagar». No paga nada |

El flujo de Tesorería Pagos vive en
[processors/tesoreria_pagos.py](../processors/tesoreria_pagos.py) y es el mismo
que usan ADO220 y PMP450 al finalizar.

## Mensaje

Mismo sobre que un ADO/PMP (`operation_data.operation.tipo` / `.detalle`):

```json
{ "tipo": "ordenarypagar",
  "detalle": {
    "num_operacion": "326100196",
    "ordenar": false,
    "pagar": true,
    "fecha_ordenamiento": "31/08/2026",
    "fecha_pago": "02/10/2026" } }
```

| Campo | |
|---|---|
| `num_operacion` \| `num_lista` | Exactamente uno de los dos |
| `ordenar` | Por defecto `true` con `num_operacion`. Con `num_lista` no cabe: la lista ya está ordenada |
| `pagar` | Por defecto `true` |
| `fecha_ordenamiento` | `DD/MM/YYYY` o `DDMMYYYY`. Si falta, la de pago |
| `fecha_pago` | Si falta, la de ordenación. Si las dos difieren, se teclea la de pago antes de pagar |
| `comprobar` | Solo con `num_operacion`, y sin `ordenar` ni `pagar`. Teclea el número en «Pagar», lee el aviso de SICAL si sale y **cancela sin validar**. Devuelve `pago.comprobacion = {acepta, aviso_sical, avisos_cerrados, no_seleccionable}` |

Todo lo que no cuadra se rechaza **antes de abrir SICAL**: la tarea vuelve
`FAILED` con el motivo en `error` y sin haber tocado nada.

`listas_pendientes_pago` solo lleva, opcional, `fecha` (por defecto, hoy): se
teclea antes de pulsar «Pagar», como en un pago. Sin ella, la primera prueba en
SICAL no llegó a ver el diálogo.

## Resultado

El de siempre, con un campo nuevo, `result.pago`, que dice hasta dónde llegó
cada paso. Se escribe en cuanto el paso termina, así que sobrevive a un fallo a
mitad:

```json
"pago": {
  "modo": "num_operacion",
  "num_operacion": "326100196",
  "num_lista": null,
  "fecha_ordenamiento": "31082026",
  "fecha_pago": "02102026",
  "ordenacion": "no_solicitado",
  "pago": "hecho",
  "error_sical": null }
```

| `ordenacion` / `pago` | |
|---|---|
| `pendiente` | Pedido y no terminado: **es lo que falta** |
| `hecho` | Hecho en esta ejecución |
| `ya_estaba` | Solo `ordenacion`: SICAL dio error al teclear el número, que se lee como «ya ordenada» (como hasta ahora) |
| `no_solicitado` | No se pidió |

Con una operación ya pagada, al teclearla en «Pagar» SICAL saca **dos veces**
el aviso «Nº de Operación no seleccionable para la etapa de tesorería»
(comprobado a mano y por el robot el 02/10/2026 con la 326100219). Es un «no se
puede pagar», no un «ya está pagada»: una sin ordenar dará previsiblemente el
mismo. El robot cierra los dos avisos, cancela sin validar, sale de la ventana
y la tarea vuelve `FAILED` con `pago: pendiente` y el aviso en `error_sical`.

`error_sical` es el texto de SICAL cuando el fallo ocurre con su ventana de
errores (`TFVerError`) o un aviso (`TMessageForm`) abierto; también va en
`error`, en vez del volcado del localizador.

**`result.pago` también lo devuelven ADO220 y PMP450** cuando finalizan. Es lo
que permite al productor ofrecer «Finalizar» sobre una tarea que se contabilizó
y falló al ordenar o pagar, y pedir solo lo que falta: si `ordenacion` es
`hecho` y `pago` es `pendiente`, se publica `ordenarypagar` con `ordenar: false`.

`listas_pendientes_pago` devuelve
`"pago": {"modo": "consulta_listas", "listas_pendientes": ["20130213", "20260103"]}`,
tal como aparecen en el desplegable salvo el «0» que trae siempre, que no es
ninguna lista; `null` si no se pudo leer (y la tarea sale `FAILED`). Una lista
vacía sí quiere decir que no hay ninguna.

## Lo que tiene que saber el productor

- **No juzgar estas tareas por `num_operacion`.** `classifyOperationOutcome`
  decide CREATED/NOT_CREATED por ese campo. En `ordenarypagar` por operación
  viene relleno —es la operación sobre la que se actuó, no una creada—; en el
  pago por lista viene vacío y saldría `NOT_CREATED`. El resultado de estas
  tareas es `status` + `result.pago`.
- **Documento de pago por operación**: es la fase `P` de esa operación en
  ConOpera. El robot de documentos ya la sabe sacar (`capturePaymentPhase`,
  hoy apagado) y queda en `task_contable_documents (task_id, 'P')`, ligado a la
  tarea y, por ella, a su movimiento bancario.
- **Documento del pago por lista**: pendiente. ConOpera trabaja por operación;
  hay que decidir qué documento es y de dónde sale.

## Estado

- Pago por operación (ordenar, pagar o ambos): montado sobre los mismos pasos y
  localizadores que el cierre de ADO/PMP. Ordenar sin pagar, y teclear una
  segunda fecha antes de pagar, son pasos nuevos **sin probar en SICAL**.
- Pago por lista: montado hasta validar la lista. Antes de teclearla se
  comprueba que está entre las pendientes del desplegable: es lo que impide
  pagarla dos veces o pagar otra por un número mal tecleado. **Falta el paso
  de seleccionar todas las operaciones**; mientras tanto
  `tesoreria_pagos.PAGO_LISTA_DISPONIBLE = False` y el robot abre «Pagar»,
  comprueba la lista y **cancela antes de teclearla**, sea cual sea el caso:

  | La lista | Resultado | `error` |
  |---|---|---|
  | ya pagada / no existe | `FAILED` | `ListaNoPendiente`: no está entre las pendientes |
  | pendiente | `FAILED` | `PagoListaNoDisponible`: está pendiente, falta el paso |
  | desplegable ilegible | `FAILED` | `PagoListaNoDisponible`: no se ha podido comprobar |

  Así se prueba en SICAL el fallo antes que el acierto, sin pagar nada:
  `python enviar_tarea_prueba.py lista <nº de una lista ya pagada>`.
- Lectura del desplegable: por mensajes Win32 (`CB_GETCOUNT`/`CB_GETLBTEXT`)
  sobre el handle del control, probada entre procesos contra un COMBOBOX
  nativo ANSI; **sin probar contra el de SICAL**.
