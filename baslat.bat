@echo off
title Klipal - BU PENCEREYI KAPATMAYIN
cd /d "%~dp0"

echo.
echo   Klipal baslatiliyor...
echo.

rem --- 1) Python ---
set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY (
  py -3 --version >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  echo [!] Python bulunamadi. Simdi kuruluyor...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo.
  echo Python kuruldu. Bu pencereyi KAPATIP baslat.bat dosyasini tekrar calistirin.
  echo Kurulum olmadiysa: https://www.python.org/downloads/ adresinden kurun,
  echo kurulumda "Add Python to PATH" kutusunu isaretleyin.
  pause
  exit /b 1
)

rem --- 2) Sanal ortam ve paketler (ilk kurulum birkac dakika surebilir) ---
if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Ilk kurulum yapiliyor, birkac dakika surebilir...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [HATA] Sanal ortam olusturulamadi.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [HATA] Paketler kurulamadi. Internet baglantisini kontrol edip tekrar deneyin.
    rmdir /s /q .venv
    pause
    exit /b 1
  )
) else (
  echo [1/2] Video indirme motoru guncelleniyor...
  ".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check --retries 1 --timeout 15 --upgrade -r requirements.txt
)

rem --- 3) Sunucu ---
echo [2/2] Sunucu aciliyor. Tarayici kendiliginden acilacak.
set OPEN_BROWSER=1
".venv\Scripts\python.exe" app.py

echo.
echo [!] Sunucu durdu. Yukaridaki mesajin ekran goruntusunu alin.
pause
