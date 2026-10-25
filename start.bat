@echo off
setlocal
cd /d "%~dp0"
set "PROJECT_ROOT=%~dp0"
set "PYTHON_EXE="

if exist "%PROJECT_ROOT%.venv\Scripts\python.exe" set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%PROJECT_ROOT%.venv312\Scripts\python.exe" set "PYTHON_EXE=%PROJECT_ROOT%.venv312\Scripts\python.exe"

if not defined PYTHON_EXE (
  echo [FrameSutra] Python environment not found.
  echo Create one with: py -3 -m venv .venv
  echo Then install dependencies with: .venv\Scripts\python.exe -m pip install -r Requirements.txt
  goto :fail
)

"%PYTHON_EXE%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
  echo [FrameSutra] Backend packages are missing from the selected Python environment.
  echo Install them with: "%PYTHON_EXE%" -m pip install -r Requirements.txt
  goto :fail
)

where.exe node >nul 2>&1
if errorlevel 1 (
  echo [FrameSutra] Node.js is required for the React interface. Install Node.js and try again.
  goto :fail
)
where.exe npm >nul 2>&1
if errorlevel 1 (
  echo [FrameSutra] npm was not found. Repair or reinstall Node.js, then try again.
  goto :fail
)

if not exist "%PROJECT_ROOT%.env" if exist "%PROJECT_ROOT%.env.example" (
  copy /y "%PROJECT_ROOT%.env.example" "%PROJECT_ROOT%.env" >nul
  echo [FrameSutra] Created .env from .env.example. Add your provider keys before analysis.
)

echo [FrameSutra] Checking local provider and media-tool setup:
"%PYTHON_EXE%" "%PROJECT_ROOT%check_setup.py"
where.exe ffmpeg >nul 2>&1
if errorlevel 1 echo [FrameSutra] FFmpeg was not found. Install it before analyzing media.
where.exe ffprobe >nul 2>&1
if errorlevel 1 echo [FrameSutra] ffprobe was not found. Install it before analyzing media.

if not exist "%PROJECT_ROOT%frontend\node_modules" (
  echo [FrameSutra] Installing the locked web dependencies with npm ci...
  call npm.cmd ci --prefix "%PROJECT_ROOT%frontend"
  if errorlevel 1 goto :npm_failed
)

echo [FrameSutra] Starting the local API and web interface...
start "FrameSutra API" /D "%PROJECT_ROOT%" "%PYTHON_EXE%" -m uvicorn api:app --host 127.0.0.1 --port 8000
start "FrameSutra Web" /D "%PROJECT_ROOT%frontend" cmd /k "npm run dev -- --host 127.0.0.1"
echo.
echo Web app:  http://localhost:5173
echo API docs: http://127.0.0.1:8000/docs
echo Keep both service windows open while using FrameSutra.
timeout /t 2 /nobreak >nul
start "" "http://localhost:5173"
exit /b 0

:npm_failed
echo [FrameSutra] npm could not install the web dependencies. Check the output above and try npm ci in frontend.

:fail
echo.
pause
exit /b 1
