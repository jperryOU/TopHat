@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto missing
echo AUTO-SELECTION: Top Hat may save a response immediately when selected.
echo Exact matches with verified prepared answers only. Attendance is manual.
.venv\Scripts\python.exe -m physics_assistant.live --auto-select
pause
exit /b
:missing
echo Run setup_windows.cmd first.
pause
exit /b 1
