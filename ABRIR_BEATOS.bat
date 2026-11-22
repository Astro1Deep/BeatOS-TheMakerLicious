@echo off
setlocal
set "BEATOS_CODE=%~dp0"
if "%BEATOS_CODE:~-1%"=="\" set "BEATOS_CODE=%BEATOS_CODE:~0,-1%"

if defined BEATOS_VENV_DIR (
  if exist "%BEATOS_VENV_DIR%\Scripts\python.exe" (
    "%BEATOS_VENV_DIR%\Scripts\python.exe" -B "%BEATOS_CODE%\serve_mpc.py" %*
    exit /b %ERRORLEVEL%
  )
)
if exist "%LOCALAPPDATA%\BeatOS\venv\Scripts\python.exe" (
  "%LOCALAPPDATA%\BeatOS\venv\Scripts\python.exe" -B "%BEATOS_CODE%\serve_mpc.py" %*
  exit /b %ERRORLEVEL%
)
if exist "%BEATOS_CODE%\.venv\Scripts\python.exe" (
  "%BEATOS_CODE%\.venv\Scripts\python.exe" -B "%BEATOS_CODE%\serve_mpc.py" %*
  exit /b %ERRORLEVEL%
)
where py >nul 2>&1 && (
  py -3 -B "%BEATOS_CODE%\serve_mpc.py" %*
  exit /b %ERRORLEVEL%
)
python -B "%BEATOS_CODE%\serve_mpc.py" %*
endlocal
