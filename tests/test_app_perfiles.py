"""Varios perfiles de publicación: ajustes, selector y diálogos (sin red ni Llavero real)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from app import credenciales, cuentas
from app.credenciales import huella_perfil
from app.settings import Ajustes
from app.widgets.dialogo_redes import DialogoRedes
from app.widgets.selector_perfil import SelectorPerfil
from tests.redes_falsos import ProveedorFalso
from tests.test_app_redes import CLAVE, _esperar_consultas, _redes
from videopipeline.redes.modelo import (
    Ciudad, Cuenta, ModoFacebook, ModoInstagram, ModoTikTok, Pagina, Plataforma,
)
from videopipeline.redes.proveedor import PROVEEDOR_POR_DEFECTO as P, ErrorConsulta

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


def test_listar_perfiles_nunca_lanza(llavero_falso):
    pedidos = []

    def fabrica(perfiles):
        def crear(nombre, clave, datos):
            pedidos.append((clave, datos))
            return ProveedorFalso(perfiles_cuenta=perfiles)
        return crear

    assert cuentas.listar_perfiles(credenciales, fabrica(["a"]), P) == (
        None, "Falta la API key del servicio: guárdala en Redes…")
    assert cuentas.listar_perfiles(credenciales, fabrica(["a", "b"]), P, clave="k") == (
        ["a", "b"], "")
    assert pedidos[-1] == ("k", {"perfil": "", "pagina_facebook": ""})
    assert cuentas.listar_perfiles(credenciales, fabrica(ErrorConsulta("401 mala")), P,
                                   clave="k") == (None, "401 mala")
    perfiles, motivo = cuentas.listar_perfiles(
        credenciales, fabrica(RuntimeError("clave-secreta")), P, clave="clave-secreta")
    assert perfiles is None and "RuntimeError" in motivo and "clave-secreta" not in motivo


def _elegir(combo, texto: str) -> None:
    """Como el usuario: marca la entrada y emite `activated`."""
    indice = combo.findText(texto)
    assert indice >= 0, texto
    combo.setCurrentIndex(indice)
    combo.activated.emit(indice)


def test_selector_lista_los_perfiles_y_avisa_solo_si_el_usuario_cambia(qtbot, ajustes):
    ajustes.perfil_redes = "personal"
    ajustes.anadir_perfil(P, "six")
    selector = SelectorPerfil()
    qtbot.addWidget(selector)
    elegidos: list[str] = []
    selector.perfil_elegido.connect(elegidos.append)
    selector.recargar(ajustes)
    assert [selector.itemText(i) for i in range(selector.count())] == ["personal", "six"]
    assert selector.currentText() == "personal"
    assert elegidos == []
    _elegir(selector, "six")
    assert elegidos == ["six"]
    selector.activated.emit(selector.currentIndex())  # la misma otra vez
    assert elegidos == ["six"]


def test_selector_sin_perfiles(qtbot, ajustes):
    selector = SelectorPerfil()
    qtbot.addWidget(selector)
    elegidos: list[str] = []
    selector.perfil_elegido.connect(elegidos.append)
    selector.recargar(ajustes)
    assert selector.count() == 1
    assert selector.itemText(0) == "Sin perfil: añádelo en Redes…"
    assert not selector.model().item(0).isEnabled()
    selector.activated.emit(0)
    assert elegidos == []


def test_selector_sin_perfil_activo_entre_los_de_la_lista_no_marca_ninguno(qtbot, ajustes):
    ajustes.anadir_perfil(P, "personal")
    ajustes.perfil_redes = ""
    selector = SelectorPerfil()
    qtbot.addWidget(selector)
    selector.recargar(ajustes)
    assert selector.count() == 1 and selector.currentIndex() == -1


def _dos_perfiles(ajustes) -> None:
    """«personal» (activo) y «six», con datos distintos."""
    ajustes.perfil_redes = "personal"
    ajustes.tiktok_modo = ModoTikTok.PUBLICO
    ajustes.pagina_facebook = Pagina("111", "Personal")
    ajustes.plataformas_redes = [T]
    ajustes.guardar_cuentas({T: Cuenta(T, "Personal TT")})
    ajustes.anadir_perfil(P, "six")
    six = ajustes.de_perfil(P, "six")
    six.ciudad = Ciudad.SEVILLA
    six.x_premium = True
    six.youtube_categoria = "28"
    six.pagina_facebook = Pagina("222", "Six")
    six.plataformas_redes = [Y]
    six.guardar_cuentas({T: Cuenta(T, "Six TT")})


def _responder_redes(monkeypatch, respuesta):
    preguntas = []

    def pregunta(*args, **kwargs):
        preguntas.append(args[2])
        return respuesta

    monkeypatch.setattr("app.widgets.dialogo_redes.QMessageBox.question", pregunta)
    return preguntas


def test_redes_carga_los_datos_del_perfil_elegido_y_guarda_en_el(qtbot, ajustes,
                                                                  llavero_falso):
    _dos_perfiles(ajustes)
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    combo = dialogo.combo_perfil
    assert [combo.itemText(i) for i in range(combo.count())] == ["personal", "six"]
    assert dialogo.campo_perfil.text() == "personal"
    assert dialogo.combo_tiktok.currentData() == ModoTikTok.PUBLICO.value
    _elegir(combo, "six")
    assert dialogo.combo_tiktok.currentData() == ModoTikTok.BORRADOR.value
    assert dialogo.casilla_x_premium.isChecked()
    assert dialogo.combo_categoria.currentData() == "28"
    assert dialogo.pagina_elegida() == Pagina("222", "Six")
    assert dialogo.etiqueta_ubicacion.text().startswith("Sevilla")
    assert "Six TT" in dialogo.etiquetas_cuentas[T].text()
    dialogo.combo_instagram.setCurrentIndex(
        dialogo.combo_instagram.findData(ModoInstagram.NORMAL.value))
    dialogo.accept()
    assert ajustes.perfil_redes == "six"
    assert ajustes.instagram_modo == ModoInstagram.NORMAL
    personal = ajustes.de_perfil(P, "personal")
    assert personal.tiktok_modo == ModoTikTok.PUBLICO
    assert personal.instagram_modo == ModoInstagram.PRUEBA
    assert personal.pagina_facebook == Pagina("111", "Personal")


def test_cancelar_redes_no_cambia_el_perfil_activo(qtbot, ajustes, llavero_falso):
    _dos_perfiles(ajustes)
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    _elegir(dialogo.combo_perfil, "six")
    dialogo.reject()
    assert ajustes.perfil_redes == "personal"


def test_escribir_un_perfil_nuevo_empieza_con_los_valores_de_siempre(qtbot, ajustes,
                                                                      llavero_falso):
    _dos_perfiles(ajustes)
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    dialogo.campo_perfil.setText("nuevo")
    dialogo.campo_perfil.editingFinished.emit()
    assert dialogo.combo_tiktok.currentData() == ModoTikTok.BORRADOR.value
    assert dialogo.pagina_elegida() is None
    assert not dialogo.boton_quitar_perfil.isEnabled()
    dialogo.accept()
    assert ajustes.perfiles_de(P) == ["personal", "six", "nuevo"]
    assert ajustes.tiktok_modo == ModoTikTok.BORRADOR


def test_buscar_perfiles_anade_los_del_servicio(qtbot, ajustes, llavero_falso):
    ajustes.perfil_redes = "personal"
    capturado: dict = {}
    dialogo = _redes(qtbot, ajustes, ProveedorFalso(perfiles_cuenta=["personal", "six"]),
                     capturado)
    dialogo.campo_clave.setText(CLAVE)
    dialogo.boton_buscar_perfiles.click()
    _esperar_consultas(qtbot)
    assert capturado["clave"] == CLAVE and capturado["datos"]["perfil"] == ""
    combo = dialogo.combo_perfil
    assert [combo.itemText(i) for i in range(combo.count())] == ["personal", "six"]
    assert ajustes.perfiles_de(P) == ["personal", "six"]
    assert dialogo.campo_perfil.text() == "personal"  # lo escrito no cambia
    assert "six" in dialogo.etiqueta_consulta.text()
    assert dialogo.boton_buscar_perfiles.isEnabled()


def test_si_la_lista_falla_el_perfil_se_escribe_a_mano(qtbot, ajustes, llavero_falso):
    credenciales.guardar(P, CLAVE)
    dialogo = _redes(qtbot, ajustes, ProveedorFalso(perfiles_cuenta=ErrorConsulta(
        "Respuesta inesperada del servicio: no trae los perfiles.")))
    dialogo.boton_buscar_perfiles.click()
    _esperar_consultas(qtbot)
    assert "no trae los perfiles" in dialogo.etiqueta_consulta.text()
    assert CLAVE not in dialogo.etiqueta_consulta.text()
    assert dialogo.boton_buscar_perfiles.isEnabled()
    dialogo.campo_perfil.setText("a_mano")
    dialogo.accept()
    assert ajustes.perfil_redes == "a_mano" and ajustes.perfiles_de(P) == ["a_mano"]


def test_quitar_perfil_pide_confirmacion_y_borra_sus_datos(qtbot, ajustes, llavero_falso,
                                                           monkeypatch):
    _dos_perfiles(ajustes)
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    _elegir(dialogo.combo_perfil, "six")
    assert dialogo.boton_quitar_perfil.isEnabled()
    preguntas = _responder_redes(monkeypatch, QMessageBox.StandardButton.No)
    dialogo.boton_quitar_perfil.click()
    assert "six" in preguntas[0] and ajustes.perfiles_de(P) == ["personal", "six"]
    _responder_redes(monkeypatch, QMessageBox.StandardButton.Yes)
    dialogo.boton_quitar_perfil.click()
    assert ajustes.perfiles_de(P) == ["personal"]
    assert ajustes.de_perfil(P, "six").x_premium is False
    assert dialogo.campo_perfil.text() == "personal"
    assert dialogo.combo_tiktok.currentData() == ModoTikTok.PUBLICO.value


def test_escribir_un_perfil_nuevo_y_guardar_sin_perder_el_foco(qtbot, ajustes,
                                                               llavero_falso):
    """En macOS Guardar no quita el foco al campo: no sale `editingFinished`."""
    _dos_perfiles(ajustes)
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    dialogo.campo_perfil.setText("")
    QTest.keyClicks(dialogo.campo_perfil, "sixpodcast")
    assert dialogo.pagina_elegida() is None
    assert dialogo.combo_tiktok.currentData() == ModoTikTok.BORRADOR.value
    dialogo.combo_instagram.setCurrentIndex(
        dialogo.combo_instagram.findData(ModoInstagram.NORMAL.value))
    dialogo.accept()
    assert ajustes.perfil_redes == "sixpodcast"
    nuevo = ajustes.de_perfil(P, "sixpodcast")
    assert nuevo.pagina_facebook is None
    assert nuevo.instagram_modo == ModoInstagram.NORMAL  # lo editado después se guarda
    personal = ajustes.de_perfil(P, "personal")
    assert personal.pagina_facebook == Pagina("111", "Personal")
    assert personal.tiktok_modo == ModoTikTok.PUBLICO
    assert personal.instagram_modo == ModoInstagram.PRUEBA
