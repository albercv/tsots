from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import PipelineConfig
from .pipeline import run
from .steps import BASE_DIR, PasoFallido


def _imprimir(evento: dict) -> None:
    print(json.dumps(evento, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ejecuta el pipeline de limpieza y emite progreso JSON."
    )
    parser.add_argument("--config", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        if error.code in (None, 0):
            # --help u otra salida "limpia" de argparse: ya se imprimió lo debido.
            return 0
        _imprimir({"error": "argumentos inválidos: se requiere --config", "step": 0})
        return 1

    # Resolver la ruta de config contra el cwd del llamador ANTES del chdir.
    config_path = args.config.expanduser().resolve()

    # Los checkpoints de ClearVoice se resuelven relativos a clearvoice/.
    os.chdir(BASE_DIR)

    ultimo_paso = 0

    def on_progress(evento: dict) -> None:
        nonlocal ultimo_paso
        ultimo_paso = evento.get("step", ultimo_paso)
        _imprimir(evento)

    try:
        config = PipelineConfig.from_json(
            config_path.read_text(encoding="utf-8")
        )
        salida = run(config, on_progress)
    except PasoFallido as error:
        mensaje = str(error)
        if error.detalle:
            mensaje = f"{mensaje}\n{error.detalle}"
        _imprimir({"error": mensaje, "step": ultimo_paso})
        return 1
    except Exception as error:  # noqa: BLE001 — el subproceso reporta todo por JSON
        _imprimir({"error": str(error), "step": ultimo_paso})
        return 1

    _imprimir({"done": True, "salida": str(salida)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
