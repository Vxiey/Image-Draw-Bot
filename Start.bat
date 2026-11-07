@echo off
setlocal
cd /d "%~dp0"
title Image Draw Bot - Startup
set "DRAW_LOG=%TEMP%\ImageDrawBot-start.log"
>"%DRAW_LOG%" echo Image Draw Bot startup log
echo Starting Image Draw Bot. The first launch can take a little longer.
echo Startup log: %DRAW_LOG%
if not exist "SourceStartup.py" goto missing_files
if not exist "DrawBot.py" goto missing_files
if not exist "requirements.txt" goto missing_files
if exist ".venv\Scripts\python.exe" goto existing_venv
py -3 -I -c "import sys; sys.exit(sys.version_info < (3,11))" >>"%DRAW_LOG%" 2>&1
if not errorlevel 1 goto launch_py
python -I -c "import sys; sys.exit(sys.version_info < (3,11))" >>"%DRAW_LOG%" 2>&1
if not errorlevel 1 goto launch_python
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" goto launch_local
echo Python 3.11 or later was not found. Pillow 13 requires Python 3.11+.
echo Install Python and enable "Add python.exe to PATH".
goto error
:existing_venv
".venv\Scripts\python.exe" -E -s SourceStartup.py %* >>"%DRAW_LOG%" 2>&1
goto finished
:launch_py
py -3 -E -s SourceStartup.py %* >>"%DRAW_LOG%" 2>&1
goto finished
:launch_python
python -E -s SourceStartup.py %* >>"%DRAW_LOG%" 2>&1
goto finished
:launch_local
"%LocalAppData%\Programs\Python\Python312\python.exe" -E -s SourceStartup.py %* >>"%DRAW_LOG%" 2>&1
:finished
if errorlevel 1 goto error
echo Image Draw Bot closed normally.
echo Startup log: %DRAW_LOG%
pause
exit /b 0
:missing_files
echo Required files are missing. Extract the ENTIRE ZIP file before starting Image Draw Bot.
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
