#!/bin/bash
# Instalador de The Silence of the Shorts para macOS (Apple Silicon).
#
# Doble clic desde el Finder o `./instalar.command` en Terminal. Se puede
# ejecutar tantas veces como haga falta: cada paso comprueba si ya está hecho.
#
# Opciones (variables de entorno):
#   SIN_OLLAMA=1     no instala Ollama ni descarga el modelo (sin Caption SEO)
#   SIN_DOCK=1       no añade la app al Dock
#   MODELO_OLLAMA=…  modelo a descargar (por defecto qwen3.5:9b)
set -euo pipefail
cd "$(dirname "$0")"
PROYECTO="$(pwd)"
MODELO_OLLAMA="${MODELO_OLLAMA:-qwen3.5:9b}"

# Mensajes en español o inglés según el idioma del sistema (o TSOTS_LANG).
case "${TSOTS_LANG:-${LC_ALL:-${LANG:-es}}}" in en*) EN=1 ;; *) EN= ;; esac
t() { if [ -n "$EN" ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

paso() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m    ✓ %s\033[0m\n' "$*"; }
fallo() { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- requisitos
paso "$(t "Comprobando el Mac" "Checking the Mac")"
[ "$(uname -s)" = "Darwin" ] || fallo "$(t "Este instalador es solo para macOS." "This installer is for macOS only.")"
[ "$(uname -m)" = "arm64" ] || fallo "$(t "Se necesita un Mac con Apple Silicon (M1 o posterior)." "An Apple Silicon Mac (M1 or later) is required.") $(uname -m)"
VERSION_MACOS="$(sw_vers -productVersion)"
[ "${VERSION_MACOS%%.*}" -ge 13 ] || fallo "$(t "Se necesita macOS 13 o posterior" "macOS 13 or later is required") ($VERSION_MACOS)"
ok "Apple Silicon, macOS $VERSION_MACOS"

paso "$(t "Herramientas de línea de comandos de Xcode" "Xcode Command Line Tools")"
if ! xcode-select -p >/dev/null 2>&1; then
    echo "    $(t "macOS va a mostrar un diálogo para instalarlas. Acepta, espera a que termine y vuelve a ejecutar este instalador." "macOS will show a dialog to install them. Accept, wait for it to finish and run this installer again.")"
    xcode-select --install || true
    exit 1
fi
ok "$(t "instaladas en" "installed at") $(xcode-select -p)"

paso "Homebrew"
if [ -x /opt/homebrew/bin/brew ]; then
    ok "$(t "ya instalado" "already installed")"
else
    echo "    $(t "Se instala Homebrew (pide tu contraseña de usuario)." "Installing Homebrew (asks for your user password).")"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
eval "$(/opt/homebrew/bin/brew shellenv)"

paso "$(t "Python 3.11, ffmpeg, ffmpeg-full y auto-editor (Homebrew)" "Python 3.11, ffmpeg, ffmpeg-full and auto-editor (Homebrew)")"
brew install python@3.11 ffmpeg ffmpeg-full auto-editor gettext
ok "$(/opt/homebrew/opt/python@3.11/bin/python3.11 --version), $(ffmpeg -version | head -1 | cut -d' ' -f1-3), auto-editor $(auto-editor --version)"

if [ -z "${SIN_OLLAMA:-}" ]; then
    paso "$(t "Ollama (modelo local para el caption SEO)" "Ollama (local model for the SEO caption)")"
    if [ -d /Applications/Ollama.app ] || command -v ollama >/dev/null 2>&1; then
        ok "$(t "ya instalado" "already installed")"
    else
        brew install --cask ollama-app
    fi
    OLLAMA_BIN="$(command -v ollama || echo /Applications/Ollama.app/Contents/Resources/ollama)"
    if [ ! -x "$OLLAMA_BIN" ]; then
        echo "    $(t "No se encuentra el ejecutable 'ollama'; abre la app de Ollama una vez y vuelve a ejecutar." "The 'ollama' executable was not found; open the Ollama app once and run again.")"
    else
        [ -d /Applications/Ollama.app ] && open -g -a Ollama || true
        # Espera a que el servidor responda (la app tarda unos segundos).
        for _ in $(seq 1 30); do
            curl -s -m 1 localhost:11434/api/version >/dev/null && break
            sleep 1
        done
        if "$OLLAMA_BIN" list 2>/dev/null | awk '{print $1}' | grep -qx "$MODELO_OLLAMA"; then
            ok "$(t "modelo" "model") $MODELO_OLLAMA $(t "ya descargado" "already downloaded")"
        else
            echo "    $(t "Descargando" "Downloading") $MODELO_OLLAMA (~6 GB, $(t "una sola vez" "one time only"))…"
            "$OLLAMA_BIN" pull "$MODELO_OLLAMA"
        fi
    fi
fi

# ------------------------------------------------------------- entorno Python
paso "$(t "Entorno Python" "Python environment") (.venv-clearvoice)"
PY=/opt/homebrew/opt/python@3.11/bin/python3.11
if [ -x .venv-clearvoice/bin/python ] && .venv-clearvoice/bin/python -c "import PySide6, torch, clearvoice, faster_whisper" 2>/dev/null; then
    ok "$(t "ya creado y completo" "already created and complete")"
else
    rm -rf .venv-clearvoice
    "$PY" -m venv .venv-clearvoice
    .venv-clearvoice/bin/python -m pip install --quiet --upgrade pip
    echo "    $(t "Instalando dependencias (torch, PySide6, ClearVoice… ~2,5 GB; varios minutos)…" "Installing dependencies (torch, PySide6, ClearVoice… ~2.5 GB; several minutes)…")"
    .venv-clearvoice/bin/python -m pip install --quiet -r requirements.txt
    .venv-clearvoice/bin/python -m pip install --quiet -e .
    ok "$(t "dependencias instaladas" "dependencies installed")"
fi

paso "$(t "Modelo de limpieza de audio" "Audio cleaning model") (MossFormer2_SE_48K, 221 MB)"
if [ -f checkpoints/MossFormer2_SE_48K/last_best_checkpoint.pt ]; then
    ok "$(t "ya descargado" "already downloaded")"
else
    .venv-clearvoice/bin/python - <<'EOF'
from huggingface_hub import snapshot_download
snapshot_download(repo_id="alibabasglab/MossFormer2_SE_48K",
                  local_dir="checkpoints/MossFormer2_SE_48K")
print("    descargado")
EOF
fi

# --------------------------------------------------------------------- la app
paso "$(t "Construyendo" "Building") TheSilenceOfTheShorts.app"
chmod +x lanzador/construir_app.sh TheSilenceOfTheShorts.command desinstalar.command
lanzador/construir_app.sh >/dev/null
ok "$(t "app lista en" "app ready at") $PROYECTO/TheSilenceOfTheShorts.app"

if [ -z "${SIN_DOCK:-}" ]; then
    paso "$(t "Acceso directo en el Dock" "Dock shortcut")"
    APP_URL="file://$PROYECTO/TheSilenceOfTheShorts.app/"
    if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "TheSilenceOfTheShorts.app"; then
        ok "$(t "ya estaba en el Dock" "already in the Dock")"
    else
        defaults write com.apple.dock persistent-apps -array-add "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$APP_URL</string><key>_CFURLStringType</key><integer>15</integer></dict></dict><key>tile-type</key><string>file-tile</string></dict>"
        killall Dock
        ok "$(t "añadido" "added")"
    fi
fi

paso "$(t "Comprobación final" "Final check")"
.venv-clearvoice/bin/python - <<'EOF'
import shutil
faltan = [b for b in ("ffmpeg", "ffprobe", "auto-editor") if shutil.which(b) is None]
assert not faltan, f"faltan en PATH: {faltan}"
import app, videopipeline.pipeline  # importa toda la app
print("    todo importa correctamente")
EOF

echo
printf '\033[1;32m%s\033[0m %s\n' "$(t "Instalación completa." "Installation complete.")" "$(t "Abre \"The Silence of the Shorts\" desde el Dock o con doble clic en TheSilenceOfTheShorts.app. Guía de uso: README.es.md" "Open \"The Silence of the Shorts\" from the Dock or by double-clicking TheSilenceOfTheShorts.app. User guide: README.md")"
echo
echo "$(t "La primera vez que actives subtítulos se descargará Whisper (~460 MB)." "The first time you enable subtitles, Whisper (~460 MB) will be downloaded.")"
echo "$(t "macOS pedirá permiso para acceder a Documentos/Escritorio la primera vez: acepta." "macOS will ask for permission to access Documents/Desktop the first time: accept.")"
