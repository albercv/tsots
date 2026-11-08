"""Fotogramas candidatos: elige fotogramas nítidos y con la cara entera.

Sirven de base para la portada del blog y de LinkedIn.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .seguimiento import UMBRAL_CONFIANZA, Detector, _detector_s3fd
from .steps import duracion_video
from .subtitles import Palabra

NUM_CANDIDATOS = 6
NITIDEZ_MINIMA = 40.0
MARGEN_BORDE = 0.02  # fracción del ancho/alto que la cara deja libre en cada borde
CARA_MIN_ALTO = 0.12  # fracción mínima del alto del fotograma
DESPLAZAMIENTOS = (0.0, -1.0, 1.0, -2.0, 2.0)  # segundos alrededor de cada momento


@dataclass(frozen=True)
class Candidato:
    archivo: Path
    segundo: float
    texto: str
    cara: tuple[int, int, int, int] | None  # x1, y1, x2, y2 en píxeles del fotograma
    nitidez: float


def momentos(duracion: float, n: int = NUM_CANDIDATOS) -> list[float]:
    """`n` instantes equiespaciados entre el 5 % y el 95 % de la duración."""
    if duracion < 30:
        n = max(1, int(duracion // 5))
    if n == 1:
        return [duracion / 2]
    return [duracion * (0.05 + 0.9 * i / (n - 1)) for i in range(n)]


def nitidez(imagen_bgr: np.ndarray) -> float:
    gris = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gris, cv2.CV_64F).var())


def cara_completa(
    cajas: np.ndarray, ancho: int, alto: int
) -> tuple[int, int, int, int] | None:
    """Caja de mayor área, con margen a los bordes y tamaño suficiente."""
    mejor, area_mejor = None, 0.0
    for x1, y1, x2, y2, score in cajas:
        area = (x2 - x1) * (y2 - y1)
        if (
            score >= UMBRAL_CONFIANZA
            and x1 >= MARGEN_BORDE * ancho
            and x2 <= (1 - MARGEN_BORDE) * ancho
            and y1 >= MARGEN_BORDE * alto
            and y2 <= (1 - MARGEN_BORDE) * alto
            and y2 - y1 >= CARA_MIN_ALTO * alto
            and area > area_mejor
        ):
            mejor, area_mejor = (int(x1), int(y1), int(x2), int(y2)), area
    return mejor


def texto_en(palabras: list[Palabra], segundo: float, radio: float = 8.0) -> str:
    return " ".join(
        p.texto for p in palabras if segundo - radio <= p.inicio <= segundo + radio
    )


def _leer_cv2(video: Path, segundo: float) -> np.ndarray | None:
    captura = cv2.VideoCapture(str(video))
    try:
        captura.set(cv2.CAP_PROP_POS_MSEC, segundo * 1000)
        ok, frame = captura.read()
        return frame if ok else None
    finally:
        captura.release()


def extraer_candidatos(
    video: Path,
    palabras: list[Palabra],
    destino: Path,
    *,
    n: int = NUM_CANDIDATOS,
    detector: Detector | None = None,
    leer: Callable[[Path, float], np.ndarray | None] | None = None,
    duracion: float | None = None,
) -> list[Candidato]:
    duracion = duracion_video(video) if duracion is None else duracion
    detector = detector or _detector_s3fd()
    leer = leer or _leer_cv2
    # por momento: (segundo, imagen, cara, nitidez) del elegido y del más nítido
    elegidos, nitidos = [], []
    for base in momentos(duracion, n):
        vistos = []
        for d in DESPLAZAMIENTOS:
            t = min(max(base + d, 0.0), duracion)
            frame = leer(video, t)
            if frame is None:
                continue
            alto, ancho = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)  # S3FD espera RGB
            cara = cara_completa(np.asarray(detector(rgb)).reshape(-1, 5), ancho, alto)
            vistos.append((t, frame, cara, nitidez(frame)))
        if vistos:
            elegidos.append(max(vistos, key=lambda v: (v[2] is not None, v[3])))
            nitidos.append(max(vistos, key=lambda v: v[3]))
    nitidos_ok = [e for e in elegidos if e[3] >= NITIDEZ_MINIMA]
    # si todos son borrosos, se queda el más nítido de cada momento
    finales = nitidos_ok or nitidos
    destino.mkdir(parents=True, exist_ok=True)
    resultado = []
    for i, (t, frame, cara, nit) in enumerate(sorted(finales, key=lambda v: v[0])):
        archivo = destino / f"candidato_{i:02d}.jpg"
        cv2.imwrite(str(archivo), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        resultado.append(Candidato(archivo, t, texto_en(palabras, t), cara, nit))
    return resultado
