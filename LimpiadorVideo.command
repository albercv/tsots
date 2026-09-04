#!/bin/bash
cd "$(dirname "$0")"
source .venv-clearvoice/bin/activate
exec python -m app
