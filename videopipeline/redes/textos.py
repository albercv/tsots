"""Límites de texto de cada plataforma (no del proveedor).

El caption se recorta si hace falta; los hashtags nunca se cortan por la
mitad: van completos al final del texto.

X es distinta: un post admite 280 caracteres contados a su manera (ver
`longitud_x`) y su texto por defecto es título + hashtags.
"""
from __future__ import annotations

import re
import unicodedata

from .modelo import Plataforma, Publicacion

MAX_TITULO_YOUTUBE = 100
# Facebook no documenta un límite de título claro para vídeos: uno prudente.
MAX_TITULO_FACEBOOK = 255
MAX_TEXTO_X = 280
# Con Premium, X admite posts largos (hasta 25 000 caracteres).
MAX_TEXTO_X_PREMIUM = 25_000
MAX_TEXTO = {
    Plataforma.TIKTOK: 2200,
    Plataforma.YOUTUBE: 5000,
    Plataforma.INSTAGRAM: 2200,
    Plataforma.X: MAX_TEXTO_X,
    # Facebook admite mucho más en un post; en vídeos y reels se usa el
    # mismo límite prudente que en Instagram.
    Plataforma.FACEBOOK: 2200,
}
MAX_HASHTAGS = {Plataforma.INSTAGRAM: 30}
# YouTube cuenta las comas y las comillas de las etiquetas con espacios.
MAX_ETIQUETAS_YOUTUBE = 500
ELIPSIS = "…"


def _recortar(texto: str, limite: int) -> str:
    """Corta en el último espacio antes del límite y añade «…»."""
    texto = texto.strip()
    if len(texto) <= limite:
        return texto
    if limite <= len(ELIPSIS):
        return texto[:max(limite, 0)]
    corte = texto[: limite - len(ELIPSIS)]
    espacio = corte.rfind(" ")
    if espacio > len(corte) // 2:
        corte = corte[:espacio]
    return corte.rstrip(" ,.;:-") + ELIPSIS


def _sin_angulos(texto: str) -> str:
    # YouTube rechaza «<» y «>» en título y descripción.
    return texto.replace("<", "").replace(">", "")


def hashtags_para(plataforma: Plataforma, publicacion: Publicacion) -> list[str]:
    vistos: set[str] = set()
    hashtags: list[str] = []
    for bruto in publicacion.hashtags:
        etiqueta = bruto.strip()
        if not etiqueta:
            continue
        if not etiqueta.startswith("#"):
            etiqueta = "#" + etiqueta
        if etiqueta.lower() in vistos:
            continue
        vistos.add(etiqueta.lower())
        hashtags.append(etiqueta)
    maximo = MAX_HASHTAGS.get(plataforma)
    return hashtags[:maximo] if maximo is not None else hashtags


def titulo_para(plataforma: Plataforma, publicacion: Publicacion) -> str:
    titulo = publicacion.titulo.strip()
    if plataforma == Plataforma.YOUTUBE:
        return _recortar(_sin_angulos(titulo), MAX_TITULO_YOUTUBE)
    if plataforma == Plataforma.FACEBOOK:
        return _recortar(titulo, MAX_TITULO_FACEBOOK)
    return _recortar(titulo, MAX_TEXTO[plataforma])


def texto_para(plataforma: Plataforma, publicacion: Publicacion, *,
               x_premium: bool = False) -> str:
    """Caption + hashtags dentro del límite de la plataforma. En X, el texto
    propio del post (o el de por defecto): sin Premium, nunca pasa de 280."""
    if plataforma == Plataforma.X:
        texto = publicacion.texto_x.strip() or texto_x_por_defecto(publicacion)
        limite_x = MAX_TEXTO_X_PREMIUM if x_premium else MAX_TEXTO_X
        return texto if longitud_x(texto) <= limite_x else recortar_x(texto, limite_x)
    limite = MAX_TEXTO[plataforma]
    caption = publicacion.caption.strip()
    hashtags = hashtags_para(plataforma, publicacion)
    if plataforma == Plataforma.YOUTUBE:
        caption = _sin_angulos(caption)
    # Caso extremo: ni los hashtags caben. Se quitan enteros desde el final.
    while hashtags and len(" ".join(hashtags)) > limite:
        hashtags.pop()
    bloque = " ".join(hashtags)
    if not bloque:
        return _recortar(caption, limite)
    if not caption:
        return bloque
    disponible = limite - len(bloque) - 2
    if disponible <= len(ELIPSIS):
        return bloque
    return f"{_recortar(caption, disponible)}\n\n{bloque}"


def etiquetas_youtube(publicacion: Publicacion) -> list[str]:
    """Palabras clave como etiquetas, sin pasar de 500 caracteres."""
    etiquetas: list[str] = []
    total = 0
    for bruta in publicacion.palabras_clave:
        etiqueta = _sin_angulos(bruta.strip().lstrip("#"))
        if not etiqueta or etiqueta in etiquetas:
            continue
        coste = len(etiqueta) + (2 if " " in etiqueta else 0) + (1 if etiquetas else 0)
        if total + coste > MAX_ETIQUETAS_YOUTUBE:
            break
        etiquetas.append(etiqueta)
        total += coste
    return etiquetas


# --- X ---
#
# Aproximación a la cuenta de `twitter-text` (configuración v3), la que usa X:
# - El texto se normaliza (NFC) antes de contar.
# - Cada URL cuenta 23, sea cual sea su longitud. Se reconocen las que
#   empiezan por http(s):// o www. y los dominios con un TLD habitual
#   (ejemplo.com); X reconoce más TLD.
# - Un emoji cuenta 2, también las secuencias (tono de piel, ZWJ, banderas,
#   teclas).
# - El resto pesa 1 si está en los rangos «ligeros» (latín, griego, cirílico,
#   hebreo, árabe… y la puntuación tipográfica habitual) y 2 si no (CJK…).
# Casos raros (símbolos sueltos que X trata como emoji, TLD poco comunes)
# pueden contar distinto por unos pocos caracteres.

URL_X = 23
_RANGOS_LIGEROS = ((0x0000, 0x10FF), (0x2000, 0x200D), (0x2010, 0x201F), (0x2032, 0x2037))
_TLD = ("com|net|org|es|io|co|ai|app|dev|me|info|biz|eu|uk|us|tv|ly|gl|gg|link|"
        "online|site|store|shop|blog|tech|xyz|cat|mx|ar|cl|pe|fr|de|it|pt")
_FIN_URL = r"[^\s.,;:!?¡¿()\[\]{}<>\"'«»“”‘’]"
_RE_URL_X = re.compile(
    rf"(?:https?://|www\.)\S*{_FIN_URL}"
    rf"|(?<![\w@.#-])[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)*\.(?:{_TLD})\b"
    rf"(?:/\S*{_FIN_URL}|/)?",
    re.IGNORECASE)
_TONOS_PIEL = range(0x1F3FB, 0x1F400)
_ETIQUETAS_EMOJI = range(0xE0020, 0xE0080)
_SELECTORES = (0xFE0E, 0xFE0F)
_ZWJ = 0x200D
_TECLA = 0x20E3


def _es_emoji(cp: int) -> bool:
    return (0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF
            or 0x2300 <= cp <= 0x23FF)


def _es_indicador_regional(cp: int) -> bool:
    return 0x1F1E6 <= cp <= 0x1F1FF


def _peso(cp: int) -> int:
    return 1 if any(a <= cp <= b for a, b in _RANGOS_LIGEROS) else 2


def _longitud_sin_urls(texto: str) -> int:
    cps = [ord(c) for c in texto]
    total, i, n = 0, 0, len(cps)
    while i < n:
        cp = cps[i]
        tecla = (chr(cp) in "0123456789#*" and i + 1 < n
                 and (cps[i + 1] == _TECLA
                      or (cps[i + 1] in _SELECTORES and i + 2 < n and cps[i + 2] == _TECLA)))
        if tecla:
            total += 2
            i += 3 if cps[i + 1] in _SELECTORES else 2
            continue
        if _es_indicador_regional(cp):
            total += 2
            i += 2 if i + 1 < n and _es_indicador_regional(cps[i + 1]) else 1
            continue
        if not _es_emoji(cp):
            total += _peso(cp)
            i += 1
            continue
        # Un emoji y todo lo que se le une cuentan 2.
        total += 2
        i += 1
        while i < n:
            siguiente = cps[i]
            if (siguiente in _SELECTORES or siguiente in _TONOS_PIEL
                    or siguiente in _ETIQUETAS_EMOJI):
                i += 1
            elif siguiente == _ZWJ and i + 1 < n and _es_emoji(cps[i + 1]):
                i += 2
            else:
                break
    return total


def longitud_x(texto: str) -> int:
    """Caracteres de `texto` según X (ver la aproximación arriba)."""
    texto = unicodedata.normalize("NFC", texto or "")
    total, inicio = 0, 0
    for url in _RE_URL_X.finditer(texto):
        total += _longitud_sin_urls(texto[inicio:url.start()]) + URL_X
        inicio = url.end()
    return total + _longitud_sin_urls(texto[inicio:])


def recortar_x(texto: str, limite: int = MAX_TEXTO_X) -> str:
    """Como `_recortar`, pero midiendo con `longitud_x`."""
    texto = unicodedata.normalize("NFC", texto.strip())
    if longitud_x(texto) <= limite:
        return texto
    coste = longitud_x(ELIPSIS)
    # El prefijo más largo que cabe con la elipsis (la cuenta no decrece al
    # alargar el prefijo: búsqueda binaria).
    bajo, alto = 0, len(texto)
    while bajo < alto:
        medio = (bajo + alto + 1) // 2
        if longitud_x(texto[:medio]) + coste <= limite:
            bajo = medio
        else:
            alto = medio - 1
    corte = texto[:bajo]
    espacio = corte.rfind(" ")
    if espacio > len(corte) // 2:
        corte = corte[:espacio]
    corte = corte.rstrip(" ,.;:-\n")
    # Quitar el final pudo convertir una URL a medias en otra cosa: se asegura.
    while corte and longitud_x(corte) + coste > limite:
        corte = corte[:-1].rstrip()
    return corte + ELIPSIS if corte else ""


def texto_x_por_defecto(publicacion: Publicacion) -> str:
    """Título + hashtags en 280 caracteres de X: primero se quitan hashtags
    desde el final; si ni el título solo cabe, se acorta el título."""
    titulo = publicacion.titulo.strip()
    hashtags = hashtags_para(Plataforma.X, publicacion)

    def unir(etiquetas: list[str]) -> str:
        bloque = " ".join(etiquetas)
        return f"{titulo}\n\n{bloque}" if titulo and bloque else (titulo or bloque)

    while hashtags and longitud_x(unir(hashtags)) > MAX_TEXTO_X:
        hashtags.pop()
    texto = unir(hashtags)
    return texto if longitud_x(texto) <= MAX_TEXTO_X else recortar_x(texto, MAX_TEXTO_X)
