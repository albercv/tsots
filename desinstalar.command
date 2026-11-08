#!/bin/bash
# Desinstala The Silence of the Shorts de este Mac.
#
# Borra: el entorno Python (.venv-clearvoice), la app construida
# (TheSilenceOfTheShorts.app/Contents/MacOS), los logs, los intermedios de
# audio_procesado/, las fichas de fichas/ (lo que la app recuerda de cada vídeo:
# audio limpio, base, transcripción, y la versión anterior de un resultado antiguo
# que la app sobrescribió), la entrada del Dock y el agente del blog (launchd).
# Conserva: el código, el checkpoint descargado (checkpoints/), tus vídeos
# actuales, con sus .md y .srt, y ~/TSOTS/blog.
# No toca Homebrew ni Ollama.
set -euo pipefail
cd "$(dirname "$0")"

echo "Se va a desinstalar The Silence of the Shorts de esta carpeta:"
echo "  $(pwd)"
read -r -p "¿Continuar? [s/N] " respuesta
[[ "${respuesta:-n}" =~ ^[sS]$ ]] || { echo "Cancelado."; exit 0; }

rm -rf .venv-clearvoice TheSilenceOfTheShorts.app/Contents/MacOS logs audio_procesado fichas
echo "Entorno, app, logs, intermedios y fichas borrados."

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

# Agente del blog (si existe). ~/TSOTS/blog se conserva.
PLIST_BLOG="$HOME/Library/LaunchAgents/com.tsots.blog.plist"
if [ -f "$PLIST_BLOG" ]; then
    launchctl bootout "gui/$(id -u)/com.tsots.blog" 2>/dev/null || true
    rm -f "$PLIST_BLOG"
    echo "Agente del blog eliminado (~/TSOTS/blog se conserva)."
fi

echo
echo "Para quitar también los ajustes guardados (marca, modelo, carpeta de salida):"
echo "  defaults delete com.albercv.LimpiadorVideo"
echo "Para quitar el modelo de Ollama:  ollama rm qwen3.5:9b"
echo "Para quitar las herramientas:     brew uninstall auto-editor ffmpeg-full ffmpeg"
