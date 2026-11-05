@echo off
setlocal
cd /d "%~dp0"
title Image Draw Bot - Startup
set "DRAW_LOG=%TEMP%\ImageDrawBot-start.log"
set "PYTHONFAULTHANDLER=1"
set "PYTHONUNBUFFERED=1"
>"%DRAW_LOG%" echo Image Draw Bot startup log
echo Starting Image Draw Bot. The first launch can take a little longer.
echo Startup log: %DRAW_LOG%
if not exist "DrawBot.py" goto missing_files
if not exist "requirements.txt" goto missing_files
if exist ".venv\Scripts\python.exe" goto dependencies
py -3 -c "import sys; sys.exit(sys.version_info < (3,11))" >>"%DRAW_LOG%" 2>&1
if not errorlevel 1 goto create_py
python -c "import sys; sys.exit(sys.version_info < (3,11))" >>"%DRAW_LOG%" 2>&1
if not errorlevel 1 goto create_python
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" goto create_local
echo Python 3.11 or later was not found. Pillow 13 requires Python 3.11+.
echo Install Python and enable "Add python.exe to PATH".
goto error
:create_py
echo Creating Python environment...
py -3 -m venv .venv >>"%DRAW_LOG%" 2>&1
goto check_venv
:create_python
echo Creating Python environment...
python -m venv .venv >>"%DRAW_LOG%" 2>&1
goto check_venv
:create_local
echo Using the local Python 3.12 installation...
"%LocalAppData%\Programs\Python\Python312\python.exe" -m venv .venv >>"%DRAW_LOG%" 2>&1
:check_venv
if errorlevel 1 goto error
:dependencies
echo Checking Python...
".venv\Scripts\python.exe" -c "import sys; print(sys.executable); print(sys.version); sys.exit(sys.version_info < (3,11))" >>"%DRAW_LOG%" 2>&1
if errorlevel 1 goto unsupported_python
if /i "%~1"=="--update" goto install_dependencies
if not exist ".venv\installed-requirements.txt" goto install_dependencies
fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>&1
if errorlevel 1 goto install_dependencies
".venv\Scripts\python.exe" -c "import PIL, requests, keyboard, tkinterdnd2, customtkinter" >>"%DRAW_LOG%" 2>&1
if errorlevel 1 goto install_dependencies
".venv\Scripts\python.exe" -m pip check >>"%DRAW_LOG%" 2>&1
if errorlevel 1 goto install_dependencies
goto gpu_dependencies
:install_dependencies
echo Updating pip. Internet access is required...
".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check --timeout 20 --retries 1 >>"%DRAW_LOG%" 2>&1
if errorlevel 1 echo pip could not be updated. Continuing with the installed version.
echo Checking and installing packages. Internet access is required...
".venv\Scripts\python.exe" -m pip install --upgrade --upgrade-strategy eager --disable-pip-version-check --timeout 20 --retries 1 -r requirements.txt >>"%DRAW_LOG%" 2>&1
if errorlevel 1 goto error
copy /y requirements.txt ".venv\installed-requirements.txt" >nul
:gpu_dependencies
rem Optional GPU installation is explicit; normal startup uses installed backends.
if /i "%~1"=="--update" goto setup_optional_gpu
if /i "%~1"=="--gpu" goto setup_optional_gpu
goto launch
:setup_optional_gpu
rem Image Draw Bot owns its CUDA runtime inside .venv. On NVIDIA systems the
rem bootstrap detects hardware first, tests a real CUDA kernel, and only then
rem installs/repairs CuPy + matched NVIDIA runtime/NVRTC/header wheels.
echo Checking NVIDIA GPU acceleration...
if /i "%~1"=="--update" (
  ".venv\Scripts\python.exe" AutoGpuSetup.py --ensure --force >>"%DRAW_LOG%" 2>&1
) else (
  ".venv\Scripts\python.exe" AutoGpuSetup.py --ensure >>"%DRAW_LOG%" 2>&1
)
if errorlevel 1 goto gpu_warning
if exist ".venv\gpu-install-failed.marker" del /q ".venv\gpu-install-failed.marker" >nul 2>&1
goto universal_gpu_dependencies
:gpu_warning
echo NVIDIA GPU was detected, but automatic CUDA setup could not be completed.
echo Image Draw Bot will open with CPU fallback. Run Start.bat --gpu to retry GPU setup.
:universal_gpu_dependencies
rem AMD/Intel use the vendor driver OpenCL runtime. PyOpenCL is installed only
rem inside Image Draw Bot's .venv and only when AMD/Intel hardware is detected.
echo Checking AMD / Intel GPU benchmark backend...
if /i "%~1"=="--update" (
  ".venv\Scripts\python.exe" AutoUniversalGpuSetup.py --ensure --force >>"%DRAW_LOG%" 2>&1
) else (
  ".venv\Scripts\python.exe" AutoUniversalGpuSetup.py --ensure >>"%DRAW_LOG%" 2>&1
)
if errorlevel 1 echo Optional AMD/Intel OpenCL benchmark backend is unavailable; CPU fallback remains enabled.
:launch
echo Opening Image Draw Bot...
".venv\Scripts\python.exe" -X faulthandler -u DrawBot.py >>"%DRAW_LOG%" 2>&1
if errorlevel 1 goto error
echo Image Draw Bot closed normally.
echo Startup log: %DRAW_LOG%
pause
exit /b 0
:missing_files
echo Required files are missing. Extract the ENTIRE ZIP file before starting Image Draw Bot.
goto error
:unsupported_python
echo This environment needs Python 3.11 or later for the security-fixed Pillow 13.
echo Install Python 3.11+, rename the .venv folder, and run Start.bat again.
goto error
:error
echo.
echo STARTUP FAILED. The recorded output follows:
type "%DRAW_LOG%"
echo.
echo Create a local Diagnostics ZIP from Tools, or inspect these files:
echo %DRAW_LOG%
echo %~dp0logs\ImageDrawBot-crash.log
echo %~dp0logs\ImageDrawBot-session.log
echo %~dp0logs\ImageDrawBot-mouse-probe.log
echo For a hard crash, run Enable-Crash-Dumps.bat and reproduce the issue.
pause
exit /b 1
