#!/usr/bin/env python3
"""
Entry point for the SICAL Gastos Robot GUI

This script launches the Gastos Robot monitoring GUI.
Run this file to start monitoring the Gastos Robot service.

Usage:
    python run_gui.py

For Windows executable:
    pyinstaller gastos_robot.spec
    Then place config.py next to the generated GastosRobot.exe
"""

import sys
import os


def get_application_path():
    """Get the directory where the application is running from."""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable (PyInstaller)
        return os.path.dirname(sys.executable)
    else:
        # Running as script
        return os.path.dirname(os.path.abspath(__file__))


# Ensure the script can find the modules in the current directory
app_path = get_application_path()
sys.path.insert(0, app_path)

# Import config_loader after setting up path
from config_loader import config_exists, get_config_path, init_config

# Check if config.py exists
if not config_exists():
    config_path = get_config_path()
    print("=" * 60)
    print("WARNING: config.py not found!")
    print("=" * 60)
    print()
    print(f"Expected location: {config_path}")
    print()
    print("Please create a config.py file with your RabbitMQ settings.")
    print("You can copy config.py.example and update the values:")
    print()
    if getattr(sys, 'frozen', False):
        print("  Copy config.py.example to the same folder as GastosRobot.exe")
        print("  Rename it to config.py and edit with your credentials.")
    else:
        print("  cp config.py.example config.py")
    print()
    print("Then edit config.py with your actual RabbitMQ credentials.")
    print("=" * 60)
    print()

    try:
        response = input("Do you want to continue anyway? (y/n): ")
        if response.lower() != 'y':
            sys.exit(1)
    except EOFError:
        # Running in non-interactive mode (e.g., windowed exe without console)
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Configuration Missing",
            f"config.py not found!\n\n"
            f"Expected location:\n{config_path}\n\n"
            f"Please create config.py with your RabbitMQ settings."
        )
        sys.exit(1)
else:
    # Initialize config
    init_config()

# Import and run the GUI
from gastos_gui import main

if __name__ == "__main__":
    print("=" * 60)
    print("Starting SICAL Gastos Robot GUI...")
    print("=" * 60)
    print()

    try:
        main()
    except KeyboardInterrupt:
        print("\nGUI closed by user.")
    except Exception as e:
        print(f"\nError starting GUI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
