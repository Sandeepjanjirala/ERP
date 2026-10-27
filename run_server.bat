@echo off
cd /d "%~dp0"
echo Starting Vidya ERP Local Development Server...
echo Open your browser at http://127.0.0.1:8000/
echo Press Ctrl+C to stop.
echo.
.\.venv\Scripts\python.exe manage.py runserver
pause
