#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from videopipeline.steps import PasoFallido, limpiar_audio


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Limpia ruido de un audio usando ClearVoice."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)

    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()

    if not input_path.is_file():
        print(f"ERROR: no existe el archivo: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Entrada: {input_path}")
    print(f"Salida:  {output_path}")
    print("Cargando MossFormer2_SE_48K...")
    print("Procesando audio...")

    try:
        limpiar_audio(
            input_path, output_path, "speech_enhancement", "MossFormer2_SE_48K"
        )
    except PasoFallido as error:
        print(f"ERROR: {error}", file=sys.stderr)
        if error.detalle:
            print(error.detalle, file=sys.stderr)
        sys.exit(1)

    size_mb = output_path.stat().st_size / 1024 / 1024
    print("Proceso completado.")
    print(f"Archivo: {output_path}")
    print(f"Tamaño: {size_mb:.2f} MB")


if __name__ == "__main__":
    main()
