# SICAL Gastos Robot - GUI Status Monitor

A comprehensive tkinter-based GUI for monitoring and controlling the SICAL Gastos Robot service.

## Features

### 📊 Real-Time Monitoring
- **Service Status**: Track service and RabbitMQ connection status in real-time
- **Statistics Dashboard**: View pending, processing, completed, and failed task counts
- **Success Rate**: Monitor overall task success rate
- **Uptime Tracking**: See how long the service has been running

### 🔄 Current Task Monitoring
Real-time view of the currently processing task with detailed information:
- Operation Type (ado220, pmp450, ordenarypagar)
- Operation Number
- Date and Duration
- Amount and Cash Register
- Third Party and Nature
- Description
- Line Items Progress
- Current Processing Step

### 📜 Task History
- **Searchable History**: Search tasks by ID, operation number, or third party
- **Status Filtering**: Filter by completed, failed, or error status
- **Detailed View**: Double-click any task to view full details
- **Statistics**: View overall statistics including average task duration

### 📤 Export Functionality
Export task history to multiple formats:
- **Excel (.xlsx)**: Formatted spreadsheet with styling
- **JSON**: Machine-readable format
- **CSV**: Universal spreadsheet format

### 📝 Activity Log
- Real-time log viewer with color-coded log levels
- Captures all service activity
- Auto-scrolls to latest entries

## Installation

### Prerequisites

1. **Python 3.8 or higher**

2. **Required Python packages**:
```bash
pip install pika tkinter openpyxl
```

3. **RabbitMQ Server**: Ensure you have access to a RabbitMQ server

### Setup

1. **Clone the repository** (if not already done)

2. **Configure RabbitMQ connection**:
```bash
cp config.py.example config.py
```

Then edit `config.py` with your actual RabbitMQ credentials:
```python
RABBITMQ_HOST = 'your-rabbitmq-host'
RABBITMQ_PORT = 5672
RABBITMQ_USER = 'your-username'
RABBITMQ_PASS = 'your-password'
```

3. **Verify all required files are present**:
- `gastos_gui.py` - Main GUI application
- `status_manager.py` - Status management module
- `task_history_db.py` - Database module for history
- `gasto_task_consumer.py` - Consumer with GUI callbacks
- `run_gui.py` - Entry point script

## Usage

### Starting the GUI

Simply run:
```bash
python run_gui.py
```

Or directly:
```bash
python gastos_gui.py
```

### Using the GUI

#### Monitor Tab

1. **Starting the Service**:
   - Click the "▶ Start Service" button
   - The service status will change to "RUNNING"
   - RabbitMQ connection status will show "CONNECTED" when ready

2. **Monitoring Tasks**:
   - Watch the "Current Task" panel for real-time updates
   - Statistics update automatically
   - Activity log shows all events

3. **Stopping the Service**:
   - Click the "⏹ Stop Service" button
   - Service will gracefully shut down

4. **Clear Statistics**:
   - Click "🗑 Clear Stats" to reset the statistics counter
   - Note: This only resets the current session stats, not the history database

#### History Tab

1. **Viewing Task History**:
   - Switch to the "📜 History" tab
   - Task history is loaded automatically

2. **Searching**:
   - Enter search term (task ID, operation number, or third party)
   - Select status filter (All, Completed, Failed, Error)
   - Click "🔍 Search"

3. **Viewing Details**:
   - Double-click any row to view complete task details
   - A popup window will show all information

4. **Exporting**:
   - Click "📊 Excel (.xlsx)" to export to Excel
   - Click "📄 JSON" to export to JSON
   - Click "📋 CSV" to export to CSV
   - Choose the save location in the file dialog

## Architecture

### Components

#### gastos_gui.py
Main GUI application using tkinter. Provides:
- Tabbed interface (Monitor and History tabs)
- Real-time status updates
- Service control
- History viewing and export

#### status_manager.py
Thread-safe status management:
- Tracks service and connection status
- Maintains task statistics
- Stores current task information
- Manages activity logs

#### task_history_db.py
SQLite database for persistent storage:
- Stores completed task information
- Provides search and filtering
- Calculates statistics
- Handles export functionality

#### gasto_task_consumer.py
RabbitMQ consumer with GUI callbacks:
- Processes expense operations
- Sends status updates to GUI
- Handles different operation types (ado220, pmp450, ordenarypagar)

### Callback System

The GUI uses a callback system for real-time updates:

**Status Callbacks** (from consumer):
- `connected`: RabbitMQ connection established
- `disconnected`: RabbitMQ disconnected
- `task_received`: New task received from queue
- `task_started`: Task processing began
- `task_completed`: Task finished successfully
- `task_failed`: Task failed

**Task Callbacks** (from task processor):
- `step`: Current processing step update

## Operation Types

The GUI monitors three types of expense operations:

1. **ado220**: Standard expense operation (ADO220)
2. **pmp450**: Alternative expense operation (PMP450)
3. **ordenarypagar**: Order and pay operation

Each operation type displays relevant information based on its specific requirements.

## Database

Task history is stored in an SQLite database (`gastos_task_history.db`).

### Schema

```sql
CREATE TABLE task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    operation_type TEXT,
    operation_number TEXT,
    date TEXT,
    cash_register TEXT,
    third_party TEXT,
    nature TEXT,
    amount REAL,
    description TEXT,
    total_line_items INTEGER,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration_seconds REAL,
    error_message TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
```

## Troubleshooting

### GUI Won't Start

**Issue**: Error about missing modules
```
Solution: Install required packages:
pip install pika tkinter openpyxl
```

**Issue**: config.py not found
```
Solution: Copy config.py.example to config.py and configure:
cp config.py.example config.py
```

### Service Won't Connect

**Issue**: RabbitMQ connection fails
```
Solution:
1. Verify RabbitMQ server is running
2. Check credentials in config.py
3. Verify network connectivity
4. Check firewall settings
```

### History Not Loading

**Issue**: Task history shows no data
```
Solution:
1. Process at least one task first
2. Check if gastos_task_history.db exists
3. Verify database permissions
```

### Export Fails

**Issue**: Excel export fails
```
Solution: Install openpyxl:
pip install openpyxl
```

## Development

### Adding New Features

To extend the GUI:

1. **Add new status information**:
   - Update `status_manager.py` to track new data
   - Add display widgets in `gastos_gui.py`
   - Update `update_display()` method

2. **Add new operation types**:
   - Update `gasto_task_consumer.py` callback
   - Add handling in GUI callbacks
   - Update history table columns if needed

3. **Add new export formats**:
   - Add method to `task_history_db.py`
   - Add button to export panel in GUI

### Code Structure

```
gastos_robot/
├── gastos_gui.py           # Main GUI application
├── status_manager.py       # Status management
├── task_history_db.py      # Database operations
├── gasto_task_consumer.py  # Consumer with callbacks
├── run_gui.py              # Entry point
├── config.py.example       # Configuration template
└── GUI_README.md           # This file
```

## Tips

1. **Keep the GUI open**: The GUI needs to remain open for the service to run
2. **Monitor the logs**: The activity log shows detailed information about what's happening
3. **Regular exports**: Export your history periodically for backup
4. **Clear stats**: Use "Clear Stats" between test runs to reset counters

## Support

For issues or questions:
1. Check the activity log for error messages
2. Review the troubleshooting section above
3. Check RabbitMQ server logs
4. Verify all dependencies are installed

## License

[Add your license information here]

## Version History

- **v1.0.0** (2025-01-XX): Initial release with full monitoring and history features
