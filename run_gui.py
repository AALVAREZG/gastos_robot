#!/usr/bin/env python3
"""
Entry point for the SICAL Gastos Robot GUI

This script launches the Gastos Robot monitoring GUI.
Run this file to start monitoring the Gastos Robot service.

Usage:
    python run_gui.py
"""

import sys
import os

# Ensure the script can find the modules in the current directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Check if config.py exists
if not os.path.exists(os.path.join(os.path.dirname(__file__), 'config.py')):
    print("=" * 60)
    print("WARNING: config.py not found!")
    print("=" * 60)
    print()
    print("Please create a config.py file with your RabbitMQ settings.")
    print("You can copy config.py.example and update the values:")
    print()
    print("  cp config.py.example config.py")
    print()
    print("Then edit config.py with your actual RabbitMQ credentials.")
    print("=" * 60)
    print()

    response = input("Do you want to continue anyway? (y/n): ")
    if response.lower() != 'y':
        sys.exit(1)

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
