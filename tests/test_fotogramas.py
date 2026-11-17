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
    cajas = np.array([[0, 10, 50, 80, 1.0],
                      [60, 40, 66, 46, 1.0],
                      [80, 20, 130, 85, 0.999]])
    assert cara_completa(cajas, 160, 90) == (80, 20, 130, 85)


# S3FD sobre los candidatos de odin_17_11 (1080×1920): 00, 03 y 05 son la cara;
# 01 es un dedo ante la pantalla, 04 texto de pantalla y 02 no tiene detección.
# La de 0.97 sale en otros vídeos sobre la barba, debajo de la cara de verdad.
ODIN_17_11 = {
    "00": [[232, 502, 831, 1265, 1.0]],
    "01": [[542, 1079, 1037, 1815, 0.864]],
    "02": [],
    "03": [[173, 512, 850, 1446, 1.0]],
    "04": [[27, 193, 188, 555, 0.875], [370, 988, 630, 1321, 0.635]],
    "05": [[172, 515, 875, 1458, 1.0]],
    "barba": [[359, 1130, 686, 1487, 0.974]],
}


@pytest.mark.parametrize("nombre", ODIN_17_11)
def test_cara_completa_solo_acepta_caras_reales(nombre):
    cara = cara_completa(np.array(ODIN_17_11[nombre]).reshape(-1, 5), 1080, 1920)
    assert (cara is not None) == (nombre in {"00", "03", "05"})


def test_portada_sale_de_una_cara_real_aunque_haya_falsos_mas_nitidos(tmp_path):
    from videopipeline.difusion import _elegir_portada

    # un momento por candidato; el 04 (falso positivo) es el más nítido
    nombres = ["00", "01", "02", "03", "04", "05"]
    instantes = momentos(100.0)
    nitida = np.zeros((1920, 1080, 3), np.uint8)
    nitida[::2] = 255
    borrosa = nitida.copy()
    borrosa[::4] = 0  # menos nítido, pero por encima del mínimo

    def nombre_en(f):
        return nombres[int(f[0, 0, 1])]

    def leer(v, t):
        i = min(range(6), key=lambda j: abs(instantes[j] - t))
        img = (nitida if nombres[i] == "04" else borrosa).copy()
        img[0, 0] = (0, i, 0)  # marca el candidato en un píxel
        return img

    cands = extraer_candidatos(Path("v.mp4"), [], tmp_path,
                               detector=lambda f: np.array(ODIN_17_11[nombre_en(f)]),
                               leer=leer, duracion=100.0)
    assert [c.cara is not None for c in cands] == [True, False, False, True, False, True]
    assert _elegir_portada(cands) in [cands[0], cands[3], cands[5]]


def test_prefiere_fotograma_con_cara_a_mas_nitido(tmp_path):
    con_cara = _nitida()[:, ::-1].copy()
    con_cara[::4] = 0  # menos nítido que _nitida, pero por encima del mínimo

    def leer(v, t):
        return con_cara if t == 51.0 else _nitida()

    def detector(f):
        if np.array_equal(f, cv2.cvtColor(con_cara, cv2.COLOR_BGR2RGB)):
            return np.array([[80, 20, 130, 85, 0.999]])
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


def test_el_detector_recibe_rgb(tmp_path):
    bgr = np.zeros((90, 160, 3), np.uint8)
    bgr[..., 0] = 255  # azul en BGR
    bgr[::2] = 255
    vistos = []

    def detector(f):
        vistos.append(f)
        return np.zeros((0, 5))

    extraer_candidatos(Path("v.mp4"), [], tmp_path, n=1, detector=detector,
                       leer=lambda v, t: bgr, duracion=100.0)
    assert vistos and all(np.array_equal(f, bgr[..., ::-1]) for f in vistos)
