#!/usr/bin/env sh
# تشغيل TBT CRM على Mac أو Linux
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Preparing for the first time, please wait..."
  python3 -m venv .venv || exit 1
fi
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt || exit 1
exec .venv/bin/python run.py
