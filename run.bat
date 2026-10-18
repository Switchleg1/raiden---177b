@echo off
rem  raiden_shadow - launcher: prefers the .venv created by install.bat
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    python main.py
    if errorlevel 1 (
        echo.
        echo [hint] pygame is not installed for this interpreter.
        echo        Run install.bat first, then use this script.
    )
)
endlocal
@pause
