"""Título SEO, caption y hashtags a partir de la transcripción, vía LLM local.

Todo es puro salvo `generar`, que recibe el cliente inyectado (por defecto
`ollama.chat_json`) para poder testearse sin servidor.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ollama import chat_json
from .steps import PasoFallido
from .subtitles import Palabra

MAX_PALABRAS = 3500
MAX_TITULO = 60
MIN_HASHTAGS, MAX_HASHTAGS = 8, 15

_SYSTEM = (
    "Eres un experto en SEO y copywriting para vídeo corto (Instagram Reels, "
    "TikTok, YouTube Shorts) en español de España. A partir de la transcripción "
    "de un vídeo genera:\n"
    f"- titulo: máximo {MAX_TITULO} caracteres, con la palabra clave principal al "
    "inicio, concreto, sin clickbait vacío.\n"
    "- caption: 120-200 palabras. Primera línea = gancho. Desarrollo con las 2-3 "
    "ideas clave del vídeo. Cierra con una llamada a la acción. Tono cercano y "
    "profesional. Sin hashtags dentro del caption.\n"
    f"- hashtags: entre {MIN_HASHTAGS} y {MAX_HASHTAGS}, en minúsculas, sin "
    "espacios, empezando por #. Mezcla 3 genéricos de alto volumen, 5 o más de "
    "nicho y 2 del tema concreto.\n"
    "- palabras_clave: 5-8 términos de búsqueda en español.\n"
    "No inventes datos que no estén en la transcripción. Responde solo JSON."
)

ESQUEMA: dict = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"},
                     "minItems": MIN_HASHTAGS, "maxItems": MAX_HASHTAGS},
        "palabras_clave": {"type": "array", "items": {"type": "string"}},
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


def construir_mensajes(transcripcion: str, contexto_marca: str) -> list[dict]:
    system = _SYSTEM
    if contexto_marca.strip():
        system += (
            "\n\nContexto de marca (respétalo en tono, nombre y llamada a la "
            f"acción):\n{contexto_marca.strip()}"
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Transcripción:\n{recortar(transcripcion)}"},
    ]


def _normalizar_hashtag(texto: str) -> str:
    limpio = re.sub(r"\s+", "", texto.strip().lstrip("#")).lower()
    return f"#{limpio}" if limpio else ""


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
            "La respuesta del modelo no es válida: faltan campos o tipos incorrectos",
            detalle=json.dumps(datos, ensure_ascii=False)[:2000],
        )
    vistos: list[str] = []
    for h in datos["hashtags"]:
        n = _normalizar_hashtag(str(h))
        if n and n not in vistos:
            vistos.append(n)
    return Caption(
        titulo=datos["titulo"].strip()[:MAX_TITULO],
        caption=datos["caption"].strip(),
        hashtags=vistos,
        palabras_clave=[str(p).strip() for p in datos["palabras_clave"] if str(p).strip()],
    )


def generar(
    transcripcion: str,
    contexto_marca: str,
    modelo: str,
    cliente: Callable[[str, list[dict], dict], dict] = chat_json,
) -> Caption:
    if not transcripcion.strip():
        raise PasoFallido("La transcripción está vacía; no hay texto para el caption")
    datos = cliente(modelo, construir_mensajes(transcripcion, contexto_marca), ESQUEMA)
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
