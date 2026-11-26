"""Solo la selección de shorts de una ficha, sin cortar nada ni tocar su carpeta.

    python -m videopipeline.shorts_prueba <ficha> <salida.json> [--modelo M]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import ficha as modulo_ficha
from .config import PipelineConfig
from .ficha import BASE, TRANSCRIPCION, _escribir_json
from .ollama import asegurar_servidor
from .shorts import datos_seleccion, seleccionar, trocear_frases
from .steps import PasoFallido, duracion_video
from .subtitles import Palabra


def _duracion(ficha, palabras: list[Palabra]) -> float:
    # Como `_Pasada.__init__`, pero solo leyendo: esa puede crear `tmp`.
    base = ficha.artefactos.get(BASE)
    if base is None:
        ruta = (ficha.original or ficha.final).ruta
    else:
        ruta = ficha.ruta(base.archivo) if base.archivo else ficha.final.ruta
    try:
        return duracion_video(ruta)
    except Exception:  # noqa: BLE001  # sin ffprobe o sin vídeo: la transcripción
        return palabras[-1].fin


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m videopipeline.shorts_prueba")
    ap.add_argument("ficha_id")
    ap.add_argument("salida", type=Path)
    ap.add_argument("--modelo", default=PipelineConfig(video=Path()).modelo_caption)
    args = ap.parse_args(argv)

    ficha = modulo_ficha.cargar(args.ficha_id)
    if ficha is None:
        print(f"No existe la ficha «{args.ficha_id}».", file=sys.stderr)
        return 1
    try:
        if TRANSCRIPCION not in ficha.artefactos:
            raise OSError("no tiene transcripción")
        palabras = [Palabra(**p) for p in json.loads(
            ficha.ruta("transcripcion.json").read_text(encoding="utf-8"))]
        if not palabras:
            raise OSError("la transcripción está vacía")
    except (OSError, ValueError, TypeError) as error:
        print(f"La ficha «{args.ficha_id}» no está transcrita: {error}.",
              file=sys.stderr)
        return 1

    duracion = _duracion(ficha, palabras)
    t0 = time.monotonic()
    servidor = asegurar_servidor()
    try:
        sel = seleccionar(trocear_frases(palabras), duracion, args.modelo,
                          on_aviso=lambda texto: print(texto, file=sys.stderr))
    except PasoFallido as error:
        print(f"{error}\n{getattr(error, 'detalle', '') or ''}".strip(), file=sys.stderr)
        return 1
    finally:
        servidor.cerrar()
    _escribir_json(args.salida, {
        "version": 2, "ficha": ficha.id, "video": ficha.nombre,
        **datos_seleccion(sel), "segundos": round(time.monotonic() - t0, 1)})
    for c in sel.elegidos:
        print(f"{int(c.inicio // 60):>3} min  {c.fin - c.inicio:>3.0f} s  "
              f"{c.origen:<9} {c.interes:.1f}  {c.titulo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
