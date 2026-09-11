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
if [ ! -f "$APP/Contents/Resources/icon.icns" ] || [ docs/img/icon.png -nt "$APP/Contents/Resources/icon.icns" ]; then
    TMP_ICONO="$(mktemp -d)"
    .venv-clearvoice/bin/python lanzador/generar_icono.py docs/img/icon.png "$TMP_ICONO" >/dev/null
    iconutil -c icns "$TMP_ICONO/icon.iconset" -o "$APP/Contents/Resources/icon.icns"
    rm -rf "$TMP_ICONO"
fi
# Catálogos de traducción compilados (.mo) a partir de los .po del repo.
lanzador/traducir.sh --solo-mo >/dev/null
codesign --force -s - -i com.albercv.thesilenceoftheshorts "$APP/Contents/MacOS/python"
codesign --force -s - -i com.albercv.thesilenceoftheshorts "$APP"
echo "OK: $APP"
