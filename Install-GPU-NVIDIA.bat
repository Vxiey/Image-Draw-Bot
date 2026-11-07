@echo off
setlocal
cd /d "%~dp0"
title Image Draw Bot - NVIDIA CUDA Auto Setup
echo ============================================================
echo Image Draw Bot - Automatic NVIDIA CUDA / GPU setup
echo ============================================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo Image Draw Bot environment was not found.
  echo Run Start.bat once first so the local Python environment can be created.
  pause
  exit /b 1
)
echo Detecting NVIDIA hardware and installing/repairing CUDA acceleration...
".venv\Scripts\python.exe" -E -s SourceStartup.py --setup-gpu nvidia --force --require-nvidia
if errorlevel 1 goto :fail
if exist ".venv\gpu-install-failed.marker" del /q ".venv\gpu-install-failed.marker" >nul 2>&1
echo.
echo NVIDIA CUDA acceleration is ready.
echo Start Image Draw Bot and use Detect / benchmark NVIDIA GPU to verify performance.
pause
exit /b 0
:fail
echo.
echo Automatic NVIDIA CUDA setup did not complete.
echo Image Draw Bot can still run with CPU fallback.
echo Retry this installer after closing Image Draw Bot, or run Start.bat --gpu.
pause
exit /b 1
