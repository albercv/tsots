#!/bin/bash
# Hook PreToolUse de posts_create (procesar_pendientes.sh lo pasa con --settings):
# solo deja crear borradores. posts_create publica si falta `published`.
# Exit 2 bloquea la llamada y Claude recibe el motivo de stderr.
entrada="$(cat)"
tipo="$(printf '%s' "$entrada" | plutil -type tool_input.published - 2>/dev/null)"
valor="$(printf '%s' "$entrada" | plutil -extract tool_input.published raw -o - - 2>/dev/null)"
[ "$tipo" = bool ] && [ "$valor" = false ] && exit 0
echo "Bloqueado: posts_create tiene que llevar published: false (booleano); el artículo se crea siempre como borrador." >&2
exit 2
