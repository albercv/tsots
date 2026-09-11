#!/bin/bash
# Catálogos de traducción (gettext). Español = idioma fuente (msgid).
#
#   lanzador/traducir.sh            extrae cadenas → locale/tsots.pot,
#                                   fusiona en cada locale/*/LC_MESSAGES/tsots.po
#                                   y compila los .mo
#   lanzador/traducir.sh --solo-mo  solo compila los .mo (instalador / build)
#
# Requiere gettext (brew install gettext).
set -euo pipefail
cd "$(dirname "$0")/.."
DOMINIO=tsots
POT="locale/$DOMINIO.pot"
export PATH="/opt/homebrew/bin:/opt/homebrew/opt/gettext/bin:$PATH"

compilar() {
    command -v msgfmt >/dev/null 2>&1 || { echo "Falta gettext: brew install gettext" >&2; exit 1; }
    for po in locale/*/LC_MESSAGES/$DOMINIO.po; do
        mo="${po%.po}.mo"
        msgfmt --check -o "$mo" "$po"
        echo "compilado $mo"
    done
}

if [ "${1:-}" = "--solo-mo" ]; then
    compilar
    exit 0
fi

command -v xgettext >/dev/null 2>&1 || { echo "Falta gettext: brew install gettext" >&2; exit 1; }
mkdir -p locale
# Ficheros con texto visible: la app, el pipeline y la CLI (no tests, no clearvoice/).
FUENTES="$(git ls-files 'app/*.py' 'app/widgets/*.py' 'videopipeline/*.py' 'limpiarVideo.py')"
# shellcheck disable=SC2086
xgettext --language=Python --keyword=_ --keyword=N_ --from-code=UTF-8 \
    --package-name="The Silence of the Shorts" --msgid-bugs-address="" \
    --no-location --sort-output -o "$POT" $FUENTES
sed -i '' 's/^"Content-Type: text\/plain; charset=CHARSET\\n"/"Content-Type: text\/plain; charset=UTF-8\\n"/' "$POT"
echo "extraídas $(grep -c '^msgid ' "$POT") cadenas → $POT"

for po in locale/*/LC_MESSAGES/$DOMINIO.po; do
    [ -f "$po" ] || continue
    msgmerge --quiet --update --backup=none --no-location --sort-output "$po" "$POT"
    echo "fusionado $po ($(msgfmt --statistics -o /dev/null "$po" 2>&1))"
done
compilar
