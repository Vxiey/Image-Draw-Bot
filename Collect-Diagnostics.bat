@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0ImageDrawBot.exe" (
 "%~dp0ImageDrawBot.exe" --collect-diagnostics
 goto done
)
if exist "%~dp0..\ImageDrawBot.exe" (
 "%~dp0..\ImageDrawBot.exe" --collect-diagnostics
 goto done
)
if exist "%~dp0.venv\Scripts\python.exe" (
 "%~dp0.venv\Scripts\python.exe" -E -s "%~dp0DiagnosticsPackage.py"
 goto done
)
py -3 -E -s "%~dp0DiagnosticsPackage.py"
:done
set "DIAG_RESULT=%errorlevel%"
if not "%DIAG_RESULT%"=="0" echo Collection failed. Read the message above.
echo Memory dumps are kept separately in LOCALAPPDATA\ImageDrawBot\dumps.
echo Share only the files you choose. Nothing is uploaded automatically.
pause
exit /b %DIAG_RESULT%
