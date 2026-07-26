@echo off
REM agentchattr — starts server (if not running) + Antigravity (agy) wrapper
cd /d "%~dp0.."

REM Pin agy's version — it self-updates and will otherwise drift out from under you
set AGY_CLI_DISABLE_AUTO_UPDATE=1

REM Auto-create venv and install deps on first run
if not exist ".venv" (
    python -m venv .venv
    .venv\Scripts\pip install -q -r requirements.txt >nul 2>nul
)
call .venv\Scripts\activate.bat

REM Pre-flight: check that the agy CLI is installed
where agy >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   Error: "agy" (Antigravity CLI) was not found on PATH.
    echo   Install it first, then try again.
    echo   Note: run "agy" once with no args to sign in before using it here.
    echo.
    pause
    exit /b 1
)

REM Start server if not already running, then wait for it
netstat -ano | findstr :8300 | findstr LISTENING >nul 2>&1
if %errorlevel% neq 0 (
    start "agentchattr server" cmd /c "python run.py"
)
:wait_server
netstat -ano | findstr :8300 | findstr LISTENING >nul 2>&1
if %errorlevel% neq 0 (
    timeout /t 1 /nobreak >nul
    goto :wait_server
)

python wrapper.py antigravity
if %errorlevel% neq 0 (
    echo.
    echo   Agent exited unexpectedly. Check the output above.
    pause
)
