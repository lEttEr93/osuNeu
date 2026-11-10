@echo off
setlocal
cd /d "%~dp0"
if exist "D:\AI\bin\aienv.cmd" call "D:\AI\bin\aienv.cmd"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m osuneu.annotator %*
) else (
  uv run --no-project --python 3.14 python -m osuneu.annotator %*
)
pause
