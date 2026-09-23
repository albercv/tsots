"""Título SEO, caption y hashtags a partir de la transcripción, vía LLM local.

Todo es puro salvo `generar`, que recibe el cliente inyectado (por defecto
`ollama.chat_json`) para poder testearse sin servidor.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .i18n import _
from .ollama import chat_json
from .steps import PasoFallido
from .subtitles import Palabra

MAX_PALABRAS = 3500
MAX_TITULO = 60
NUM_HASHTAGS = 5

# Etiquetas de relleno que no describen el vídeo: se descartan siempre.
HASHTAGS_GENERICOS = frozenset({
    "#viral", "#fyp", "#foryou", "#foryoupage", "#parati", "#paratii",
    "#trending", "#tendencia", "#explore", "#explorar", "#reels", "#reel",
    "#reelsinstagram", "#instagood", "#instagram", "#tiktok", "#shorts",
    "#youtubeshorts", "#video", "#videos", "#followme", "#like", "#love",
    "#xyzbca", "#fy", "#viralvideo", "#virales",
})

# Prompt del LLM: no es texto de interfaz (no se traduce con gettext). Hay una
# variante fija por idioma; `construir_mensajes` elige según `idioma`.
_SYSTEM_ES = (
    "Eres un experto en SEO y copywriting para vídeo corto (Instagram Reels, "
    "TikTok, YouTube Shorts) en español de España. A partir de la transcripción "
    "de un vídeo genera:\n"
    f"- titulo: máximo {MAX_TITULO} caracteres, con la palabra clave principal al "
    "inicio, concreto, sin clickbait vacío.\n"
    "- caption: 120-200 palabras. Primera línea = gancho. Desarrollo con las 2-3 "
    "ideas clave del vídeo. Cierra con una llamada a la acción. Tono cercano y "
    "profesional. Sin hashtags dentro del caption.\n"
    "- palabras_clave: 5-8 términos de búsqueda en español que describan el "
    "tema concreto del vídeo.\n"
    f"- hashtags: exactamente {NUM_HASHTAGS}, ordenados del más al menos "
    "relevante. Cada uno debe nombrar algo que aparece en el vídeo: sácalos de "
    "las palabras_clave y del caption. El primero, el tema principal; luego el "
    "nicho y los subtemas. En minúsculas, sin espacios, sin tildes, empezando "
    "por #. Prohibidos los de relleno que no describen el contenido (#viral, "
    "#fyp, #parati, #foryou, #reels, #trending, #explore).\n"
    "No inventes datos que no estén en la transcripción. Responde solo JSON."
)

_SYSTEM_EN = (
    "You are an SEO and copywriting expert for short-form video (Instagram "
    "Reels, TikTok, YouTube Shorts) in English. From a video transcript "
    "generate:\n"
    f"- titulo: at most {MAX_TITULO} characters, with the main keyword at the "
    "start, concrete, without empty clickbait.\n"
    "- caption: 120-200 words. First line = hook. Development with the video's "
    "2-3 key ideas. Close with a call to action. Warm and professional tone. "
    "No hashtags inside the caption.\n"
    "- palabras_clave: 5-8 search keywords describing the video's specific "
    "topic.\n"
    f"- hashtags: exactly {NUM_HASHTAGS}, ordered from most to least "
    "relevant. Each one must name something that appears in the video: take "
    "them from palabras_clave and the caption. First the main topic, then the "
    "niche and subtopics. Lowercase, no spaces, no accents, starting with #. "
    "Filler tags that don't describe the content are forbidden (#viral, #fyp, "
    "#parati, #foryou, #reels, #trending, #explore).\n"
    "Do not invent data that isn't in the transcript. Respond only with JSON."
)

ESQUEMA: dict = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "caption": {"type": "string"},
        # Orden importante: Ollama genera los campos en este orden, así los
        # hashtags salen después del caption y las palabras clave.
        "palabras_clave": {"type": "array", "items": {"type": "string"}},
        "hashtags": {"type": "array", "items": {"type": "string"},
                     "minItems": NUM_HASHTAGS, "maxItems": NUM_HASHTAGS},
    },
    "required": ["titulo", "caption", "hashtags", "palabras_clave"],
}


@dataclass
class Caption:
    titulo: str
    caption: str
    hashtags: list[str]
    palabras_clave: list[str]

    @property
    def hashtags_texto(self) -> str:
        return " ".join(self.hashtags)

    def texto_completo(self) -> str:
        return f"{self.titulo}\n\n{self.caption}\n\n{self.hashtags_texto}\n"


def texto_plano(palabras: list[Palabra]) -> str:
    return " ".join(p.texto for p in palabras)


def recortar(transcripcion: str, max_palabras: int = MAX_PALABRAS) -> str:
    palabras = transcripcion.split()
    if len(palabras) <= max_palabras:
        return transcripcion
    return " ".join(palabras[:max_palabras])


def construir_mensajes(transcripcion: str, contexto_marca: str,
                       idioma: str = "es") -> list[dict]:
    ingles = idioma == "en"
    system = _SYSTEM_EN if ingles else _SYSTEM_ES
    if contexto_marca.strip():
        if ingles:
            system += (
                "\n\nBrand context (respect it in tone, name and call to "
                f"action):\n{contexto_marca.strip()}"
            )
        else:
            system += (
                "\n\nContexto de marca (respétalo en tono, nombre y llamada a la "
                f"acción):\n{contexto_marca.strip()}"
            )
    etiqueta = "Transcript" if ingles else "Transcripción"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{etiqueta}:\n{recortar(transcripcion)}"},
    ]


def _sin_tildes(texto: str) -> str:
    """Quita tildes y diéresis pero conserva la ñ."""
    partes = []
    for c in texto:
        if c in "ñÑ":
            partes.append(c)
        else:
            partes.append("".join(
                d for d in unicodedata.normalize("NFD", c)
                if unicodedata.category(d) != "Mn"
            ))
    return "".join(partes)


def _normalizar_hashtag(texto: str) -> str:
    limpio = _sin_tildes(texto.strip().lstrip("#")).lower()
    limpio = re.sub(r"[^\w]", "", limpio)
    return f"#{limpio}" if limpio else ""


def _elegir_hashtags(propuestos: list, palabras_clave: list[str]) -> list[str]:
    """Los `NUM_HASHTAGS` más relevantes, sin relleno ni repetidos.

    Si el modelo propone menos de los necesarios tras filtrar, se completan
    con las palabras clave convertidas en hashtag.
    """
    elegidos: list[str] = []
    for candidato in [*map(str, propuestos), *palabras_clave]:
        h = _normalizar_hashtag(candidato)
        if h and h not in elegidos and h not in HASHTAGS_GENERICOS:
            elegidos.append(h)
        if len(elegidos) == NUM_HASHTAGS:
            break
    return elegidos


def _validar(datos: dict) -> Caption:
    faltan = [c for c in ESQUEMA["required"] if c not in datos]
    tipos_mal = (
        not isinstance(datos.get("titulo"), str)
        or not isinstance(datos.get("caption"), str)
        or not isinstance(datos.get("hashtags"), list)
        or not isinstance(datos.get("palabras_clave"), list)
    )
    if faltan or tipos_mal:
        raise PasoFallido(
            _("La respuesta del modelo no es válida: faltan campos o tipos "
              "incorrectos"),
            detalle=json.dumps(datos, ensure_ascii=False)[:2000],
        )
    palabras_clave = [
        " ".join(str(p).split()) for p in datos["palabras_clave"] if str(p).strip()
    ]
    return Caption(
        titulo=" ".join(datos["titulo"].split())[:MAX_TITULO],
        caption=datos["caption"].strip(),
        hashtags=_elegir_hashtags(datos["hashtags"], palabras_clave),
        palabras_clave=palabras_clave,
    )


def generar(
    transcripcion: str,
    contexto_marca: str,
    modelo: str,
    cliente: Callable[[str, list[dict], dict], dict] = chat_json,
    idioma: str = "es",
) -> Caption:
    if not transcripcion.strip():
        raise PasoFallido(
            _("La transcripción está vacía; no hay texto para el caption")
        )
    datos = cliente(
        modelo, construir_mensajes(transcripcion, contexto_marca, idioma), ESQUEMA
    )
    return _validar(datos)


def escribir_md(caption: Caption, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    lineas = [
        f"# {caption.titulo}", "",
        "## Caption", caption.caption, "",
        "## Hashtags", caption.hashtags_texto, "",
        "## Palabras clave",
        *[f"- {p}" for p in caption.palabras_clave], "",
    ]
    ruta.write_text("\n".join(lineas), encoding="utf-8")


def leer_md(ruta: Path) -> Caption | None:
    """Inverso de `escribir_md`. `None` si no existe o no tiene el formato.

    Se ancla el análisis desde el final porque las secciones posteriores nunca pueden
    contener líneas de encabezado: los hashtags son tokens sin espacios que empiezan
    con #, las palabras clave empiezan con "- ". Así se garantiza exactitud incluso
    si el caption contiene líneas como "## Nota".
    """
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    # Validar estructura mínima: línea 0 con "# ", línea 1 vacía, línea 2 exactamente "## Caption"
    if len(lineas) < 3 or not lineas[0].startswith("# ") or lineas[1] != "" or lineas[2] != "## Caption":
        return None

    titulo = lineas[0][2:].strip()

    # Encontrar la ÚLTIMA línea igual a "## Palabras clave"
    pos_pc = None
    for i in range(len(lineas) - 1, -1, -1):
        if lineas[i] == "## Palabras clave":
            pos_pc = i
            break

    if pos_pc is None or pos_pc <= 2:
        return None

    # Encontrar la ÚLTIMA línea igual a "## Hashtags" con índice < pos_pc
    pos_h = None
    for i in range(pos_pc - 1, -1, -1):
        if lineas[i] == "## Hashtags":
            pos_h = i
            break

    if pos_h is None or pos_h <= 2:
        return None

    # Extraer secciones
    caption = "\n".join(lineas[3:pos_h]).strip()
    hashtags = "\n".join(lineas[pos_h + 1:pos_pc]).split()
    palabras_clave = [l[2:].strip() for l in lineas[pos_pc + 1:] if l.startswith("- ")]

    return Caption(
        titulo=titulo,
        caption=caption,
        hashtags=hashtags,
        palabras_clave=palabras_clave,
    )
