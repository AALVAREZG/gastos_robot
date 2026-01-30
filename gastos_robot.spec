# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for SICAL Gastos Robot

Usage:
    pyinstaller gastos_robot.spec

This creates a Windows executable that:
- Looks for config.py in the same directory as the .exe
- Bundles all required dependencies
- Creates a single .exe file (--onefile mode)

IMPORTANT: Place your config.py in the same folder as the generated .exe
"""

import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Collect all submodules for RPA libraries
hiddenimports = [
    # Core imports
    'pika',
    'pika.adapters',
    'pika.adapters.blocking_connection',

    # RPA Framework
    'RPA',
    'RPA.Windows',
    'RPA.Windows.keywords',
    'RPA.core',

    # Robocorp
    'robocorp',
    'robocorp.windows',
    'robocorp.windows._vendored',
    'robocorp.windows._vendored.uiautomation',

    # COM support for Windows automation
    'comtypes',
    'comtypes.client',
    'comtypes.gen',

    # UI
    'tkinter',
    'tkinter.ttk',
    'tkinter.messagebox',
    'tkinter.filedialog',

    # Database
    'sqlite3',

    # Other dependencies
    'PIL',
    'PIL.Image',
    'tenacity',
    'dotenv',

    # Project modules
    'config',
    'gastos_gui',
    'gasto_task_consumer',
    'sical_base',
    'sical_config',
    'sical_constants',
    'sical_logging',
    'sical_utils',
    'sical_security',
    'status_manager',
    'task_history_db',
    'processors',
    'processors.ado220_processor',
    'processors.pmp450_processor',
    'processors.ordenar_tasks',
]

# Collect additional submodules
hiddenimports += collect_submodules('pika')
hiddenimports += collect_submodules('comtypes')

# Data files to include
datas = [
    # Include config.py.example as reference
    ('config.py.example', '.'),
]

# Binary files (DLLs, etc.)
binaries = []

a = Analysis(
    ['run_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'IPython',
        'jupyter',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GastosRobot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to True if you want to see console output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add path to .ico file: icon='icon.ico'
)
