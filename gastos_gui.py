"""
SICAL Gastos Robot - GUI Status Monitor

A tkinter-based GUI for monitoring the Gastos Robot service.
Provides real-time status updates, task monitoring, and service control.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import logging
from datetime import datetime
from typing import Optional

from status_manager import status_manager
from task_history_db import get_task_history_db


class LogHandler(logging.Handler):
    """Custom logging handler that sends logs to the status manager."""

    def emit(self, record):
        """Emit a log record to the status manager."""
        try:
            msg = self.format(record)
            status_manager.add_log(msg, record.levelname)
        except Exception:
            self.handleError(record)


class GastosGUI:
    """Main GUI application for the Gastos Robot service."""

    def __init__(self, root):
        """Initialize the GUI."""
        self.root = root
        self.root.title("SICAL Gastos Robot - Status Monitor")
        self.root.geometry("900x850")
        self.root.resizable(True, True)

        # Consumer thread reference
        self.consumer_thread: Optional[threading.Thread] = None
        self.consumer = None

        # Setup logging to capture logs
        self.setup_logging()

        # Create UI
        self.create_widgets()

        # Start update loop
        self.update_display()

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_logging(self):
        """Setup logging to capture all logs for display."""
        # Get root logger
        root_logger = logging.getLogger()

        # Add our custom handler
        gui_handler = LogHandler()
        gui_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(name)s - %(message)s')
        gui_handler.setFormatter(formatter)
        root_logger.addHandler(gui_handler)

    def create_widgets(self):
        """Create all GUI widgets."""
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure grid weights for resizing
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)  # Notebook expands

        # Title
        title_label = ttk.Label(
            main_frame,
            text="SICAL Gastos Robot - Status Monitor",
            font=("Segoe UI", 14, "bold")
        )
        title_label.grid(row=0, column=0, pady=(0, 10))

        # Create notebook (tabbed interface)
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Create tabs
        self.create_monitor_tab()
        self.create_history_tab()
        self.create_logs_tab()

    def create_monitor_tab(self):
        """Create the Monitor tab with real-time status."""
        # Create frame for monitor tab
        monitor_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(monitor_frame, text="📊 Monitor")

        # Configure grid
        monitor_frame.columnconfigure(0, weight=1)
        monitor_frame.rowconfigure(4, weight=1)  # Log panel expands

        # Add all panels
        self.create_status_panel(monitor_frame)
        self.create_statistics_panel(monitor_frame)
        self.create_current_task_panel(monitor_frame)
        self.create_control_panel(monitor_frame)
        self.create_log_panel(monitor_frame)

    def create_history_tab(self):
        """Create the History tab with task history table."""
        # Create frame for history tab
        history_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(history_frame, text="📜 History")

        # Configure grid
        history_frame.columnconfigure(0, weight=1)
        history_frame.rowconfigure(2, weight=1)  # Table expands

        # Search/Filter Panel
        self.create_history_search_panel(history_frame)

        # Statistics Panel
        self.create_history_stats_panel(history_frame)

        # History Table
        self.create_history_table(history_frame)

        # Export Panel
        self.create_export_panel(history_frame)

    def create_history_search_panel(self, parent):
        """Create search and filter controls for history."""
        search_frame = ttk.LabelFrame(parent, text="🔍 Search & Filter", padding="10")
        search_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        # Search entry
        ttk.Label(search_frame, text="Search:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.search_entry = ttk.Entry(search_frame, width=40)
        self.search_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))

        # Status filter
        ttk.Label(search_frame, text="Status:").grid(row=0, column=2, sticky=tk.W, padx=(10, 5))
        self.status_filter = ttk.Combobox(
            search_frame,
            values=["All", "Completed", "Failed", "Error"],
            state="readonly",
            width=15
        )
        self.status_filter.set("All")
        self.status_filter.grid(row=0, column=3, sticky=tk.W, padx=(0, 10))

        # Search button
        search_btn = ttk.Button(
            search_frame,
            text="🔍 Search",
            command=self.load_history,
            width=12
        )
        search_btn.grid(row=0, column=4, padx=5)

        # Refresh button
        refresh_btn = ttk.Button(
            search_frame,
            text="🔄 Refresh",
            command=self.load_history,
            width=12
        )
        refresh_btn.grid(row=0, column=5, padx=5)

        # Configure column weights
        search_frame.columnconfigure(1, weight=1)

    def create_history_stats_panel(self, parent):
        """Create overall history statistics panel."""
        stats_frame = ttk.LabelFrame(parent, text="📈 Overall Statistics", padding="10")
        stats_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        # Total tasks
        ttk.Label(stats_frame, text="Total Tasks:", font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky=tk.W, padx=(0, 20)
        )
        self.hist_total_label = ttk.Label(
            stats_frame,
            text="0",
            font=("Segoe UI", 10, "bold")
        )
        self.hist_total_label.grid(row=0, column=1, sticky=tk.W)

        # Completed
        ttk.Label(stats_frame, text="Completed:", font=("Segoe UI", 9)).grid(
            row=0, column=2, sticky=tk.W, padx=(20, 5)
        )
        self.hist_completed_label = ttk.Label(
            stats_frame,
            text="0",
            font=("Segoe UI", 10, "bold"),
            foreground="green"
        )
        self.hist_completed_label.grid(row=0, column=3, sticky=tk.W, padx=(0, 20))

        # Failed
        ttk.Label(stats_frame, text="Failed:", font=("Segoe UI", 9)).grid(
            row=0, column=4, sticky=tk.W, padx=(0, 5)
        )
        self.hist_failed_label = ttk.Label(
            stats_frame,
            text="0",
            font=("Segoe UI", 10, "bold"),
            foreground="red"
        )
        self.hist_failed_label.grid(row=0, column=5, sticky=tk.W, padx=(0, 20))

        # Average duration
        ttk.Label(stats_frame, text="Avg Duration:", font=("Segoe UI", 9)).grid(
            row=0, column=6, sticky=tk.W, padx=(0, 5)
        )
        self.hist_avg_duration_label = ttk.Label(
            stats_frame,
            text="--",
            font=("Segoe UI", 10, "bold")
        )
        self.hist_avg_duration_label.grid(row=0, column=7, sticky=tk.W)

    def create_history_table(self, parent):
        """Create the task history table."""
        table_frame = ttk.LabelFrame(parent, text="📋 Task History", padding="5")
        table_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))

        # Create Treeview with scrollbars
        tree_scroll_y = ttk.Scrollbar(table_frame, orient=tk.VERTICAL)
        tree_scroll_x = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL)

        self.history_tree = ttk.Treeview(
            table_frame,
            columns=("task_id", "type", "operation", "date", "amount", "cash_register",
                    "third_party", "nature", "status", "duration", "completed_at"),
            show="headings",
            yscrollcommand=tree_scroll_y.set,
            xscrollcommand=tree_scroll_x.set,
            height=15
        )

        tree_scroll_y.config(command=self.history_tree.yview)
        tree_scroll_x.config(command=self.history_tree.xview)

        # Define columns
        self.history_tree.heading("task_id", text="Task ID")
        self.history_tree.heading("type", text="Type")
        self.history_tree.heading("operation", text="Operation")
        self.history_tree.heading("date", text="Date")
        self.history_tree.heading("amount", text="Amount")
        self.history_tree.heading("cash_register", text="Cash Reg.")
        self.history_tree.heading("third_party", text="Third Party")
        self.history_tree.heading("nature", text="Nature")
        self.history_tree.heading("status", text="Status")
        self.history_tree.heading("duration", text="Duration")
        self.history_tree.heading("completed_at", text="Completed At")

        # Column widths
        self.history_tree.column("task_id", width=150, minwidth=100)
        self.history_tree.column("type", width=80, minwidth=60)
        self.history_tree.column("operation", width=100, minwidth=80)
        self.history_tree.column("date", width=90, minwidth=70)
        self.history_tree.column("amount", width=100, minwidth=80)
        self.history_tree.column("cash_register", width=80, minwidth=60)
        self.history_tree.column("third_party", width=150, minwidth=100)
        self.history_tree.column("nature", width=100, minwidth=80)
        self.history_tree.column("status", width=90, minwidth=70)
        self.history_tree.column("duration", width=80, minwidth=60)
        self.history_tree.column("completed_at", width=150, minwidth=120)

        # Grid layout
        self.history_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree_scroll_y.grid(row=0, column=1, sticky=(tk.N, tk.S))
        tree_scroll_x.grid(row=1, column=0, sticky=(tk.W, tk.E))

        # Configure grid weights
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        # Bind double-click to view details
        self.history_tree.bind("<Double-1>", self.on_history_row_double_click)

        # Tag colors for status
        self.history_tree.tag_configure("completed", foreground="green")
        self.history_tree.tag_configure("failed", foreground="red")
        self.history_tree.tag_configure("error", foreground="dark red")

    def create_export_panel(self, parent):
        """Create export buttons."""
        export_frame = ttk.LabelFrame(parent, text="📤 Export", padding="10")
        export_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 5))

        ttk.Label(export_frame, text="Export history to:").grid(row=0, column=0, padx=(0, 10))

        # Excel export
        excel_btn = ttk.Button(
            export_frame,
            text="📊 Excel (.xlsx)",
            command=lambda: self.export_history("excel"),
            width=15
        )
        excel_btn.grid(row=0, column=1, padx=5)

        # JSON export
        json_btn = ttk.Button(
            export_frame,
            text="📄 JSON",
            command=lambda: self.export_history("json"),
            width=15
        )
        json_btn.grid(row=0, column=2, padx=5)

        # CSV export
        csv_btn = ttk.Button(
            export_frame,
            text="📋 CSV",
            command=lambda: self.export_history("csv"),
            width=15
        )
        csv_btn.grid(row=0, column=3, padx=5)

    def create_logs_tab(self):
        """Create the Logs tab with complete logging history and filtering."""
        # Create frame for logs tab
        logs_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(logs_frame, text="📋 Complete Logs")

        # Configure grid
        logs_frame.columnconfigure(0, weight=1)
        logs_frame.rowconfigure(1, weight=1)  # Log display expands

        # Filter Panel
        self.create_log_filter_panel(logs_frame)

        # Log Display
        self.create_complete_log_display(logs_frame)

        # Control Panel
        self.create_log_control_panel(logs_frame)

    def create_log_filter_panel(self, parent):
        """Create log filter controls."""
        filter_frame = ttk.LabelFrame(parent, text="🔍 Log Filters", padding="10")
        filter_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        # Log level filter
        ttk.Label(filter_frame, text="Level:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.log_level_filter = ttk.Combobox(
            filter_frame,
            values=["All", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            state="readonly",
            width=12
        )
        self.log_level_filter.set("All")
        self.log_level_filter.grid(row=0, column=1, sticky=tk.W, padx=(0, 15))
        self.log_level_filter.bind("<<ComboboxSelected>>", lambda e: self.apply_log_filters())

        # Search entry
        ttk.Label(filter_frame, text="Search:").grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        self.log_search_entry = ttk.Entry(filter_frame, width=40)
        self.log_search_entry.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=(0, 10))
        self.log_search_entry.bind("<KeyRelease>", lambda e: self.apply_log_filters())

        # Apply button
        apply_btn = ttk.Button(
            filter_frame,
            text="Apply",
            command=self.apply_log_filters,
            width=10
        )
        apply_btn.grid(row=0, column=4, padx=5)

        # Clear filters button
        clear_btn = ttk.Button(
            filter_frame,
            text="Clear",
            command=self.clear_log_filters,
            width=10
        )
        clear_btn.grid(row=0, column=5, padx=5)

        # Configure column weights
        filter_frame.columnconfigure(3, weight=1)

    def create_complete_log_display(self, parent):
        """Create the complete log display area."""
        log_frame = ttk.LabelFrame(parent, text="📝 Complete Log History", padding="5")
        log_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))

        # Log text widget with scrollbar
        self.complete_log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            width=100,
            height=25,
            font=("Consolas", 9),
            state=tk.DISABLED
        )
        self.complete_log_text.pack(fill=tk.BOTH, expand=True)

        # Configure log text tags for colors
        self.complete_log_text.tag_config("INFO", foreground="black")
        self.complete_log_text.tag_config("WARNING", foreground="orange")
        self.complete_log_text.tag_config("ERROR", foreground="red")
        self.complete_log_text.tag_config("CRITICAL", foreground="dark red")
        self.complete_log_text.tag_config("DEBUG", foreground="gray")

        # Configure grid weights
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

    def create_log_control_panel(self, parent):
        """Create log control buttons."""
        control_frame = ttk.LabelFrame(parent, text="⚙️ Controls", padding="10")
        control_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 5))

        # Auto-scroll checkbox
        self.auto_scroll_var = tk.BooleanVar(value=True)
        auto_scroll_check = ttk.Checkbutton(
            control_frame,
            text="Auto-scroll to bottom",
            variable=self.auto_scroll_var
        )
        auto_scroll_check.grid(row=0, column=0, padx=5)

        # Show timestamps checkbox
        self.show_timestamps_var = tk.BooleanVar(value=True)
        timestamps_check = ttk.Checkbutton(
            control_frame,
            text="Show timestamps",
            variable=self.show_timestamps_var,
            command=self.apply_log_filters
        )
        timestamps_check.grid(row=0, column=1, padx=5)

        # Clear logs button
        clear_logs_btn = ttk.Button(
            control_frame,
            text="🗑 Clear Logs",
            command=self.clear_complete_logs,
            width=15
        )
        clear_logs_btn.grid(row=0, column=2, padx=5)

        # Export logs button
        export_logs_btn = ttk.Button(
            control_frame,
            text="💾 Export Logs",
            command=self.export_logs,
            width=15
        )
        export_logs_btn.grid(row=0, column=3, padx=5)

        # Refresh button
        refresh_logs_btn = ttk.Button(
            control_frame,
            text="🔄 Refresh",
            command=self.refresh_complete_logs,
            width=15
        )
        refresh_logs_btn.grid(row=0, column=4, padx=5)

    def apply_log_filters(self):
        """Apply filters to the log display."""
        # Get filter values
        level_filter = self.log_level_filter.get()
        search_term = self.log_search_entry.get().lower()
        show_timestamps = self.show_timestamps_var.get()

        # Get all logs from status manager
        status = status_manager.get_status()
        all_logs = status['recent_logs']

        # Filter logs
        filtered_logs = []
        for log in all_logs:
            # Level filter
            if level_filter != "All":
                if f"[{level_filter}]" not in log:
                    continue

            # Search filter
            if search_term and search_term not in log.lower():
                continue

            # Remove timestamps if needed
            if not show_timestamps and log.startswith("["):
                # Extract just the message part
                parts = log.split("]", 2)
                if len(parts) >= 3:
                    log = parts[2].strip()

            filtered_logs.append(log)

        # Update display
        self.complete_log_text.config(state=tk.NORMAL)
        self.complete_log_text.delete("1.0", tk.END)

        for log in filtered_logs:
            # Determine tag based on log level
            tag = "INFO"
            if "[ERROR]" in log or "[CRITICAL]" in log:
                tag = "ERROR"
            elif "[WARNING]" in log:
                tag = "WARNING"
            elif "[DEBUG]" in log:
                tag = "DEBUG"

            self.complete_log_text.insert(tk.END, log + "\n", tag)

        # Auto-scroll if enabled
        if self.auto_scroll_var.get():
            self.complete_log_text.see(tk.END)

        self.complete_log_text.config(state=tk.DISABLED)

    def clear_log_filters(self):
        """Clear all log filters."""
        self.log_level_filter.set("All")
        self.log_search_entry.delete(0, tk.END)
        self.apply_log_filters()

    def clear_complete_logs(self):
        """Clear the complete log display."""
        if messagebox.askyesno("Clear Logs", "Are you sure you want to clear all logs?"):
            self.complete_log_text.config(state=tk.NORMAL)
            self.complete_log_text.delete("1.0", tk.END)
            self.complete_log_text.config(state=tk.DISABLED)
            status_manager.add_log("Logs cleared from display", "INFO")

    def refresh_complete_logs(self):
        """Refresh the complete log display."""
        self.apply_log_filters()

    def export_logs(self):
        """Export logs to a text file."""
        try:
            # File dialog
            filepath = filedialog.asksaveasfilename(
                title="Export Logs",
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
            )

            if not filepath:
                return  # User cancelled

            # Get all logs
            status = status_manager.get_status()
            all_logs = status['recent_logs']

            # Write to file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("SICAL Gastos Robot - Complete Logs\n")
                f.write("=" * 80 + "\n\n")
                for log in all_logs:
                    f.write(log + "\n")

            messagebox.showinfo("Success", f"Logs exported successfully to:\n{filepath}")
            status_manager.add_log(f"Logs exported to {filepath}", "INFO")

        except Exception as e:
            status_manager.add_log(f"Failed to export logs: {e}", "ERROR")
            messagebox.showerror("Error", f"Failed to export logs:\n{e}")

    def create_status_panel(self, parent):
        """Create the service status panel."""
        status_frame = ttk.LabelFrame(parent, text="Service Status", padding="10")
        status_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # Service status
        ttk.Label(status_frame, text="Service:").grid(row=0, column=0, sticky=tk.W)
        self.service_status_label = ttk.Label(
            status_frame,
            text="● STOPPED",
            foreground="red",
            font=("Segoe UI", 10, "bold")
        )
        self.service_status_label.grid(row=0, column=1, sticky=tk.W, padx=(5, 20))

        # RabbitMQ status
        ttk.Label(status_frame, text="RabbitMQ:").grid(row=0, column=2, sticky=tk.W)
        self.rabbitmq_status_label = ttk.Label(
            status_frame,
            text="● DISCONNECTED",
            foreground="red",
            font=("Segoe UI", 10, "bold")
        )
        self.rabbitmq_status_label.grid(row=0, column=3, sticky=tk.W, padx=5)

        # Uptime
        ttk.Label(status_frame, text="Uptime:").grid(row=0, column=4, sticky=tk.W, padx=(20, 0))
        self.uptime_label = ttk.Label(status_frame, text="--:--:--")
        self.uptime_label.grid(row=0, column=5, sticky=tk.W, padx=5)

    def create_statistics_panel(self, parent):
        """Create the statistics panel."""
        stats_frame = ttk.LabelFrame(parent, text="📊 Statistics", padding="10")
        stats_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # Configure columns
        for i in range(5):
            stats_frame.columnconfigure(i, weight=1)

        # Pending
        ttk.Label(stats_frame, text="Pending:", font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky=tk.W
        )
        self.pending_label = ttk.Label(
            stats_frame,
            text="0",
            font=("Segoe UI", 11, "bold"),
            foreground="orange"
        )
        self.pending_label.grid(row=1, column=0, sticky=tk.W)

        # Processing
        ttk.Label(stats_frame, text="Processing:", font=("Segoe UI", 9)).grid(
            row=0, column=1, sticky=tk.W
        )
        self.processing_label = ttk.Label(
            stats_frame,
            text="0",
            font=("Segoe UI", 11, "bold"),
            foreground="blue"
        )
        self.processing_label.grid(row=1, column=1, sticky=tk.W)

        # Completed
        ttk.Label(stats_frame, text="Completed:", font=("Segoe UI", 9)).grid(
            row=0, column=2, sticky=tk.W
        )
        self.completed_label = ttk.Label(
            stats_frame,
            text="0",
            font=("Segoe UI", 11, "bold"),
            foreground="green"
        )
        self.completed_label.grid(row=1, column=2, sticky=tk.W)

        # Failed
        ttk.Label(stats_frame, text="Failed:", font=("Segoe UI", 9)).grid(
            row=0, column=3, sticky=tk.W
        )
        self.failed_label = ttk.Label(
            stats_frame,
            text="0",
            font=("Segoe UI", 11, "bold"),
            foreground="red"
        )
        self.failed_label.grid(row=1, column=3, sticky=tk.W)

        # Success Rate
        ttk.Label(stats_frame, text="Success Rate:", font=("Segoe UI", 9)).grid(
            row=0, column=4, sticky=tk.W
        )
        self.success_rate_label = ttk.Label(
            stats_frame,
            text="0.0%",
            font=("Segoe UI", 11, "bold")
        )
        self.success_rate_label.grid(row=1, column=4, sticky=tk.W)

    def create_current_task_panel(self, parent):
        """Create the current task panel."""
        task_frame = ttk.LabelFrame(parent, text="🔄 Current Task", padding="10")
        task_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # Configure grid columns for better layout
        task_frame.columnconfigure(1, weight=1)
        task_frame.columnconfigure(3, weight=1)

        # Task info labels
        self.current_task_label = ttk.Label(
            task_frame,
            text="No task currently processing",
            font=("Segoe UI", 9, "bold"),
            foreground="gray"
        )
        self.current_task_label.grid(row=0, column=0, sticky=tk.W, columnspan=4, pady=(0, 5))

        # Row 1: Operation Type and Operation Number
        ttk.Label(task_frame, text="Type:", font=("Segoe UI", 9)).grid(
            row=1, column=0, sticky=tk.W
        )
        self.operation_type_label = ttk.Label(task_frame, text="--")
        self.operation_type_label.grid(row=1, column=1, sticky=tk.W, padx=(5, 15))

        ttk.Label(task_frame, text="Operation:", font=("Segoe UI", 9)).grid(
            row=1, column=2, sticky=tk.W
        )
        self.operation_label = ttk.Label(task_frame, text="--")
        self.operation_label.grid(row=1, column=3, sticky=tk.W, padx=5)

        # Row 2: Date and Duration
        ttk.Label(task_frame, text="Date:", font=("Segoe UI", 9)).grid(
            row=2, column=0, sticky=tk.W
        )
        self.date_label = ttk.Label(task_frame, text="--")
        self.date_label.grid(row=2, column=1, sticky=tk.W, padx=(5, 15))

        ttk.Label(task_frame, text="Duration:", font=("Segoe UI", 9)).grid(
            row=2, column=2, sticky=tk.W
        )
        self.duration_label = ttk.Label(task_frame, text="--")
        self.duration_label.grid(row=2, column=3, sticky=tk.W, padx=5)

        # Row 3: Amount and Cash Register
        ttk.Label(task_frame, text="Amount:", font=("Segoe UI", 9)).grid(
            row=3, column=0, sticky=tk.W
        )
        self.amount_label = ttk.Label(task_frame, text="--")
        self.amount_label.grid(row=3, column=1, sticky=tk.W, padx=(5, 15))

        ttk.Label(task_frame, text="Cash Register:", font=("Segoe UI", 9)).grid(
            row=3, column=2, sticky=tk.W
        )
        self.cash_register_label = ttk.Label(task_frame, text="--")
        self.cash_register_label.grid(row=3, column=3, sticky=tk.W, padx=5)

        # Row 4: Nature (full width)
        ttk.Label(task_frame, text="Nature:", font=("Segoe UI", 9)).grid(
            row=4, column=0, sticky=tk.W
        )
        self.nature_label = ttk.Label(task_frame, text="--")
        self.nature_label.grid(row=4, column=1, sticky=tk.W, columnspan=3, padx=5)

        # Row 5: Third Party (full width)
        ttk.Label(task_frame, text="Third Party:", font=("Segoe UI", 9)).grid(
            row=5, column=0, sticky=tk.W
        )
        self.third_party_label = ttk.Label(task_frame, text="--", wraplength=600)
        self.third_party_label.grid(row=5, column=1, sticky=tk.W, columnspan=3, padx=5)

        # Row 6: Description (full width)
        ttk.Label(task_frame, text="Description:", font=("Segoe UI", 9)).grid(
            row=6, column=0, sticky=tk.W
        )
        self.description_label = ttk.Label(task_frame, text="--", wraplength=600)
        self.description_label.grid(row=6, column=1, sticky=tk.W, columnspan=3, padx=5)

        # Separator
        ttk.Separator(task_frame, orient='horizontal').grid(
            row=7, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=8
        )

        # Row 8: Line items progress
        ttk.Label(task_frame, text="Line Items:", font=("Segoe UI", 9, "bold")).grid(
            row=8, column=0, sticky=tk.W
        )
        self.line_items_label = ttk.Label(task_frame, text="--", font=("Segoe UI", 9))
        self.line_items_label.grid(row=8, column=1, sticky=tk.W, columnspan=3, padx=5)

        # Row 9: Current line item details
        ttk.Label(task_frame, text="Current Item:", font=("Segoe UI", 9)).grid(
            row=9, column=0, sticky=tk.W
        )
        self.line_item_details_label = ttk.Label(task_frame, text="--", wraplength=600)
        self.line_item_details_label.grid(row=9, column=1, sticky=tk.W, columnspan=3, padx=5)

        # Row 10: Current step
        ttk.Label(task_frame, text="Status:", font=("Segoe UI", 9)).grid(
            row=10, column=0, sticky=tk.W
        )
        self.step_label = ttk.Label(task_frame, text="--", wraplength=600, foreground="blue")
        self.step_label.grid(row=10, column=1, sticky=tk.W, columnspan=3, padx=5)

        # Separator
        ttk.Separator(task_frame, orient='horizontal').grid(
            row=11, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=8
        )

        # Row 12: Duplicate Policy (bold label)
        ttk.Label(task_frame, text="Duplicate Policy:", font=("Segoe UI", 9, "bold")).grid(
            row=12, column=0, sticky=tk.W
        )
        self.policy_label = ttk.Label(task_frame, text="--", font=("Segoe UI", 9))
        self.policy_label.grid(row=12, column=1, sticky=tk.W, columnspan=3, padx=5)

        # Row 13: Confirmation Token
        ttk.Label(task_frame, text="Token:", font=("Segoe UI", 9, "bold")).grid(
            row=13, column=0, sticky=tk.W
        )
        self.token_label = ttk.Label(task_frame, text="--", font=("Segoe UI", 9), wraplength=600)
        self.token_label.grid(row=13, column=1, sticky=tk.W, columnspan=3, padx=5)

    def create_control_panel(self, parent):
        """Create the control buttons panel."""
        control_frame = ttk.Frame(parent)
        control_frame.grid(row=5, column=0, columnspan=2, pady=10)

        # Start button
        self.start_button = ttk.Button(
            control_frame,
            text="▶ Start Service",
            command=self.start_service,
            width=20
        )
        self.start_button.grid(row=0, column=0, padx=5)

        # Stop button
        self.stop_button = ttk.Button(
            control_frame,
            text="⏹ Stop Service",
            command=self.stop_service,
            state=tk.DISABLED,
            width=20
        )
        self.stop_button.grid(row=0, column=1, padx=5)

        # Clear stats button
        self.clear_button = ttk.Button(
            control_frame,
            text="🗑 Clear Stats",
            command=self.clear_stats,
            width=20
        )
        self.clear_button.grid(row=0, column=2, padx=5)

    def create_log_panel(self, parent):
        """Create the log display panel."""
        log_frame = ttk.LabelFrame(parent, text="📝 Activity Log", padding="5")
        log_frame.grid(row=6, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)

        # Log text widget with scrollbar
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            width=80,
            height=15,
            font=("Consolas", 9),
            state=tk.DISABLED
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Configure log text tags for colors
        self.log_text.tag_config("INFO", foreground="black")
        self.log_text.tag_config("WARNING", foreground="orange")
        self.log_text.tag_config("ERROR", foreground="red")
        self.log_text.tag_config("CRITICAL", foreground="dark red")
        self.log_text.tag_config("DEBUG", foreground="gray")

    def start_service(self):
        """Start the consumer service in a background thread."""
        if self.consumer_thread and self.consumer_thread.is_alive():
            status_manager.add_log("Service is already running", "WARNING")
            return

        status_manager.add_log("Starting Gastos Robot service...", "INFO")
        status_manager.update_service_status(True)
        status_manager.reset_stats()

        # Import consumer here to set up callbacks first
        from gasto_task_consumer import GastoConsumer

        # Create consumer instance with logger
        logger = logging.getLogger('GastoConsumer')
        self.consumer = GastoConsumer(logger)

        # Set up callbacks
        self.consumer.set_status_callback(self.status_callback)
        self.consumer.set_task_callback(self.task_callback)

        # Start consumer in background thread
        self.consumer_thread = threading.Thread(
            target=self.run_consumer,
            daemon=True,
            name="ConsumerThread"
        )
        self.consumer_thread.start()

        # Update button states
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)

    def run_consumer(self):
        """Run the consumer (blocking call in background thread)."""
        try:
            self.consumer.start_consuming()
        except Exception as e:
            status_manager.add_log(f"Consumer error: {e}", "ERROR")
            status_manager.update_service_status(False)

    def stop_service(self):
        """Stop the consumer service."""
        if not self.consumer or not self.consumer_thread or not self.consumer_thread.is_alive():
            status_manager.add_log("Service is not running", "WARNING")
            return

        status_manager.add_log("Stopping Gastos Robot service...", "INFO")

        # Stop consumer gracefully
        if self.consumer:
            self.consumer.stop_consuming()

        status_manager.update_service_status(False)
        status_manager.update_rabbitmq_status(False)

        # Update button states
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def clear_stats(self):
        """Clear statistics."""
        status_manager.reset_stats()
        status_manager.add_log("Statistics cleared", "INFO")

    def status_callback(self, event: str, **kwargs):
        """
        Callback from consumer for status updates.

        Events:
        - 'connected': Successfully connected to RabbitMQ
        - 'disconnected': Disconnected from RabbitMQ
        - 'task_received': New task received from queue
        - 'task_started': Task processing started
        - 'task_completed': Task completed successfully
        - 'task_failed': Task failed
        """
        if event == 'connected':
            status_manager.update_rabbitmq_status(True)
        elif event == 'disconnected':
            status_manager.update_rabbitmq_status(False)
        elif event == 'task_received':
            task_id = kwargs.get('task_id', 'unknown')
            status_manager.task_received(task_id)
        elif event == 'task_started':
            task_id = kwargs.get('task_id', 'unknown')
            operation_type = kwargs.get('operation_type')
            operation_number = kwargs.get('operation_number')
            amount = kwargs.get('amount')

            # Pass all additional kwargs
            additional_kwargs = {k: v for k, v in kwargs.items()
                               if k not in ('task_id', 'operation_type', 'operation_number', 'amount')}

            status_manager.task_started(task_id, operation_type, operation_number, amount, **additional_kwargs)
        elif event == 'task_completed':
            task_id = kwargs.get('task_id', 'unknown')
            status_manager.task_completed(task_id, success=True)

            # Save to history database - remove task_id from kwargs to avoid duplication
            history_kwargs = {k: v for k, v in kwargs.items() if k != 'task_id'}
            self.save_task_to_history(task_id, 'completed', **history_kwargs)
        elif event == 'task_failed':
            task_id = kwargs.get('task_id', 'unknown')
            status_manager.task_completed(task_id, success=False)

            # Save to history database - remove task_id from kwargs to avoid duplication
            history_kwargs = {k: v for k, v in kwargs.items() if k != 'task_id'}
            self.save_task_to_history(task_id, 'failed', **history_kwargs)

    def task_callback(self, event: str, **kwargs):
        """
        Callback from task processor for detailed progress updates.

        Events:
        - 'step': Current processing step
        """
        if event == 'step':
            step = kwargs.get('step', '')
            additional_kwargs = {k: v for k, v in kwargs.items() if k != 'step'}
            status_manager.task_progress(step, **additional_kwargs)

    def save_task_to_history(self, task_id: str, status: str, **kwargs):
        """Save completed task to history database."""
        try:
            db = get_task_history_db()

            task_data = {
                'task_id': task_id,
                'operation_type': kwargs.get('operation_type'),
                'operation_number': kwargs.get('operation_number'),
                'date': kwargs.get('date'),
                'cash_register': kwargs.get('cash_register'),
                'third_party': kwargs.get('third_party'),
                'nature': kwargs.get('nature'),
                'amount': kwargs.get('amount'),
                'description': kwargs.get('description'),
                'total_line_items': kwargs.get('total_line_items'),
                'status': status,
                'started_at': kwargs.get('started_at'),
                'completed_at': datetime.now().isoformat(),
                'duration_seconds': kwargs.get('duration_seconds'),
                'error_message': kwargs.get('error_message')
            }

            db.add_task(task_data)

        except Exception as e:
            status_manager.add_log(f"Failed to save task to history: {e}", "ERROR")

    def update_display(self):
        """Update the display with current status (called periodically)."""
        # Get current status
        status = status_manager.get_status()

        # Update service status
        if status['service_running']:
            self.service_status_label.config(text="● RUNNING", foreground="green")
        else:
            self.service_status_label.config(text="● STOPPED", foreground="red")

        # Update RabbitMQ status
        if status['rabbitmq_connected']:
            self.rabbitmq_status_label.config(text="● CONNECTED", foreground="green")
        else:
            self.rabbitmq_status_label.config(text="● DISCONNECTED", foreground="red")

        # Update uptime
        if status['uptime']:
            hours = int(status['uptime'] // 3600)
            minutes = int((status['uptime'] % 3600) // 60)
            seconds = int(status['uptime'] % 60)
            self.uptime_label.config(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self.uptime_label.config(text="--:--:--")

        # Update statistics
        stats = status['stats']
        self.pending_label.config(text=str(stats['pending']))
        self.processing_label.config(text=str(stats['processing']))
        self.completed_label.config(text=str(stats['completed']))
        self.failed_label.config(text=str(stats['failed']))
        self.success_rate_label.config(text=f"{status['success_rate']:.1f}%")

        # Update current task
        current_task = status['current_task']
        if current_task:
            task_id = current_task['task_id'][:16] + "..." if len(current_task['task_id']) > 16 else current_task['task_id']
            self.current_task_label.config(
                text=f"Processing: {task_id}",
                foreground="blue"
            )

            # Basic info
            operation_type = (current_task['operation_type'] or 'unknown').upper()
            self.operation_type_label.config(text=operation_type)

            operation = current_task['operation_number'] or "--"
            self.operation_label.config(text=operation)

            date = current_task.get('date') or "--"
            self.date_label.config(text=date)

            duration = current_task['duration']
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            self.duration_label.config(text=f"{minutes:02d}:{seconds:02d}")

            cash_register = current_task.get('cash_register') or "--"
            self.cash_register_label.config(text=cash_register)

            amount = current_task['amount']
            if amount is not None:
                self.amount_label.config(text=f"€{amount:.2f}")
            else:
                self.amount_label.config(text="--")

            nature_display = current_task.get('nature_display') or "--"
            self.nature_label.config(text=nature_display)

            # Detailed info
            third_party = current_task.get('third_party') or "--"
            self.third_party_label.config(text=third_party)

            description = current_task.get('description') or "--"
            self.description_label.config(text=description)

            # Line items progress
            total_items = current_task.get('total_line_items', 0)
            current_item = current_task.get('current_line_item', 0)
            if total_items > 0:
                progress_text = f"{current_item} of {total_items}"
                if current_item > 0:
                    percentage = (current_item / total_items) * 100
                    progress_text += f" ({percentage:.0f}%)"
                self.line_items_label.config(text=progress_text)
            else:
                self.line_items_label.config(text="--")

            line_details = current_task.get('line_item_details') or "--"
            self.line_item_details_label.config(text=line_details)

            step = current_task['current_step'] or "Processing..."
            self.step_label.config(text=step)

            # Display policy and token information
            policy = current_task.get('duplicate_policy', 'abort_on_duplicate')
            if policy:
                policy_display = policy.replace('_', ' ').title()
                # Color code based on policy type
                policy_color = "black"
                if policy == 'check_only':
                    policy_color = "blue"
                elif policy == 'force_create':
                    policy_color = "orange"
                elif policy == 'abort_on_duplicate':
                    policy_color = "red"
                self.policy_label.config(text=policy_display, foreground=policy_color)
            else:
                self.policy_label.config(text="Abort On Duplicate (default)", foreground="red")

            # Display token with status color coding
            token = current_task.get('duplicate_confirmation_token')
            token_status = current_task.get('token_status', 'none')
            if token:
                # Truncate token for display
                token_display = f"{token[:16]}...{token[-8:]}" if len(token) > 32 else token
                token_display += f" [{token_status.upper()}]"

                # Color code based on token status
                token_color = "gray"
                if token_status == 'received':
                    token_color = "orange"  # Pending
                elif token_status == 'validated':
                    token_color = "blue"    # Validated
                elif token_status == 'processing':
                    token_color = "green"   # Processing
                elif token_status == 'finalized':
                    token_color = "gray"    # Completed

                self.token_label.config(text=token_display, foreground=token_color)
            else:
                self.token_label.config(text="No token (N/A)", foreground="gray")
        else:
            # Check if there's a last completed task to display
            last_completed = status.get('last_completed_task')
            if last_completed:
                # Show last completed task info in a muted style
                task_id = last_completed['task_id'][:16] + "..." if len(last_completed['task_id']) > 16 else last_completed['task_id']
                completion_status = last_completed.get('completion_status', 'COMPLETED')
                self.current_task_label.config(
                    text=f"Last: {task_id} - {completion_status}",
                    foreground="gray"
                )

                # Show basic info from last task
                operation_type = (last_completed['operation_type'] or 'unknown').upper()
                self.operation_type_label.config(text=operation_type)

                operation = last_completed['operation_number'] or "--"
                self.operation_label.config(text=operation)

                date = last_completed.get('date') or "--"
                self.date_label.config(text=date)

                self.duration_label.config(text="--")

                cash_register = last_completed.get('cash_register') or "--"
                self.cash_register_label.config(text=cash_register)

                amount = last_completed['amount']
                if amount is not None:
                    self.amount_label.config(text=f"€{amount:.2f}")
                else:
                    self.amount_label.config(text="--")

                nature_display = last_completed.get('nature_display') or "--"
                self.nature_label.config(text=nature_display)

                third_party = last_completed.get('third_party') or "--"
                self.third_party_label.config(text=third_party)

                description = last_completed.get('description') or "--"
                self.description_label.config(text=description)

                total_items = last_completed.get('total_line_items', 0)
                self.line_items_label.config(text=f"{total_items} items")

                self.line_item_details_label.config(text="--")
                self.step_label.config(text=f"{completion_status}")

                # Display retained policy and token info
                policy = last_completed.get('duplicate_policy')
                if policy:
                    policy_display = policy.replace('_', ' ').title()
                    self.policy_label.config(text=policy_display + " (Last task)", foreground="gray")
                else:
                    self.policy_label.config(text="--", foreground="gray")

                token = last_completed.get('duplicate_confirmation_token')
                token_status = last_completed.get('token_status', 'finalized')
                if token:
                    token_display = f"{token[:16]}...{token[-8:]}" if len(token) > 32 else token
                    token_display += f" [{token_status.upper()}]"
                    self.token_label.config(text=token_display, foreground="gray")
                else:
                    self.token_label.config(text="No token (Last task)", foreground="gray")
            else:
                # No current task and no last completed task
                self.current_task_label.config(
                    text="No task currently processing",
                    foreground="gray"
                )
                self.operation_type_label.config(text="--")
                self.operation_label.config(text="--")
                self.date_label.config(text="--")
                self.duration_label.config(text="--")
                self.cash_register_label.config(text="--")
                self.amount_label.config(text="--")
                self.nature_label.config(text="--")
                self.third_party_label.config(text="--")
                self.description_label.config(text="--")
                self.line_items_label.config(text="--")
                self.line_item_details_label.config(text="--")
                self.step_label.config(text="--")
                self.policy_label.config(text="--", foreground="gray")
                self.token_label.config(text="--", foreground="gray")

        # Update logs
        recent_logs = status['recent_logs']
        if recent_logs:
            # Get current text
            current_logs = self.log_text.get("1.0", tk.END).strip()
            new_logs = "\n".join(recent_logs)

            # Only update if changed
            if current_logs != new_logs:
                self.log_text.config(state=tk.NORMAL)
                self.log_text.delete("1.0", tk.END)

                for log in recent_logs:
                    # Determine tag based on log level
                    tag = "INFO"
                    if "[ERROR]" in log or "[CRITICAL]" in log:
                        tag = "ERROR"
                    elif "[WARNING]" in log:
                        tag = "WARNING"
                    elif "[DEBUG]" in log:
                        tag = "DEBUG"

                    self.log_text.insert(tk.END, log + "\n", tag)

                # Auto-scroll to bottom
                self.log_text.see(tk.END)
                self.log_text.config(state=tk.DISABLED)

        # Update complete logs tab if it exists
        if hasattr(self, 'complete_log_text'):
            # Only update if the logs tab is visible or auto-refresh is needed
            try:
                self.refresh_complete_logs()
            except Exception:
                pass  # Ignore errors during refresh

        # Schedule next update (500ms)
        self.root.after(500, self.update_display)

    def load_history(self):
        """Load task history from database."""
        try:
            db = get_task_history_db()

            # Get search term and status filter
            search_term = self.search_entry.get().strip()
            status_filter_value = self.status_filter.get()

            # Map UI values to database values
            status_map = {
                "All": None,
                "Completed": "completed",
                "Failed": "failed",
                "Error": "error"
            }
            status_db = status_map.get(status_filter_value)

            # Get tasks from database
            if search_term:
                tasks = db.search_tasks(search_term, limit=500)
                # Apply status filter if needed
                if status_db:
                    tasks = [t for t in tasks if t.get('status') == status_db]
            else:
                tasks = db.get_all_tasks(limit=500, status_filter=status_db)

            # Clear existing items
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)

            # Populate tree
            for task in tasks:
                # Format values
                task_id = task.get('task_id', '--')[:30]
                operation_type = (task.get('operation_type', '--') or '--').upper()
                operation = task.get('operation_number', '--')
                date = task.get('date', '--')
                amount = f"€{task.get('amount', 0):.2f}" if task.get('amount') else "--"
                cash_reg = task.get('cash_register', '--')
                third_party = (task.get('third_party', '--') or '--')[:25]

                # Nature display
                nature = task.get('nature')
                if nature in ('1', '2', '3', '4'):
                    nature_display = "Presupuestary"
                elif nature == '5':
                    nature_display = "Non-presupuestary"
                else:
                    nature_display = nature or "--"

                status = (task.get('status', '--') or '--').capitalize()

                # Duration
                duration_sec = task.get('duration_seconds')
                if duration_sec:
                    minutes = int(duration_sec // 60)
                    seconds = int(duration_sec % 60)
                    duration = f"{minutes:02d}:{seconds:02d}"
                else:
                    duration = "--"

                # Completed at
                completed_at = task.get('completed_at', '--')
                if completed_at and completed_at != '--':
                    try:
                        # Format datetime if it's a timestamp
                        if isinstance(completed_at, str):
                            dt = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                            completed_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        pass

                # Insert with tag for coloring
                tag = task.get('status', '').lower()
                self.history_tree.insert(
                    "",
                    0,  # Insert at beginning (most recent first)
                    values=(task_id, operation_type, operation, date, amount, cash_reg,
                           third_party, nature_display, status, duration, completed_at),
                    tags=(tag,)
                )

            # Update statistics
            stats = db.get_statistics()
            self.hist_total_label.config(text=str(stats.get('total_tasks', 0)))
            self.hist_completed_label.config(text=str(stats.get('completed', 0)))
            self.hist_failed_label.config(text=str(stats.get('failed', 0)))

            avg_duration = stats.get('avg_duration')
            if avg_duration:
                minutes = int(avg_duration // 60)
                seconds = int(avg_duration % 60)
                self.hist_avg_duration_label.config(text=f"{minutes:02d}:{seconds:02d}")
            else:
                self.hist_avg_duration_label.config(text="--")

            status_manager.add_log(f"Loaded {len(tasks)} tasks from history", "INFO")

        except Exception as e:
            status_manager.add_log(f"Failed to load history: {e}", "ERROR")
            messagebox.showerror("Error", f"Failed to load history:\n{e}")

    def on_history_row_double_click(self, event):
        """Handle double-click on history row to show details."""
        selection = self.history_tree.selection()
        if not selection:
            return

        # Get task_id from selected row
        item = self.history_tree.item(selection[0])
        task_id = item['values'][0]  # task_id is first column

        try:
            db = get_task_history_db()
            # Search for full task (task_id might be truncated in display)
            tasks = db.search_tasks(task_id, limit=1)
            if not tasks:
                messagebox.showinfo("Not Found", "Task details not found in database")
                return

            task = tasks[0]

            # Create detail window
            detail_window = tk.Toplevel(self.root)
            detail_window.title(f"Task Details - {task.get('task_id', 'Unknown')}")
            detail_window.geometry("600x550")

            # Create scrolled text widget
            text = scrolledtext.ScrolledText(
                detail_window,
                wrap=tk.WORD,
                font=("Consolas", 10),
                padx=10,
                pady=10
            )
            text.pack(fill=tk.BOTH, expand=True)

            # Pre-format complex values
            amount_str = f"€{task.get('amount'):.2f}" if task.get('amount') is not None else '--'
            duration_str = '--'
            if task.get('duration_seconds') is not None:
                dur_sec = task.get('duration_seconds')
                duration_str = f"{int(dur_sec // 60):02d}:{int(dur_sec % 60):02d}"

            nature = task.get('nature')
            nature_str = '--'
            if nature in ('1', '2', '3', '4'):
                nature_str = f"{nature} (Presupuestary)"
            elif nature == '5':
                nature_str = f"{nature} (Non-presupuestary)"
            elif nature:
                nature_str = nature

            # Format task details
            details = f"""
╔═══════════════════════════════════════════════════════════════╗
║                        TASK DETAILS                           ║
╚═══════════════════════════════════════════════════════════════╝

Task ID:          {task.get('task_id', '--')}
Operation Type:   {(task.get('operation_type', '--') or '--').upper()}
Operation Number: {task.get('operation_number', '--')}
Status:           {(task.get('status', '--') or '--').upper()}

╔═══════════════════════════════════════════════════════════════╗
║                     OPERATION DETAILS                         ║
╚═══════════════════════════════════════════════════════════════╝

Date:             {task.get('date', '--')}
Cash Register:    {task.get('cash_register', '--')}
Third Party:      {task.get('third_party', '--') or '--'}
Nature:           {nature_str}
Amount:           {amount_str}
Description:      {task.get('description', '--') or '--'}
Total Line Items: {task.get('total_line_items', 0) or 0}

╔═══════════════════════════════════════════════════════════════╗
║                      TIMING INFORMATION                       ║
╚═══════════════════════════════════════════════════════════════╝

Started At:       {task.get('started_at', '--')}
Completed At:     {task.get('completed_at', '--')}
Duration:         {duration_str}

"""
            # Add error message if present
            if task.get('error_message'):
                details += f"""╔═══════════════════════════════════════════════════════════════╗
║                        ERROR MESSAGE                          ║
╚═══════════════════════════════════════════════════════════════╝

{task.get('error_message')}
"""

            text.insert("1.0", details)
            text.config(state=tk.DISABLED)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load task details:\n{e}")

    def export_history(self, format_type):
        """Export history to file."""
        try:
            db = get_task_history_db()

            # File dialog
            filetypes = {
                "excel": [("Excel files", "*.xlsx"), ("All files", "*.*")],
                "json": [("JSON files", "*.json"), ("All files", "*.*")],
                "csv": [("CSV files", "*.csv"), ("All files", "*.*")]
            }

            default_ext = {
                "excel": ".xlsx",
                "json": ".json",
                "csv": ".csv"
            }

            filepath = filedialog.asksaveasfilename(
                title="Export History",
                defaultextension=default_ext[format_type],
                filetypes=filetypes[format_type]
            )

            if not filepath:
                return  # User cancelled

            # Export based on format
            success = False
            if format_type == "excel":
                success = db.export_to_excel(filepath)
            elif format_type == "json":
                success = db.export_to_json(filepath)
            elif format_type == "csv":
                success = db.export_to_csv(filepath)

            if success:
                messagebox.showinfo("Success", f"History exported successfully to:\n{filepath}")
                status_manager.add_log(f"Exported history to {filepath}", "INFO")
            else:
                messagebox.showerror("Error", "Export failed. Check logs for details.")

        except Exception as e:
            status_manager.add_log(f"Export failed: {e}", "ERROR")
            messagebox.showerror("Error", f"Export failed:\n{e}")

    def on_closing(self):
        """Handle window closing event."""
        if self.consumer and self.consumer_thread and self.consumer_thread.is_alive():
            status_manager.add_log("Stopping service before exit...", "INFO")
            self.stop_service()
            # Give it a moment to cleanup
            self.root.after(1000, self.root.destroy)
        else:
            self.root.destroy()


def main():
    """Main entry point for the GUI application."""
    root = tk.Tk()
    app = GastosGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
