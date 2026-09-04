from __future__ import annotations

import subprocess
from pathlib import Path

from .steps import PasoFallido, _binario, ffmpeg_con_ass, resolucion_video
from .subtitles import Bloque, Palabra, agrupar, generar_ass

_TEXTO_EJEMPLO = ("Así", "se", "ven", "tus", "subtítulos")


def extraer_frame(video: Path, destino_png: Path,
                  segundo: float = 1.0) -> None:
    destino_png.parent.mkdir(parents=True, exist_ok=True)
    base = [
        _binario("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
    ]
    intentos = (
        base + ["-ss", str(segundo), "-i", str(video),
                "-frames:v", "1", str(destino_png)],
        base + ["-i", str(video), "-frames:v", "1", str(destino_png)],
    )
    ultimo_stderr = ""
    for cmd in intentos:
        resultado = subprocess.run(cmd, capture_output=True, text=True)
        ultimo_stderr = resultado.stderr
        if (resultado.returncode == 0 and destino_png.is_file()
                and destino_png.stat().st_size > 0):
            return
    raise PasoFallido(
        f"No se pudo extraer un frame de: {video}",
        detalle=ultimo_stderr.strip()[-1000:],
    )


def renderizar_preview(frame_png: Path, preset_id: str, posicion: int,
                       tamano: int, destino_png: Path) -> None:
    resolucion = resolucion_video(frame_png)
    palabras = [
        Palabra(texto=texto, inicio=0.2 * i, fin=0.2 * i + 0.2)
        for i, texto in enumerate(_TEXTO_EJEMPLO)
    ]
    bloques = agrupar(palabras, preset_id)
    # El frame se quema en t=0: el primer bloque debe estar en pantalla.
    muestra = bloques[0]
    muestra = Bloque(palabras=muestra.palabras, inicio=0.0, fin=2.0)

    destino_png.parent.mkdir(parents=True, exist_ok=True)
    ass = destino_png.parent / f".{destino_png.stem}_preview.ass"
    generar_ass([muestra], preset_id, posicion, resolucion, ass, tamano=tamano)
    try:
        cmd = [
            ffmpeg_con_ass(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(frame_png),
            "-vf", f"ass={ass.name}",
            "-frames:v", "1",
            str(destino_png),
        ]
        resultado = subprocess.run(
            cmd, cwd=str(ass.parent), capture_output=True, text=True
        )
        if (resultado.returncode != 0 or not destino_png.is_file()
                or destino_png.stat().st_size == 0):
            raise PasoFallido(
                "No se pudo renderizar la previsualización",
                detalle=resultado.stderr.strip()[-1000:],
            )
    finally:
        ass.unlink(missing_ok=True)
