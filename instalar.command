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

paso() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m    ✓ %s\033[0m\n' "$*"; }
fallo() { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- requisitos
paso "Comprobando el Mac"
[ "$(uname -s)" = "Darwin" ] || fallo "Este instalador es solo para macOS."
[ "$(uname -m)" = "arm64" ] || fallo "Se necesita un Mac con Apple Silicon (M1 o posterior). Este es $(uname -m)."
VERSION_MACOS="$(sw_vers -productVersion)"
[ "${VERSION_MACOS%%.*}" -ge 13 ] || fallo "Se necesita macOS 13 o posterior (tienes $VERSION_MACOS)."
ok "Apple Silicon, macOS $VERSION_MACOS"

paso "Herramientas de línea de comandos de Xcode"
if ! xcode-select -p >/dev/null 2>&1; then
    echo "    macOS va a mostrar un diálogo para instalarlas. Acepta, espera a"
    echo "    que termine y vuelve a ejecutar este instalador."
    xcode-select --install || true
    exit 1
fi
ok "instaladas en $(xcode-select -p)"

paso "Homebrew"
if [ -x /opt/homebrew/bin/brew ]; then
    ok "ya instalado"
else
    echo "    Se instala Homebrew (pide tu contraseña de usuario)."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
eval "$(/opt/homebrew/bin/brew shellenv)"

paso "Python 3.11, ffmpeg, ffmpeg-full y auto-editor (Homebrew)"
brew install python@3.11 ffmpeg ffmpeg-full auto-editor
ok "$(/opt/homebrew/opt/python@3.11/bin/python3.11 --version), $(ffmpeg -version | head -1 | cut -d' ' -f1-3), auto-editor $(auto-editor --version)"

if [ -z "${SIN_OLLAMA:-}" ]; then
    paso "Ollama (modelo local para el caption SEO)"
    if [ -d /Applications/Ollama.app ] || command -v ollama >/dev/null 2>&1; then
        ok "ya instalado"
    else
        brew install --cask ollama-app
    fi
    OLLAMA_BIN="$(command -v ollama || echo /Applications/Ollama.app/Contents/Resources/ollama)"
    if [ ! -x "$OLLAMA_BIN" ]; then
        echo "    No se encuentra el ejecutable 'ollama'; abre la app de Ollama una vez y vuelve a ejecutar."
    else
        [ -d /Applications/Ollama.app ] && open -g -a Ollama || true
        # Espera a que el servidor responda (la app tarda unos segundos).
        for _ in $(seq 1 30); do
            curl -s -m 1 localhost:11434/api/version >/dev/null && break
            sleep 1
        done
        if "$OLLAMA_BIN" list 2>/dev/null | awk '{print $1}' | grep -qx "$MODELO_OLLAMA"; then
            ok "modelo $MODELO_OLLAMA ya descargado"
        else
            echo "    Descargando $MODELO_OLLAMA (~6 GB, una sola vez)…"
            "$OLLAMA_BIN" pull "$MODELO_OLLAMA"
        fi
    fi
fi

# ------------------------------------------------------------- entorno Python
paso "Entorno Python (.venv-clearvoice)"
PY=/opt/homebrew/opt/python@3.11/bin/python3.11
if [ -x .venv-clearvoice/bin/python ] && .venv-clearvoice/bin/python -c "import PySide6, torch, clearvoice, faster_whisper" 2>/dev/null; then
    ok "ya creado y completo"
else
    rm -rf .venv-clearvoice
    "$PY" -m venv .venv-clearvoice
    .venv-clearvoice/bin/python -m pip install --quiet --upgrade pip
    echo "    Instalando dependencias (torch, PySide6, ClearVoice… ~2,5 GB; varios minutos)…"
    .venv-clearvoice/bin/python -m pip install --quiet -r requirements.txt
    .venv-clearvoice/bin/python -m pip install --quiet -e .
    ok "dependencias instaladas"
fi

paso "Modelo de limpieza de audio (MossFormer2_SE_48K, 221 MB)"
if [ -f checkpoints/MossFormer2_SE_48K/last_best_checkpoint.pt ]; then
    ok "ya descargado"
else
    .venv-clearvoice/bin/python - <<'EOF'
from huggingface_hub import snapshot_download
snapshot_download(repo_id="alibabasglab/MossFormer2_SE_48K",
                  local_dir="checkpoints/MossFormer2_SE_48K")
print("    descargado")
EOF
fi

# --------------------------------------------------------------------- la app
paso "Construyendo TheSilenceOfTheShorts.app"
chmod +x lanzador/construir_app.sh TheSilenceOfTheShorts.command desinstalar.command
lanzador/construir_app.sh >/dev/null
ok "app lista en $PROYECTO/TheSilenceOfTheShorts.app"

if [ -z "${SIN_DOCK:-}" ]; then
    paso "Acceso directo en el Dock"
    APP_URL="file://$PROYECTO/TheSilenceOfTheShorts.app/"
    if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "TheSilenceOfTheShorts.app"; then
        ok "ya estaba en el Dock"
    else
        defaults write com.apple.dock persistent-apps -array-add "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$APP_URL</string><key>_CFURLStringType</key><integer>15</integer></dict></dict><key>tile-type</key><string>file-tile</string></dict>"
        killall Dock
        ok "añadido"
    fi
fi

paso "Comprobación final"
.venv-clearvoice/bin/python - <<'EOF'
import shutil
faltan = [b for b in ("ffmpeg", "ffprobe", "auto-editor") if shutil.which(b) is None]
assert not faltan, f"faltan en PATH: {faltan}"
import app, videopipeline.pipeline  # importa toda la app
print("    todo importa correctamente")
EOF

echo
printf '\033[1;32mInstalación completa.\033[0m Abre "The Silence of the Shorts" desde el Dock\n'
echo "o con doble clic en TheSilenceOfTheShorts.app. Guía de uso: README.md"
echo
echo "La primera vez que actives subtítulos se descargará Whisper (~460 MB)."
echo "macOS pedirá permiso para acceder a Documentos/Escritorio la primera vez: acepta."
