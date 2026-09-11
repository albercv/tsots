"""Traducción de errores crípticos de herramientas externas a diagnósticos.

Un `Diagnostico` conserva SIEMPRE el detalle técnico original: la
explicación es una capa encima, nunca un reemplazo. Así un error
desconocido sigue siendo investigable.
"""
from __future__ import annotations

import re
import signal
from dataclasses import dataclass

from .i18n import _, N_

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# Progreso de `auto-editor --progress machine`: "(mp4) h264+aac~38.0~13944.0~8.48"
_PROGRESO_AUTO_EDITOR = re.compile(r"^\(\w+\)\s.*~[\d.]+~[\d.]+~")
# Progreso de `ffmpeg -progress pipe:1`: "out_time_us=123", "progress=continue"
_PROGRESO_FFMPEG = re.compile(
    r"^(frame|fps|stream_\d+_\d+_q|bitrate|total_size|out_time\w*|dup_frames"
    r"|drop_frames|speed|progress)="
)


def limpiar_salida(texto: str) -> str:
    """Quita códigos ANSI, retornos de carro y líneas de progreso."""
    texto = _ANSI.sub("", texto).replace("\r\n", "\n").replace("\r", "\n")
    lineas = []
    for linea in texto.split("\n"):
        linea = linea.strip()
        if not linea:
            continue
        if _PROGRESO_AUTO_EDITOR.match(linea) or _PROGRESO_FFMPEG.match(linea):
            continue
        lineas.append(linea)
    return "\n".join(lineas)


@dataclass
class Diagnostico:
    titulo: str
    causa: str
    solucion: str
    detalle: str
    conocido: bool

    def texto(self) -> str:
        partes = [
            self.titulo,
            _("Causa: {causa}").format(causa=self.causa),
            _("Qué hacer: {solucion}").format(solucion=self.solucion),
        ]
        if self.detalle:
            partes.append(_("Detalle técnico:\n{detalle}").format(detalle=self.detalle))
        return "\n".join(partes)


# (patrón sobre mensaje+detalle, título, causa, solución). Los patrones que
# reconocen mensajes generados por nuestro propio código (no salida de
# herramientas externas) son bilingües: ese mensaje se traduce al lanzarlo,
# así que el patrón debe reconocer tanto el original en español como su
# traducción al inglés.
_CONOCIDOS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        re.compile(r"Could not write packet", re.I),
        N_("auto-editor no pudo escribir el vídeo"),
        N_("auto-editor (31.5/31.6) no soporta la estructura de timestamps del "
           "stream H.264 de este vídeo: al escribir la salida genera un DTS no "
           "monótono y el muxer lo rechaza. Ocurre con exportaciones de algunos "
           "editores; el archivo original está bien."),
        N_("La app reencoda el vídeo con h264_videotoolbox y reintenta "
           "automáticamente. Si sigue fallando, reencoda a mano: "
           "ffmpeg -i entrada.mp4 -c:v h264_videotoolbox -b:v 14M -c:a copy "
           "salida.mp4"),
    ),
    (
        re.compile(r"No space left on device|ENOSPC", re.I),
        N_("No queda espacio en disco"),
        N_("El disco donde se escriben los temporales o la salida está lleno. "
           "Los intermedios (WAV 48 kHz + MP4 remuxado) ocupan varias veces el "
           "tamaño del vídeo original."),
        N_("Libera espacio o vacía audio_procesado/ y vuelve a procesar."),
    ),
    (
        re.compile(r"moov atom not found|Invalid data found when processing input",
                   re.I),
        N_("Archivo de vídeo incompleto o corrupto"),
        N_("ffmpeg no encuentra la cabecera (moov) o no reconoce los datos: el "
           "archivo está incompleto o corrupto (truncado, aún se estaba "
           "escribiendo, o un paso anterior dejó una salida a medias)."),
        N_("Comprueba que el vídeo se reproduce en QuickTime. Si es un "
           "intermedio en audio_procesado/, bórralo y vuelve a procesar."),
    ),
    (
        re.compile(r"out of memory|Cannot allocate memory|MemoryError", re.I),
        N_("Sin memoria suficiente"),
        N_("El modelo de limpieza (ClearVoice) o Whisper han agotado la "
           "RAM/GPU. Los vídeos largos a 48 kHz cargan el audio completo en "
           "memoria."),
        N_("Cierra otras aplicaciones, o divide el vídeo en partes más "
           "cortas."),
    ),
    (
        re.compile(
            r"no está instalado o no está en PATH|is not installed or not in "
            r"PATH|command not found", re.I,
        ),
        N_("Falta una herramienta externa"),
        N_("El pipeline invoca ffmpeg, ffprobe y auto-editor desde el PATH y "
           "alguno no se encuentra."),
        N_("brew install ffmpeg ffmpeg-full auto-editor"),
    ),
    (
        re.compile(
            r"Ningún ffmpeg disponible soporta subtítulos|No available ffmpeg "
            r"supports subtitles", re.I,
        ),
        N_("ffmpeg sin soporte de subtítulos (libass)"),
        N_("Quemar subtítulos necesita el filtro `ass`, que solo trae "
           "ffmpeg-full."),
        N_("brew install ffmpeg-full"),
    ),
    (
        re.compile(r"Permission denied|Operation not permitted", re.I),
        N_("Sin permisos para leer o escribir"),
        N_("macOS ha denegado el acceso a la carpeta del vídeo o de salida "
           "(Escritorio, Documentos y discos externos requieren permiso)."),
        N_("Ajustes del Sistema → Privacidad y seguridad → Archivos y "
           "carpetas: concede acceso a Terminal/Python, o elige otra carpeta "
           "de salida."),
    ),
    (
        re.compile(r"HTTPSConnectionPool|Max retries exceeded|Name or service not "
                   r"known|nodename nor servname|ConnectionError", re.I),
        N_("Sin conexión para descargar un modelo"),
        N_("Falta el modelo (ClearVoice o Whisper) en caché y no se ha "
           "podido descargar de HuggingFace."),
        N_("Conecta a internet y vuelve a procesar; los modelos se "
           "descargan una sola vez."),
    ),
    (
        re.compile(r"Ollama no está instalado|Ollama is not installed", re.I),
        N_("Ollama no está instalado"),
        N_("El caption SEO se genera con un modelo local servido por Ollama "
           "y no se encuentra el ejecutable `ollama` en PATH."),
        N_("brew install ollama   (y luego: ollama pull qwen3.5:9b)"),
    ),
    (
        re.compile(r"Modelo no descargado|Model not downloaded", re.I),
        N_("Modelo de Ollama no descargado"),
        N_("Ollama responde pero no tiene el modelo pedido en local."),
        N_("ollama pull <modelo>  (el nombre exacto está en el detalle "
           "técnico)"),
    ),
    (
        re.compile(r"Ollama no responde|Ollama is not responding", re.I),
        N_("Ollama no responde"),
        N_("No hay servidor en http://localhost:11434 y no se pudo arrancar "
           "`ollama serve` a tiempo (puerto ocupado, app de Ollama colgada, "
           "o descarga del modelo en curso)."),
        N_("Ejecuta `ollama serve` en una terminal para ver el error, o abre "
           "la app de Ollama. Si el puerto 11434 está ocupado, libéralo."),
    ),
)


def explicar(mensaje: str, detalle: str = "") -> Diagnostico:
    """Convierte (mensaje, detalle técnico) en un diagnóstico legible."""
    detalle = limpiar_salida(detalle)
    conjunto = f"{mensaje}\n{detalle}"
    for patron, titulo, causa, solucion in _CONOCIDOS:
        if patron.search(conjunto):
            return Diagnostico(
                titulo=_(titulo), causa=_(causa), solucion=_(solucion),
                detalle=detalle or mensaje, conocido=True,
            )
    return Diagnostico(
        titulo=mensaje,
        causa=_("Error desconocido: no está en la tabla de errores conocidos."),
        solucion=_("Abre el log del trabajo y añade este caso a "
                   "videopipeline/errores.py para que la próxima vez se "
                   "explique."),
        detalle=detalle,
        conocido=False,
    )


_SENALES = {
    signal.SIGKILL: N_("SIGKILL: el sistema mató el proceso, casi siempre por "
                       "falta de memoria (jetsam) o porque se cerró la app"),
    signal.SIGSEGV: N_("SIGSEGV: fallo de segmentación en una librería nativa "
                       "(torch, ctranslate2, PyAV)"),
    signal.SIGABRT: N_("SIGABRT: una librería nativa abortó (aserción "
                       "fallida)"),
    signal.SIGBUS: N_("SIGBUS: acceso a memoria inválido en una librería "
                      "nativa"),
    signal.SIGTERM: N_("SIGTERM: el proceso fue terminado desde fuera"),
}


def explicar_codigo_salida(codigo: int) -> str:
    """Explica un código de salida cuando corresponde a una señal.

    Devuelve "" para salidas normales (0) o errores ordinarios (1..127),
    que ya vienen explicados por el propio programa.
    """
    if codigo < 0:
        numero = -codigo
    elif codigo > 128:
        numero = codigo - 128
    else:
        return ""
    try:
        senal = signal.Signals(numero)
    except ValueError:
        return _("señal desconocida {numero}").format(numero=numero)
    if senal in _SENALES:
        return _(_SENALES[senal])
    return _("{nombre}: el proceso murió por una señal").format(nombre=senal.name)
