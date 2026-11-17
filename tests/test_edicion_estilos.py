import pytest

from videopipeline.edicion.estilos import IDS, cargar


def test_cargar_los_tres_estilos():
    for i in IDS:
        assert cargar(i).id == i


def test_estilo_inexistente():
    with pytest.raises(ValueError):
        cargar("neon")


def test_divertido_permite_emojis_y_formal_no():
    assert "emoji" in cargar("divertido").tipos
    assert "emoji" not in cargar("formal").tipos
    assert "golpe" not in cargar("academico").tipos


def test_densidades_de_la_tabla():
    assert cargar("divertido").densidad_max == 0.4
    assert cargar("formal").densidad_max == pytest.approx(1 / 6)
    assert cargar("academico").densidad_max == 0.2


def test_academico_musica_suave_y_sin_zoom():
    e = cargar("academico")
    assert (e.musica["db"], e.musica["progresion"]) == (-24, "tranquila")
    assert e.zoom_max == 0 and e.zoom_lento == 0


def test_titulo_en_todos_y_formal_sin_zoom_de_golpe():
    for i in IDS:
        assert "titulo" in cargar(i).tipos
    assert "zoom" not in cargar("formal").tipos
