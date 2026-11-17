"""CLI: python -m videopipeline.edicion.validar_plan <trabajo>

Imprime OK y escribe plan.validado.json, o un error por línea (exit 1).
"""
import json
import subprocess
import sys
from pathlib import Path

from videopipeline.edicion import estilos, plan as P
from videopipeline.subtitles import Palabra

FFPROBE = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"


def _duracion(video: Path) -> float:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(video)], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def main(argv: list[str]) -> int:
    d = Path(argv[0])
    salida = d / "plan.validado.json"
    salida.unlink(missing_ok=True)
    try:
        plan = P.leer(d / "plan.json")
        palabras = [Palabra(**p) for p in json.loads((d / "palabras.json").read_text("utf-8"))]
        tj = json.loads((d / "trabajo.json").read_text("utf-8"))
        nuevo, errs = P.validar(plan, palabras, tj["zonas"], estilos.cargar(tj["estilo"]),
                                _duracion(d / "video.mp4"))
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as e:
        print(f"Error: {e}")
        return 1
    if errs:
        print("\n".join(errs))
        return 1
    P.guardar(nuevo, salida)
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
