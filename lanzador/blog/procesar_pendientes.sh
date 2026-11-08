#!/bin/bash
# Agente del blog: convierte cada carpeta de <dir_blog>/pendientes/ en un
# BORRADOR de evolve2digital.com con `claude -p` e instrucciones.md.
# Lo lanza launchd (com.tsots.blog) cuando cambia pendientes/ y cada hora.
#   hechos/   la carpeta con resultado.json (slug, locale y URL del borrador)
#   errores/  la carpeta con motivo.txt (final de claude.log)
set -u

DIR="${1:?uso: procesar_pendientes.sh <dir_blog>}"
AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
PYTHON="$RAIZ/.venv-clearvoice/bin/python"
E2D=mcp__claude_ai_E2D_-_Blog__
HERRAMIENTAS="${E2D}posts_create,${E2D}posts_request_upload,${E2D}posts_validate,${E2D}posts_set_cover,${E2D}posts_list_media,Read,Write,Bash($PYTHON -m videopipeline.blog_subida:*)"

mkdir -p "$DIR/pendientes" "$DIR/hechos" "$DIR/errores"
mkdir "$DIR/.bloqueo" 2>/dev/null || exit 0
trap 'rmdir "$DIR/.bloqueo"' EXIT

export PATH="$PATH:$HOME/.local/bin:/opt/homebrew/bin"
export PYTHONPATH="$RAIZ"
CLAUDE="$(command -v claude)"
INSTRUCCIONES="$(cat "$AQUI/instrucciones.md")"
INSTRUCCIONES="${INSTRUCCIONES//@PYTHON@/$PYTHON}"

# `*` no casa los nombres con punto: las .<nombre>.tmp aún se están escribiendo.
for carpeta in "$DIR"/pendientes/*/; do
    [ -d "$carpeta" ] || continue
    carpeta="${carpeta%/}"
    if [ -z "$CLAUDE" ]; then
        echo "No se encuentra claude (ni en PATH, ni en ~/.local/bin, ni en /opt/homebrew/bin)" \
            > "$carpeta/motivo.txt"
    else
        (cd "$carpeta" && "$CLAUDE" -p "$INSTRUCCIONES" --add-dir "$carpeta" \
            --allowedTools "$HERRAMIENTAS") > "$carpeta/claude.log" 2>&1
        url="$(plutil -extract url raw -o - "$carpeta/resultado.json" 2>/dev/null)"
        if [ -n "$url" ]; then
            mv "$carpeta" "$DIR/hechos/"
            echo "$(date '+%F %T') $(basename "$carpeta"): borrador $url"
            continue
        fi
        tail -n 40 "$carpeta/claude.log" > "$carpeta/motivo.txt"
    fi
    mv "$carpeta" "$DIR/errores/"
    echo "$(date '+%F %T') $(basename "$carpeta"): error, ver errores/$(basename "$carpeta")/motivo.txt"
done
