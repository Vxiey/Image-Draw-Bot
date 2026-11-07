@echo off
setlocal
cd /d "%~dp0"
echo Native crash dump configuration requires administrator rights.
echo Start the drawing application normally after this setup.
if exist "%~dp0ImageDrawBot.exe" (
 "%~dp0ImageDrawBot.exe" --configure-crash-dumps enable
 goto done
)
if exist "%~dp0..\ImageDrawBot.exe" (
 "%~dp0..\ImageDrawBot.exe" --configure-crash-dumps enable
 goto done
)
if exist "%~dp0.venv\Scripts\python.exe" (
 "%~dp0.venv\Scripts\python.exe" -E -s "%~dp0CrashDumpConfig.py" enable --include-python
 goto done
)
py -3 -E -s "%~dp0CrashDumpConfig.py" enable --include-python
:done
set "DUMP_RESULT=%errorlevel%"
if not "%DUMP_RESULT%"=="0" echo Setup FAILED. Read the error above.
pause
exit /b %DUMP_RESULT%
