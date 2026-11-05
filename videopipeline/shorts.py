"""Shorts (1:00-2:59) cortados de un vídeo largo a partir de su transcripción.

Flujo: la transcripción por palabras se trocea en frases numeradas; el LLM
propone trozos como rangos de frases; el código valida esos rangos (existen,
duran entre 60 y 179 s, no se repiten) y elige los mejores sin solapes.
Aquí solo hay la lógica pura: las llamadas al modelo y la generación van aparte.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .i18n import _
from .steps import PasoFallido
from .subtitles import Palabra

DURACION_MIN = 60.0
DURACION_MAX = 179.0
UMBRAL_INTERES = 2.0
UMBRAL_INDEPENDIENTE = 0.5
PAUSA_FRASE = 1.0  # s de silencio que cierran una frase sin puntuación
MAX_PALABRAS_FRASE = 60
MARGEN_CORTE = 0.25  # s de aire antes y después del trozo
MINUTOS_PARTE = 20
MINUTOS_SOLAPE = 2
MAX_NOMBRE = 60

_PUNTUACION_FINAL = (".", "!", "?", "…")
_NO_VALIDOS_EN_NOMBRE = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f-\x9f]')

# Por qué se descarta un candidato (`Candidato.descarte`; "" = sigue en pie).
DESCARTES = (
    "fuera_de_rango", "duracion", "repetido", "flojo", "no_se_entiende_solo",
    "solapa", "sobra",
)


@dataclass
class Frase:
    palabras: list[Palabra]

    @property
    def inicio(self) -> float:
        return self.palabras[0].inicio

    @property
    def fin(self) -> float:
        return self.palabras[-1].fin

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palabras)


@dataclass
class Candidato:
    frase_inicio: int  # de 1 a n, globales
    frase_fin: int
    titulo: str
    motivo: str
    inicio: float = 0.0  # segundos de corte, con margen
    fin: float = 0.0
    independiente: float | None = None  # probabilidad de «se entiende solo»
    interes: float | None = None  # de 0 a 4
    descarte: str = ""
    archivo: str = ""  # nombre del .mp4 si salió


def trocear_frases(palabras: list[Palabra]) -> list[Frase]:
    """Frases por puntuación, por pausa larga o al llegar al tope de palabras.

    Whisper a veces no pone puntos: sin las dos últimas reglas saldría una sola
    frase enorme y no habría dónde cortar.
    """
    frases: list[Frase] = []
    actual: list[Palabra] = []
    for p in palabras:
        if actual and p.inicio - actual[-1].fin > PAUSA_FRASE:
            frases.append(Frase(actual))
            actual = []
        actual.append(p)
        if p.texto.endswith(_PUNTUACION_FINAL) or len(actual) >= MAX_PALABRAS_FRASE:
            frases.append(Frase(actual))
            actual = []
    if actual:
        frases.append(Frase(actual))
    return frases


def maximo_shorts(duracion: float) -> int:
    return int(duracion // 180)


def partes(frases: list[Frase]) -> list[tuple[int, int]]:
    """Rangos `[desde, hasta)` de frases de como mucho `MINUTOS_PARTE` minutos.

    Cada parte empieza `MINUTOS_PARTE - MINUTOS_SOLAPE` minutos después de la
    anterior, para que un trozo cortado por el límite quepa entero en la
    siguiente.
    """
    paso = (MINUTOS_PARTE - MINUTOS_SOLAPE) * 60
    resultado: list[tuple[int, int]] = []
    desde = 0
    while desde < len(frases):
        limite = frases[desde].inicio + MINUTOS_PARTE * 60
        hasta = desde + 1  # una parte nunca está vacía
        while hasta < len(frases) and frases[hasta].fin <= limite:
            hasta += 1
        resultado.append((desde, hasta))
        if hasta == len(frases):
            break
        siguiente = frases[desde].inicio + paso
        desde += 1
        while desde < len(frases) and frases[desde].inicio < siguiente:
            desde += 1
    return resultado


def _entero(valor) -> int | None:
    """Un entero, o el texto de uno ("12"); `None` si no lo es (bool no cuenta)."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str):
        try:
            return int(valor)
        except ValueError:
            return None
    return None


def validar(datos: dict, frases: list[Frase], duracion: float) -> list[Candidato]:
    """Un `Candidato` por entrada válida de `datos["candidatos"]`.

    Los que no valen quedan con su código en `descarte`; a los que valen se
    les calcula el corte (`inicio`/`fin`), con margen pero sin pisar las
    frases vecinas.
    """
    entradas = datos.get("candidatos") if isinstance(datos, dict) else None
    if not isinstance(entradas, list):
        raise PasoFallido(
            _("La respuesta del modelo no es válida: faltan los candidatos"),
            detalle=json.dumps(datos, ensure_ascii=False, default=str)[:2000],
        )
    candidatos: list[Candidato] = []
    vistos: set[tuple[int, int]] = set()
    for entrada in entradas:
        if not isinstance(entrada, dict):
            continue
        ini = _entero(entrada.get("frase_inicio"))
        fin = _entero(entrada.get("frase_fin"))
        if ini is None or fin is None:
            continue
        c = Candidato(
            ini, fin,
            titulo=" ".join(str(entrada.get("titulo") or "").split()),
            motivo=str(entrada.get("motivo") or "").strip(),
        )
        candidatos.append(c)
        if not 1 <= ini <= fin <= len(frases):
            c.descarte = "fuera_de_rango"
            continue
        largo = frases[fin - 1].fin - frases[ini - 1].inicio
        if not DURACION_MIN <= largo <= DURACION_MAX:
            c.descarte = "duracion"
        elif (ini, fin) in vistos:
            c.descarte = "repetido"
        else:
            vistos.add((ini, fin))
            anterior = frases[ini - 2].fin if ini > 1 else 0.0
            siguiente = frases[fin].inicio if fin < len(frases) else duracion
            c.inicio = max(frases[ini - 1].inicio - MARGEN_CORTE, anterior)
            c.fin = min(frases[fin - 1].fin + MARGEN_CORTE, siguiente)
    return candidatos


def elegir(candidatos: list[Candidato], maximo: int) -> list[Candidato]:
    """Los mejores candidatos puntuados, sin solapes y como mucho `maximo`.

    Marca en `descarte` el motivo de los que no entran y devuelve los elegidos
    de mejor a peor. Un candidato sin nota no pasa.
    """
    vivos = [c for c in candidatos if not c.descarte]
    for c in vivos:
        if (c.interes or 0.0) < UMBRAL_INTERES:
            c.descarte = "flojo"
        elif (c.independiente or 0.0) < UMBRAL_INDEPENDIENTE:
            c.descarte = "no_se_entiende_solo"
    pasan = [c for c in vivos if not c.descarte]
    pasan.sort(key=lambda c: (-c.interes, -c.independiente, c.inicio))
    elegidos: list[Candidato] = []
    for c in pasan:
        if any(c.inicio < e.fin and e.inicio < c.fin for e in elegidos):
            c.descarte = "solapa"
        elif len(elegidos) >= maximo:
            c.descarte = "sobra"
        else:
            elegidos.append(c)
    return elegidos


def nombre_archivo(numero: int, titulo: str) -> str:
    """`"03 - Título limpio"`, sin extensión y válido como nombre de archivo."""
    limpio = " ".join(_NO_VALIDOS_EN_NOMBRE.sub(" ", titulo).split())
    limpio = limpio.strip(". ")[:MAX_NOMBRE].rstrip(". ")
    return f"{numero:02d} - {limpio or 'Short'}"


def tramo_palabras(palabras: list[Palabra], inicio: float, fin: float) -> list[Palabra]:
    """Copias de las palabras de `[inicio, fin]`, con los tiempos desde 0."""
    return [
        Palabra(p.texto, p.inicio - inicio, p.fin - inicio)
        for p in palabras if inicio <= p.inicio and p.fin <= fin
    ]
