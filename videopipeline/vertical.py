from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from .i18n import _
from .steps import (
    FILTRO_HUECOS_AUDIO,
    PasoFallido,
    _binario,
    duracion_video,
    ejecutar_ffmpeg_con_progreso,
    ffmpeg_con_ass,
    fps_objetivo,
)

ANCHO_VERTICAL = 1080
ALTO_VERTICAL = 1920

_AUDIO_COMPATIBLE_MP4 = {"aac", "mp3", "alac", "ac3", "eac3"}


def ancho_recorte(alto: int) -> int:
    """Ancho par de un recorte 9:16 a altura completa."""
    return int(alto * 9 / 16) // 2 * 2


def es_ya_vertical(ancho: int, alto: int) -> bool:
    return alto * 9 >= ancho * 16


def filtro_vertical(
    encuadre: str,
    ancho: int,
    alto: int,
    x_cara: int | None = None,
    ass_nombre: str | None = None,
) -> str:
    """Grafo de filtros completo ``[0:v]…[v]`` para salida 1080x1920."""
    w, h = ANCHO_VERTICAL, ALTO_VERTICAL
    final = f"setsar=1{f',ass={ass_nombre}' if ass_nombre else ''},format=yuv420p[v]"
    if encuadre == "central":
        return f"[0:v]crop={ancho_recorte(alto)}:{alto},scale={w}:{h},{final}"
    if encuadre == "barras":
        return (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease"
            f":force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,{final}"
        )
    if encuadre == "difuminado":
        return (
            "[0:v]split[a][b];"
            # Desenfoque a 1/4 de resolución: a tamaño completo es ~5x más lento.
            f"[a]scale={w // 4}:{h // 4}:force_original_aspect_ratio=increase,"
            f"crop={w // 4}:{h // 4},boxblur=5:2,scale={w}:{h}[bg];"
            f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease"
            ":force_divisible_by=2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{final}"
        )
    if encuadre == "cara":
        if x_cara is None:
            raise ValueError("el encuadre 'cara' necesita x_cara")
        return (
            f"[0:v]sendcmd=f=cara.cmd,crop@v={ancho_recorte(alto)}:{alto}"
            f":{x_cara}:0,scale={w}:{h},{final}"
        )
    raise ValueError(f"encuadre desconocido: {encuadre!r}")


def cmd_convertir_vertical(
    ffmpeg: str, video: Path, filtro: str, salida: Path, fps: str, audio: str
) -> list[str]:
    """`audio`: "copiar", "aac" o "rellenar" (AAC rellenando los huecos del
    audio del iPhone, para fuentes sin procesar)."""
    pista = {
        "copiar": ["-c:a", "copy"],
        "aac": ["-c:a", "aac", "-b:a", "192k"],
        "rellenar": ["-af", FILTRO_HUECOS_AUDIO, "-c:a", "aac", "-b:a", "192k"],
    }[audio]
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video),
        "-filter_complex", filtro,
        "-map", "[v]", "-map", "0:a:0?",
        "-r", fps,  # TikTok recodifica los vídeos de tasa variable del iPhone
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        *pista,
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(salida),
    ]


def audio_cabe_en_mp4(video: Path) -> bool:
    """True si la pista de audio se puede copiar tal cual a MP4 (o no hay)."""
    resultado = subprocess.run(
        [
            _binario("ffprobe"), "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name",
            "-of", "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
    )
    codec = resultado.stdout.strip().rstrip(",")
    return codec == "" or codec in _AUDIO_COMPATIBLE_MP4


def convertir_vertical(
    video: Path,
    salida: Path,
    filtro: str,
    cwd: Path,
    usa_ass: bool,
    desde_original: bool = False,
    on_percent: Callable[[float], None] | None = None,
) -> None:
    salida.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_con_ass() if usa_ass else _binario("ffmpeg")
    if desde_original:
        audio = "rellenar"
    else:
        audio = "copiar" if audio_cabe_en_mp4(video) else "aac"
    cmd = cmd_convertir_vertical(
        ffmpeg, video, filtro, salida, fps_objetivo(video), audio
    )
    codigo, salida_ffmpeg = ejecutar_ffmpeg_con_progreso(
        cmd, cwd, duracion_video(video), on_percent
    )
    if codigo != 0:
        raise PasoFallido(
            _("La conversión a vertical falló (código {codigo})").format(
                codigo=codigo),
            detalle=salida_ffmpeg.strip()[-4000:],
        )
    if not salida.is_file() or salida.stat().st_size == 0:
        raise PasoFallido(
            _("No se generó el vídeo vertical: {salida}").format(salida=salida)
        )
