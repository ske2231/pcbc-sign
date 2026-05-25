@echo off
REM Start the Ponca City Beauty College Document Signing System

cd /d "%~dp0"

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing dependencies...
pip install -q flask

echo.
echo ==========================================
echo   PCBC Document Signing System
echo ==========================================
echo   Opening at: http://localhost:5000
echo   Admin:      admin / ponca2024
echo ==========================================
echo.

python app.py
pause
