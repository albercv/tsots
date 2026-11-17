"""Hoja de contactos (verificacion.png) de salida.mp4 para que Haiku la revise."""
import io
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from videopipeline.edicion import plan as plan_mod
from videopipeline.edicion.componer import FFMPEG, _duracion

ANCHO, ALTO, COLUMNAS = 270, 480, 6


def _tiempos(plan, dur: float) -> list[float]:
    ts = [0.5, dur - 0.3]
    for m in plan.momentos:
        ts.append((m.t0 + m.t1) / 2 if m.tipo == "zoom" else m.t + 0.4)
    if plan.final:
        ts.append(dur - plan_mod.DURACION_FINAL + 0.4)
    return sorted(min(max(t, 0), dur - 0.05) for t in ts)


def hoja(trabajo: Path) -> Path:
    trabajo = Path(trabajo)
    salida = trabajo / "salida.mp4"
    plan = plan_mod.leer(trabajo / "plan.validado.json")
    dur = float(_duracion(salida))
    ts = _tiempos(plan, dur)
    filas = -(-len(ts) // COLUMNAS)
    lienzo = Image.new("RGB", (ANCHO * min(len(ts), COLUMNAS), ALTO * filas))
    dib = ImageDraw.Draw(lienzo)
    for i, t in enumerate(ts):
        png = subprocess.run(
            [FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-i", str(salida), "-frames:v", "1",
             "-vf", f"scale={ANCHO}:{ALTO}", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True, check=True).stdout
        x, y = (i % COLUMNAS) * ANCHO, (i // COLUMNAS) * ALTO
        lienzo.paste(Image.open(io.BytesIO(png)).convert("RGB"), (x, y))
        dib.rectangle((x, y, x + 62, y + 14), fill=(0, 0, 0))
        dib.text((x + 3, y + 1), f"{t:.2f} s", fill=(255, 255, 0))
    destino = trabajo / "verificacion.png"
    lienzo.save(destino)
    return destino


def main(args: list[str]) -> int:
    try:
        print(hoja(Path(args[0])))
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo crear la hoja de verificación: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
