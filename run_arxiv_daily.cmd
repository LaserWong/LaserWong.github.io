@echo off
setlocal
set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "REQ=%ROOT%requirements.txt"
set "SCRIPT=%ROOT%tools\generate_arxiv_portal.py"
set "BOOTSTRAP="

call :log "[arXiv Daily] Starting..."

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if %errorlevel%==0 set "BOOTSTRAP=py -3"
)
if not defined BOOTSTRAP (
  where python >nul 2>nul
  if %errorlevel%==0 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if %errorlevel%==0 set "BOOTSTRAP=python"
  )
)

if not defined BOOTSTRAP (
  call :log "[arXiv Daily] Python 3.10+ not found. Attempting installation..."
  where winget >nul 2>nul
  if %errorlevel%==0 (
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
  ) else (
    where choco >nul 2>nul
    if %errorlevel%==0 (
      choco install python -y
    ) else (
      call :log "[arXiv Daily] Could not auto-install Python. Please install Python 3.10+ manually."
      pause
      exit /b 1
    )
  )
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if %errorlevel%==0 set "BOOTSTRAP=py -3"
  )
  if not defined BOOTSTRAP (
    where python >nul 2>nul
    if %errorlevel%==0 (
      python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
      if %errorlevel%==0 set "BOOTSTRAP=python"
    )
  )
)

if not defined BOOTSTRAP (
  call :log "[arXiv Daily] Python bootstrap still unavailable."
  pause
  exit /b 1
)

if exist "%VENV%\Scripts\python.exe" (
  "%VENV%\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if %errorlevel% neq 0 rmdir /s /q "%VENV%"
)
if not exist "%VENV%\Scripts\python.exe" (
  call :log "[arXiv Daily] Creating local virtual environment..."
  call %BOOTSTRAP% -m venv "%VENV%"
  if %errorlevel% neq 0 (
    call :log "[arXiv Daily] Failed to create virtual environment."
    pause
    exit /b 1
  )
)

call :log "[arXiv Daily] Installing / updating dependencies..."
call "%VENV%\Scripts\python.exe" -m ensurepip --upgrade >nul 2>nul
call "%VENV%\Scripts\python.exe" -m pip install --upgrade pip
if %errorlevel% neq 0 (
  call :log "[arXiv Daily] Failed to upgrade pip."
  pause
  exit /b 1
)
call "%VENV%\Scripts\python.exe" -m pip install -r "%REQ%"
if %errorlevel% neq 0 (
  call :log "[arXiv Daily] Dependency installation failed."
  pause
  exit /b 1
)

call :log "[arXiv Daily] Running both archive generators..."
call "%VENV%\Scripts\python.exe" -u "%SCRIPT%" %*
if %errorlevel% neq 0 (
  echo.
  call :log "[arXiv Daily] Generation failed."
  pause
  exit /b 1
)

echo.
call :log "[arXiv Daily] Generation finished."
if exist "%ROOT%index.html" (
  call :log "[arXiv Daily] Opening portal page..."
  start "" "%ROOT%index.html"
)
exit /b 0

:log
echo %~1
exit /b 0

