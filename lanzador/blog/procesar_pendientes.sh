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
LIMITE="${TSOTS_BLOG_LIMITE:-1800}"  # segundos por carpeta; la variable es solo para los tests
E2D=mcp__claude_ai_E2D_-_Blog__
HERRAMIENTAS="${E2D}posts_create,${E2D}posts_request_upload,${E2D}posts_validate,${E2D}posts_set_cover,${E2D}posts_list_media,Read,Write,Bash($PYTHON -m videopipeline.blog_subida:*)"
# Las prohibidas ganan a las permitidas y a cualquier modo de permisos: ni publicar
# ni tocar un post que ya existe.
PROHIBIDAS="${E2D}posts_update_frontmatter,${E2D}posts_delete,${E2D}posts_update_body,${E2D}posts_rebuild"
# shortcut: una ruta con comillas o «\» rompe este JSON; escapar si llega a pasar.
AJUSTES="$(printf '{"hooks": {"PreToolUse": [{"matcher": "%sposts_create", "hooks": [{"type": "command", "command": "%s"}]}]}}' \
    "$E2D" "/bin/bash '$AQUI/guarda_borrador.sh'")"

ahora() { date '+%F %T'; }

mkdir -p "$DIR/pendientes" "$DIR/hechos" "$DIR/errores"
# launchd nunca lanza dos a la vez: un bloqueo sin tocar en 180 min es de una
# ejecución muerta (SIGKILL, apagón); cada carpeta lo renueva y dura 30 min como mucho.
if ! mkdir "$DIR/.bloqueo" 2>/dev/null; then
    if [ -z "$(find "$DIR/.bloqueo" -maxdepth 0 -mmin +180)" ]; then
        echo "$(ahora) bloqueo activo ($DIR/.bloqueo): otra ejecución sigue en marcha"
        exit 0
    fi
    echo "$(ahora) bloqueo de hace más de 180 min: se quita y se sigue"
    rm -rf "$DIR/.bloqueo"
    mkdir "$DIR/.bloqueo" 2>/dev/null || exit 0
fi
trap 'rmdir "$DIR/.bloqueo"' EXIT

export PATH="$PATH:$HOME/.local/bin:/opt/homebrew/bin"
export PYTHONPATH="$RAIZ"
CLAUDE="$(command -v claude)"
INSTRUCCIONES="$(cat "$AQUI/instrucciones.md")"
INSTRUCCIONES="${INSTRUCCIONES//@PYTHON@/$PYTHON}"

# Mueve la carpeta a $1 (hechos o errores). Si no puede, la aparta con un
# nombre oculto en pendientes/: si se quedara, cada pasada crearía otro borrador.
mover() {
    local nombre destino
    nombre="$(basename "$carpeta")"
    destino="$DIR/$1/$nombre"
    if [ ! -e "$destino" ] && mv "$carpeta" "$destino"; then
        # El borrador ya lleva el vídeo: este (enlace duro o copia) sobra.
        [ "$1" = hechos ] && rm -f "$destino/video.mp4"
        echo "$(ahora) $nombre: $2"
    elif mv "$carpeta" "$DIR/pendientes/.$nombre.no-movida"; then
        echo "$(ahora) $nombre: $2; no se pudo mover a $1/, apartada en pendientes/.$nombre.no-movida"
    else
        echo "$(ahora) $nombre: $2; no se pudo mover a $1/ ni apartar: se volverá a procesar"
    fi
}

# `*` no casa los nombres con punto: las .<nombre>.tmp aún se están escribiendo.
for carpeta in "$DIR"/pendientes/*/; do
    [ -d "$carpeta" ] || continue
    carpeta="${carpeta%/}"
    touch "$DIR/.bloqueo"
    if [ -z "$CLAUDE" ]; then
        echo "No se encuentra claude (ni en PATH, ni en ~/.local/bin, ni en /opt/homebrew/bin)" \
            > "$carpeta/motivo.txt"
        mover errores "error, sin claude"
        continue
    fi
    # perl (viene con macOS) pone el límite de tiempo: alarm sobrevive al exec.
    (cd "$carpeta" && perl -e 'alarm shift; exec @ARGV' "$LIMITE" \
        "$CLAUDE" -p "$INSTRUCCIONES" --add-dir "$carpeta" \
        --allowedTools "$HERRAMIENTAS" --disallowedTools "$PROHIBIDAS" \
        --settings "$AJUSTES") > "$carpeta/claude.log" 2>&1
    rc=$?
    url="$(plutil -extract url raw -o - "$carpeta/resultado.json" 2>/dev/null)"
    if [ -n "$url" ]; then
        mover hechos "borrador $url"
        continue
    fi
    slug="$(plutil -extract slug raw -o - "$carpeta/borrador.json" 2>/dev/null)"
    {
        [ "$rc" -eq 142 ] && echo "Tiempo agotado: claude no terminó en $((LIMITE / 60)) min ($LIMITE s)."
        [ -n "$slug" ] && echo "El borrador ya está creado en el blog (slug $slug):" \
            "revísalo antes de reintentar, porque reintentar crea otro."
        tail -n 40 "$carpeta/claude.log"
    } > "$carpeta/motivo.txt"
    mover errores "error, ver errores/$(basename "$carpeta")/motivo.txt"
done
