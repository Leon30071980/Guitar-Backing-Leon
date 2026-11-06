@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  echo Eseguire prima INSTALLA.bat con doppio clic.
  pause
  exit /b 1
)
echo Avvio Guitar Backing Leon 2.66...
echo Non chiudere questa finestra mentre si utilizza il programma.
echo Aprire nel browser: http://127.0.0.1:8765
echo.
".venv\Scripts\python.exe" app.py
if errorlevel 1 (
  echo.
  echo Il programma e terminato con un errore. Copiare il messaggio sopra.
  pause
)
