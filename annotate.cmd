@echo off
setlocal
cd /d "%~dp0"
if exist "D:\AI\bin\aienv.cmd" call "D:\AI\bin\aienv.cmd"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m osuneu.desktop %*
) else (
  uv run --no-project --python 3.14 --with PySide6==6.10.2 python -m osuneu.desktop %*
)
pause
