@echo off
setlocal
cd /d "%~dp0"
title Image Draw Bot - Build v1 release

echo ============================================================
echo Image Draw Bot - Windows release build
echo ============================================================
echo This runs tests, builds ImageDrawBot.exe and creates a release ZIP.
echo If Inno Setup 6 is installed, it can also create a per-user installer.
echo.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 || goto nopython
  set "PY=python"
)
%PY% -c "import sys; sys.exit(sys.version_info < (3,11))"
if errorlevel 1 goto nopython

set "INSTALLER="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "INSTALLER=--installer"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "INSTALLER=--installer"

%PY% build_release.py %INSTALLER%
if errorlevel 1 goto failed

echo.
echo Release complete. Open the release folder for ZIP, hashes and Setup EXE if available.
start "" "%~dp0release"
pause
exit /b 0

:nopython
echo Python 3.11+ was not found. Install Python and enable Add Python to PATH.
pause
exit /b 2

:failed
echo.
echo Release build failed. Read the error above.
pause
exit /b 1
