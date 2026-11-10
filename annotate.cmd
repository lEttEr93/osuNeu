@echo off
setlocal
cd /d "%~dp0"
if exist "D:\AI\bin\aienv.cmd" call "D:\AI\bin\aienv.cmd"
if not exist "%~dp0.venv\Scripts\python.exe" goto bootstrap
"%~dp0.venv\Scripts\python.exe" -u -m osuneu.desktop %*
goto done
:bootstrap
uv run --no-project --python 3.14 --with PySide6==6.10.2 python -u -m osuneu.desktop %*
:done
if errorlevel 1 echo osu!neu failed. See the startup log path printed above.
pause
