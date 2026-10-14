@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto missing
echo Open http://127.0.0.1:5000 in your regular browser after the server starts.
.venv\Scripts\python.exe -m physics_assistant.web
pause
exit /b
:missing
echo Run setup_windows.cmd first.
pause
exit /b 1
