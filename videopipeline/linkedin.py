"""Texto de LinkedIn a partir de la transcripción, vía LLM local, y sus ficheros.

Junto al vídeo final `x_limpio.mp4` viven `x_limpio.linkedin.md` (el texto) y la
carpeta `x_limpio.linkedin/` (las fotos). `generar` recibe el cliente inyectado
para poder testearse sin servidor.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from .caption import HASHTAGS_GENERICOS, _normalizar_hashtag, recortar
from .i18n import _
from .ollama import chat_json
from .steps import PasoFallido

MIN_CARACTERES, MAX_CARACTERES = 1300, 2500
MIN_ACEPTADO = 600  # por debajo de esto el modelo no ha escrito un post
MAX_HASHTAGS = 5
MAX_IDEAS = 3
PALABRAS_IDEA = (3, 12)  # menos no dice nada; más no cabe grande en la tarjeta

# Post real aprobado por el usuario: referencia de estilo para el prompt.
EJEMPLO_ES = """Si usas Claude Code con subagentes, estabas pagando por un trabajo que se hacía dos veces.

Anthropic acaba de corregirlo, y el ahorro llega hasta el 99 % de los tokens.

El problema no estaba en cómo trabajas, sino en cómo se informaba del progreso.

Imagina tres subagentes en paralelo: uno con el backend, otro con el frontend y otro con los tests. Para que tú vieras en el chat una frase tan simple como «estoy haciendo test en la tarea 1», había otro agente, siempre en Opus, el modelo más caro, que se leía el contexto completo de cada uno de sus compañeros.

Es decir: el trabajo se procesaba por duplicado solo para escribirte un resumen de estado.

Con el cambio, ese seguimiento lo hace un subagente más ligero que solo lee los resúmenes y las notas de cada tarea, no el contexto completo. Menos lectura, menos tokens.

Qué significa en la práctica:
→ Si usas la API, pagas menos por el mismo trabajo.
→ Si usas suscripción, tardas mucho más en llegar a los límites.

Está disponible desde la versión 2.1.136 de Claude Code. Compruébalo en un minuto:

claude --version
claude update

Lo interesante no es solo el ahorro. Es la lección de fondo: cuando montas agentes en paralelo, el coste no está solo en el trabajo que hacen, sino en quién los supervisa y cuánto lee para hacerlo. Conviene revisarlo en cualquier sistema multiagente que tengas en tu empresa.

¿Ya lo has actualizado?

#ClaudeCode #Anthropic #AgentesDeIA #IAparaPymes #Evolve2Digital"""

# Prompt del LLM: no es texto de interfaz (no se traduce con gettext).
_SYSTEM_ES = (
    "Eres un experto en LinkedIn y copywriting en español de España. A partir de "
    "la transcripción de un vídeo escribe un post de LinkedIn:\n"
    f"- texto: entre {MIN_CARACTERES} y {MAX_CARACTERES} caracteres, tono "
    "profesional y cercano.\n"
    "- Las 2 primeras líneas son el gancho. Párrafos cortos. Sin hashtags dentro "
    "del texto.\n"
    "- Estructura: gancho, el problema o la noticia, un ejemplo concreto, una "
    "lista corta tipo «Qué significa en la práctica:» con líneas que empiezan "
    "por una flecha (→), una conclusión concreta y aplicable, y una pregunta "
    "final al lector.\n"
    "- hashtags: entre 3 y 5, relevantes al tema, que irán al final del post.\n"
    "- ideas: 3 ideas clave del vídeo, cada una un titular corto (de 4 a 10 "
    "palabras) que se entienda solo, sin leer el post, para ponerlo sobre una "
    "imagen. Sin hashtags ni emojis.\n"
    "Cierra con una pregunta al lector, como en el ejemplo. Prohibido el CTA "
    "de Instagram/TikTok («enlace en bio», «sígueme para más»). No nombres "
    "productos, modelos, versiones, empresas ni cifras que no aparezcan "
    "literalmente en la transcripción: si la transcripción no lo nombra, no lo "
    "nombres.\n"
    "No inventes datos que no estén en la transcripción. Responde solo JSON "
    'con el esquema {"texto": str, "hashtags": [str], "ideas": [str]}.\n\n'
    "Ejemplo de estilo (no copies su contenido ni sus datos, solo el tono, la "
    f"estructura y la longitud):\n{EJEMPLO_ES}"
)

_SYSTEM_EN = (
    "You are a LinkedIn and copywriting expert. From a video transcript write a "
    "LinkedIn post in English:\n"
    f"- texto: between {MIN_CARACTERES} and {MAX_CARACTERES} characters, "
    "professional but warm tone.\n"
    "- The first 2 lines are the hook. Short paragraphs. No hashtags inside the "
    "text.\n"
    "- Structure: hook, the problem or news, a concrete example, a short list "
    "like \"What this means in practice:\" with lines starting with an arrow "
    "(→), a concrete actionable takeaway, and a closing question to the "
    "reader.\n"
    "- hashtags: 3 to 5, relevant to the topic, to be placed at the end.\n"
    "- ideas: 3 key ideas from the video, each a short headline (4 to 10 "
    "words) that stands on its own, without reading the post, to be placed on "
    "an image. No hashtags or emojis.\n"
    "Close with a question to the reader, as in the example. Instagram/TikTok "
    "style CTAs (\"link in bio\", \"follow me for more\") are forbidden. Do not "
    "name products, models, versions, companies or figures that do not appear "
    "literally in the transcript: if the transcript doesn't name it, don't name "
    "it.\n"
    "Do not invent data that isn't in the transcript. Respond only with JSON "
    'with the schema {"texto": str, "hashtags": [str], "ideas": [str]}.\n\n'
    "Style example below. It is in Spanish: only its tone, structure and length "
    "apply, do not copy its content or data, and write in English:\n"
    f"{EJEMPLO_ES}"
)

ESQUEMA: dict = {
    "type": "object",
    "properties": {
        "texto": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "ideas": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["texto", "hashtags", "ideas"],
}


def construir_mensajes(transcripcion: str, contexto_marca: str,
                       idioma: str) -> list[dict]:
    ingles = idioma == "en"
    system = _SYSTEM_EN if ingles else _SYSTEM_ES
    if contexto_marca.strip():
        if ingles:
            system += ("\n\nBrand context (respect it in tone, name and call to "
                       f"action):\n{contexto_marca.strip()}")
        else:
            system += ("\n\nContexto de marca (respétalo en tono, nombre y "
                       f"llamada a la acción):\n{contexto_marca.strip()}")
    etiqueta = "Transcript" if ingles else "Transcripción"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{etiqueta}:\n{recortar(transcripcion)}"},
    ]


def _cortar_por_parrafo(texto: str) -> str:
    if len(texto) <= MAX_CARACTERES:
        return texto
    corte = texto.rfind("\n\n", 0, MAX_CARACTERES + 1)
    # shortcut: sin fin de párrafo previo se corta en seco, el modelo casi nunca lo hace
    return texto[:corte if corte > 0 else MAX_CARACTERES].rstrip()


_SOLO_HASHTAGS = re.compile(r"(?:#\w+\s*)+")
_HASHTAGS_FINALES = re.compile(r"(?:[ \t]+#\w+)+\s*$")
_FRASE_BIO = re.compile(r"[^.!?\n]*(?:enlace en bio|link in bio)[^.!?\n]*[.!?]?", re.I)


def _limpiar(texto: str) -> str:
    """Quita el CTA de «bio» y los hashtags que el modelo dejó al final."""
    texto = re.sub(r"[ \t]{2,}", " ", _FRASE_BIO.sub("", texto)).strip()
    lineas = texto.split("\n")
    while lineas and (not lineas[-1].strip() or _SOLO_HASHTAGS.fullmatch(lineas[-1].strip())):
        lineas.pop()
    if lineas:
        lineas[-1] = _HASHTAGS_FINALES.sub("", lineas[-1]).rstrip()
    return "\n".join(lineas).strip()


def _ideas(crudas) -> list[str]:
    """Titulares para las tarjetas; sin ideas válidas el post sale igual."""
    elegidas: list[str] = []
    for idea in crudas if isinstance(crudas, list) else []:
        if not isinstance(idea, str):
            continue
        idea = " ".join(idea.split()).strip("«»\"“”'. ")
        if (PALABRAS_IDEA[0] <= len(idea.split()) <= PALABRAS_IDEA[1]
                and idea.lower() not in (e.lower() for e in elegidas)):
            elegidas.append(idea)
    return elegidas[:MAX_IDEAS]


def generar(transcripcion: str, contexto_marca: str, modelo: str,
            cliente: Callable[[str, list[dict], dict], dict] = chat_json,
            idioma: str = "es") -> tuple[str, list[str]]:
    """(texto del post con hashtags, ideas clave para las tarjetas)."""
    datos = cliente(modelo, construir_mensajes(transcripcion, contexto_marca, idioma),
                    ESQUEMA)
    texto, hashtags = datos.get("texto"), datos.get("hashtags")
    if not isinstance(texto, str) or not isinstance(hashtags, list):
        raise PasoFallido(
            _("La respuesta del modelo no es válida: faltan campos o tipos "
              "incorrectos"),
            detalle=json.dumps(datos, ensure_ascii=False)[:2000],
        )
    texto = texto.strip()
    if len(texto) < MIN_ACEPTADO:
        raise PasoFallido(
            _("El texto de LinkedIn generado es demasiado corto"),
            detalle=texto[:2000],
        )
    elegidos: list[str] = []
    for h in map(_normalizar_hashtag, map(str, hashtags)):
        if h and h not in elegidos and h not in HASHTAGS_GENERICOS:
            elegidos.append(h)
    texto = _cortar_por_parrafo(_limpiar(texto))
    if elegidos:
        texto = "\n\n".join([texto, " ".join(elegidos[:MAX_HASHTAGS])])
    return texto, _ideas(datos.get("ideas"))


def rutas(final: Path) -> tuple[Path, Path]:
    """(texto .md, carpeta de fotos) junto al vídeo final."""
    return (final.with_suffix(".linkedin.md"), final.with_suffix(".linkedin"))


def escribir(texto: str, final: Path) -> None:
    md, carpeta = rutas(final)
    carpeta.mkdir(parents=True, exist_ok=True)
    md.write_text(texto, encoding="utf-8")


def leer(final: Path) -> tuple[str, list[Path]] | None:
    md, carpeta = rutas(final)
    try:
        texto = md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):  # ilegible: como si no hubiera post
        return None
    # glob no entra en subcarpetas, así que `candidatos/` queda fuera
    imagenes = sorted(p for p in carpeta.glob("*") if p.is_file()
                      and p.suffix.lower() in (".png", ".jpg"))
    return texto, imagenes
