"""Límites de vídeo de X (regla de la plataforma, no del proveedor)."""
from __future__ import annotations

import pytest

from videopipeline.redes.limites import (
    MAX_DURACION_X,
    MAX_TAMANO_X,
    duracion_legible,
    motivo_no_admite_x,
)

MB = 1024 * 1024


def test_limites_de_x_sin_premium():
    assert MAX_DURACION_X == 140
    assert MAX_TAMANO_X == 512 * MB


@pytest.mark.parametrize("segundos, texto", [
    (0, "0:00"), (59.2, "1:00"), (140, "2:20"), (167.1, "2:48"), (3725, "1:02:05"),
])
def test_duracion_legible(segundos, texto):
    assert duracion_legible(segundos) == texto


def test_video_corto_y_ligero_se_admite():
    assert motivo_no_admite_x(140.0, 512 * MB, premium=False) == ""
    assert motivo_no_admite_x(30.0, 10 * MB, premium=False) == ""


def test_video_largo_sin_premium_explica_el_motivo():
    motivo = motivo_no_admite_x(167.4, 10 * MB, premium=False)
    assert motivo == "X sin Premium admite vídeos de hasta 2:20; este dura 2:48."


def test_video_pesado_sin_premium_explica_el_motivo():
    motivo = motivo_no_admite_x(60.0, 610 * MB, premium=False)
    assert motivo == "X sin Premium admite vídeos de hasta 512 MB; este ocupa 610 MB."


def test_con_premium_no_se_limita():
    assert motivo_no_admite_x(3600.0, 4000 * MB, premium=True) == ""


def test_duracion_o_tamano_desconocidos_no_bloquean():
    assert motivo_no_admite_x(None, 10 * MB, premium=False) == ""
    assert motivo_no_admite_x(0.0, None, premium=False) == ""
    assert "512 MB" in motivo_no_admite_x(None, 600 * MB, premium=False)
