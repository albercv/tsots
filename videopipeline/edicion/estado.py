"""Estado de «Editar con Claude» para la cola: qué tanda de shorts se está
editando, cuántos van, en qué fase está el actual y cuánto falta.

Solo lee `~/TSOTS/edicion`: los trabajos de `pendientes/`, `hechos/` y
`errores/` se agrupan por su `grupo` (la tanda; si no lo trae, la carpeta del `origen`
de su `trabajo.json`). La fase del trabajo en curso sale de los ficheros que
va dejando (`contexto.md`, `plan.json`, …), y su inicio de `inicio`, que
escribe el agente al empezarlo. El tiempo restante es una estimación con lo
que tardaron los ya hechos de esa tanda.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

VENTANA_S = 6 * 3600  # una tanda terminada se sigue mostrando estas horas
SEGUNDOS_POR_DEFECTO = 120.0  # por short, sin ninguno hecho en la tanda
BLOQUEO_VIGENTE_S = 180 * 60  # como el script: un bloqueo más viejo es de un agente muerto
_MARGEN_TANDA_S = 300  # trabajos de una tanda encolados con estos segundos de diferencia

# (fichero que la marca, fase, fracción del short hecha), de la más avanzada a la menos
_FASES = (
    ("salida.mp4", "revisando", 0.85),
    ("plan.validado.json", "montando", 0.55),
    ("plan.json", "validando", 0.45),
    ("contexto.md", "decide", 0.2),
)
_FASE_INICIAL = ("preparando", 0.05)


@dataclass(frozen=True)
class EstadoEdicion:
    total: int
    hechos: int
    errores: int
    en_cola: int  # sin contar el que está en curso
    actual: str | None  # nombre (stem) del short en curso
    fase: str | None  # preparando, decide, validando, montando, revisando
    porcentaje: float  # de la tanda, 0-100
    restante_s: float | None  # None si la tanda ya terminó
    agente_activo: bool
    con_error: tuple[str, ...]


@dataclass
class _Trabajo:
    carpeta: Path
    stem: str
    donde: str  # pendientes | hechos | errores
    ruta: Path
    encolado: float
    inicio: float | None
    fin: float | None


def _numero(ruta: Path) -> float | None:
    try:
        return float(ruta.read_text().strip())
    except (OSError, ValueError):
        return None


def _mtime(ruta: Path) -> float | None:
    try:
        return ruta.stat().st_mtime
    except OSError:
        return None


def _trabajos(dir_edicion: Path) -> list[_Trabajo]:
    trabajos = []
    for donde in ("pendientes", "hechos", "errores"):
        try:
            carpetas = [p for p in (dir_edicion / donde).iterdir()
                        if p.is_dir() and not p.name.startswith(".")]
        except OSError:
            continue
        for ruta in carpetas:
            tj = ruta / "trabajo.json"
            try:
                datos = json.loads(tj.read_text(encoding="utf-8"))
                origen = Path(datos["origen"])
                # los trabajos viejos no traen `grupo`: se agrupan por carpeta
                grupo = Path(datos["grupo"]) if datos.get("grupo") else origen.parent
                encolado = tj.stat().st_mtime
            except (OSError, ValueError, KeyError, TypeError):
                continue
            fin = None
            if donde == "hechos":
                fin = _mtime(ruta / "resultado.json") or _mtime(ruta)
            elif donde == "errores":
                fin = _mtime(ruta / "motivo.txt") or _mtime(ruta)
            trabajos.append(_Trabajo(grupo, origen.stem, donde, ruta, encolado,
                                     _numero(ruta / "inicio"), fin))
    return trabajos


def _fase(ruta: Path) -> tuple[str, float]:
    for fichero, fase, fraccion in _FASES:
        if (ruta / fichero).exists():
            return fase, fraccion
    return _FASE_INICIAL


def _bloqueo(dir_edicion: Path, ahora: float) -> float | None:
    """Cuándo empezó el trabajo en curso según el bloqueo del agente (lo toca
    al empezar cada uno), o None si no hay agente en marcha."""
    cuando = _mtime(dir_edicion / ".bloqueo")
    if cuando is None or ahora - cuando > BLOQUEO_VIGENTE_S:
        return None
    return cuando


def leer(dir_edicion: Path, ahora: float | None = None) -> dict[Path, EstadoEdicion]:
    """El estado por carpeta de shorts. Solo carpetas con trabajos pendientes
    o con una tanda terminada hace menos de `VENTANA_S`. Nunca lanza."""
    ahora = time.time() if ahora is None else ahora
    bloqueo = _bloqueo(dir_edicion, ahora)
    por_carpeta: dict[Path, list[_Trabajo]] = {}
    for t in _trabajos(dir_edicion):
        por_carpeta.setdefault(t.carpeta, []).append(t)
    estados = {}
    for carpeta, todos in por_carpeta.items():
        pendientes = [t for t in todos if t.donde == "pendientes"]
        recientes = [t for t in todos if t.fin is not None and ahora - t.fin < VENTANA_S]
        base = pendientes or recientes
        if not base:
            continue
        desde = min(t.encolado for t in base) - _MARGEN_TANDA_S
        tanda = [t for t in todos if t.encolado >= desde]
        estados[carpeta] = _resumir(tanda, bloqueo, ahora)
    return estados


def _resumir(tanda: list[_Trabajo], bloqueo: float | None, ahora: float) -> EstadoEdicion:
    hechos = [t for t in tanda if t.donde == "hechos"]
    errores = [t for t in tanda if t.donde == "errores"]
    pendientes = [t for t in tanda if t.donde == "pendientes"]
    actual = None
    if bloqueo is not None:
        # el que empezó con este bloqueo; un reintento conserva su `inicio` viejo
        en_curso = [t for t in pendientes if t.inicio is not None and t.inicio >= bloqueo - 5]
        actual = max(en_curso, key=lambda t: t.inicio, default=None)
    duraciones = [t.fin - t.inicio for t in hechos
                  if t.inicio is not None and t.fin is not None and t.fin > t.inicio]
    por_short = sum(duraciones) / len(duraciones) if duraciones else SEGUNDOS_POR_DEFECTO
    en_cola = len(pendientes) - (1 if actual else 0)
    fase, fraccion = None, 0.0
    restante = None
    if pendientes:
        restante = en_cola * por_short
        if actual is not None:
            fase, fraccion_fase = _fase(actual.ruta)
            transcurrido = max(0.0, ahora - actual.inicio)
            fraccion = max(fraccion_fase, min(transcurrido / por_short, 0.95))
            restante += max(por_short - transcurrido, 0.1 * por_short)
    total = len(tanda)
    porcentaje = 100.0 * (len(hechos) + len(errores) + fraccion) / total if total else 0.0
    return EstadoEdicion(
        total=total, hechos=len(hechos), errores=len(errores), en_cola=en_cola,
        actual=actual.stem if actual else None, fase=fase,
        porcentaje=porcentaje if pendientes else 100.0,
        restante_s=restante, agente_activo=bloqueo is not None,
        con_error=tuple(sorted(t.stem for t in errores)))


def minutos(segundos: float) -> int:
    """Minutos para mostrar, redondeando hacia arriba (nunca «0 min»)."""
    return max(1, math.ceil(segundos / 60))
