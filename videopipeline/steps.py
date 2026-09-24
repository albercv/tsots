from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .i18n import _

BASE_DIR = Path(__file__).resolve().parent.parent


class PasoFallido(RuntimeError):
    def __init__(self, mensaje: str, detalle: str = ""):
        super().__init__(mensaje)
        self.detalle = detalle


def comprobar_dependencias() -> list[str]:
    return [
        nombre
        for nombre in ("ffmpeg", "ffprobe", "auto-editor")
        if shutil.which(nombre) is None
    ]


def _ejecutar(cmd: list[str], descripcion: str) -> None:
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise PasoFallido(
            _("{descripcion} falló (código {codigo})").format(
                descripcion=descripcion, codigo=resultado.returncode),
            detalle=resultado.stderr.strip()[-4000:],
        )


# El iPhone graba audio que arranca tarde y con cortes entre paquetes (hasta
# 0,3 s por vídeo). Si no se rellenan con silencio, ffmpeg y auto-editor los
# colapsan y la voz se adelanta al vídeo, cada vez más hacia el final.
# min_hard_comp baja el umbral de relleno de 0,1 s (defecto) a 10 ms.
FILTRO_HUECOS_AUDIO = "aresample=async=1:min_hard_comp=0.01:first_pts=0"


def cmd_extraer_audio(
    ffmpeg: str, video: Path, wav: Path, sample_rate: int
) -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video),
        "-map", "0:a:0", "-vn",
        "-af", FILTRO_HUECOS_AUDIO,
        "-ac", "1", "-ar", str(sample_rate),
        "-c:a", "pcm_s16le",
        str(wav),
    ]


def cmd_remux(
    ffmpeg: str, video: Path, audio: Path, salida: Path, intermedio: bool = False
) -> list[str]:
    """Sustituye la pista de audio. `intermedio`: audio PCM (salida .mov) para
    que auto-editor no herede el retardo de arranque del AAC (~23 ms)."""
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-map_metadata", "0",
        "-c:v", "copy",
        *(["-c:a", "pcm_s16le"] if intermedio
          else ["-c:a", "aac", "-b:a", "192k"]),
        "-movflags", "+faststart",
        "-shortest",
        str(salida),
    ]


def cmd_cortar_silencios(
    auto_editor: str,
    entrada: Path,
    salida: Path,
    margen: str,
    umbral: str,
    silencios: str,
    velocidad: int,
    fps: str = "30",
) -> list[str]:
    """Salida lista para redes: audio AAC (auto-editor copiaría el PCM del
    intermedio a un MP4) y fps entero (auto-editor usaría la media del VFR
    del iPhone, p. ej. 30,02, que TikTok obliga a recodificar)."""
    cmd = [
        auto_editor, str(entrada),
        "--margin", margen,
        "--edit", f"audio:threshold={umbral}",
        "-c:a", "aac", "-b:a", "192k",
        "--frame-rate", fps,
        "--progress", "machine",
        "--no-open",
        "-o", str(salida),
    ]
    if silencios == "acelerar":
        cmd[2:2] = ["--when-silent", f"speed:{velocidad}"]
    return cmd


def _binario(nombre: str) -> str:
    ruta = shutil.which(nombre)
    if ruta is None:
        raise PasoFallido(
            _("{nombre} no está instalado o no está en PATH").format(nombre=nombre)
        )
    return ruta


_RUTAS_FFMPEG_ASS = (
    Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"),
    Path("/usr/local/opt/ffmpeg-full/bin/ffmpeg"),
)

_ffmpeg_ass_cache: str | None = None


def ffmpeg_con_ass() -> str:
    """Devuelve un ffmpeg con soporte del filtro ass (libass).

    El resultado se memoiza en proceso: sondear cada candidato lanza un
    subproceso por quemado de subtítulos, y el binario válido no cambia
    durante la vida de la aplicación.
    """
    global _ffmpeg_ass_cache
    if _ffmpeg_ass_cache is not None:
        return _ffmpeg_ass_cache
    candidatos = [str(r) for r in _RUTAS_FFMPEG_ASS if r.is_file()]
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        candidatos.append(ffmpeg_path)
    for candidato in candidatos:
        resultado = subprocess.run(
            [candidato, "-hide_banner", "-filters"],
            capture_output=True, text=True,
            timeout=10,
        )
        if " ass " in resultado.stdout:
            _ffmpeg_ass_cache = candidato
            return candidato
    raise PasoFallido(
        _("Ningún ffmpeg disponible soporta subtítulos (libass). "
          "Instala ffmpeg-full: brew install ffmpeg-full")
    )


def extraer_audio(video: Path, wav: Path, sample_rate: int) -> None:
    wav.parent.mkdir(parents=True, exist_ok=True)
    _ejecutar(
        cmd_extraer_audio(_binario("ffmpeg"), video, wav, sample_rate),
        _("Extracción de audio"),
    )
    if not wav.is_file() or wav.stat().st_size == 0:
        raise PasoFallido(_("No se generó el WAV: {wav}").format(wav=wav))


def cmd_rellenar_huecos_audio(ffmpeg: str, video: Path, salida: Path) -> list[str]:
    """Copia el vídeo tal cual y reescribe solo el audio con los huecos
    rellenos, para que auto-editor no los colapse. PCM (sin el retardo de
    arranque del AAC): la salida debe ser .mov."""
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video),
        "-map", "0:v:0", "-map", "0:a:0",
        "-map_metadata", "0",
        "-c:v", "copy",
        "-af", FILTRO_HUECOS_AUDIO,
        "-c:a", "pcm_s16le",
        str(salida),
    ]


def rellenar_huecos_audio(video: Path, salida: Path) -> None:
    salida.parent.mkdir(parents=True, exist_ok=True)
    _ejecutar(
        cmd_rellenar_huecos_audio(_binario("ffmpeg"), video, salida),
        _("Preparación del audio"),
    )
    if not salida.is_file() or salida.stat().st_size == 0:
        raise PasoFallido(
            _("No se generó el vídeo preparado: {salida}").format(salida=salida)
        )


def remux(
    video: Path, audio: Path, salida: Path, intermedio: bool = False
) -> None:
    salida.parent.mkdir(parents=True, exist_ok=True)
    _ejecutar(
        cmd_remux(_binario("ffmpeg"), video, audio, salida, intermedio),
        _("Sustitución de la pista de audio"),
    )
    if not salida.is_file() or salida.stat().st_size == 0:
        raise PasoFallido(
            _("No se generó el vídeo remuxado: {salida}").format(salida=salida)
        )


def _parsear_progreso(linea: str) -> float | None:
    """Extrae el porcentaje de una línea de progreso de auto-editor.

    El formato real de ``auto-editor --progress machine`` no usa '%'; usa
    campos separados por '~', p. ej.:
        (mp4) h264+aac~1497.0~1801.0~0.06
    donde el segundo campo es el valor actual y el tercero el total.
    """
    campos = linea.strip().split("~")
    if len(campos) < 3:
        return None
    try:
        actual = float(campos[1])
        total = float(campos[2])
    except ValueError:
        return None
    if total <= 0:
        return None
    return min(100.0, actual / total * 100.0)


def cmd_normalizar_video(ffmpeg: str, entrada: Path, salida: Path) -> list[str]:
    """Reencoda solo el vídeo (audio copiado) con el encoder por hardware.

    auto-editor 31.x falla ("Could not write packet") con el H.264 de algunas
    exportaciones; una pasada por h264_videotoolbox produce un stream que sí
    acepta. Bitrate alto: auto-editor vuelve a codificar después.
    """
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(entrada),
        "-map", "0:v:0", "-map", "0:a:0",
        "-c:v", "h264_videotoolbox", "-b:v", "14M",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(salida),
    ]


def normalizar_video(entrada: Path, salida: Path) -> None:
    _ejecutar(
        cmd_normalizar_video(_binario("ffmpeg"), entrada, salida),
        _("Reencodado del vídeo (h264_videotoolbox)"),
    )
    if not salida.is_file() or salida.stat().st_size == 0:
        raise PasoFallido(
            _("No se generó el vídeo reencodado: {salida}").format(salida=salida)
        )


# Firma del bug de auto-editor que se resuelve reencodando la entrada.
_ERROR_PAQUETE_AUTO_EDITOR = "Could not write packet"


def _ejecutar_auto_editor(
    entrada: Path,
    salida: Path,
    margen: str,
    umbral: str,
    silencios: str,
    velocidad: int,
    on_percent: Callable[[float], None] | None,
) -> tuple[int, str]:
    """Lanza auto-editor y devuelve (código, salida cruda)."""
    cmd = cmd_cortar_silencios(
        _binario("auto-editor"), entrada, salida, margen, umbral, silencios,
        velocidad, fps=fps_objetivo(entrada),
    )
    proceso = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lineas: list[str] = []
    assert proceso.stdout is not None
    for linea in proceso.stdout:
        lineas.append(linea)
        if on_percent is not None:
            porcentaje = _parsear_progreso(linea)
            if porcentaje is not None:
                on_percent(porcentaje)
    proceso.wait()
    return proceso.returncode, "".join(lineas)


def cortar_silencios(
    entrada: Path,
    salida: Path,
    margen: str,
    umbral: str,
    silencios: str,
    velocidad: int,
    on_percent: Callable[[float], None] | None = None,
    on_aviso: Callable[[str], None] | None = None,
) -> None:
    salida.parent.mkdir(parents=True, exist_ok=True)
    codigo, texto = _ejecutar_auto_editor(
        entrada, salida, margen, umbral, silencios, velocidad, on_percent
    )
    reintentado = False
    if codigo != 0 and _ERROR_PAQUETE_AUTO_EDITOR in texto:
        reintentado = True
        normalizado = salida.with_name(f".{entrada.stem}_normalizado.mp4")
        try:
            normalizar_video(entrada, normalizado)
            if on_aviso is not None:
                on_aviso(
                    _("auto-editor no aceptó el stream H.264 original "
                      "({error}); el vídeo se ha reencodado con "
                      "h264_videotoolbox y se ha reintentado."
                      ).format(error=_ERROR_PAQUETE_AUTO_EDITOR)
                )
            codigo, texto = _ejecutar_auto_editor(
                normalizado, salida, margen, umbral, silencios, velocidad,
                on_percent,
            )
        finally:
            normalizado.unlink(missing_ok=True)
    if codigo != 0:
        if reintentado:
            mensaje = _(
                "auto-editor falló (código {codigo}) incluso tras reencodar "
                "la entrada"
            ).format(codigo=codigo)
        else:
            mensaje = _("auto-editor falló (código {codigo})").format(codigo=codigo)
        raise PasoFallido(mensaje, detalle=texto[-4000:])
    if not salida.is_file() or salida.stat().st_size == 0:
        raise PasoFallido(
            _("No se generó el vídeo editado: {salida}").format(salida=salida)
        )


def tiene_pista_audio(video: Path) -> bool:
    resultado = subprocess.run(
        [
            _binario("ffprobe"), "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
    )
    return bool(resultado.stdout.strip())


def resolucion_video(video: Path) -> tuple[int, int]:
    """Resolución de DISPLAY: aplica la rotación de los metadatos.

    Parseo por líneas clave=valor: robusto ante side-data extra que en
    formato CSV producía campos vacíos/colas de coma.
    """
    resultado = subprocess.run(
        [
            _binario("ffprobe"), "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height:stream_side_data=rotation",
            "-of", "default=noprint_wrappers=1",
            str(video),
        ],
        capture_output=True,
        text=True,
    )
    valores: dict[str, str] = {}
    for linea in resultado.stdout.splitlines():
        clave, separador, valor = linea.partition("=")
        if separador:
            valores[clave.strip()] = valor.strip()
    try:
        ancho = int(valores["width"])
        alto = int(valores["height"])
    except (KeyError, ValueError):
        raise PasoFallido(
            _("No se pudo leer la resolución del vídeo: {video}").format(video=video),
            detalle=(resultado.stderr or resultado.stdout).strip()[-1000:],
        ) from None
    if resultado.returncode != 0:
        raise PasoFallido(
            _("No se pudo leer la resolución del vídeo: {video}").format(video=video),
            detalle=resultado.stderr.strip()[-1000:],
        )
    try:
        rotacion = float(valores.get("rotation") or 0)
    except ValueError:
        rotacion = 0.0
    if abs(rotacion) % 180 == 90:
        ancho, alto = alto, ancho
    return ancho, alto


_TASAS_ESTANDAR = (
    (24000, 1001), (24, 1), (25, 1), (30000, 1001), (30, 1),
    (50, 1), (60000, 1001), (60, 1),
)


def _fraccion(texto: str) -> float:
    num, _sep, den = texto.strip().partition("/")
    try:
        valor = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return valor if valor > 0 else 0.0


def fps_objetivo(video: Path) -> str:
    """Fps entero para la salida de auto-editor.

    La nominal (`r_frame_rate`: 30 en el iPhone aunque grabe tramos a 60) si
    es razonable y cercana a la media; si no, la tasa estándar más cercana a
    la media. Sin datos, 30.
    """
    resultado = subprocess.run(
        [
            _binario("ffprobe"), "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate,avg_frame_rate",
            "-of", "default=noprint_wrappers=1",
            str(video),
        ],
        capture_output=True,
        text=True,
    )
    valores: dict[str, str] = {}
    for linea in resultado.stdout.splitlines():
        clave, separador, valor = linea.partition("=")
        if separador:
            valores[clave.strip()] = valor.strip()
    nominal_txt = valores.get("r_frame_rate", "")
    nominal = _fraccion(nominal_txt)
    media = _fraccion(valores.get("avg_frame_rate", ""))
    if 0 < nominal <= 60 and (media == 0 or abs(nominal - media) / media < 0.10):
        return nominal_txt
    referencia = media or nominal
    if referencia == 0:
        return "30"
    num, den = min(
        _TASAS_ESTANDAR, key=lambda t: abs(t[0] / t[1] - referencia)
    )
    return f"{num}/{den}" if den != 1 else str(num)


def duracion_video(video: Path) -> float:
    resultado = subprocess.run(
        [
            _binario("ffprobe"), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(resultado.stdout.strip().rstrip(","))
    except ValueError:
        return 0.0


def cmd_quemar_subtitulos(
    ffmpeg: str, video: Path, ass_nombre: str, salida: Path
) -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video),
        "-vf", f"ass={ass_nombre}",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(salida),
    ]


def quemar_subtitulos(
    video: Path,
    ass: Path,
    salida: Path,
    on_percent: Callable[[float], None] | None = None,
) -> None:
    if not ass.is_file():
        raise PasoFallido(
            _("No existe el archivo de subtítulos: {ass}").format(ass=ass)
        )
    salida.parent.mkdir(parents=True, exist_ok=True)
    duracion = duracion_video(video)
    cmd = cmd_quemar_subtitulos(ffmpeg_con_ass(), video, ass.name, salida)
    proceso = subprocess.Popen(
        cmd,
        cwd=str(ass.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lineas: list[str] = []
    assert proceso.stdout is not None
    for linea in proceso.stdout:
        lineas.append(linea)
        if on_percent is not None and duracion > 0 and "out_time_us=" in linea:
            try:
                us = int(linea.split("=", 1)[1])
                on_percent(min(100.0, us / 1_000_000 / duracion * 100.0))
            except ValueError:
                pass
    proceso.wait()
    if proceso.returncode != 0:
        raise PasoFallido(
            _("El quemado de subtítulos falló (código {codigo})").format(
                codigo=proceso.returncode),
            detalle="".join(lineas).strip()[-4000:],
        )
    if not salida.is_file() or salida.stat().st_size == 0:
        raise PasoFallido(
            _("No se generó el vídeo con subtítulos: {salida}").format(salida=salida)
        )


def _crear_clearvoice(tarea: str, modelo: str):
    # Import perezoso: torch solo se carga en el subproceso del runner.
    from clearvoice import ClearVoice

    return ClearVoice(task=tarea, model_names=[modelo])


def limpiar_audio(entrada: Path, salida: Path, tarea: str, modelo: str) -> None:
    salida.parent.mkdir(parents=True, exist_ok=True)
    clear_voice = _crear_clearvoice(tarea, modelo)
    audio = clear_voice(input_path=str(entrada), online_write=False)
    clear_voice.write(audio, output_path=str(salida))
    if not salida.is_file():
        # Separación de hablantes: ClearVoice escribe <stem>_s1/_s2.
        s1 = salida.with_name(f"{salida.stem}_s1{salida.suffix}")
        if s1.is_file():
            shutil.copyfile(s1, salida)
    if not salida.is_file() or salida.stat().st_size == 0:
        raise PasoFallido(
            _("ClearVoice no generó el audio limpio: {salida}").format(salida=salida)
        )
