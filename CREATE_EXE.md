Building the Windows Executable
Step 1: On Windows, activate your venv and install PyInstaller
.\venv\Scripts\activate
pip install pyinstaller

Step 2: Build the executable
pyinstaller gastos_robot.spec

Step 3: The output
The executable will be created at:

dist/GastosRobot.exe

Step 4: Deploy with config
When distributing, place these files together:

📁 Your folder/
├── GastosRobot.exe      # The executable
└── config.py            # Your RabbitMQ credentials (create from config.py.example)

How config.py Works
Scenario	Config Location
Running python run_gui.py	config.py in project directory
Running GastosRobot.exe	config.py in same folder as the .exe
The executable looks for config.py next to itself, so users can update RabbitMQ credentials without rebuilding.

Files Created
File	Purpose
gastos_robot.spec	PyInstaller build configuration
config_loader.py	Handles config loading for both script and frozen exe