# Ordenar y pagar operaciones ya contabilizadas

Dos tipos nuevos en la cola de siempre (`sical_queue.gasto`), atendidos por
este mismo robot. Un consumidor aparte compartiría asiento con este —un
asiento es una máquina— y no ganaría nada, salvo otro proceso que vigilar.

| `tipo` | Qué hace |
|---|---|
| `ordenarypagar` | Ordena y/o paga una operación por su número, o paga una lista |
| `listas_pendientes_pago` | Lee las listas pendientes de pago del desplegable de «Pagar». No paga nada |
| `relacion_lista` | Saca en PDF la relación de operaciones de una lista. No paga nada |

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
  "error_sical": null,
  "motivo": null }
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

`motivo` es un código, para no depender del texto, cuando lo pedido no se hizo
por una razón conocida y el robot salió limpio, sin validar nada:

| `motivo` | Qué pasó |
|---|---|
| `lista_no_pendiente` | La lista no figura entre las pendientes: ya pagada, aún sin ordenar o número equivocado. El robot no puede distinguirlo |
| `operacion_no_seleccionable` | SICAL no deja seleccionar la operación para pagarla: ya pagada o aún sin ordenar |
| `lista_no_comprobable` | No se pudo leer el desplegable de listas; sin comprobarla no se paga |
| `pago_lista_no_disponible` | Pago por lista desactivado (`PAGO_LISTA_DISPONIBLE = False`) |

Los dos primeros no son un fallo del robot: el productor los enseña como «No
pendiente», no como «Fallida».

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
- **Documento del pago por lista**: la relación de operaciones de la lista
  (abajo). Llega en `contable_documents` con la fase `P` y queda en
  `task_contable_documents (task_id, 'P')`, igual que lo hará la fase P de
  ConOpera en el pago por operación. Solo si el mensaje pide
  `inline_capture`; el productor publica así los pagos por lista aunque el
  modo general sea `deferred`, porque el robot de documentos no lo saca.

## El documento del pago por lista

Es la **«Relación de las Operaciones Procesadas»** de la lista: cada operación
con su nº de orden y de pago, el tercero, el banco y el líquido, y el total.
Sale por la vía de impresión de Tesorería Pagos, no de ConOpera, y por eso lo
saca este robot justo después de pagar: la ventana ya está abierta y con la
fecha puesta. Se paga, se guarda y se sale.

El desplegable del panel trae **todas** las listas del ejercicio, también las
ya pagadas (104 el 07/10/2026), así que la relación se puede sacar cuando se
quiera. Un documento que falla al pagar no deja la tarea sin arreglo: se pide
otra vez con `relacion_lista`, sin volver a pagar. Y por lo mismo se puede
probar en SICAL con cualquier lista, sin pagar nada:

```bash
python enviar_tarea_prueba.py relacion 20260111 --guardar relacion.pdf
```

`relacion_lista` lleva `num_lista` y, opcional, `fecha` (por defecto, hoy;
solo sirve para activar «Imprimir»). Sale `COMPLETED` si el PDF llega
capturado y `FAILED` con el motivo si no; el documento se devuelve siempre,
sea cual sea el `document_mode`, porque es el objeto de la tarea.

En el pago por lista, un fallo del documento **no toca el pago**: la tarea
sale `COMPLETED` con `pago: hecho`, y el sobre `FAILED` con su
`capture_error`. Con `legacy_print` no se imprime nada: imprimir desde el
Visualizador no está mapeado.

### Recorrido (mapeado con sical-inspector el 07/10/2026, lista 20260111)

1. Con la fecha tecleada se activa **Imprimir** (grupo «Operaciones»). Abre el
   panel «Seleccionar Listados» (`TFLisSele`) **sin ninguna casilla marcada**,
   con «Nº Lista» elegida y el desplegable de listas en 0.
2. Marcar **Relación de Operaciones Procesadas** abre «Ordenar el listado por
   ...» (`TInputQueryForm`), con 1 por defecto: (1) Nº Operación, (2) Nº Orden,
   (3) Nº Pago. Se contesta **3**.
3. Se elige la lista en el desplegable y se pulsa el botón del check, que se
   activa al aceptar el orden: se abre el Visualizador.
4. En el Visualizador: Guardar PDF → «Guardar como» → Salir. Al salir, el panel
   se cerró con él (o en los 5 s siguientes); si sigue, se cierra con su puerta.

Tras un pago SICAL deja abierto **este mismo panel** (su puerta es el
`salir_impresion_button` de siempre), con lo que él marque. No se usa ese
estado, que no está mapeado: se cierra y se abre de nuevo con Imprimir.

| Clave | En pantalla | Control | Localizador | Notas |
|---|---|---|---|---|
| `imprimir_button` | Imprimir | `TBitBtn` | grupo «Operaciones» > `name:"Imprimir"` | `TFVerError` tiene otro «Imprimir» |
| `panel_listados` | Seleccionar Listados | `TFLisSele` | por clase | Hijo 1 de la ventana: la corre una posición |
| `check_relacion_operaciones` | Relación de Operaciones Procesadas | `TCheckBox` | grupo «Seleccionar Listados» > por nombre | Las demás casillas van a la impresora |
| `orden_listado_form` / `_input` | Ordenar el listado por ... | `TInputQueryForm` / `TEdit` | por clase | Trae «1» |
| `opcion_lista_listado` | Nº Lista | `TGroupButton` | panel > por nombre | `TFTesoSele` tiene otra «Nº Lista» |
| `combo_lista_listado` | (desplegable de Nº Lista) | `TComboBox` | panel > `path:"1\|3\|7"` | Se lee y se comprueba por `CB_GETCURSEL` |
| `aceptar_listado_button` | (check) | `TBitBtn` sin nombre | panel > `path:"1\|9"` | Formulario fijo; desactivado hasta aceptar el orden |
| `salir_listado_button` | (puerta) | `TBitBtn` sin nombre | panel > `path:"1\|10"` | = `salir_impresion_button` desde la ventana |

Lo que se comprueba antes de cada paso, porque el panel genera también cartas,
mandamientos y cheques que salen por la impresora:

- el panel se abre sin nada marcado; si no, no se genera nada;
- la lista está en el desplegable antes de marcar nada (`ListaInexistente`);
- el diálogo de orden tiene el 3 antes de aceptarlo; si no, se cancela;
- antes del check solo está marcada la relación;
- el desplegable **muestra** la lista pedida: un desplegable que no hizo caso
  sacaría la relación de otra y llegaría a la tarea como si fuera la suya;
- el PDF nombra la lista (como `nombra_operacion` con la operación).

**El Visualizador se maneja por icono, no por path** (`doc_pipeline/iconos.py`,
referencias en `iconos/visualizador.json`). Con este documento la barra tiene 7
botones y `2|2|3` es Guardar PDF, como en un ADO; en el listado del banco tiene
6 y `2|2|3` es el que lo manda a portafirmas. Las huellas son las de la skill
`sical-inspector` y valen para el equipo y el escalado en que se registraron:
en otro equipo un icono puede no casar, y entonces no se pulsa nada y el
documento sale `FAILED`. Se re-registran allí con la skill.

## Estado

- Pago por operación (ordenar, pagar o ambos): montado sobre los mismos pasos y
  localizadores que el cierre de ADO/PMP. Ordenar sin pagar, y teclear una
  segunda fecha antes de pagar, son pasos nuevos **sin probar en SICAL**.
- Pago por lista: se marca «Nº Lista», se comprueba que la lista está entre
  las pendientes del desplegable —sin poder leerlo no se paga: es lo que impide
  pagarla dos veces o pagar otra por un número mal tecleado—, se teclea, se
  valida, se pulsa «Todos» (esperando a que se active) y se valida el pago.
  Si al pulsar «Todos» SICAL avisa —puede avisar de retenciones; no se ha
  visto aún— el robot para sin validar y deja el aviso abierto.
  `PAGO_LISTA_DISPONIBLE = False` vuelve al modo que cancela antes de teclear.

- Lectura del desplegable: por mensajes Win32 (`CB_GETCOUNT`/`CB_GETLBTEXT`)
  sobre el handle del control. Probada contra el de SICAL: el de «Pagar» en el
  pago real del 02/10/2026 y el del panel de listados el 07/10/2026 (104
  listas).
- Relación de la lista: **probada en SICAL el 07/10/2026** con
  `enviar_tarea_prueba.py relacion 20260111`. Salió `COMPLETED` a la primera:
  PDF de 1 página con las 3 operaciones (226102751 a 226102753) y el total de
  835,64 €, lo mismo que enseña el Visualizador. 43 s en total (14 s en abrir
  Tesorería Pagos, 29 s en la relación), y SICAL quedó en el menú. SICAL abre
  el PDF en Edge al guardarlo, como con ADO/PMP, y ahí se queda.
  **Sin probar todavía**: el paso tras un pago real, que cierra antes el panel
  que SICAL abre al pagar.
