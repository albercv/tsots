from pathlib import Path

import cv2
import numpy as np
import pytest

from videopipeline.fotogramas import (
    cara_completa,
    extraer_candidatos,
    momentos,
    texto_en,
)
from videopipeline.subtitles import Palabra

SIN_CARAS = lambda f: np.zeros((0, 5))  # noqa: E731


def _nitida():
    img = np.zeros((90, 160, 3), np.uint8)
    img[::2] = 255
    return img


def _borrosa(valor=128):
    return np.full((90, 160, 3), valor, np.uint8)


def test_momentos_reparte_entre_5_y_95_por_ciento():
    assert momentos(100.0, 6) == pytest.approx([5.0, 23.0, 41.0, 59.0, 77.0, 95.0])


def test_video_corto_da_menos_candidatos(tmp_path):
    cands = extraer_candidatos(Path("v.mp4"), [], tmp_path, detector=SIN_CARAS,
                               leer=lambda v, t: _borrosa(), duracion=12.0)
    assert len(cands) == 2


def test_cara_completa_descarta_cortada_y_pequena():
    cajas = np.array([[0, 10, 50, 80, 0.99],
                      [60, 40, 66, 46, 0.99],
                      [80, 20, 130, 85, 0.95]])
    assert cara_completa(cajas, 160, 90) == (80, 20, 130, 85)


def test_prefiere_fotograma_con_cara_a_mas_nitido(tmp_path):
    con_cara = _nitida()[:, ::-1].copy()
    con_cara[::4] = 0  # menos nítido que _nitida, pero por encima del mínimo

    def leer(v, t):
        return con_cara if t == 51.0 else _nitida()

    def detector(f):
        if f is con_cara:
            return np.array([[80, 20, 130, 85, 0.95]])
        return np.zeros((0, 5))

    cands = extraer_candidatos(Path("v.mp4"), [], tmp_path, n=1, detector=detector,
                               leer=leer, duracion=100.0)
    assert cands[0].segundo == 51.0 and cands[0].cara == (80, 20, 130, 85)


def test_sin_caras_devuelve_los_mas_nitidos(tmp_path):
    cands = extraer_candidatos(Path("v.mp4"), [], tmp_path, detector=SIN_CARAS,
                               leer=lambda v, t: _nitida(), duracion=100.0)
    assert len(cands) == 6 and all(c.cara is None for c in cands)
    assert all(cv2.imread(str(c.archivo)) is not None for c in cands)


def test_borrosos_se_descartan_salvo_que_lo_sean_todos(tmp_path):
    cands = extraer_candidatos(Path("v.mp4"), [], tmp_path, detector=SIN_CARAS,
                               leer=lambda v, t: _nitida() if t < 30 else _borrosa(),
                               duracion=100.0)
    assert [c.segundo for c in cands] == [5.0, 23.0]
    todos = extraer_candidatos(Path("v.mp4"), [], tmp_path, detector=SIN_CARAS,
                               leer=lambda v, t: _borrosa(), duracion=100.0)
    assert len(todos) == 6


def test_texto_en_junta_palabras_del_entorno():
    palabras = [Palabra("hola", 1.0, 1.5), Palabra("mundo", 9.5, 10.0), Palabra("lejos", 30.0, 30.5)]
    assert texto_en(palabras, 5.0) == "hola mundo"
