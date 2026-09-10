#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from videopipeline.config import PipelineConfig
from videopipeline.pipeline import run
from videopipeline.steps import (
    PasoFallido,
    comprobar_dependencias,
    tiene_pista_audio,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Extrae el audio de un vídeo, lo limpia con ClearVoice, "
            "sustituye la pista original y recorta silencios con auto-editor."
        )
    )
    parser.add_argument("video", type=Path, help="Vídeo de entrada.")
    parser.add_argument(
        "salida",
        type=Path,
        nargs="?",
        help="Vídeo final. Por defecto: nombre_limpio.mp4",
    )
    parser.add_argument(
        "--caption", action="store_true",
        help="Genera título SEO, caption y hashtags (nombre_limpio.md) con Ollama.",
    )
    parser.add_argument(
        "--marca", default="",
        help="Contexto de marca para el caption (quién eres, tono, CTA).",
    )
    args = parser.parse_args(argv)

    faltan = comprobar_dependencias()
    if faltan:
        print(
            f"ERROR: faltan dependencias en PATH: {', '.join(faltan)}",
            file=sys.stderr,
        )
        sys.exit(1)

    video = args.video.expanduser().resolve()
    if not video.is_file():
        print(f"ERROR: no existe el vídeo: {video}", file=sys.stderr)
        sys.exit(1)

    if not tiene_pista_audio(video):
        print(
            "ERROR: el vídeo no contiene ninguna pista de audio.",
            file=sys.stderr,
        )
        sys.exit(1)

    salida = args.salida.expanduser().resolve() if args.salida else None
    config = PipelineConfig(
        video=video, salida=salida,
        caption_seo=args.caption, contexto_marca=args.marca,
    )

    if config.ruta_salida_final() == video:
        print(
            "ERROR: la salida no puede ser el mismo archivo que la entrada.",
            file=sys.stderr,
        )
        sys.exit(1)

    def on_progress(evento: dict) -> None:
        if "warning" in evento:
            print(f"AVISO: {evento['warning']}", file=sys.stderr)
            return
        print(f"[{evento['step']}/{evento['total']}] {evento['label']}...")

    try:
        final = run(config, on_progress)
    except (PasoFallido, ValueError, FileNotFoundError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        detalle = getattr(error, "detalle", "")
        if detalle:
            print(detalle, file=sys.stderr)
        sys.exit(1)

    print()
    print("Proceso completado correctamente.")
    print(f"Vídeo final:     {final}")


if __name__ == "__main__":
    main()
