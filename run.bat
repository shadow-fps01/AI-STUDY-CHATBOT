@echo off
cd /d "%~dp0"
echo ===================================================
echo   StudyMaster AI - Commercial Platform Server
echo ===================================================
echo.
set PORT=8080
if not "%~1"=="" set PORT=%~1

echo Dashboard URL : http://127.0.0.1:%PORT%
echo Swagger Docs  : http://127.0.0.1:%PORT%/docs
echo.
echo Starting FastAPI application with Uvicorn on port %PORT%...
echo.

if exist "C:\Users\User\miniconda3\envs\langagent\Scripts\uvicorn.exe" (
    "C:\Users\User\miniconda3\envs\langagent\Scripts\uvicorn.exe" api1:app --reload --host 127.0.0.1 --port %PORT%
) else if exist ".venv\Scripts\uvicorn.exe" (
    ".venv\Scripts\uvicorn.exe" api1:app --reload --host 127.0.0.1 --port %PORT%
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m uvicorn api1:app --reload --host 127.0.0.1 --port %PORT%
) else (
    python -m uvicorn api1:app --reload --host 127.0.0.1 --port %PORT%
)

if errorlevel 1 (
    echo.
    echo ===================================================
    echo Server stopped or encountered an error.
    echo ===================================================
    pause
)
