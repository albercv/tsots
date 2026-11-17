#!/bin/bash
# Agente de edición: convierte cada carpeta de <dir_edicion>/pendientes/ en un
# short editado con `claude -p` (Haiku) y SKILL.md; entregar.py lo deja junto al original.
# Lo lanza la app (edicion.lanzar_agente_edicion) al encolar shorts y al abrirse.
#   hechos/   la carpeta con resultado.json
#   errores/  la carpeta con motivo.txt (salida de entregar + final de claude.log)
set -u

DIR="${1:?uso: procesar_pendientes.sh <dir_edicion>}"
AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
PYTHON="${TSOTS_EDICION_PYTHON:-$RAIZ/.venv-clearvoice/bin/python}"  # la variable es solo para los tests
LIMITE="${TSOTS_EDICION_LIMITE:-1200}"  # segundos por carpeta

ahora() { date '+%F %T'; }

mkdir -p "$DIR/pendientes" "$DIR/hechos" "$DIR/errores"
# Con otro en marcha, este sale sin hacer nada. Un bloqueo sin tocar en 180 min es
# de una ejecución muerta (SIGKILL, apagón); cada carpeta lo renueva y dura 30 min
# como mucho.
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
# Sin el frontmatter YAML (empieza por «-»: el CLI lo tomaría por una opción) y con
# una primera línea de texto normal.
INSTRUCCIONES="Instrucciones para editar un short:

$(awk '/^---$/ && n < 2 { n++; next } n != 1' "$AQUI/SKILL.md")"
INSTRUCCIONES="${INSTRUCCIONES//@PYTHON@/$PYTHON}"

# Mueve la carpeta a $1 (hechos o errores). Si no puede, la aparta con un
# nombre oculto en pendientes/: si se quedara, cada pasada crearía otro borrador.
mover() {
    local nombre destino
    nombre="$(basename "$carpeta")"
    destino="$DIR/$1/$nombre"
    if [ ! -e "$destino" ] && mv "$carpeta" "$destino"; then
        [ "$1" = hechos ] && rm -f "$destino/video.mp4"
        echo "$(ahora) $nombre: $2"
    elif mv "$carpeta" "$DIR/pendientes/.$nombre.no-movida"; then
        echo "$(ahora) $nombre: $2; no se pudo mover a $1/, apartada en pendientes/.$nombre.no-movida"
    else
        echo "$(ahora) $nombre: $2; no se pudo mover a $1/ ni apartar: se volverá a procesar"
    fi
}

# Se repasa pendientes/ hasta no encontrar nada nuevo: la carpeta de un vídeo que
# termina mientras tanto (su arranque salió por el bloqueo) entra en esta ejecución.
# Cada nombre se procesa una vez como mucho, así que una carpeta que no se pudo
# mover nunca se repite (sería otro borrador). «/» no cabe en un nombre.
vistas=/
nuevas=1
while [ "$nuevas" = 1 ]; do
    nuevas=0
    # `*` no casa los nombres con punto: las .<nombre>.tmp aún se están escribiendo.
    for carpeta in "$DIR"/pendientes/*/; do
        [ -d "$carpeta" ] || continue
        carpeta="${carpeta%/}"
        case "$vistas" in *"/${carpeta##*/}/"*) continue ;; esac
        vistas="$vistas${carpeta##*/}/"
        nuevas=1
        touch "$DIR/.bloqueo"
        if [ -z "$CLAUDE" ]; then
            echo "No se encuentra claude (ni en PATH, ni en ~/.local/bin, ni en /opt/homebrew/bin)" \
                > "$carpeta/motivo.txt"
            mover errores "error, sin claude"
            continue
        fi
        HERRAMIENTAS="Read,Edit(./plan.json),Bash($PYTHON -m videopipeline.edicion.preparar:*),Bash($PYTHON -m videopipeline.edicion.validar_plan:*),Bash($PYTHON -m videopipeline.edicion.renderizar:*),Bash($PYTHON -m videopipeline.edicion.verificar:*)"
        # perl (viene con macOS) pone el límite de tiempo: alarm sobrevive al exec.
        # Sin los ajustes de usuario, los plugins y hooks personales no se cuelan.
        (cd "$carpeta" && perl -e 'alarm shift; exec @ARGV' "$LIMITE" \
            "$CLAUDE" -p "$INSTRUCCIONES

Trabajo: $carpeta" --model claude-haiku-5-5 --add-dir "$carpeta" \
            --allowedTools "$HERRAMIENTAS" \
            --disallowedTools "NotebookEdit,WebFetch,WebSearch" \
            --setting-sources project,local) > "$carpeta/claude.log" 2>&1
        rc=$?
        # Solo entregar.py entrega, y solo si la salida pasa sus comprobaciones.
        if destino="$(cd "$carpeta" && "$PYTHON" -m videopipeline.edicion.entregar "$carpeta" 2>&1)"; then
            mover hechos "editado $destino"
            continue
        fi
        {
            echo "$destino"
            [ "$rc" -eq 142 ] && echo "Tiempo agotado: claude no terminó en $((LIMITE / 60)) min ($LIMITE s)."
            tail -n 40 "$carpeta/claude.log"
        } > "$carpeta/motivo.txt"
        mover errores "error, ver errores/$(basename "$carpeta")/motivo.txt"
    done
done
