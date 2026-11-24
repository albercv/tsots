from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from PIL import Image

from .i18n import _
from .steps import (
    FILTRO_HUECOS_AUDIO,
    PasoFallido,
    _binario,
    duracion_video,
    ejecutar_ffmpeg_con_progreso,
    ffmpeg_con_ass,
    filtro_ass,
    fps_objetivo,
)

ANCHO_VERTICAL = 1080
ALTO_VERTICAL = 1920

# Proporción ancho/alto de la ventana que sigue la cara. 9:16 sería el máximo
# zoom (la cara llena la pantalla); más ancha deja ver más escena y la altura
# que sobra se rellena con fondo difuminado. Si cambia, el seguimiento guardado
# en las fichas deja de valer (su clave la incluye: `clave_seguimiento`).
PROPORCION_VENTANA_CARA = 4 / 3

_AUDIO_COMPATIBLE_MP4 = {"aac", "mp3", "alac", "ac3", "eac3"}

SEPARACION_BANNER = 40  # px entre el pie de los subtítulos y el banner
ALTO_MAXIMO_BANNER = ALTO_VERTICAL // 4  # un banner es una franja: más alto taparía el vídeo


def ancho_recorte(alto: int) -> int:
    """Ancho par de un recorte 9:16 a altura completa."""
    return int(alto * 9 / 16) // 2 * 2


def ancho_ventana_cara(ancho: int, alto: int) -> int:
    """Ancho par de la ventana que sigue la cara, sin pasar del fotograma."""
    return min(round(alto * PROPORCION_VENTANA_CARA), ancho) // 2 * 2


def es_ya_vertical(ancho: int, alto: int) -> bool:
    return alto * 9 >= ancho * 16


def _sobre_fondo_difuminado(w: int, h: int) -> str:
    """Tramo de filtros que centra la imagen de entrada sobre su propio fondo
    desenfocado, a w x h."""
    return (
        "split[a][b];"
        # Desenfoque a 1/4 de resolución: a tamaño completo es ~5x más lento.
        f"[a]scale={w // 4}:{h // 4}:force_original_aspect_ratio=increase,"
        f"crop={w // 4}:{h // 4},boxblur=5:2,scale={w}:{h}[bg];"
        f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease"
        ":force_divisible_by=2[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )


def banner_vertical(ruta: Path, posicion_subs: int) -> tuple[Image.Image, int]:
    """La imagen `ruta` sin su parte transparente, a lo ancho del vertical, y
    su y: bajo el pie de los subtítulos (los haya o no) o, si ahí no cabe,
    pegada abajo. OSError si no se puede leer; ValueError si no sirve de banner."""
    with Image.open(ruta) as original:
        imagen = original.convert("RGBA")
    caja = imagen.getchannel("A").getbbox()
    if caja is None:
        raise ValueError(_("la imagen es transparente entera"))
    imagen = imagen.crop(caja)
    alto = round(imagen.height * ANCHO_VERTICAL / imagen.width)
    if alto > ALTO_MAXIMO_BANNER:
        raise ValueError(_("es demasiado alta para un banner: recórtala a una "
                           "franja con fondo transparente"))
    imagen = imagen.resize((ANCHO_VERTICAL, alto), Image.LANCZOS)
    # El pie de los subtítulos, como su MarginV en `generar_ass`.
    pie = ALTO_VERTICAL - int(ALTO_VERTICAL * (100 - posicion_subs) / 100)
    return imagen, min(pie + SEPARACION_BANNER, ALTO_VERTICAL - alto)


def filtro_vertical(
    encuadre: str,
    ancho: int,
    alto: int,
    x_cara: int | None = None,
    ass_nombre: str | None = None,
    banner_y: int | None = None,
) -> str:
    """Grafo de filtros completo ``[0:v]…[v]`` para salida 1080x1920.

    En ``"cara"``, ``x_cara`` es la x inicial de la ventana (la mueve
    ``cara.cmd``); sin ella (no hay caras) la ventana queda quieta, centrada.
    Con ``banner_y``, la entrada ``[1:v]`` (el banner ya a 1080 de ancho) va a
    esa altura, por debajo de los subtítulos y el título.
    """
    w, h = ANCHO_VERTICAL, ALTO_VERTICAL
    ass = f",{filtro_ass(ass_nombre)}" if ass_nombre else ""
    banner = (f"[fondo];[fondo][1:v]overlay=0:{banner_y}"
              if banner_y is not None else "")
    final = f"setsar=1{banner}{ass},format=yuv420p[v]"
    if encuadre == "central":
        return f"[0:v]crop={ancho_recorte(alto)}:{alto},scale={w}:{h},{final}"
    if encuadre == "barras":
        return (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease"
            f":force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,{final}"
        )
    if encuadre == "difuminado":
        return f"[0:v]{_sobre_fondo_difuminado(w, h)},{final}"
    if encuadre == "cara":
        ancho_v = ancho_ventana_cara(ancho, alto)
        if x_cara is None:
            ventana = f"crop={ancho_v}:{alto}"  # x por defecto: centrada
        else:
            x = max(0, min(x_cara, ancho - ancho_v))
            ventana = f"sendcmd=f=cara.cmd,crop@v={ancho_v}:{alto}:{x}:0"
        return f"[0:v]{ventana},{_sobre_fondo_difuminado(w, h)},{final}"
    raise ValueError(f"encuadre desconocido: {encuadre!r}")


def cmd_convertir_vertical(
    ffmpeg: str, video: Path, filtro: str, salida: Path, fps: str, audio: str,
    tramo: tuple[float, float] | None = None, banner: Path | None = None,
) -> list[str]:
    """`audio`: "copiar", "aac" o "rellenar" (AAC rellenando los huecos del
    audio del iPhone, para fuentes sin procesar). Con `tramo` (inicio, fin) solo
    se convierte ese trozo; los tiempos de salida empiezan en 0. `banner` es la
    imagen de la entrada `[1:v]` del filtro."""
    pista = {
        "copiar": ["-c:a", "copy"],
        "aac": ["-c:a", "aac", "-b:a", "192k"],
        "rellenar": ["-af", FILTRO_HUECOS_AUDIO, "-c:a", "aac", "-b:a", "192k"],
    }[audio]
    # Búsqueda en la entrada: exacta al recodificar, y el `.ass` y el `sendcmd`
    # ya cuentan desde el inicio del tramo.
    corte = (
        ["-ss", f"{tramo[0]:.3f}", "-t", f"{tramo[1] - tramo[0]:.3f}"] if tramo else []
    )
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        *corte,
        "-i", str(video),
        *(["-i", str(banner)] if banner else []),
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
    tramo: tuple[float, float] | None = None,
    banner: Path | None = None,
) -> None:
    salida.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_con_ass() if usa_ass else _binario("ffmpeg")
    if desde_original:
        audio = "rellenar"
    elif tramo is not None or not audio_cabe_en_mp4(video):
        # Copiar AAC desde un punto de búsqueda descuadra el inicio del audio.
        audio = "aac"
    else:
        audio = "copiar"
    cmd = cmd_convertir_vertical(
        ffmpeg, video, filtro, salida, fps_objetivo(video), audio, tramo, banner
    )
    duracion = tramo[1] - tramo[0] if tramo else duracion_video(video)
    codigo, salida_ffmpeg = ejecutar_ffmpeg_con_progreso(
        cmd, cwd, duracion, on_percent
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
