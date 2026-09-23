"""Límites de texto de cada plataforma (no del proveedor).

El caption se recorta si hace falta; los hashtags nunca se cortan por la
mitad: van completos al final del texto.
"""
from __future__ import annotations

from .modelo import Plataforma, Publicacion

MAX_TITULO_YOUTUBE = 100
MAX_TEXTO = {
    Plataforma.TIKTOK: 2200,
    Plataforma.YOUTUBE: 5000,
    Plataforma.INSTAGRAM: 2200,
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
    return _recortar(titulo, MAX_TEXTO[plataforma])


def texto_para(plataforma: Plataforma, publicacion: Publicacion) -> str:
    """Caption + hashtags dentro del límite de la plataforma."""
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
