"""Ubicación de las publicaciones: catálogo de ciudades, tipos neutros y
búsqueda del lugar de TikTok."""
from __future__ import annotations

import logging

import pytest

from tests.redes_falsos import ProveedorFalso
from videopipeline.redes import publicador
from videopipeline.redes.modelo import (
    UBICACION_POR_DEFECTO,
    Ciudad,
    Lugar,
    Opciones,
    Plataforma,
    Publicacion,
    Ubicacion,
    elegir_lugar,
    id_instagram_valido,
    id_x_valido,
)
from videopipeline.redes.proveedor import ErrorConsulta

T, Y, I = Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM
X, F = Plataforma.X, Plataforma.FACEBOOK

# Lugares de TikTok falsos: los de verdad son de la cuenta y nunca van al repo.
MADRID = Lugar("v2_madrid", "Madrid", "Comunidad de Madrid, España")
BARAJAS = Lugar("v2_barajas", "Aeropuerto Madrid-Barajas", "Madrid")


@pytest.fixture
def pub(tmp_path) -> Publicacion:
    video = tmp_path / "clip_limpio.mp4"
    video.write_bytes(b"MP4")
    return Publicacion(video=video, titulo="t", caption="c", hashtags=("#a",))


# --- catálogo ---


def test_madrid_trae_sus_ids_publicos():
    # Facebook Places de Madrid (Wikidata Q2807, P1997) y lugar de X «Madrid, España».
    assert Ciudad.MADRID.nombre == "Madrid"
    assert Ciudad.MADRID.instagram_id == "106504859386230"
    assert Ciudad.MADRID.x_id == "206c436ce43a43a3"


@pytest.mark.parametrize("ciudad", list(Ciudad))
def test_cada_ciudad_del_catalogo_es_valida(ciudad):
    assert ciudad.nombre.strip()
    assert not ciudad.instagram_id or id_instagram_valido(ciudad.instagram_id)
    assert not ciudad.x_id or id_x_valido(ciudad.x_id)


def test_nombres_del_catalogo_sin_repetir():
    nombres = [c.nombre.casefold() for c in Ciudad]
    assert len(nombres) == len(set(nombres))


def test_ciudad_por_clave_guardada():
    assert Ciudad.de_clave("MADRID") is Ciudad.MADRID
    assert Ciudad.de_clave("ATLANTIDA") is None
    assert Ciudad.de_clave("") is None


def test_madrid_por_defecto_en_las_tres_redes():
    assert UBICACION_POR_DEFECTO == Ubicacion(Ciudad.MADRID)
    assert UBICACION_POR_DEFECTO.plataformas() == (T, I, X)
    assert Opciones().ubicacion == Ubicacion()


# --- ubicación ---


@pytest.mark.parametrize("ubicacion, plataformas", [
    (Ubicacion(), ()),
    (Ubicacion(Ciudad.MADRID), (T, I, X)),  # TikTok busca la ciudad al publicar
    (Ubicacion(Ciudad.MADRID, tiktok=BARAJAS), (T, I, X)),
    (Ubicacion(tiktok=MADRID), (T,)),
])
def test_plataformas_que_llevan_la_ubicacion(ubicacion, plataformas):
    assert ubicacion.plataformas() == plataformas


def test_ids_y_nombre_salen_de_la_ciudad():
    ubicacion = Ubicacion(Ciudad.MADRID)
    assert ubicacion.nombre == "Madrid"
    assert ubicacion.instagram_id == Ciudad.MADRID.instagram_id
    assert ubicacion.x_id == Ciudad.MADRID.x_id
    assert Ubicacion().nombre == Ubicacion().instagram_id == Ubicacion().x_id == ""


def test_visible_es_la_ciudad_o_el_lugar():
    assert Ubicacion(Ciudad.MADRID, tiktok=BARAJAS).visible == "Madrid"
    assert Ubicacion(tiktok=MADRID).visible == "Madrid"
    assert Ubicacion().visible == ""
    assert MADRID.visible == "Madrid · Comunidad de Madrid, España"
    assert Lugar("1", "Sol").visible == "Sol"


def test_el_id_de_tiktok_no_sale_al_imprimir():
    """El id de un lugar de TikTok es de la cuenta: ni en `repr` ni en `str`."""
    opciones = Opciones(ubicacion=Ubicacion(Ciudad.MADRID, tiktok=MADRID))
    for texto in (repr(MADRID), str(MADRID), repr(opciones), str(opciones)):
        assert "v2_madrid" not in texto


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


def test_tiktok_busca_el_lugar_de_la_ciudad_al_publicar(pub, caplog):
    caplog.set_level(logging.DEBUG, logger="videopipeline.redes")
    proveedor = ProveedorFalso(lugares=[BARAJAS, MADRID])
    resultados = _publicar(proveedor, pub, [T, I], Ubicacion(Ciudad.MADRID))
    assert resultados[T].ok and resultados[I].ok
    assert proveedor.consultas == ["lugares:Madrid"]
    assert _ubicacion_enviada(proveedor, T) == Ubicacion(Ciudad.MADRID, tiktok=MADRID)
    # Las demás redes reciben la ubicación tal cual.
    assert _ubicacion_enviada(proveedor, I) == Ubicacion(Ciudad.MADRID)
    assert "Madrid" in caplog.text and "v2_madrid" not in caplog.text


def test_tiktok_sin_lugar_que_se_llame_igual_publica_sin_ubicacion(pub):
    proveedor = ProveedorFalso(lugares=[BARAJAS])
    resultados = _publicar(proveedor, pub, [T], Ubicacion(Ciudad.MADRID))
    assert resultados[T].ok
    assert _ubicacion_enviada(proveedor, T).tiktok is None


def test_tiktok_si_la_busqueda_falla_publica_igual(pub):
    proveedor = ProveedorFalso(lugares=ErrorConsulta("Reconecta TikTok"))
    resultados = _publicar(proveedor, pub, [T, X], Ubicacion(Ciudad.MADRID))
    assert resultados[T].ok and resultados[X].ok
    assert _ubicacion_enviada(proveedor, T).tiktok is None
    assert _ubicacion_enviada(proveedor, X).x_id == Ciudad.MADRID.x_id


def test_tiktok_con_lugar_elegido_no_busca(pub):
    proveedor = ProveedorFalso(lugares=[BARAJAS])
    _publicar(proveedor, pub, [T], Ubicacion(Ciudad.MADRID, tiktok=MADRID))
    assert proveedor.consultas == []
    assert _ubicacion_enviada(proveedor, T).tiktok == MADRID


@pytest.mark.parametrize("plataformas, ubicacion", [([Y, I], Ubicacion(Ciudad.MADRID)),
                                                    ([T], Ubicacion())])
def test_sin_tiktok_o_sin_ciudad_no_busca(pub, plataformas, ubicacion):
    proveedor = ProveedorFalso(lugares=[MADRID])
    _publicar(proveedor, pub, plataformas, ubicacion)
    assert proveedor.consultas == []
