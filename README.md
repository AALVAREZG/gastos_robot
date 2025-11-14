# SICAL Gastos Robot

Robot de automatización para introducir automáticamente apuntes de gastos en SICAL mediante RabbitMQ.

## Descripción

SICAL Gastos Robot es un sistema automatizado de procesamiento de operaciones de gastos para el sistema de gestión financiera SICAL. Utiliza automatización RPA (Robotic Process Automation) para interactuar con la aplicación de escritorio Windows de SICAL, procesando operaciones recibidas mediante colas de mensajes RabbitMQ.

### Características principales

- **Automatización de operaciones ADO220**: Creación automática de operaciones de gasto presupuestario
- **Procesamiento de pagos**: Ordenación y pago de operaciones existentes
- **Detección de duplicados**: Consulta la base de datos de SICAL antes de crear operaciones
- **Interfaz GUI de monitorización**: Monitorización en tiempo real del servicio
- **Base de datos de histórico**: Almacenamiento persistente de todas las tareas procesadas
- **Exportación de datos**: Exportar histórico a Excel, JSON y CSV
- **Soporte multi-formato**: Compatible con formatos de mensaje v1 (legacy) y v2

## Arquitectura

```
┌──────────────────────┐
│  Productor externo   │ (Publica tareas)
└──────────┬───────────┘
           │
           v
┌──────────────────────┐
│   RabbitMQ Broker    │
│ sical_queue.gasto    │
└──────────┬───────────┘
           │
           v
┌──────────────────────┐
│  Gastos Consumer     │ (gasto_task_consumer.py)
│  - Procesa mensajes  │
│  - Enruta operaciones│
└──────────┬───────────┘
           │
           v
┌──────────────────────┐
│  Procesadores Tasks  │
│  - gasto_tasks.py    │
│  - ordenar_tasks.py  │
│  - Automatización UI │
└──────────┬───────────┘
           │
           v
┌──────────────────────┐
│   Sistema SICAL      │
│  (Aplicación Windows)│
└──────────────────────┘
```

## Componentes principales

### 1. Consumer de RabbitMQ (`gasto_task_consumer.py`)
- Consume mensajes de la cola `sical_queue.gasto`
- Enruta operaciones según tipo (ado220, pmp450, ordenarypagar)
- Envía respuestas a través de `reply_to` queue
- Callbacks para actualización de GUI

### 2. Procesadores de tareas
- **`gasto_tasks.py`**: Lógica de negocio para operaciones ADO220
  - Automatización de ventanas SICAL
  - Validación e impresión de operaciones
  - Detección de duplicados
  - Gestión de órdenes de pago

- **`ordenar_tasks.py`**: Procesamiento de "ordenar y pagar"
  - Ordenación de operaciones validadas
  - Generación de mandamientos de pago
  - Integración con módulo de tesorería

### 3. Interfaz GUI (`gastos_gui.py`)
- **Pestaña Monitor**: Estado del servicio, estadísticas, tarea actual, logs
- **Pestaña Histórico**: Búsqueda de tareas, filtros, exportación
- Control de servicio (iniciar/detener)
- Actualización en tiempo real

### 4. Gestión de estado (`status_manager.py`)
- Thread-safe status tracking
- Estadísticas de tareas (pendientes, en proceso, completadas, fallidas)
- Registro de actividad

### 5. Base de datos (`task_history_db.py`)
- Almacenamiento SQLite de histórico de tareas
- Operaciones CRUD
- Búsqueda y filtrado
- Exportación a múltiples formatos

## Requisitos previos

- **Sistema operativo**: Windows (requerido para automatización de SICAL)
- **Python**: 3.10.12 o superior
- **SICAL**: Aplicación de escritorio instalada y accesible
- **RabbitMQ**: Broker accesible para recepción de mensajes
- **Permisos**: Acceso de administrador para automatización UI

## Instalación

### 1. Clonar el repositorio

```bash
git clone <repository-url>
cd gastos_robot
```

### 2. Crear entorno virtual

```bash
python -m venv venv
venv\Scripts\activate  # En Windows
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Configurar RabbitMQ

Crear un archivo `config.py` basado en `config.py.example`:

```python
# config.py
RABBITMQ_HOST = "tu-servidor-rabbitmq"
RABBITMQ_PORT = 5672
RABBITMQ_USER = "tu-usuario"
RABBITMQ_PASS = "tu-contraseña"
```

**Importante**: El archivo `config.py` está en `.gitignore` para no exponer credenciales.

## Uso

### Modo GUI (Recomendado)

Ejecutar la interfaz gráfica de monitorización:

```bash
python run_gui.py
```

La GUI permite:
- Iniciar/detener el servicio consumer
- Monitorizar tareas en tiempo real
- Ver estadísticas y logs
- Consultar histórico de tareas
- Exportar datos

### Modo Consola

Ejecutar solo el consumer en modo standalone:

```bash
python main.py
```

## Tipos de operaciones soportadas

### ADO220 - Operaciones de gasto presupuestario
Creación completa de operaciones de gasto con:
- Datos de cabecera (tercero, fecha, importe, etc.)
- Múltiples líneas de detalle (económica, funcional, importes)
- Validación automática
- Impresión de documentos
- Ordenación y pago (opcional)

### Ordenar y Pagar
Procesamiento de operaciones existentes:
- Ordenación de operaciones validadas
- Generación de mandamientos de pago
- Procesamiento por lista de operaciones

### PMP450 (En desarrollo)
Operaciones de tipo PMP 450 (implementación parcial).

## Formato de mensajes

El sistema soporta dos versiones de formato de mensaje:

### Mensaje v2 (Actual)
Ver ejemplos completos en:
- `example_message_v2_ado220.json`
- `example_message_v2_ordenarypagar.json`

### Migración v1 a v2
Consultar documentación completa en `MESSAGE_FORMAT_MIGRATION.md`.

## Documentación adicional

- **`GUI_README.md`**: Documentación detallada de la interfaz gráfica
- **`MESSAGE_FORMAT_MIGRATION.md`**: Guía de migración de formatos de mensaje
- **`example_message_*.json`**: Ejemplos de mensajes para cada tipo de operación

## Estructura del proyecto

```
gastos_robot/
├── main.py                     # Entry point modo consola
├── run_gui.py                  # Entry point modo GUI
├── gasto_task_consumer.py      # Consumer RabbitMQ
├── gasto_tasks.py              # Lógica operaciones ADO220
├── ordenar_tasks.py            # Lógica ordenar y pagar
├── gastos_gui.py               # Interfaz gráfica
├── status_manager.py           # Gestión de estado
├── task_history_db.py          # Base de datos histórico
├── tasks.py                    # Implementación legacy
├── config.py.example           # Plantilla configuración
├── robot.yaml                  # Configuración Robocorp
├── conda.yaml                  # Especificación entorno
├── requirements.txt            # Dependencias Python
├── README.md                   # Este archivo
├── GUI_README.md               # Doc interfaz gráfica
├── MESSAGE_FORMAT_MIGRATION.md # Doc migración formatos
└── example_message_*.json      # Ejemplos de mensajes
```

## Desarrollo

### Configuración del entorno de desarrollo

1. Instalar todas las dependencias incluyendo opcionales:
```bash
pip install -r requirements.txt
pip install openpyxl  # Para exportación Excel
```

2. Ejecutar en modo desarrollo con logs detallados:
```bash
python main.py
```

### Testing

El proyecto incluye validación automática de:
- Detección de duplicados antes de crear operaciones
- Validación de formatos de fecha
- Verificación de campos obligatorios
- Comprobación de estados de ventana

## Troubleshooting

### El servicio no se conecta a RabbitMQ
- Verificar que `config.py` existe y tiene las credenciales correctas
- Comprobar conectividad de red al servidor RabbitMQ
- Verificar que el usuario tiene permisos en la cola

### SICAL no responde a la automatización
- Asegurarse de que SICAL está abierto y en la ventana principal
- Verificar que no hay ventanas modales bloqueando la aplicación
- Comprobar que la sesión tiene permisos de administrador

### La exportación a Excel falla
- Instalar la dependencia opcional: `pip install openpyxl`

### El GUI no muestra estadísticas
- Verificar que la base de datos SQLite no está corrupta
- Comprobar permisos de escritura en el directorio del proyecto

## Logs

Los logs se escriben en:
- Consola (stdout)
- GUI (pestaña Monitor > Activity Log)
- Base de datos SQLite (histórico de tareas)

Nivel de log por defecto: `INFO`

## Contribuir

1. Fork el repositorio
2. Crear una rama de feature (`git checkout -b feature/nueva-funcionalidad`)
3. Commit cambios (`git commit -am 'Add nueva funcionalidad'`)
4. Push a la rama (`git push origin feature/nueva-funcionalidad`)
5. Crear Pull Request

## Licencia

[Especificar licencia aquí]

## Contacto

[Especificar información de contacto]

## Notas importantes

- Este sistema está diseñado específicamente para el sistema SICAL
- Requiere ejecución en entorno Windows
- Las credenciales de RabbitMQ deben mantenerse seguras (no commitear `config.py`)
- El sistema realiza operaciones financieras - usar con precaución en entornos de producción
- Se recomienda testing exhaustivo en entorno de desarrollo antes de usar en producción
