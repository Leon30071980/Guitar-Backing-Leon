@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo =======================================================
echo       GUITAR BACKING LEON 2.66 - INSTALLAZIONE
 echo =======================================================
echo Windows 10/11 x64 e Python 3.11 x64 richiesti.
echo Necessaria una connessione Internet per librerie e modelli AI.
echo Consigliati almeno 10 GB liberi. NON copiare .venv da altri PC.
echo.
py -3.11 -c "import sys; assert sys.maxsize > 2**32" >nul 2>&1
if errorlevel 1 (
 echo ERRORE: Python 3.11 x64 non trovato.
 echo Installare Python 3.11 x64 da https://www.python.org/downloads/
 echo e riavviare questo file.
 goto :fail
)
if not exist ".venv\Scripts\python.exe" (
 echo [1/7] Creo l'ambiente Python...
 py -3.11 -m venv .venv
 if errorlevel 1 goto :fail
)
set "PY=%~dp0.venv\Scripts\python.exe"
echo.
echo [2/7] Aggiorno pip nell'ambiente privato dell'app...
"%PY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo.
echo Scelga il tipo di installazione PyTorch:
echo   1 - NVIDIA GPU (CUDA 12.1, consigliato se driver compatibili)
echo   2 - Solo CPU (funziona anche senza scheda NVIDIA, piu lento)
choice /C 12 /N /M "Premere 1 o 2: "
if errorlevel 2 goto :cpu
:nvidia
echo [3/7] Installa PyTorch e TorchAudio con CUDA...
"%PY%" -m pip install "torch==2.4.1" "torchaudio==2.4.1" --index-url https://download.pytorch.org/whl/cu121
if errorlevel 1 goto :fail
goto :common
:cpu
echo [3/7] Installa PyTorch e TorchAudio per CPU...
"%PY%" -m pip install "torch==2.4.1" "torchaudio==2.4.1" --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto :fail
:common
echo.
echo [4/7] Dipendenze dell'app, Demucs, A^&S e Google Drive...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo [5/7] Whisper per il karaoke...
"%PY%" -m pip install "openai-whisper==20250625"
if errorlevel 1 goto :fail

echo.
echo [6/7] Stable-ts per allineamento parole...
"%PY%" -m pip install --no-deps "stable-ts==2.19.1"
if errorlevel 1 goto :fail

echo.
echo [7/7] Verifica importazione librerie necessarie...
"%PY%" -c "import torch,torchaudio,whisper,stable_whisper,flask,demucs,librosa,imageio_ffmpeg,requests,bs4,googleapiclient; print('PyTorch:',torch.__version__,'; CUDA:',torch.cuda.is_available()); print('Importazione librerie: OK')"
if errorlevel 1 goto :fail

echo.
echo INSTALLAZIONE COMPLETATA.
echo Facoltativo: copiare credenziali_desktop.json e fare doppio clic su COLLEGA_GOOGLE_DRIVE.bat.
echo Infine avviare AVVIA.bat.
pause
exit /b 0
:fail
echo.
echo INSTALLAZIONE NON COMPLETATA: vedere il messaggio sopra.
echo Copiare il log prima di chiudere questa finestra.
pause
exit /b 1
