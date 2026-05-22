# Gasto contable capture — Phase B′ (handoff)

Self-contained context for the gasto consumer's contable-document capture.
Mirrors the arqueo pipeline (`arqueos_robot/docs/`), adapted for gasto's
two-phase model. Read alongside the arqueo specs:
`../../arqueos_robot/docs/{attachment-finalization-spec.md,
contable-assembly-dry-run.md, session-handoff.md}`.

Repo root: `C:\Users\antonioalvarez\desarrollo\python\ayto\automatiza\v10_rabbit\`

---

## 1. Goal

When a gasto consumer finalizes a SICAL operation, capture the **ADO/PMP
contable PDF** from the Visualizador and return it to sical-robot (which
merges it with the task's pooled attachments, optionally prints, and stages
it for portafirmas) instead of the legacy in-app print. Strict integrity is
preserved (sha256 + size verified producer-side).

## 2. Why gasto differs from arqueo

A single `ado220`/`pmp450` task, when `finalizar_operacion=True`, runs **two
phases** in `processors/*_processor.py` `process_operation_form`:

1. **Phase 1 — ADO/PMP contable doc** (`_print_operation_document`):
   Consulta window → `Imprimir` → opens the **`Visualizador de Documentos de
   SICAL v2`** window (the *same* window arqueo uses; `salir`=`2|2|6`). This
   is what we capture — it mirrors arqueo's `sical_capture.py`.
2. **Ordenamiento doc (`phase='OP'`)** — **captured (Phase B′ ext, shipped).**
   After `_order_and_pay`, a second pass reuses `_print_operation_document`
   against the ConOpera window: Imprimir → the "¿En qué estado imprimirá
   Documento?" modal (`TEdit` path `1|3`) → send `'O'` → click OK
   (`TButton name:"OK"`) → the **same Visualizador** opens → captured exactly
   like ADO/PMP. The legacy in-app `O` print inside `_order_and_pay` is left
   running; capture is additive (`confirm_with_ok=True`, gated on
   `contable_capture_enabled()`). **Earlier assumption was wrong**: the
   Ordenamiento doc is *not* a Windows print-dialog problem.
3. **Pago doc (`phase='P'`)** — still **deferred**. The `(P)ago` state in the
   same modal should route through the Visualizador too; not yet wired.

So one gasto task now produces **two captured documents** (`ADO`/`PMP` + `OP`);
a third (`P`) can be added with no schema change (the envelope and the
`(task_id, phase)` PK already accommodate it).

## 3. What shipped (consumer — `gastos_robot/`)

- **`config.py` / `config.py.example`** — added `CONTABLE_CAPTURE_ENABLED`
  (default **`false`**, UNVERIFIED), `SICAL_PDF_WORKDIR`, `MAX_INLINE_BYTES`.
  Read via `import config` (config_loader installs the loaded module as
  `sys.modules['config']`).
- **`doc_pipeline/`** (new, vendored from arqueo):
  - `sical_capture.py` — operates on the **already-open** Visualizador
    (gasto navigates to it via Consulta → Imprimir, unlike arqueo's
    "Documento" selector). `capture_visualizador_pdf(ventana_visual,
    num_operacion, dest_dir)`: Guardar PDF (`2|2|3`, **UNVERIFIED**) →
    'Guardar como' → robust close (`close_visualizador`: restore +
    foreground + Salir `2|2|6` + `close_window` fallback, retried/verified;
    handles SICAL auto-opening the saved doc which minimizes the viewer).
  - `capture_and_return.py` — builds the **phase-tagged** envelope
    `{phase, filename, mime_type, page_count, size_bytes, sha256,
    transport:'inline_base64', data, capture_status, capture_error}`. Never
    raises (a committed SICAL op must not be regressed by a capture failure).
  - `__init__.py` — re-exports `sical_capture` symbols only; **does not**
    re-export the `capture_and_return` function (it would shadow the
    submodule). Import it as
    `from doc_pipeline.capture_and_return import capture_and_return`.
- **`sical_base.py`** — `OperationResult` gained `capture_status` /
  `capture_error` (added to `OperationEncoder` too). New helpers:
  - `contable_capture_enabled()` — reads the config flag, defaults False on
    any error.
  - `attach_contable_document(result, envelope)` — appends to the out-of-band
    `result._contable_documents` list and mirrors the latest
    capture_status/error onto the dataclass fields.
- **`processors/ado220_processor.py` + `pmp450_processor.py`** — in
  `_print_operation_document`, when `contable_capture_enabled()`: capture
  (phase `ADO` / `PMP` respectively) **instead of** clicking Imprimir, and
  `attach_contable_document(result, envelope)`. Else: unchanged in-app print.
- **`gasto_task_consumer.py`** — attaches the top-level `contable_documents`
  array (`getattr(result, '_contable_documents', None)`) to the result
  message and logs how many phases were captured.
- **`test_capture_and_return.py`** (repo root, like `test_rate_limiting.py`)
  — 8 tests: envelope success/failure/oversize/unexpected-error, the attach
  helper (accumulation + status mirroring), and OperationResult
  serialization. All green (`pytest -q` → 14 passed total).

## 4. What shipped (producer — `sical-robot/`, minimal & phase-aware)

The producer is otherwise consumer-agnostic; these are the only changes:

- `src/services/rabbitmq/TaskQueueManager.js` — forwards `contableDocuments`
  (array) on the `taskResult` event, alongside the existing arqueo
  `contableDocument`.
- `src/main.js` — flattens `contableDocument` (arqueo) + `contableDocuments[]`
  (gasto) into one job list and runs `contableAssembly.assembleFromResult`
  per doc with its `phase` (null for arqueo).
- `src/services/contableAssembly.js` — `phase` threaded through
  `assembleFromResult` / `recordCapture` / `runPipeline` / `recover` /
  `reassemble`. Staged file + sidecar become `<task_id>_<phase>.{pdf,json}`
  (arqueo stays `<task_id>.pdf`).
- `src/database.js` — additive `phase` column on `task_contable_documents`
  (nullable); stored by `saveContableDocument`.

**Producer PK (widened, shipped)**: `task_contable_documents` PK is now
`(task_id, phase)`, holding two docs per gasto task (`ADO`/`PMP` + `OP`).
database.js rebuilds the table on startup if it finds the legacy single-
`task_id` PK (guarded + idempotent; back up `prueba05.sqlite` first). The
`OP` doc is staged **contable-only** (no pooled attachments). Independent
per-phase attachment assignment (associate docs to ADO vs OP separately in
the Contabilizar dialog) is still deferred.

## 5. Activation

| Side | Flag | Default | Where |
|---|---|---|---|
| consumer | `CONTABLE_CAPTURE_ENABLED` | `false` | `gastos_robot/config.py` (env override) |
| producer | `contableAssemblyEnabled` | `true` | `sical-robot/src/data/app-settings.json` |
| producer | `contableAssembly.printEnabled` | `false` | same |

Default OFF on the consumer → gasto tasks behave exactly as today until you
flip `CONTABLE_CAPTURE_ENABLED=true`. The producer flag is already ON and is
consumer-agnostic, so flipping the consumer flag is the only step to activate.

## 6. VERIFIED

The `Guardar PDF` path `2|2|3` + 'Guardar como' flow in
`doc_pipeline/sical_capture.py` is **live-confirmed for both ADO and PMP**
(capture → merge → STAGED on real ops, 2026-05-22, e.g. task
`203_02052026_-10_cuotat_0`). The `OP` (Ordenamiento) capture reuses the same
Visualizador path and the same `2|2|3` selector, reached via ConOpera →
Imprimir → state-modal `'O'` + OK.

Still unconfirmed on a live run: the **`OP` capture end-to-end** (the modal
`TEdit 1|3` + OK selectors are from the operator's report, not yet observed in
an automated run) and the producer **PK-widen migration** on the live DB. On a
selector failure: capture_status=FAILED, the SICAL op is unaffected (committed
at validate), operator handles the doc manually.

**OP dry-run**: with `CONTABLE_CAPTURE_ENABLED=true`, finalize one ADO with
`finalizar_operacion=True` (order+pay), and confirm:
1. consumer log "Returning 2/2 contable document(s) ... phases: ['ADO', 'OP']";
2. two `task_contable_documents` rows reach `STAGED` (`phase='ADO'`, `'OP'`);
3. `<task_id>_ADO.pdf` and `<task_id>_OP.pdf` (+ `.json`) exist in the outbox.

## 7. Next steps

1. Live dry-run of the `OP` capture (confirm the `TEdit 1|3` + OK modal
   selectors and the PK-widen migration on the real DB).
2. Pago (`P`) doc — capture the third state from the same modal (`phase='P'`);
   no schema change needed.
3. Independent per-phase attachment assignment in the Contabilizar dialog
   (so the OP packet can carry its own attachments instead of contable-only).
