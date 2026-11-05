from __future__ import annotations

import logging
from typing import Callable

from .caption import recortar
from .i18n import _
from .ollama import chat_json
from .steps import PasoFallido
from .subtitles import _tiempo_ass, partir_en_dos

log = logging.getLogger(__name__)

MIN_PALABRAS = 3
MAX_PALABRAS = 5
_QUITAR = str.maketrans("", "", "\"'«»“”#")

# Prompt del LLM: no es texto de interfaz (no se traduce con gettext). Hay una
# variante fija por idioma; `construir_mensajes` elige según `idioma`.
_SYSTEM_ES = (
    "Eres un experto en vídeo corto (Instagram Reels, TikTok, YouTube Shorts) en "
    "español de España. A partir de la transcripción de un vídeo escribe el "
    "título que se sobreimprime en grande durante los primeros segundos:\n"
    f"- titulo: de {MIN_PALABRAS} a {MAX_PALABRAS} palabras clave que digan de qué "
    "trata el vídeo, con los temas, nombres o conceptos concretos que se "
    "mencionan.\n"
    "- Nada genérico (\"vídeo interesante\", \"mira esto\").\n"
    "- Sin emojis, hashtags, comillas ni punto final.\n"
    "- En el mismo idioma que la transcripción.\n"
    "No inventes datos que no estén en la transcripción. Responde solo JSON."
)

_SYSTEM_EN = (
    "You are a short-form video expert (Instagram Reels, TikTok, YouTube Shorts). "
    "From a video transcript write the title that is overlaid in large type "
    "during the first seconds:\n"
    f"- titulo: {MIN_PALABRAS} to {MAX_PALABRAS} keywords that say what the video "
    "is about, using the specific topics, names or concepts it mentions.\n"
    "- Nothing generic (\"interesting video\", \"look at this\").\n"
    "- No emojis, hashtags, quotes or final period.\n"
    "- In the same language as the transcript.\n"
    "Do not invent data that isn't in the transcript. Respond only with JSON."
)

ESQUEMA: dict = {
    "type": "object",
    "properties": {"titulo": {"type": "string"}},
    "required": ["titulo"],
}

DURACION = 5.0
FUENTE = "Titan One"
TAMANO_HORIZONTAL = 0.07
TAMANO_VERTICAL = 0.055  # fracción de la altura; vertical si alto > ancho
ANCHO_UTIL = 0.90
MARGEN_SUPERIOR = 0.08
# Avance medio de una mayúscula de Titan One por punto de `Fontsize` de libass.
ANCHO_CARACTER = 0.62
# BORDE, BORDE_DORADO y DESPLAZAMIENTO: fracciones del tamaño de letra.
BORDE = 0.08
BORDE_DORADO = 0.16
DESPLAZAMIENTO = 0.06
DORADO = "&H0000C8FF"  # #FFC800 en &HAABBGGRR
FUNDIDO_MS = 300


def _ancho_en_fs(n: int) -> float:
    return n * ANCHO_CARACTER + 2 * BORDE_DORADO + DESPLAZAMIENTO


def lineas_titulo(texto: str, resolucion: tuple[int, int], inicio: float = 0.0,
                  duracion: float = DURACION) -> tuple[list[str], list[str]]:
    """(líneas `Style:`, líneas `Dialogue:`) del título, para `generar_ass(extra=…)`
    o para añadir a cualquier `.ass`. `([], [])` si el texto queda vacío."""
    ancho, alto = resolucion
    for c in "{}\\":
        texto = texto.replace(c, "")
    texto = " ".join(texto.split()).upper()
    if not texto:
        return [], []

    fs = round(alto * (TAMANO_VERTICAL if alto > ancho else TAMANO_HORIZONTAL))
    if _ancho_en_fs(len(texto)) * fs > ANCHO_UTIL * ancho:
        texto = partir_en_dos(texto)
    n = max(len(linea) for linea in texto.split("\\N"))
    fs = max(8, min(fs, int(ANCHO_UTIL * ancho / _ancho_en_fs(n))))
    borde = max(1, round(fs * BORDE))
    dorado = round(fs * BORDE_DORADO)
    d = max(1, round(fs * DESPLAZAMIENTO))
    x, y = ancho // 2, round(alto * MARGEN_SUPERIOR)

    estilos = [
        f"Style: TituloDorado,{FUENTE},{fs},{DORADO},&H00FFFFFF,{DORADO},"
        f"&H00000000,0,0,0,0,100,100,0,0,1,{dorado},0,8,0,0,0,1",
        f"Style: Titulo,{FUENTE},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,"
        f"&H00000000,0,0,0,0,100,100,0,0,1,{borde},0,8,0,0,0,1",
    ]
    tiempos = f"{_tiempo_ass(inicio)},{_tiempo_ass(inicio + duracion)}"
    fundido = f"\\fad({FUNDIDO_MS},{FUNDIDO_MS})"
    eventos = [
        f"Dialogue: 0,{tiempos},TituloDorado,,0,0,0,,"
        f"{{\\an8\\pos({x + d},{y + d}){fundido}}}{texto}",
        f"Dialogue: 1,{tiempos},Titulo,,0,0,0,,"
        f"{{\\an8\\pos({x},{y}){fundido}}}{texto}",
    ]
    return estilos, eventos


def construir_mensajes(transcripcion: str, idioma: str) -> list[dict]:
    ingles = idioma == "en"
    etiqueta = "Transcript" if ingles else "Transcripción"
    return [
        {"role": "system", "content": _SYSTEM_EN if ingles else _SYSTEM_ES},
        {"role": "user", "content": f"{etiqueta}:\n{recortar(transcripcion)}"},
    ]


def pedir_titulo(transcripcion: str, idioma: str, modelo: str,
                 cliente: Callable[[str, list[dict], dict], dict] = chat_json) -> str:
    """Título de 3 a 5 palabras para la transcripción. Lanza `PasoFallido`."""
    if not transcripcion.strip():
        raise PasoFallido(
            _("La transcripción está vacía; no hay texto para el título"))
    datos = cliente(modelo, construir_mensajes(transcripcion, idioma), ESQUEMA)
    titulo = datos.get("titulo")
    if not isinstance(titulo, str):
        raise PasoFallido(_("La respuesta del modelo no trae un título"))
    titulo = " ".join(titulo.translate(_QUITAR).split()[:MAX_PALABRAS]).rstrip(".,;: ")
    if len(titulo.split()) < MIN_PALABRAS:
        raise PasoFallido(
            _("El modelo no propuso un título de 3 a 5 palabras: «{titulo}»")
            .format(titulo=titulo))
    return titulo


def generar_titulo(transcripcion: str, idioma: str, modelo: str,
                   cliente: Callable[[str, list[dict], dict], dict] = chat_json
                   ) -> str | None:
    """Contrato con shorts: el título o `None` (con aviso en el log) si algo falla;
    nunca lanza, para que un fallo del modelo no tumbe el procesado."""
    try:
        return pedir_titulo(transcripcion, idioma, modelo, cliente)
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo generar el título de inicio: %s", e)
        return None
