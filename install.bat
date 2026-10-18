@echo off
rem ---------------------------------------------------------------------------
rem  raiden_shadow - dependency installer
rem  Creates a local virtual environment (.venv) if one does not already exist,
rem  then installs everything from requirements.txt into it.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "PY=python"
where %PY% >nul 2>&1
if errorlevel 1 (
    set "PY=py -3"
    %PY% --version >nul 2>&1
    if errorlevel 1 (
        echo [error] Python 3.12+ was not found on PATH.
        echo         Install it from https://www.python.org/downloads/ and re-run this script.
        pause
        exit /b 1
    )
)

echo [info] using: %PY%
%PY% --version

if not exist ".venv\Scripts\python.exe" (
    echo [info] creating virtual environment .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [error] could not create the virtual environment.
        pause
        exit /b 1
    )
)

set "VPY=.venv\Scripts\python.exe"

echo [info] upgrading pip ...
"%VPY%" -m pip install --upgrade pip

echo [info] installing requirements.txt ...
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [error] dependency installation failed.
    pause
    exit /b 1
)

echo.
echo [ok] dependencies installed. Start the game with run.bat, or:
echo        .venv\Scripts\python.exe main.py
endlocal
@pause
