@echo off
setlocal
cd /d "%~dp0"
title ApexQuant-XAU

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ was not found. Install it from python.org and tick "Add to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
  echo Creating virtual environment...
  python -m venv .venv
)
call ".venv\Scripts\activate.bat"

if not exist ".venv\deps_ok.flag" (
  echo Installing dependencies...
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  if errorlevel 1 (
    echo Dependency install failed.
    pause
    exit /b 1
  )
  echo ok> ".venv\deps_ok.flag"
)

if not exist ".env" copy ".env.example" ".env" >nul

REM Skip Streamlit's first-run email prompt
set "SCRED=%USERPROFILE%\.streamlit\credentials.toml"
if not exist "%SCRED%" (
  if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
  > "%SCRED%" echo [general]
  >> "%SCRED%" echo email = ""
)

set "PORT=8501"
for /f "tokens=2 delims==" %%a in ('findstr /b "DASHBOARD_PORT=" ".env"') do set "PORT=%%a"

echo Starting dashboard on http://localhost:%PORT% ...
streamlit run app.py --server.port %PORT% --browser.gatherUsageStats false
pause
