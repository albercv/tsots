"""Estilos de edición de shorts: JSON en lanzador/edicion/estilos/."""
import json
from dataclasses import dataclass

from videopipeline.steps import BASE_DIR

IDS = ("divertido", "formal", "academico")


@dataclass(frozen=True)
class Paleta:
    acento: tuple[int, int, int]
    fondo: tuple[int, int, int, int]
    texto: tuple[int, int, int]
    fuente: tuple[str, int]


@dataclass(frozen=True)
class Estilo:
    id: str
    densidad_max: float  # momentos por segundo
    tipos: frozenset[str]
    transiciones: str  # letras permitidas, p. ej. "ABCDEFG"
    zoom_max: float
    zoom_lento: float
    sfx: dict[str, float]  # ganancia en dB por tipo de efecto
    musica: dict | None  # {"bpm", "db", "progresion", "fade_out"}
    paleta: Paleta


def cargar(id: str) -> Estilo:
    if id not in IDS:
        raise ValueError(f"Estilo de edición desconocido: {id!r}")
    d = json.loads((BASE_DIR / "lanzador" / "edicion" / "estilos" / f"{id}.json").read_text("utf-8"))
    p = d["paleta"]
    paleta = Paleta(tuple(p["acento"]), tuple(p["fondo"]), tuple(p["texto"]), tuple(p["fuente"]))
    return Estilo(
        id=id, densidad_max=d["densidad_max"], tipos=frozenset(d["tipos"]),
        transiciones=d["transiciones"], zoom_max=d["zoom_max"], zoom_lento=d["zoom_lento"],
        sfx=d["sfx"], musica=d["musica"], paleta=paleta,
    )
