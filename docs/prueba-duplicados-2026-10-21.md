# Prueba de extremo a extremo: gasto marcado como posible duplicado

21/10/2026. Productor `sical-robot` (rama `main`) y este robot (rama
`ordenar-pagar-operaciones`, con los arreglos de la actualización de SICAL del
mismo día). Seguido leyendo a la vez la tabla `accounting_tasks` del productor
(solo lectura) y `logs/gastos-20261021.log`.

**Resultado: funciona de extremo a extremo.** El primer intento lo rechazó el
robot en la fase 2 por estar fuera de horario (7:00–19:00) y el token quedó
gastado. Se repitió con el horario ampliado a 7:00–23:00 solo para la prueba,
y el gasto se creó, validó, ordenó y pagó: **226102786**. El horario se
restauró al terminar.

## La operación

Un ADO220 legítimo con la misma fecha (02/10/2026), banco (203) e importe
(10,00 €) que otro ya contabilizado y pagado esa tarde (226102785). Tarea
`203_02102026_-10_cuotat_ae64c0_0`, `document_mode` `deferred`.

## El flujo

| Fase | Productor | Robot |
|---|---|---|
| 1 | Publica con `duplicate_policy: check_only` | Busca en ConOpera → Filtros (tercero, fecha, funcional, económica, importe, banco) |
| 1 | | Si encuentra registros: genera un token (5 min, de un solo uso, en memoria) y devuelve `P_DUPLICATED` sin abrir la ventana del gasto |
| 1 | Guarda `P_DUPLICATED`, el token y `similar_records_count`; la tarjeta sale como «Duplicate» | |
| 2 | Al confirmar, reenvía con `force_create` y el token | Valida el token, pasa el limitador (horario + cupos) y crea, valida, ordena y paga sin volver a buscar |

## Línea de tiempo

| Hora | Lado | Qué pasó |
|---|---|---|
| 20:15:53 | Productor | Publica la tarea con `check_only` (`PUBLISHED`) |
| 20:15:53 | Robot | La recibe; abre Consulta de operaciones (3,8 s de menú) |
| 20:16:14 | Robot | `Found 1 similar records` (la 226102785) |
| 20:16:14 | Robot | Genera el token; caduca a los 300 s |
| 20:16:15 | Robot | Devuelve `P_DUPLICATED`; no abre la ventana del gasto |
| 20:16:15 | Productor | Fila en `P_DUPLICATED`, `similar_records_count: 1` |
| 20:17:10 | Productor | Reenvía con `force_create` y el token (`attempt_count: 1`) |
| 20:17:10 | Robot | Token válido (quedaban 244 s) y **consumido** |
| 20:17:10 | Robot | El limitador lo rechaza: fuera de 7:00–19:00 Europe/Madrid |
| 20:17:10 | Productor | Fila en `FAILED`: «Rate limit exceeded: Operations only allowed during business hours…» |

Fase 1 completa en 22 s. Entre `P_DUPLICATED` y el reenvío, 55 s.

### Repetición con el horario ampliado

Para probar la fase 2 fuera de horario se generó un `rate_limit_config.json`
firmado (mismos cupos, horario 7:00–23:00) y se arrancó el consumidor con su
`SICAL_CONFIG_SECRET_KEY`. Al terminar se borraron fichero y clave y se
reinició sin ellos: vuelve el 7:00–19:00 por defecto.

| Hora | Lado | Qué pasó |
|---|---|---|
| 20:20:39 | Productor | Reintenta la tarea; el mensaje **no lleva `duplicate_policy`** (en su base la fila sigue con `force_create`) |
| 20:20:39 | Robot | Sin política en el mensaje toma `abort_on_duplicate` y busca |
| 20:21:00 | Robot | `Found 1 similar records`; token nuevo |
| 20:21:00 | Robot | Abre un cuadro «Proceso abortado» **modal de sistema** y se queda esperando a que alguien pulse Aceptar |
| 20:21:18 | Robot / Productor | Tras el Aceptar, `P_DUPLICATED` en los dos lados |
| 20:21:31 | Productor | Reenvía con `force_create` y el token (`attempt_count: 3`) |
| 20:21:31 | Robot | Token válido (269 s), horario 7:00–23:00, cupos 1/15 y 1/30: pasa |
| 20:22:11 | Robot | Validada: **226102786** (sin «Information», No a adjuntar) |
| 20:22:23 | Robot | Tesorería: ordena y paga con fecha 02/10/2026 |
| 20:22:54 | Robot / Productor | `COMPLETED` en los dos lados |

Fase 2 completa en 1 min 23 s.

## Lo que se ha visto

1. **La detección funciona tras la actualización de SICAL.** Encontrar el
   registro prueba que los filtros se teclean en sus campos, también fecha e
   importe, que en una ventana de Filtros abierta estrecha quedan fuera de ella.

2. **`force_create` solo se admite de 7:00 a 19:00.** Es una regla a propósito
   ([RATE_LIMITING.md](../RATE_LIMITING.md)); un gasto normal a las 20:06 no la
   pasa porque el limitador solo se aplica a `force_create`. Ni el productor
   avisa antes de reenviar fuera de horario ni la tarjeta lo explica más que
   con el texto del error.

3. **El token se gasta antes de mirar el horario.** En
   `_validate_force_create_token` ([sical_base.py](../sical_base.py)) primero se
   valida —y consume— el token y después se consulta el limitador. Un rechazo
   por horario o por cupo deja el token usado: aunque se reintentara a tiempo,
   el robot contestaría «token already used». Para crear el gasto hay que
   repetir la fase 1 entera.

4. **El mensaje de error del consumidor confunde.** Tras el rechazo por
   horario registra `Token validation failed - aborting without opening
   window`, cuando el token era válido.

5. **Tras `P_DUPLICATED` queda ConOpera abierta.** La búsqueda solo cierra
   Filtros en ese caso. No estorba a la fase 2 (con `force_create` no se
   busca), pero es un resto en pantalla para la siguiente tarea.

6. **El token vive solo en la memoria del robot.** Reiniciar el consumidor
   entre la fase 1 y la 2 lo invalida. Y caduca a los 5 minutos.

7. **Sin `SICAL_CONFIG_SECRET_KEY` ni `rate_limit_config.json`.** El limitador
   usa sus valores por defecto (15 por hora, 30 al día, 7:00–19:00) y una clave
   temporal; lo avisa en el log a cada `force_create`.

8. **Un reintento desde el productor sale sin `duplicate_policy`.** El robot
   cae entonces en `abort_on_duplicate`, que con un duplicado abre un
   `MessageBox` **modal de sistema** (`show_windows_message_box`, en
   [sical_utils.py](../sical_utils.py)) y no sigue hasta que alguien lo
   acepta. Sin nadie delante, el consumidor se queda parado. En la base del
   productor la fila seguía diciendo `force_create`: lo guardado y lo enviado
   no coinciden.

9. **El resto del flujo, bien tras la actualización de SICAL:** la validación
   sin «Information» y la espera al diálogo de Tesorería funcionaron también
   en el camino de `force_create`.

## Pendiente

- Decidir si el limitador se consulta antes de consumir el token (punto 3) y si
  se corrige el mensaje del consumidor (punto 4).
- Que el reintento del productor envíe `check_only` (punto 8, en
  `sical-robot`), y que el robot no abra un cuadro modal estando desatendido.
- La 226102784 (primer gasto de prueba del día) consta `FAILED` en el
  productor pero está validada, ordenada y pagada en SICAL: no reenviarla.
