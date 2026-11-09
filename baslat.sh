#!/usr/bin/env bash
# Klipal — macOS / Linux başlatıcı
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "İlk kurulum yapılıyor, birkaç dakika sürebilir..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
else
  .venv/bin/python -m pip install -q --upgrade -r requirements.txt || true
fi
OPEN_BROWSER=1 exec .venv/bin/python app.py
