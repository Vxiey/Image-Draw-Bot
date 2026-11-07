@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Image Draw Bot .venv was not found. Run Start.bat first.
  pause
  exit /b 2
)
echo Detecting AMD / Intel GPU and installing the optional OpenCL benchmark backend...
".venv\Scripts\python.exe" -E -s AutoUniversalGpuSetup.py --ensure --force
if errorlevel 1 (
  echo.
  echo Universal GPU setup could not be completed. Image Draw Bot can still use CPU fallback.
) else (
  echo.
  echo Universal GPU benchmark backend is ready.
)
pause
