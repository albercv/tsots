"""Fotograma de portada: el más nítido mientras el título quemado está en pantalla."""
from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import cv2

from .. import fotogramas, steps
from .modelo import Publicacion

log = logging.getLogger(__name__)

# El título se ve durante los primeros 5 s.
INSTANTES = tuple(x / 2 for x in range(1, 10))


def elegir(video: Path, duracion: float | None = None, leer=None):
    """(segundo, fotograma) más nítido, o None. Nunca lanza."""
    try:
        leer = leer or fotogramas._leer_cv2
        if duracion is None:
            duracion = steps.duracion_video(video)
        mejor = None
        for segundo in (s for s in INSTANTES if s < duracion):
            frame = leer(video, segundo)
            if frame is None:
                continue
            n = fotogramas.nitidez(frame)
            if mejor is None or n > mejor[0]:
                mejor = (n, segundo, frame)
        return (mejor[1], mejor[2]) if mejor else None
    except Exception:
        log.exception("No se pudo elegir el fotograma de portada de %s", video)
        return None


def con_portada(publicacion: Publicacion, carpeta: Path) -> Publicacion:
    elegido = elegir(publicacion.video)
    if elegido is None:
        return publicacion
    segundo, frame = elegido
    ruta = carpeta / "miniatura.jpg"
    try:
        if not cv2.imwrite(str(ruta), frame, [cv2.IMWRITE_JPEG_QUALITY, 92]):
            return publicacion
    except Exception:
        log.exception("No se pudo escribir la miniatura %s", ruta)
        return publicacion
    return replace(publicacion, portada=segundo, miniatura=ruta)
