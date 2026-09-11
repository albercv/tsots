#!/bin/bash
# Desinstala The Silence of the Shorts de este Mac.
#
# Borra: el entorno Python (.venv-clearvoice), la app construida
# (TheSilenceOfTheShorts.app/Contents/MacOS), los logs, los intermedios de
# audio_procesado/ y la entrada del Dock. Conserva: el código, el checkpoint
# descargado (checkpoints/) y tus vídeos. No toca Homebrew ni Ollama.
set -euo pipefail
cd "$(dirname "$0")"

echo "Se va a desinstalar The Silence of the Shorts de esta carpeta:"
echo "  $(pwd)"
read -r -p "¿Continuar? [s/N] " respuesta
[[ "${respuesta:-n}" =~ ^[sS]$ ]] || { echo "Cancelado."; exit 0; }

rm -rf .venv-clearvoice TheSilenceOfTheShorts.app/Contents/MacOS logs audio_procesado
echo "Entorno, app, logs e intermedios borrados."

# Entrada del Dock (si existe).
python3 - <<'EOF'
import plistlib, subprocess
try:
    datos = plistlib.loads(subprocess.check_output(["defaults", "export", "com.apple.dock", "-"]))
except Exception:
    raise SystemExit(0)
apps = datos.get("persistent-apps", [])
filtradas = [a for a in apps if "TheSilenceOfTheShorts.app" not in
             a.get("tile-data", {}).get("file-data", {}).get("_CFURLString", "")]
if len(filtradas) != len(apps):
    datos["persistent-apps"] = filtradas
    subprocess.run(["defaults", "import", "com.apple.dock", "-"], input=plistlib.dumps(datos), check=True)
    subprocess.run(["killall", "Dock"])
    print("Entrada del Dock eliminada.")
EOF

echo
echo "Para quitar también los ajustes guardados (marca, modelo, carpeta de salida):"
echo "  defaults delete com.albercv.LimpiadorVideo"
echo "Para quitar el modelo de Ollama:  ollama rm qwen3.5:9b"
echo "Para quitar las herramientas:     brew uninstall auto-editor ffmpeg-full ffmpeg"
