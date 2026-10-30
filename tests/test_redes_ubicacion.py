"""Ubicación de las publicaciones: tipos neutros y búsqueda del lugar de TikTok."""
from __future__ import annotations

import pytest

from tests.redes_falsos import ProveedorFalso
from videopipeline.redes import publicador
from videopipeline.redes.modelo import (
    UBICACION_POR_DEFECTO,
    Lugar,
    Opciones,
    Plataforma,
    Publicacion,
    Ubicacion,
    elegir_lugar,
    id_instagram_valido,
    id_x_valido,
    ubicacion_conocida,
)
from videopipeline.redes.proveedor import ErrorConsulta

T, Y, I = Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM
X, F = Plataforma.X, Plataforma.FACEBOOK

MADRID = Lugar("v2_madrid", "Madrid", "Comunidad de Madrid, España")
BARAJAS = Lugar("v2_barajas", "Aeropuerto Madrid-Barajas", "Madrid")


@pytest.fixture
def pub(tmp_path) -> Publicacion:
    video = tmp_path / "clip_limpio.mp4"
    video.write_bytes(b"MP4")
    return Publicacion(video=video, titulo="t", caption="c", hashtags=("#a",))


def test_madrid_por_defecto_en_las_tres_redes():
    # Facebook Places de Madrid (Wikidata Q2807, P1997) y lugar de X «Madrid, España».
    assert UBICACION_POR_DEFECTO == Ubicacion("Madrid", instagram_id="106504859386230",
                                              x_id="206c436ce43a43a3")
    assert UBICACION_POR_DEFECTO.plataformas() == (T, I, X)
    assert Opciones().ubicacion == Ubicacion()


@pytest.mark.parametrize("nombre", ["Madrid", "  madrid ", "MADRID"])
def test_madrid_es_un_lugar_conocido(nombre):
    assert ubicacion_conocida(nombre) == UBICACION_POR_DEFECTO


@pytest.mark.parametrize("nombre", ["Sevilla", "", "Madrid centro"])
def test_otros_lugares_no_son_conocidos(nombre):
    assert ubicacion_conocida(nombre) is None


@pytest.mark.parametrize("ubicacion, plataformas", [
    (Ubicacion(), ()),
    (Ubicacion("Madrid"), (T,)),  # TikTok la busca por nombre al publicar
    (Ubicacion(tiktok=MADRID), (T,)),
    (Ubicacion("Madrid", instagram_id="110184922344060", x_id="01a9a39529b27f36"), (T, I, X)),
    (Ubicacion(instagram_id="Madrid", x_id="no vale"), ()),  # IDs inválidos: no se envían
    (Ubicacion("  ", instagram_id=" 123 "), (I,)),
])
def test_plataformas_que_llevan_la_ubicacion(ubicacion, plataformas):
    assert ubicacion.plataformas() == plataformas


def test_visible_prefiere_el_nombre_escrito():
    assert Ubicacion("Madrid", tiktok=BARAJAS).visible == "Madrid"
    assert Ubicacion(tiktok=MADRID).visible == "Madrid"
    assert Ubicacion(instagram_id="123").visible == ""
    assert MADRID.visible == "Madrid · Comunidad de Madrid, España"
    assert Lugar("1", "Sol").visible == "Sol"


@pytest.mark.parametrize("texto, valido", [
    ("110184922344060", True), (" 123 ", True), ("", False), ("Madrid", False), ("12a", False)])
def test_id_de_instagram(texto, valido):
    assert id_instagram_valido(texto) is valido


@pytest.mark.parametrize("texto, valido", [
    ("01a9a39529b27f36", True), ("01A9A395", True), ("", False), ("Madrid", False),
    ("01a9 a395", False)])
def test_id_de_x(texto, valido):
    assert id_x_valido(texto) is valido


@pytest.mark.parametrize("lugares, nombre, esperado", [
    ([BARAJAS, MADRID], "Madrid", MADRID),
    ([BARAJAS, MADRID], "  madrid ", MADRID),
    ([Lugar("1", "Málaga")], "malaga", Lugar("1", "Málaga")),
    ([Lugar("1", "Madrid, Spain")], "Madrid", Lugar("1", "Madrid, Spain")),
    ([BARAJAS], "Madrid", None),  # ninguno se llama así: no se adivina
    ([], "Madrid", None),
    ([MADRID], "", None),
])
def test_elegir_lugar_solo_si_se_llama_igual(lugares, nombre, esperado):
    assert elegir_lugar(lugares, nombre) == esperado


# --- búsqueda al publicar en TikTok ---


def _publicar(proveedor, pub, plataformas, ubicacion):
    return publicador.publicar(proveedor, pub, Opciones(ubicacion=ubicacion), plataformas,
                               nombre_proveedor="falso", espera=lambda s: None,
                               registrar=False)


def _ubicacion_enviada(proveedor, plataforma):
    return next(c[3].ubicacion for c in proveedor.llamadas
                if c[0] == "publicar" and c[1] == plataforma)


def test_tiktok_busca_el_lugar_por_nombre_al_publicar(pub):
    proveedor = ProveedorFalso(lugares=[BARAJAS, MADRID])
    resultados = _publicar(proveedor, pub, [T, I], Ubicacion("Madrid", instagram_id="123"))
    assert resultados[T].ok and resultados[I].ok
    assert proveedor.consultas == ["lugares:Madrid"]
    assert _ubicacion_enviada(proveedor, T) == Ubicacion("Madrid", tiktok=MADRID,
                                                         instagram_id="123")
    # Las demás redes reciben la ubicación tal cual.
    assert _ubicacion_enviada(proveedor, I) == Ubicacion("Madrid", instagram_id="123")


def test_tiktok_sin_lugar_que_se_llame_igual_publica_sin_ubicacion(pub):
    proveedor = ProveedorFalso(lugares=[BARAJAS])
    resultados = _publicar(proveedor, pub, [T], Ubicacion("Madrid"))
    assert resultados[T].ok
    assert _ubicacion_enviada(proveedor, T).tiktok is None


def test_tiktok_si_la_busqueda_falla_publica_igual(pub):
    proveedor = ProveedorFalso(lugares=ErrorConsulta("Reconecta TikTok"))
    resultados = _publicar(proveedor, pub, [T, X], Ubicacion("Madrid", x_id="01a9a395"))
    assert resultados[T].ok and resultados[X].ok
    assert _ubicacion_enviada(proveedor, T).tiktok is None
    assert _ubicacion_enviada(proveedor, X).x_id == "01a9a395"


def test_tiktok_con_lugar_elegido_no_busca(pub):
    proveedor = ProveedorFalso(lugares=[BARAJAS])
    _publicar(proveedor, pub, [T], Ubicacion("Madrid", tiktok=MADRID))
    assert proveedor.consultas == []
    assert _ubicacion_enviada(proveedor, T).tiktok == MADRID


@pytest.mark.parametrize("plataformas, ubicacion", [([Y, I], Ubicacion("Madrid")),
                                                    ([T], Ubicacion())])
def test_sin_tiktok_o_sin_nombre_no_busca(pub, plataformas, ubicacion):
    proveedor = ProveedorFalso(lugares=[MADRID])
    _publicar(proveedor, pub, plataformas, ubicacion)
    assert proveedor.consultas == []
