"""Registro local de publicaciones: `<vídeo>.publicado.json` junto al vídeo.

Guarda plataforma, fecha, url, proveedor y modo. Nunca la clave. Lo que el
servicio no llegó a confirmar se anota con `sin_confirmar`: puede estar
publicado, así que también cuenta para avisar antes de repetir. Lo
programado lleva `programada` (fecha ISO en que saldrá) y `referencia` (la
del servicio, para olvidarlo si se cancela).
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .modelo import Plataforma

SUFIJO = ".publicado.json"
VERSION = 1


@dataclass(frozen=True)
class Entrada:
    plataforma: Plataforma
    fecha: str
    url: str = ""
    proveedor: str = ""
    modo: str = ""
    sin_confirmar: bool = False
    programada: str = ""
    referencia: str = ""


def ruta(video: Path) -> Path:
    video = Path(video)
    return video.with_name(video.stem + SUFIJO)


def leer(video: Path) -> list[Entrada]:
    """Entradas del registro, de la más antigua a la más reciente. Un fichero
    ausente o dañado equivale a un registro vacío."""
    try:
        datos = json.loads(ruta(video).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entradas: list[Entrada] = []
    for bruta in datos.get("publicaciones", []) if isinstance(datos, dict) else []:
        try:
            entradas.append(Entrada(
                plataforma=Plataforma(bruta["plataforma"]),
                fecha=str(bruta.get("fecha", "")),
                url=str(bruta.get("url", "") or ""),
                proveedor=str(bruta.get("proveedor", "") or ""),
                modo=str(bruta.get("modo", "") or ""),
                sin_confirmar=bruta.get("sin_confirmar") is True,
                programada=str(bruta.get("programada", "") or ""),
                referencia=str(bruta.get("referencia", "") or ""),
            ))
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    return entradas


def anotar(video: Path, plataforma: Plataforma, url: str = "", proveedor: str = "",
           modo: str = "", fecha: datetime | None = None,
           sin_confirmar: bool = False, programada: datetime | None = None,
           referencia: str = "") -> Entrada:
    """Añade una publicación al registro (escritura atómica)."""
    entrada = Entrada(
        plataforma=Plataforma(plataforma),
        fecha=(fecha or datetime.now()).isoformat(timespec="seconds"),
        url=url, proveedor=proveedor, modo=modo, sin_confirmar=sin_confirmar,
        programada=programada.isoformat(timespec="seconds") if programada else "",
        referencia=referencia,
    )
    _escribir(video, leer(video) + [entrada])
    return entrada


def olvidar(video: Path, referencia: str) -> bool:
    """Quita las entradas con esa `referencia` (una programación cancelada).
    `False` si no había ninguna: el fichero no se toca."""
    entradas = leer(video)
    quedan = [e for e in entradas if not referencia or e.referencia != referencia]
    if len(quedan) == len(entradas):
        return False
    _escribir(video, quedan)
    return True


def _escribir(video: Path, entradas: list[Entrada]) -> None:
    destino = ruta(video)
    contenido = {
        "version": VERSION,
        "publicaciones": [_a_json(e) for e in entradas],
    }
    fd, temporal = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=destino.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(contenido, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temporal, destino)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise


def _a_json(entrada: Entrada) -> dict:
    datos = {**asdict(entrada), "plataforma": entrada.plataforma.value}
    # Solo se escriben cuando hace falta.
    for campo in ("sin_confirmar", "programada", "referencia"):
        if not datos[campo]:
            del datos[campo]
    return datos


def ultimas(video: Path) -> dict[Plataforma, Entrada]:
    """La publicación más reciente de cada plataforma."""
    return {e.plataforma: e for e in leer(video)}


def ya_publicado(video: Path) -> set[Plataforma]:
    return set(ultimas(video))
