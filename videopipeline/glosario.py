"""Glosario de términos del usuario para la transcripción.

Formato (una entrada por línea; `#` = comentario):

    Claude Code = Cloud Code, Claus Code
    Anthropic

A la izquierda, la forma correcta. A la derecha, opcional, las formas en que
Whisper se equivoca. Se usa de dos maneras:

1. `prompt_whisper`: las formas correctas se pasan a Whisper como pista antes
   de transcribir.
2. `corregir`: las variantes conocidas se sustituyen después de transcribir,
   conservando los tiempos. Cubre los vídeos largos, donde la pista pierde
   efecto (Whisper solo mira los últimos 224 tokens de contexto).

Todo es puro: sin E/S ni dependencias.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace

from .subtitles import Palabra

# Whisper admite unos 224 tokens de contexto; 600 caracteres ≈ 200 tokens.
MAX_CHARS_PROMPT = 600


@dataclass(frozen=True)
class Termino:
    correcto: str
    variantes: tuple[str, ...]


@dataclass(frozen=True)
class Glosario:
    terminos: tuple[Termino, ...] = ()

    @property
    def vacio(self) -> bool:
        return not self.terminos

    @property
    def n_terminos(self) -> int:
        return len(_correctos(self))

    @property
    def n_correcciones(self) -> int:
        return sum(len(t.variantes) for t in self.terminos)


def _normalizar(texto: str) -> str:
    """Minúsculas, sin tildes ni signos: para comparar, nunca para mostrar."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^\w]", "", sin_tildes)


def _clave(texto: str) -> tuple[str, ...]:
    """Palabras normalizadas: "Cloud  Code." → ("cloud", "code")."""
    return tuple(_normalizar(w) for w in texto.split())


def parsear(texto: str) -> Glosario:
    terminos: list[Termino] = []
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        correcto, _, resto = linea.partition("=")
        correcto = " ".join(correcto.split())
        if not correcto:
            continue
        clave = _clave(correcto)
        variantes: list[str] = []
        for v in resto.split(","):
            v = " ".join(v.split())
            if v and _clave(v) != clave and v not in variantes:
                variantes.append(v)
        terminos.append(Termino(correcto, tuple(variantes)))
    return Glosario(tuple(terminos))


def _correctos(g: Glosario) -> tuple[str, ...]:
    vistos: list[str] = []
    for t in g.terminos:
        if t.correcto not in vistos:
            vistos.append(t.correcto)
    return tuple(vistos)


def _incluidos_en_prompt(g: Glosario) -> list[str]:
    incluidos: list[str] = []
    for termino in _correctos(g):
        candidato = ", ".join([*incluidos, termino]) + "."
        if len(candidato) > MAX_CHARS_PROMPT:
            break
        incluidos.append(termino)
    return incluidos


def prompt_whisper(g: Glosario) -> str | None:
    incluidos = _incluidos_en_prompt(g)
    return ", ".join(incluidos) + "." if incluidos else None


def recortados(g: Glosario) -> int:
    """Términos que no caben en el prompt de Whisper."""
    return len(_correctos(g)) - len(_incluidos_en_prompt(g))


def terminos_caption(g: Glosario) -> tuple[str, ...]:
    return _correctos(g)


def _bordes(texto: str) -> tuple[str, str]:
    """Signos pegados al principio y al final ('¿Cloud' → '¿', '')."""
    inicio = re.match(r"^[^\w]*", texto).group(0)
    fin = re.search(r"[^\w]*$", texto[len(inicio):]).group(0)
    return inicio, fin


def _sustituir(tramo: list[Palabra], correcto: str) -> list[Palabra]:
    prefijo, _ = _bordes(tramo[0].texto)
    _, sufijo = _bordes(tramo[-1].texto)
    nuevas = correcto.split()
    nuevas[0] = prefijo + nuevas[0]
    nuevas[-1] = nuevas[-1] + sufijo
    if len(nuevas) == len(tramo):
        return [replace(p, texto=t) for p, t in zip(tramo, nuevas)]
    inicio, fin = tramo[0].inicio, tramo[-1].fin
    paso = (fin - inicio) / len(nuevas)
    return [
        Palabra(texto=t, inicio=inicio + i * paso, fin=inicio + (i + 1) * paso)
        for i, t in enumerate(nuevas)
    ]


def corregir(palabras: list[Palabra], g: Glosario) -> list[Palabra]:
    """Sustituye las variantes conocidas por su forma correcta.

    Compara palabras completas, sin mayúsculas, tildes ni signos, y prefiere
    la variante con más palabras cuando varias encajan en el mismo sitio.
    Nunca modifica la lista recibida: devuelve otra, o la misma si el
    glosario no tiene correcciones.
    """
    reglas = sorted(
        (
            (_clave(v), t.correcto)
            for t in g.terminos for v in t.variantes
        ),
        key=lambda regla: len(regla[0]),
        reverse=True,
    )
    reglas = [(clave, correcto) for clave, correcto in reglas if all(clave)]
    if not reglas:
        return palabras

    normalizadas = [_normalizar(p.texto) for p in palabras]
    resultado: list[Palabra] = []
    i = 0
    while i < len(palabras):
        for clave, correcto in reglas:
            n = len(clave)
            if tuple(normalizadas[i:i + n]) == clave:
                resultado.extend(_sustituir(palabras[i:i + n], correcto))
                i += n
                break
        else:
            resultado.append(palabras[i])
            i += 1
    return resultado
