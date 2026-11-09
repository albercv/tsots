"""Varios perfiles de publicación: ajustes, selector y diálogos (sin red ni Llavero real)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from app.credenciales import huella_perfil
from app.settings import Ajustes
from videopipeline.redes.modelo import (
    Ciudad, Cuenta, ModoFacebook, ModoInstagram, ModoTikTok, Pagina, Plataforma,
)
from videopipeline.redes.proveedor import PROVEEDOR_POR_DEFECTO as P

T, Y, I, X = Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM, Plataforma.X


def _q(tmp_path, nombre="t.ini") -> QSettings:
    return QSettings(str(tmp_path / nombre), QSettings.Format.IniFormat)


@pytest.fixture
def ajustes(tmp_path) -> Ajustes:
    return Ajustes(_q(tmp_path))


def _de_antes(q: QSettings) -> None:
    """Ajustes como los deja la versión de hoy: un perfil y todo global."""
    q.setValue(f"redes/perfil/{P}", "personal")
    q.setValue("redes/ciudad", "SEVILLA")
    q.setValue("caption/contexto_marca", "Soy Alberto")
    q.setValue("redes/tiktok_modo", "publico")
    q.setValue(f"redes/facebook_pagina/{P}", "111")
    q.setValue(f"redes/facebook_pagina_nombre/{P}", "Mi página")
    q.setValue("redes/plataformas", "tiktok,x")


def test_migracion_el_perfil_de_hoy_hereda_y_uno_nuevo_empieza_de_cero(tmp_path):
    q = _q(tmp_path)
    _de_antes(q)
    ajustes = Ajustes(q)
    assert ajustes.perfiles_de(P) == ["personal"]
    assert ajustes.ciudad is Ciudad.SEVILLA
    assert ajustes.contexto_marca == "Soy Alberto"
    assert ajustes.tiktok_modo == ModoTikTok.PUBLICO
    assert ajustes.pagina_facebook == Pagina("111", "Mi página")
    assert ajustes.plataformas_redes == [T, X]
    ajustes.perfil_redes = "sixpodcast"
    assert ajustes.perfiles_de(P) == ["personal", "sixpodcast"]
    assert ajustes.ciudad is Ciudad.MADRID
    assert ajustes.contexto_marca == ""
    assert ajustes.tiktok_modo == ModoTikTok.BORRADOR
    assert ajustes.pagina_facebook is None
    assert ajustes.plataformas_redes == [T, Y, I]


def test_la_migracion_es_una_sola_vez(tmp_path):
    q = _q(tmp_path)
    _de_antes(q)
    Ajustes(q).ciudad = Ciudad.BARCELONA
    q.setValue("redes/ciudad", "VALENCIA")  # una versión anterior la cambia después
    assert Ajustes(q).ciudad is Ciudad.BARCELONA


def test_version_anterior_sigue_leyendo_sus_claves(tmp_path):
    q = _q(tmp_path)
    _de_antes(q)
    ajustes = Ajustes(q)
    ajustes.ciudad = Ciudad.BARCELONA
    ajustes.contexto_marca = "Otra"
    assert q.value("redes/ciudad") == "SEVILLA"
    assert q.value("caption/contexto_marca") == "Soy Alberto"
    ajustes.perfil_redes = "sixpodcast"
    assert q.value(f"redes/perfil/{P}") == "sixpodcast"


def test_cambiar_el_activo_cambia_lo_que_leen_todas(ajustes):
    ajustes.perfil_redes = "personal"
    ajustes.ciudad = Ciudad.SEVILLA
    ajustes.contexto_marca = "A"
    ajustes.x_premium = True
    ajustes.youtube_categoria = "28"
    ajustes.instagram_modo = ModoInstagram.NORMAL
    ajustes.facebook_modo = ModoFacebook.VIDEO
    ajustes.plataformas_redes = [X]
    ajustes.pagina_facebook = Pagina("1", "A")
    ajustes.guardar_cuentas({T: Cuenta(T, "A")})
    ajustes.perfil_redes = "six"
    assert (ajustes.ciudad, ajustes.contexto_marca, ajustes.x_premium,
            ajustes.youtube_categoria, ajustes.instagram_modo, ajustes.facebook_modo,
            ajustes.plataformas_redes, ajustes.pagina_facebook, ajustes.cuentas_guardadas()) == (
        Ciudad.MADRID, "", False, "22", ModoInstagram.PRUEBA, ModoFacebook.REEL,
        [T, Y, I], None, None)
    ajustes.perfil_redes = "personal"
    assert ajustes.ciudad is Ciudad.SEVILLA and ajustes.x_premium is True
    assert ajustes.plataformas_redes == [X]
    assert ajustes.cuentas_guardadas().cuentas == {T: Cuenta(T, "A")}
    assert ajustes.ajustes_proveedor() == {"perfil": "personal", "pagina_facebook": "1"}


def test_sin_perfil_activo_se_usan_las_claves_de_siempre(ajustes):
    """Quien nunca configuró Redes conserva su contexto de marca."""
    ajustes.contexto_marca = "Marca"
    assert ajustes._q.value("caption/contexto_marca") == "Marca"
    assert ajustes.perfiles_de(P) == []
    ajustes.perfil_redes = "yo"  # el primero hereda lo de siempre
    assert ajustes.contexto_marca == "Marca"
    ajustes.perfil_redes = "otro"
    assert ajustes.contexto_marca == ""


def test_anadir_no_duplica_y_quitar_borra_sus_datos(ajustes):
    ajustes.perfil_redes = "personal"
    for nombre in (" six ", "six", ""):
        ajustes.anadir_perfil(P, nombre)
    assert ajustes.perfiles_de(P) == ["personal", "six"]
    six = ajustes.de_perfil(P, "six")
    six.ciudad = Ciudad.SEVILLA
    six.contexto_marca = "S"
    ajustes.quitar_perfil(P, "six")
    assert ajustes.perfiles_de(P) == ["personal"]
    assert ajustes.de_perfil(P, "six").ciudad is Ciudad.MADRID
    assert ajustes.de_perfil(P, "six").contexto_marca == ""
    assert not any(huella_perfil("six") in k for k in ajustes._q.allKeys())
    assert ajustes.perfil_redes == "personal"


def test_quitar_el_activo_deja_activo_el_siguiente_o_ninguno(ajustes):
    ajustes.perfil_redes = "personal"
    ajustes.anadir_perfil(P, "six")
    ajustes.quitar_perfil(P, "personal")
    assert ajustes.perfil_redes == "six"
    ajustes.quitar_perfil(P, "six")
    assert ajustes.perfil_redes == "" and ajustes.perfiles_de(P) == []


def test_de_perfil_lee_y_escribe_otro_sin_cambiar_el_activo(ajustes):
    ajustes.perfil_redes = "personal"
    six = ajustes.de_perfil(P, "six")
    six.tiktok_modo = ModoTikTok.PUBLICO
    six.pagina_facebook = Pagina("2", "Six")
    assert ajustes.perfil_redes == "personal" and ajustes.perfiles_de(P) == ["personal"]
    assert ajustes.tiktok_modo == ModoTikTok.BORRADOR and ajustes.pagina_facebook is None
    assert six.ajustes_proveedor() == {"perfil": "six", "pagina_facebook": "2"}


@pytest.mark.parametrize("nombre", ["mi perfil/2", "  señal ñ 🎙  ", "a/b\\c d"])
def test_perfil_con_barras_espacios_o_unicode(tmp_path, nombre):
    a = Ajustes(_q(tmp_path, "p.ini"))
    a.perfil_redes = nombre
    a.ciudad = Ciudad.SEVILLA
    a.contexto_marca = "M"
    a._q.sync()
    b = Ajustes(_q(tmp_path, "p.ini"))
    assert b.perfil_redes == nombre.strip()
    assert b.perfiles_de(P) == [nombre.strip()]
    assert b.ciudad is Ciudad.SEVILLA and b.contexto_marca == "M"
    assert all(nombre.strip() not in k for k in b._q.allKeys())


def test_lista_de_perfiles_estropeada_es_vacia(ajustes):
    ajustes._q.setValue(f"redes/perfiles/{P}", "{no es json")
    assert ajustes.perfiles_de(P) == []
    ajustes._q.setValue(f"redes/perfiles/{P}", '["ok", 5, "  "]')
    assert ajustes.perfiles_de(P) == ["ok"]
