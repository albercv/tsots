#!/bin/bash
cd "$(dirname "$0")"
source .venv-clearvoice/bin/activate
# caffeinate -i: impide que el Mac duerma mientras la app esté abierta
# (la pantalla sí puede apagarse/bloquearse; el proceso sigue).
exec caffeinate -i python -m app
