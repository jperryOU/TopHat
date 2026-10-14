@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto missing
.venv\Scripts\python.exe -m physics_assistant.live
pause
exit /b
:missing
echo Run setup_windows.cmd first.
pause
exit /b 1
