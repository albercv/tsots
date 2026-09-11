#!/bin/bash
# Reconstruye TheSilenceOfTheShorts.app (lanzador nativo + copia del intérprete +
# icono). Ejecutar tras `brew upgrade python@3.11` o si el bundle no arranca.
set -euo pipefail
cd "$(dirname "$0")/.."
APP="TheSilenceOfTheShorts.app"
PY_REAL="$(readlink -f .venv-clearvoice/bin/python)"            # .../Versions/3.11/bin/python3.11
PY_APP="$(dirname "$(dirname "$PY_REAL")")/Resources/Python.app/Contents/MacOS/Python"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$PY_APP" "$APP/Contents/MacOS/python"
clang -O2 -Wall -o "$APP/Contents/MacOS/TheSilenceOfTheShorts" lanzador/lanzador.c
if [ ! -f "$APP/Contents/Resources/icon.icns" ]; then
    echo "Falta icon.icns: genera icon_1024.png y usa iconutil (ver docs/DESARROLLO.md)" >&2
fi
codesign --force -s - -i com.albercv.thesilenceoftheshorts "$APP/Contents/MacOS/python"
codesign --force -s - -i com.albercv.thesilenceoftheshorts "$APP"
echo "OK: $APP"
