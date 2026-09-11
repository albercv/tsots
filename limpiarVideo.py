#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from videopipeline import i18n
from videopipeline.config import PipelineConfig
from videopipeline.i18n import _
from videopipeline.pipeline import run
from videopipeline.steps import (
    PasoFallido,
    comprobar_dependencias,
    tiene_pista_audio,
)


def main(argv: list[str] | None = None) -> None:
    i18n.instalar(i18n.detectar())
    parser = argparse.ArgumentParser(
        description=_(
            "Extrae el audio de un vídeo, lo limpia con ClearVoice, "
            "sustituye la pista original y recorta silencios con auto-editor."
        )
    )
    parser.add_argument("video", type=Path, help=_("Vídeo de entrada."))
    parser.add_argument(
        "salida",
        type=Path,
        nargs="?",
        help=_("Vídeo final. Por defecto: nombre_limpio.mp4"),
    )
    parser.add_argument(
        "--caption", action="store_true",
        help=_("Genera título SEO, caption y hashtags (nombre_limpio.md) con "
               "Ollama."),
    )
    parser.add_argument(
        "--marca", default="",
        help=_("Contexto de marca para el caption (quién eres, tono, CTA)."),
    )
    args = parser.parse_args(argv)

    faltan = comprobar_dependencias()
    if faltan:
        print(
            _("ERROR: faltan dependencias en PATH: {lista}").format(
                lista=", ".join(faltan)),
            file=sys.stderr,
        )
        sys.exit(1)

    video = args.video.expanduser().resolve()
    if not video.is_file():
        print(
            _("ERROR: no existe el vídeo: {video}").format(video=video),
            file=sys.stderr,
        )
        sys.exit(1)

    if not tiene_pista_audio(video):
        print(
            _("ERROR: el vídeo no contiene ninguna pista de audio."),
            file=sys.stderr,
        )
        sys.exit(1)

    salida = args.salida.expanduser().resolve() if args.salida else None
    config = PipelineConfig(
        video=video, salida=salida,
        caption_seo=args.caption, contexto_marca=args.marca,
        idioma_ui=i18n.idioma_actual(),
    )

    if config.ruta_salida_final() == video:
        print(
            _("ERROR: la salida no puede ser el mismo archivo que la entrada."),
            file=sys.stderr,
        )
        sys.exit(1)

    def on_progress(evento: dict) -> None:
        if "warning" in evento:
            print(_("AVISO: {aviso}").format(aviso=evento['warning']),
                  file=sys.stderr)
            return
        print(f"[{evento['step']}/{evento['total']}] {evento['label']}...")

    try:
        final = run(config, on_progress)
    except (PasoFallido, ValueError, FileNotFoundError) as error:
        print(_("ERROR: {error}").format(error=error), file=sys.stderr)
        detalle = getattr(error, "detalle", "")
        if detalle:
            print(detalle, file=sys.stderr)
        sys.exit(1)

    print()
    print(_("Proceso completado correctamente."))
    print(_("Vídeo final:     {final}").format(final=final))


if __name__ == "__main__":
    main()
