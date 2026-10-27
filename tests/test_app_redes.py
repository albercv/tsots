"""Ajustes de redes, diálogo Redes… y diálogo Publicar (sin red ni Llavero real)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLineEdit, QMessageBox

from app import credenciales, segundo_plano
from app.settings import Ajustes
from app.widgets import dialogo_publicar
from app.widgets.dialogo_publicar import DialogoPublicar
from app.widgets.dialogo_redes import DialogoRedes
from tests.redes_falsos import ProveedorFalso, todas_conectadas
from videopipeline.caption import Caption
from videopipeline.redes import publicador, registro
from videopipeline.redes.modelo import (
    ORDEN,
    Cuenta,
    ModoFacebook,
    ModoInstagram,
    ModoTikTok,
    Pagina,
    Plataforma,
    Resultado,
)
from videopipeline.redes.proveedor import PROVEEDOR_POR_DEFECTO, ErrorConsulta
from videopipeline.redes.textos import longitud_x

T, Y, I = Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM
X, F = Plataforma.X, Plataforma.FACEBOOK
CLAVE = "clave-de-prueba-42"
MB = 1024 * 1024


@pytest.fixture(autouse=True)
def sin_hilos_colgando(qtbot):
    """Ningún test acaba con una publicación ni una consulta en marcha."""
    yield
    qtbot.waitUntil(lambda: dialogo_publicar.hilos_vivos() == 0, timeout=10000)
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=10000)


@pytest.fixture(autouse=True)
def duracion_falsa(monkeypatch):
    """Sin ffprobe: el vídeo de los tests dura 30 s salvo que el test diga otra cosa."""
    medidas: list = []

    def medir(video):
        medidas.append(video)
        return 30.0

    monkeypatch.setattr(dialogo_publicar, "medir_duracion", medir)
    return medidas


@pytest.fixture
def ajustes(tmp_path) -> Ajustes:
    return Ajustes(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))


@pytest.fixture
def video(tmp_path) -> Path:
    ruta = tmp_path / "clip_limpio.mp4"
    ruta.write_bytes(b"MP4")
    return ruta


def _caption() -> Caption:
    return Caption(titulo="Título X", caption="Cuerpo del caption",
                   hashtags=["#ia", "#pymes"], palabras_clave=["ia", "pymes"])


def _listo(ajustes, llavero_falso):
    ajustes.perfil_redes = "mi_perfil"
    credenciales.guardar(PROVEEDOR_POR_DEFECTO, CLAVE)


def _esperar_consultas(qtbot):
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=5000)


# --- ajustes ---


def test_ajustes_redes_por_defecto(ajustes):
    assert ajustes.proveedor_redes == PROVEEDOR_POR_DEFECTO
    assert ajustes.perfil_redes == ""
    assert ajustes.youtube_categoria == "22"
    assert ajustes.tiktok_modo == ModoTikTok.BORRADOR
    assert ajustes.instagram_modo == ModoInstagram.PRUEBA
    # X y Facebook se activan a mano la primera vez.
    assert ajustes.plataformas_redes == [T, Y, I]
    assert ajustes.x_premium is False
    assert ajustes.facebook_modo == ModoFacebook.REEL
    assert ajustes.pagina_facebook is None
    assert ajustes.cuentas_guardadas() is None


def test_ajustes_redes_persisten(tmp_path):
    ruta = str(tmp_path / "p.ini")
    a = Ajustes(QSettings(ruta, QSettings.Format.IniFormat))
    a.perfil_redes = " yo "
    a.youtube_categoria = "28"
    a.tiktok_modo = ModoTikTok.PUBLICO
    a.instagram_modo = ModoInstagram.NORMAL
    a.plataformas_redes = [I, T]
    a.x_premium = True
    a.facebook_modo = ModoFacebook.VIDEO
    a.pagina_facebook = Pagina("111", "Mi página")
    a._q.sync()
    b = Ajustes(QSettings(ruta, QSettings.Format.IniFormat))
    assert b.perfil_redes == "yo"
    assert b.ajustes_proveedor() == {"perfil": "yo", "pagina_facebook": "111"}
    assert b.x_premium is True
    assert b.facebook_modo == ModoFacebook.VIDEO
    assert b.pagina_facebook == Pagina("111", "Mi página")
    assert b.youtube_categoria == "28"
    assert b.tiktok_modo == ModoTikTok.PUBLICO
    assert b.instagram_modo == ModoInstagram.NORMAL
    assert b.plataformas_redes == [T, I]
    b.plataformas_redes = []
    assert b.plataformas_redes == []


def test_ajustes_valores_corruptos_vuelven_al_defecto(ajustes):
    ajustes._q.setValue("redes/proveedor", "desconocido")
    ajustes._q.setValue("redes/tiktok_modo", "raro")
    ajustes._q.setValue("redes/instagram_modo", "raro")
    ajustes._q.setValue("redes/facebook_modo", "raro")
    ajustes._q.setValue("redes/x_premium", "quizá")
    assert ajustes.proveedor_redes == PROVEEDOR_POR_DEFECTO
    assert ajustes.tiktok_modo == ModoTikTok.BORRADOR
    assert ajustes.instagram_modo == ModoInstagram.PRUEBA
    assert ajustes.facebook_modo == ModoFacebook.REEL
    assert ajustes.x_premium is False


@pytest.mark.parametrize("valor, esperado", [("true", True), ("false", False), (True, True),
                                             ("1", True), ("0", False)])
def test_ajustes_x_premium_tolera_formatos(ajustes, valor, esperado):
    ajustes._q.setValue("redes/x_premium", valor)
    assert ajustes.x_premium is esperado


def test_eleccion_guardada_sin_x_ni_facebook_sigue_valiendo(ajustes):
    """Usuarios con la elección de antes: X y Facebook quedan desmarcadas."""
    ajustes._q.setValue("redes/plataformas", "tiktok,instagram")
    assert ajustes.plataformas_redes == [T, I]
    ajustes._q.setValue("redes/plataformas", ["youtube"])  # formato lista de QSettings
    assert ajustes.plataformas_redes == [Y]
    ajustes.plataformas_redes = [F, X, T]
    assert ajustes.plataformas_redes == [T, X, F]
    assert ajustes._q.value("redes/plataformas") == "tiktok,x,facebook"


def test_pagina_de_facebook_por_proveedor_y_borrable(ajustes):
    ajustes.pagina_facebook = Pagina("111", "Mía")
    assert ajustes.pagina_facebook_de(PROVEEDOR_POR_DEFECTO) == Pagina("111", "Mía")
    assert ajustes.pagina_facebook_de("otro") is None
    ajustes.pagina_facebook = None
    assert ajustes.pagina_facebook is None
    assert ajustes.ajustes_proveedor()["pagina_facebook"] == ""


def test_cuentas_guardadas_ida_y_vuelta_y_ligadas_al_perfil(ajustes):
    ajustes.perfil_redes = "yo"
    cuentas = {T: Cuenta(T, "Tik", "yo_tt", capacidades=("video",)), Y: None,
               X: Cuenta(X, usuario="yo_x", reconectar=True, premium=True)}
    ajustes.guardar_cuentas(cuentas)
    guardadas = ajustes.cuentas_guardadas()
    assert guardadas.cuentas == cuentas  # I y F: no se sabe (no están)
    assert guardadas.fecha
    ajustes.perfil_redes = "otro"  # otro perfil, otras cuentas
    assert ajustes.cuentas_guardadas() is None
    ajustes.perfil_redes = "yo"
    ajustes._q.setValue(f"redes/cuentas/{PROVEEDOR_POR_DEFECTO}", "{no es json")
    assert ajustes.cuentas_guardadas() is None


def test_la_clave_nunca_va_a_qsettings(qtbot, ajustes, llavero_falso, tmp_path):
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    dialogo.campo_perfil.setText("yo")
    dialogo.campo_clave.setText(CLAVE)
    dialogo.accept()
    ajustes._q.sync()
    assert CLAVE not in (tmp_path / "t.ini").read_text(encoding="utf-8")
    assert all(CLAVE not in str(ajustes._q.value(k)) for k in ajustes._q.allKeys())


# --- diálogo Redes… ---


def test_dialogo_redes_guarda_clave_en_llavero_y_perfil(qtbot, ajustes, llavero_falso):
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    assert dialogo.combo_proveedor.currentData() == PROVEEDOR_POR_DEFECTO
    assert dialogo.campo_clave.echoMode() == QLineEdit.EchoMode.Password
    assert "Sin clave" in dialogo.etiqueta_clave.text()
    assert not dialogo.boton_olvidar.isEnabled()
    dialogo.campo_perfil.setText("mi_perfil")
    dialogo.campo_clave.setText(f" {CLAVE} ")
    dialogo.combo_tiktok.setCurrentIndex(dialogo.combo_tiktok.findData("publico"))
    dialogo.combo_instagram.setCurrentIndex(dialogo.combo_instagram.findData("normal"))
    dialogo.combo_categoria.setCurrentIndex(dialogo.combo_categoria.findData("27"))
    dialogo.accept()
    assert dialogo.result() == DialogoRedes.DialogCode.Accepted
    assert credenciales.leer(PROVEEDOR_POR_DEFECTO) == CLAVE
    assert dialogo.campo_clave.text() == ""
    assert ajustes.perfil_redes == "mi_perfil"
    assert ajustes.tiktok_modo == ModoTikTok.PUBLICO
    assert ajustes.instagram_modo == ModoInstagram.NORMAL
    assert ajustes.youtube_categoria == "27"
    assert ajustes.x_premium is False
    assert ajustes.facebook_modo == ModoFacebook.REEL


def test_dialogo_redes_premium_de_x_y_modo_de_facebook(qtbot, ajustes, llavero_falso):
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    assert not dialogo.casilla_x_premium.isChecked()
    assert "2:20" in dialogo.ayuda_x.text() and "280" in dialogo.ayuda_x.text()
    dialogo.casilla_x_premium.setChecked(True)
    dialogo.combo_facebook.setCurrentIndex(dialogo.combo_facebook.findData("borrador"))
    dialogo.accept()
    assert ajustes.x_premium is True
    assert ajustes.facebook_modo == ModoFacebook.BORRADOR
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    assert dialogo.casilla_x_premium.isChecked()


def _redes(qtbot, ajustes, proveedor, capturado=None):
    def fabrica(nombre, clave, datos):
        if capturado is not None:
            capturado.update(nombre=nombre, clave=clave, datos=datos)
        return proveedor

    dialogo = DialogoRedes(ajustes, fabrica=fabrica)
    qtbot.addWidget(dialogo)
    return dialogo


def _cuentas_variadas():
    return {T: Cuenta(T, "Mi TikTok", "yo_tt"), Y: None,
            I: Cuenta(I, "Insta", "yo_ig", reconectar=True),
            X: Cuenta(X, "Yo", "yo_x", premium=True), F: Cuenta(F, "Mi página")}


def test_dialogo_redes_comprobar_conexion(qtbot, ajustes, llavero_falso):
    _listo(ajustes, llavero_falso)
    proveedor = ProveedorFalso(cuentas_conectadas=_cuentas_variadas(),
                               paginas=[Pagina("111", "Mi página")])
    capturado: dict = {}
    dialogo = _redes(qtbot, ajustes, proveedor, capturado)
    assert "Sin comprobar" in dialogo.etiqueta_consulta.text()
    assert dialogo.combo_pagina.currentData() in (None, "")
    assert dialogo.campo_pagina_manual.isHidden()
    dialogo.boton_comprobar.click()
    assert not dialogo.boton_comprobar.isEnabled()
    _esperar_consultas(qtbot)
    assert dialogo.boton_comprobar.isEnabled()
    assert capturado["clave"] == CLAVE and capturado["datos"]["perfil"] == "mi_perfil"
    textos = {p: e.text() for p, e in dialogo.etiquetas_cuentas.items()}
    assert "@yo_tt" in textos[T]
    assert "No conectada en Upload-Post" in textos[Y]
    assert "Reconecta" in textos[I] and "Upload-Post" in textos[I]
    assert "@yo_x" in textos[X]
    assert "Mi página" in textos[F]
    # Una sola página: se elige sola. Premium detectado en X: se marca.
    assert dialogo.combo_pagina.currentData() == "111"
    assert dialogo.casilla_x_premium.isChecked()
    assert "detect" in dialogo.nota_x_premium.text().lower()
    dialogo.accept()
    assert ajustes.pagina_facebook == Pagina("111", "Mi página")
    assert ajustes.x_premium is True
    assert ajustes.cuentas_guardadas().cuentas == _cuentas_variadas()
    # Al volver a abrir, lo último comprobado sigue a la vista.
    dialogo = _redes(qtbot, ajustes, proveedor)
    assert "@yo_tt" in dialogo.etiquetas_cuentas[T].text()
    assert "Última comprobación" in dialogo.etiqueta_consulta.text()
    assert dialogo.combo_pagina.currentData() == "111"


def test_dialogo_redes_varias_paginas_no_elige_sola_salvo_la_guardada(qtbot, ajustes,
                                                                      llavero_falso):
    _listo(ajustes, llavero_falso)
    paginas = [Pagina("111", "Una"), Pagina("222", "Otra")]
    proveedor = ProveedorFalso(paginas=paginas)
    dialogo = _redes(qtbot, ajustes, proveedor)
    dialogo.boton_comprobar.click()
    _esperar_consultas(qtbot)
    assert dialogo.combo_pagina.currentData() in (None, "")
    assert dialogo.combo_pagina.count() == 3  # «sin elegir» + dos
    dialogo.combo_pagina.setCurrentIndex(dialogo.combo_pagina.findData("222"))
    dialogo.accept()
    assert ajustes.pagina_facebook == Pagina("222", "Otra")
    dialogo = _redes(qtbot, ajustes, proveedor)
    dialogo.boton_comprobar.click()
    _esperar_consultas(qtbot)
    assert dialogo.combo_pagina.currentData() == "222"


def test_dialogo_redes_sin_lista_de_paginas_permite_escribir_el_id(qtbot, ajustes,
                                                                   llavero_falso):
    _listo(ajustes, llavero_falso)
    proveedor = ProveedorFalso(paginas=ErrorConsulta("Error 500 del servicio."))
    dialogo = _redes(qtbot, ajustes, proveedor)
    dialogo.boton_comprobar.click()
    _esperar_consultas(qtbot)
    assert not dialogo.campo_pagina_manual.isHidden()
    assert "500" in dialogo.aviso_pagina.text()
    dialogo.campo_pagina_manual.setText(" 987654 ")
    dialogo.accept()
    assert ajustes.pagina_facebook == Pagina("987654")


def test_dialogo_redes_facebook_sin_conectar_no_pide_paginas(qtbot, ajustes, llavero_falso):
    _listo(ajustes, llavero_falso)
    cuentas = todas_conectadas()
    cuentas[F] = None
    proveedor = ProveedorFalso(cuentas_conectadas=cuentas)
    dialogo = _redes(qtbot, ajustes, proveedor)
    dialogo.boton_comprobar.click()
    _esperar_consultas(qtbot)
    assert proveedor.consultas == ["cuentas"]
    assert "No conectada" in dialogo.etiquetas_cuentas[F].text()


def test_dialogo_redes_comprobar_con_la_clave_recien_escrita(qtbot, ajustes, llavero_falso):
    proveedor = ProveedorFalso()
    capturado: dict = {}
    dialogo = _redes(qtbot, ajustes, proveedor, capturado)
    dialogo.campo_perfil.setText("nuevo")
    dialogo.campo_clave.setText(f" {CLAVE} ")
    dialogo.boton_comprobar.click()
    _esperar_consultas(qtbot)
    assert capturado["clave"] == CLAVE and capturado["datos"]["perfil"] == "nuevo"
    assert credenciales.leer(PROVEEDOR_POR_DEFECTO) is None  # aún sin guardar
    assert dialogo.campo_clave.text() == f" {CLAVE} "


def test_dialogo_redes_comprobar_sin_clave_o_con_error(qtbot, ajustes, llavero_falso):
    proveedor = ProveedorFalso(cuentas_conectadas=ErrorConsulta(
        "La API key no es válida o ha caducado (401)."))
    dialogo = _redes(qtbot, ajustes, proveedor)
    dialogo.campo_perfil.setText("yo")
    dialogo.boton_comprobar.click()
    _esperar_consultas(qtbot)
    assert "API key" in dialogo.etiqueta_consulta.text()
    assert proveedor.consultas == []
    credenciales.guardar(PROVEEDOR_POR_DEFECTO, CLAVE)
    dialogo.boton_comprobar.click()
    _esperar_consultas(qtbot)
    assert "401" in dialogo.etiqueta_consulta.text()
    assert CLAVE not in dialogo.etiqueta_consulta.text()


def test_dialogo_redes_muestra_guardada_sin_revelarla(qtbot, ajustes, llavero_falso):
    credenciales.guardar(PROVEEDOR_POR_DEFECTO, CLAVE)
    llavero_falso.llamadas.clear()
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    assert "Guardada" in dialogo.etiqueta_clave.text()
    assert dialogo.campo_clave.text() == ""
    assert CLAVE not in dialogo.etiqueta_clave.text()
    # Solo comprueba que existe: nunca pide el secreto (-w).
    assert llavero_falso.llamadas
    assert all("-w" not in args for args, _entrada in llavero_falso.llamadas)
    assert dialogo.boton_olvidar.isEnabled()


def test_dialogo_redes_sin_clave_nueva_no_toca_el_llavero(qtbot, ajustes, llavero_falso):
    credenciales.guardar(PROVEEDOR_POR_DEFECTO, CLAVE)
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    llavero_falso.llamadas.clear()
    dialogo.accept()
    assert all(args[1:2] != ["-i"] for args, _e in llavero_falso.llamadas)
    assert credenciales.leer(PROVEEDOR_POR_DEFECTO) == CLAVE


def test_dialogo_redes_olvidar_clave(qtbot, ajustes, llavero_falso):
    credenciales.guardar(PROVEEDOR_POR_DEFECTO, CLAVE)
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    dialogo.boton_olvidar.click()
    assert credenciales.leer(PROVEEDOR_POR_DEFECTO) is None
    assert "Sin clave" in dialogo.etiqueta_clave.text()


def test_dialogo_redes_clave_invalida_avisa_y_no_cierra(qtbot, ajustes, llavero_falso,
                                                        monkeypatch):
    avisos = []
    monkeypatch.setattr("app.widgets.dialogo_redes.QMessageBox.warning",
                        lambda *a, **k: avisos.append(a[2]))
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    dialogo.campo_clave.setText("con espacios dentro")
    dialogo.accept()
    assert avisos and "con espacios" not in avisos[0]
    assert dialogo.result() != DialogoRedes.DialogCode.Accepted
    assert credenciales.leer(PROVEEDOR_POR_DEFECTO) is None


def test_dialogo_redes_explica_el_perfil_y_avisa_si_es_un_email(qtbot, ajustes,
                                                               llavero_falso):
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    assert "Manage Users" in dialogo.ayuda_perfil.text()
    assert "email" in dialogo.ayuda_perfil.text()
    assert dialogo.aviso_perfil.isHidden()
    dialogo.campo_perfil.setText("yo@example.com")
    assert not dialogo.aviso_perfil.isHidden()
    assert "email" in dialogo.aviso_perfil.text()
    dialogo.campo_perfil.setText("mi_perfil")
    assert dialogo.aviso_perfil.isHidden()


# --- diálogo Publicar ---


def _dialogo(qtbot, video, ajustes, proveedor=None, capturado=None):
    proveedor = proveedor or ProveedorFalso()

    def fabrica(nombre, clave, datos):
        if capturado is not None:
            capturado.update(nombre=nombre, clave=clave, datos=datos)
        return proveedor

    dialogo = DialogoPublicar(video, _caption(), ajustes, fabrica=fabrica)
    qtbot.addWidget(dialogo)
    return dialogo, proveedor


def _confirmar(monkeypatch, respuesta=QMessageBox.StandardButton.Yes):
    preguntas = []

    def pregunta(*args, **kwargs):
        preguntas.append(args[2])
        return respuesta

    monkeypatch.setattr("app.widgets.dialogo_publicar.QMessageBox.question", pregunta)
    return preguntas


def test_textos_precargados_y_editables(qtbot, video, ajustes, llavero_falso):
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    assert dialogo.campo_titulo.text() == "Título X"
    assert dialogo.campo_caption.toPlainText() == "Cuerpo del caption"
    assert dialogo.campo_hashtags.text() == "#ia #pymes"
    assert not dialogo.campo_titulo.isReadOnly()
    assert not dialogo.campo_caption.isReadOnly()
    dialogo.campo_titulo.setText("Otro título")
    dialogo.campo_hashtags.setText("#uno  #dos")
    pub = dialogo.publicacion()
    assert pub.titulo == "Otro título"
    assert pub.hashtags == ("#uno", "#dos")
    assert pub.palabras_clave == ("ia", "pymes")
    assert pub.video == video
    assert dialogo.contador_titulo.text() == "11/100"


def test_casillas_en_orden_y_modos_por_defecto(qtbot, video, ajustes, llavero_falso):
    ajustes.tiktok_modo = ModoTikTok.PUBLICO
    ajustes.facebook_modo = ModoFacebook.VIDEO
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    assert list(dialogo.casillas) == [T, Y, I, X, F]
    assert [c.text() for c in dialogo.casillas.values()] == [
        "TikTok", "YouTube", "Instagram", "X", "Facebook"]
    assert [p for p, c in dialogo.casillas.items() if c.isChecked()] == [T, Y, I]
    opciones = dialogo.opciones()
    assert opciones.tiktok_modo == ModoTikTok.PUBLICO
    assert opciones.instagram_modo == ModoInstagram.PRUEBA
    assert opciones.facebook_modo == ModoFacebook.VIDEO
    assert opciones.x_premium is False
    # La rejilla respeta el orden visual.
    ys = [c.mapTo(dialogo, c.rect().topLeft()).y() for c in dialogo.casillas.values()]
    assert ys == sorted(ys)


def test_boton_deshabilitado_sin_clave_perfil_o_plataformas(qtbot, video, ajustes,
                                                            llavero_falso):
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    assert not dialogo.boton_publicar.isEnabled()
    assert "API key" in dialogo.etiqueta_servicio.text()
    credenciales.guardar(PROVEEDOR_POR_DEFECTO, CLAVE)
    dialogo.refrescar_servicio()
    assert not dialogo.boton_publicar.isEnabled()
    assert "perfil" in dialogo.etiqueta_servicio.text()
    ajustes.perfil_redes = "yo"
    dialogo.refrescar_servicio()
    assert dialogo.boton_publicar.isEnabled()
    assert "yo" in dialogo.etiqueta_servicio.text()
    for casilla in dialogo.casillas.values():
        casilla.setChecked(False)
    assert not dialogo.boton_publicar.isEnabled()
    dialogo.casillas[Y].setChecked(True)
    assert dialogo.boton_publicar.isEnabled()
    dialogo.campo_titulo.setText("  ")
    assert not dialogo.boton_publicar.isEnabled()


def test_aviso_si_ya_se_publico(qtbot, video, ajustes, llavero_falso):
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    assert dialogo.aviso_publicado.isHidden()
    registro.anotar(video, T, "", "prov", "borrador")
    registro.anotar(video, Y, "https://yt/1", "prov", "publico")
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    assert not dialogo.aviso_publicado.isHidden()
    texto = dialogo.aviso_publicado.text()
    assert "TikTok (borrador)" in texto and "YouTube" in texto
    assert "Instagram" not in texto


def test_cancelar_confirmacion_no_publica(qtbot, video, ajustes, llavero_falso, monkeypatch):
    _listo(ajustes, llavero_falso)
    dialogo, proveedor = _dialogo(qtbot, video, ajustes)
    preguntas = _confirmar(monkeypatch, QMessageBox.StandardButton.Cancel)
    dialogo.boton_publicar.click()
    assert len(preguntas) == 1
    assert "TikTok" in preguntas[0] and "Instagram" in preguntas[0]
    assert "Reel de prueba" in preguntas[0]
    assert proveedor.llamadas == []
    assert not dialogo.publicando


def test_publicar_muestra_resultados_y_enlaces(qtbot, video, ajustes, llavero_falso,
                                               monkeypatch):
    _listo(ajustes, llavero_falso)
    proveedor = ProveedorFalso(respuestas={
        T: Resultado(T, ok=True),
        Y: Resultado(Y, ok=False, error="cuota <agotada>"),
        I: Resultado(I, ok=True, url="https://instagram.com/reel/1"),
    })
    capturado: dict = {}
    dialogo, _p = _dialogo(qtbot, video, ajustes, proveedor, capturado)
    registro.anotar(video, Y, "https://yt/0", "prov")
    dialogo._refrescar_aviso()
    preguntas = _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=5000) as senal:
        dialogo.boton_publicar.click()
        assert dialogo.publicando
        assert not dialogo.boton_cerrar.isEnabled()
        assert not dialogo.boton_publicar.isEnabled()
    assert "Ya publicado antes en: YouTube" in preguntas[0]
    assert capturado == {"nombre": PROVEEDOR_POR_DEFECTO, "clave": CLAVE,
                         "datos": {"perfil": "mi_perfil", "pagina_facebook": ""}}
    resultados = senal.args[0]
    assert list(resultados) == [T, Y, I]
    assert [c[1] for c in proveedor.llamadas] == [T, Y, I]
    assert "borradores" in dialogo.estados[T].text()
    assert "✗" in dialogo.estados[Y].text()
    assert dialogo.estados[Y].toolTip() == "cuota <agotada>"
    assert "&lt;agotada&gt;" in dialogo.resumen.text()  # texto del servicio escapado
    assert 'href="https://instagram.com/reel/1"' in dialogo.estados[I].text()
    assert dialogo.estados[I].openExternalLinks()
    # Lo publicado se desmarca; lo fallido queda marcado para reintentar.
    assert not dialogo.casillas[T].isChecked()
    assert dialogo.casillas[Y].isChecked()
    assert not dialogo.casillas[I].isChecked()
    assert not dialogo.publicando and dialogo.boton_cerrar.isEnabled()
    assert registro.ya_publicado(video) == {T, Y, I}
    assert "Instagram" in dialogo.aviso_publicado.text()
    assert CLAVE not in registro.ruta(video).read_text(encoding="utf-8")


def test_publicar_solo_las_marcadas_y_recuerda_la_eleccion(qtbot, video, ajustes,
                                                           llavero_falso, monkeypatch):
    _listo(ajustes, llavero_falso)
    dialogo, proveedor = _dialogo(qtbot, video, ajustes)
    dialogo.casillas[T].setChecked(False)
    dialogo.combo_instagram.setCurrentIndex(dialogo.combo_instagram.findData("normal"))
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=5000):
        dialogo.boton_publicar.click()
    assert [c[1] for c in proveedor.llamadas] == [Y, I]
    assert proveedor.llamadas[-1][3].instagram_modo == ModoInstagram.NORMAL
    assert ajustes.plataformas_redes == [Y, I]
    assert ajustes.instagram_modo == ModoInstagram.NORMAL


def test_no_se_cierra_mientras_publica(qtbot, video, ajustes, llavero_falso):
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    dialogo.show()
    dialogo._hilo = object()  # simula una subida en marcha
    dialogo.reject()
    assert dialogo.isVisible()
    dialogo._hilo = None
    dialogo.reject()
    assert not dialogo.isVisible()


# --- ningún final silencioso: estado, resumen y registro ---


def _log(dialogo) -> str:
    assert dialogo.ruta_log is not None and dialogo.ruta_log.is_file()
    return dialogo.ruta_log.read_text(encoding="utf-8")


class ProveedorLento(ProveedorFalso):
    """Espera a que el test lo suelte antes de responder a cada plataforma."""

    def __init__(self, *a, **kw):
        import threading

        super().__init__(*a, **kw)
        self.soltar = threading.Event()

    def publicar(self, plataforma, publicacion, opciones):
        self.soltar.wait(5)
        return super().publicar(plataforma, publicacion, opciones)


def test_estado_visible_desde_el_primer_clic(qtbot, video, ajustes, llavero_falso,
                                             monkeypatch):
    _listo(ajustes, llavero_falso)
    proveedor = ProveedorLento(respuestas={
        Y: Resultado(Y, ok=False, pendiente=True, referencia="r")},
        estados={Y: [Resultado(Y, ok=True, url="https://yt/1")]})
    monkeypatch.setattr("videopipeline.redes.publicador.INTERVALO_SONDEO", 0.01)
    dialogo, _p = _dialogo(qtbot, video, ajustes, proveedor)
    dialogo.show()
    dialogo.casillas[I].setChecked(False)
    _confirmar(monkeypatch)
    dialogo.boton_publicar.click()
    # Nada más aceptar: cola, barra en marcha y línea de estado.
    assert dialogo.estados[T].text() == "En cola"
    assert dialogo.estados[Y].text() == "En cola"
    assert dialogo.estados[I].text() not in ("En cola", "Subiendo…")  # sin marcar
    assert dialogo.barra.isVisible() and dialogo.barra.height() >= 8
    assert dialogo.barra.minimum() == dialogo.barra.maximum() == 0  # indeterminada
    assert dialogo.etiqueta_estado.isVisible() and dialogo.etiqueta_estado.text()
    qtbot.waitUntil(lambda: dialogo.estados[T].text() == "Subiendo…", timeout=3000)
    assert "TikTok" in dialogo.etiqueta_estado.text()
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=5000):
        proveedor.soltar.set()
        qtbot.waitUntil(lambda: dialogo.estados[Y].text() == "Procesando en el servicio…"
                        or not dialogo.publicando, timeout=3000)
    assert not dialogo.barra.isVisible()


def test_resumen_final_con_enlaces_y_ver_registro(qtbot, video, ajustes, llavero_falso,
                                                   monkeypatch, sin_finder):
    _listo(ajustes, llavero_falso)
    ajustes.tiktok_modo = ModoTikTok.BORRADOR
    proveedor = ProveedorFalso(respuestas={
        T: Resultado(T, ok=True),
        Y: Resultado(Y, ok=True, url="https://youtube.com/shorts/1"),
        I: Resultado(I, ok=False, error="Media too long"),
    })
    dialogo, _p = _dialogo(qtbot, video, ajustes, proveedor)
    dialogo.show()
    assert dialogo.boton_registro.isHidden()
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=5000):
        dialogo.boton_publicar.click()
    assert dialogo.etiqueta_estado.text() == "Publicado en 2 de 3"
    resumen = dialogo.resumen.text()
    assert "TikTok" in resumen and "borradores" in resumen
    assert 'href="https://youtube.com/shorts/1"' in resumen
    assert "Instagram" in resumen and "Media too long" in resumen
    assert dialogo.resumen.isVisible()
    assert dialogo.boton_registro.isVisible() and dialogo.boton_registro.isEnabled()
    dialogo.boton_registro.click()
    assert sin_finder == [dialogo.ruta_log]
    log = _log(dialogo)
    for texto in ("Inicio", "Proveedor: Upload-Post", "perfil: sí", "TikTok", "borrador",
                  "Reel de prueba", str(video), f"{video.stat().st_size} bytes",
                  "Media too long", "https://youtube.com/shorts/1", "Fin"):
        assert texto in log, texto
    assert CLAVE not in log and "mi_perfil" not in log


def test_todas_fallan_lo_dice(qtbot, video, ajustes, llavero_falso, monkeypatch):
    _listo(ajustes, llavero_falso)
    proveedor = ProveedorFalso(respuestas={
        p: Resultado(p, ok=False, error="Username not associated with any profile")
        for p in ORDEN})
    dialogo, _p = _dialogo(qtbot, video, ajustes, proveedor)
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=5000):
        dialogo.boton_publicar.click()
    assert dialogo.etiqueta_estado.text() == "Falló en todas"
    assert dialogo.resumen.text().count("Username not associated") == 3


def test_pendiente_cuenta_aparte(qtbot, video, ajustes, llavero_falso, monkeypatch):
    _listo(ajustes, llavero_falso)
    proveedor = ProveedorFalso(respuestas={
        I: Resultado(I, ok=False, pendiente=True, referencia="r")})
    monkeypatch.setattr("videopipeline.redes.publicador.ESPERA_MAXIMA", 0.0)
    dialogo, _p = _dialogo(qtbot, video, ajustes, proveedor)
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=5000):
        dialogo.boton_publicar.click()
    assert dialogo.etiqueta_estado.text() == "Publicado en 2 de 3 · 1 por confirmar"
    assert "⏳" in dialogo.resumen.text()
    # Por confirmar: no se deja marcada para no publicarla dos veces sin querer.
    assert not dialogo.casillas[I].isChecked()
    assert "Instagram (sin confirmar)" in dialogo.aviso_publicado.text()


def test_fallo_inesperado_del_hilo_da_error_a_cada_plataforma(qtbot, video, ajustes,
                                                              llavero_falso, monkeypatch):
    _listo(ajustes, llavero_falso)

    def revienta(proveedor, publicacion, opciones, plataformas, *, progreso, **kw):
        progreso(T, publicador.Estado.SUBIENDO, None)
        progreso(T, publicador.Estado.HECHO, Resultado(T, ok=True, url="https://tt/1"))
        raise RuntimeError(f"algo raro con {CLAVE}")

    monkeypatch.setattr("app.widgets.dialogo_publicar.publicador.publicar", revienta)
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=5000) as senal:
        dialogo.boton_publicar.click()
    resultados = senal.args[0]
    assert list(resultados) == [T, Y, I]
    assert resultados[T].ok
    for p in (Y, I):
        assert not resultados[p].ok
        assert "RuntimeError" in resultados[p].error
        assert "registro" in resultados[p].error
        assert "✗" in dialogo.estados[p].text()
        assert "RuntimeError" in dialogo.estados[p].toolTip()
        assert "RuntimeError" in dialogo.resumen.text()
    assert dialogo.etiqueta_estado.text() == "Publicado en 1 de 3"
    assert not dialogo.publicando
    log = _log(dialogo)
    assert "Traceback" in log and "RuntimeError" in log
    assert CLAVE not in log
    assert not dialogo.boton_registro.isHidden()


class LlaveroRaro:
    """Dice que hay clave, pero al leerla devuelve `lectura` (o la lanza)."""

    def __init__(self, lectura):
        self.lectura = lectura

    def hay_clave(self, nombre):
        return True

    def leer(self, nombre):
        if isinstance(self.lectura, BaseException):
            raise self.lectura
        return self.lectura


@pytest.mark.parametrize("lectura, esperado", [
    (None, "No se encontró la API key en el Llavero"),
    (credenciales.ErrorLlavero("No se pudo leer la clave del Llavero (código 51)."),
     "código 51"),
    (OSError("sin permiso"), "OSError"),
])
def test_llavero_sin_clave_o_con_error_lo_dice(qtbot, video, ajustes, monkeypatch,
                                               lectura, esperado):
    ajustes.perfil_redes = "mi_perfil"
    proveedor = ProveedorFalso()
    dialogo = DialogoPublicar(video, _caption(), ajustes, llavero=LlaveroRaro(lectura),
                              fabrica=lambda *a: proveedor)
    qtbot.addWidget(dialogo)
    dialogo.show()
    assert dialogo.boton_publicar.isEnabled()
    _confirmar(monkeypatch)
    dialogo.boton_publicar.click()  # sin QMessageBox: el aviso va en el diálogo
    assert esperado in dialogo.etiqueta_estado.text()
    assert dialogo.etiqueta_estado.isVisible()
    assert proveedor.llamadas == []
    assert not dialogo.publicando and dialogo.boton_cerrar.isEnabled()
    for p in (T, Y, I):
        assert "✗" in dialogo.estados[p].text()
    assert esperado.split(" (")[0] in _log(dialogo) or type(lectura).__name__ in _log(dialogo)
    assert not dialogo.boton_registro.isHidden()


def test_fabrica_que_falla_lo_dice(qtbot, video, ajustes, llavero_falso, monkeypatch):
    _listo(ajustes, llavero_falso)

    def fabrica(*a):
        raise ImportError(f"falta httpx {CLAVE}")

    dialogo = DialogoPublicar(video, _caption(), ajustes, fabrica=fabrica)
    qtbot.addWidget(dialogo)
    _confirmar(monkeypatch)
    dialogo.boton_publicar.click()
    assert "ImportError" in dialogo.etiqueta_estado.text()
    assert CLAVE not in dialogo.etiqueta_estado.text()
    log = _log(dialogo)
    assert "Traceback" in log and CLAVE not in log


def test_cancelar_la_confirmacion_lo_dice(qtbot, video, ajustes, llavero_falso,
                                          monkeypatch):
    _listo(ajustes, llavero_falso)
    dialogo, proveedor = _dialogo(qtbot, video, ajustes)
    _confirmar(monkeypatch, QMessageBox.StandardButton.Cancel)
    dialogo.boton_publicar.click()
    assert "cancelada" in dialogo.etiqueta_estado.text()
    assert proveedor.llamadas == []
    assert "cancel" in _log(dialogo).lower()



def test_procesando_en_el_servicio_y_espera_final(qtbot, video, ajustes, llavero_falso):
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    dialogo._preparar([T, Y], dialogo.opciones())
    dialogo._al_progresar("tiktok", "subiendo", None)
    assert dialogo.estados[T].text() == "Subiendo…"
    assert dialogo.etiqueta_estado.text() == "Subiendo a TikTok (1 de 2)…"
    dialogo._al_progresar("tiktok", "procesando", Resultado(T, ok=False, pendiente=True))
    assert dialogo.estados[T].text() == "Procesando en el servicio…"
    assert dialogo.etiqueta_estado.text() == "Subiendo a TikTok (1 de 2)…"  # YouTube en cola
    dialogo._al_progresar("youtube", "subiendo", None)
    dialogo._al_progresar("youtube", "hecho", Resultado(Y, ok=True, url="https://y/1"))
    assert dialogo.etiqueta_estado.text() == "Esperando a que el servicio termine: TikTok…"
    dialogo._cerrar_diario()


SCRIPT_DESTRUIR = r"""
import os, sys, threading, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QSettings, QtMsgType, qInstallMessageHandler

def manejador(tipo, contexto, mensaje):
    sys.stderr.write(mensaje + "\n")
    sys.stderr.flush()
    if tipo == QtMsgType.QtFatalMsg:
        os._exit(3)  # sin abort(): nada de «Python se cerró inesperadamente»

qInstallMessageHandler(manejador)
import shiboken6
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
from app.settings import Ajustes
from app.widgets import dialogo_publicar
from videopipeline.caption import Caption
from videopipeline.redes import diario
from videopipeline.redes.modelo import Resultado

carpeta = Path(sys.argv[2])
diario.DIR_LOGS = carpeta / "logs"
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
dentro, soltar = threading.Event(), threading.Event()

class Lento:
    nombre = "Lento"
    def publicar(self, plataforma, publicacion, opciones):
        dentro.set()
        soltar.wait(10)
        return Resultado(plataforma, ok=True, url="https://x/1")
    def estado(self, plataforma, referencia):
        return Resultado(plataforma, ok=True)

class Llavero:
    def hay_clave(self, nombre): return True
    def leer(self, nombre): return "clave-falsa"

video = carpeta / "v.mp4"
video.write_bytes(b"MP4")
ajustes = Ajustes(QSettings(str(carpeta / "t.ini"), QSettings.Format.IniFormat))
ajustes.perfil_redes = "yo"
d = dialogo_publicar.DialogoPublicar(video, Caption(titulo="t", caption="c", hashtags=[], palabras_clave=[]), ajustes,
                                     llavero=Llavero(), fabrica=lambda *a: Lento())
d.publicar()
assert dentro.wait(5), "la subida no empezó"
shiboken6.delete(d)  # el diálogo desaparece en plena subida
app.processEvents()
soltar.set()
limite = time.monotonic() + 10
while dialogo_publicar.hilos_vivos() and time.monotonic() < limite:
    app.processEvents()
    time.sleep(0.01)
print("vivos", dialogo_publicar.hilos_vivos())
print("log", next((carpeta / "logs").glob("*.log")).read_text(encoding="utf-8"))
"""


def test_destruir_el_dialogo_en_plena_subida_no_aborta(tmp_path):
    """Antes, Qt abortaba la app: «QThread: Destroyed while thread is still
    running». Se prueba en otro proceso para que un aborto no tumbe la suite."""
    import os
    import subprocess
    import sys

    script = tmp_path / "destruir.py"
    script.write_text(SCRIPT_DESTRUIR, encoding="utf-8")
    raiz = Path(__file__).resolve().parent.parent
    entorno = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    salida = subprocess.run([sys.executable, str(script), str(raiz), str(tmp_path)],
                            capture_output=True, text=True, timeout=60, env=entorno)
    assert "Destroyed while thread" not in salida.stderr
    assert salida.returncode == 0, salida.stderr[-2000:]
    assert "vivos 0" in salida.stdout
    assert "Fin (hilo terminado sin diálogo)" in salida.stdout


def test_esperar_hilos_al_salir(qtbot, video, ajustes, llavero_falso, monkeypatch):
    _listo(ajustes, llavero_falso)
    proveedor = ProveedorLento()
    dialogo, _p = _dialogo(qtbot, video, ajustes, proveedor)
    _confirmar(monkeypatch)
    dialogo.boton_publicar.click()
    assert dialogo_publicar.hilos_vivos() == 1
    proveedor.soltar.set()
    dialogo_publicar.esperar_hilos(5000)
    assert dialogo_publicar.hilos_vivos() == 0


def test_no_se_cierra_con_done_mientras_publica(qtbot, video, ajustes, llavero_falso):
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    dialogo.show()
    dialogo._hilo = object()
    dialogo.accept()
    assert dialogo.isVisible()
    dialogo._hilo = None


def test_confirmacion_avisa_de_lo_que_quedo_sin_confirmar(qtbot, video, ajustes,
                                                           llavero_falso, monkeypatch):
    _listo(ajustes, llavero_falso)
    registro.anotar(video, I, "", "prov", "prueba", sin_confirmar=True)
    registro.anotar(video, Y, "https://yt/0", "prov")
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    assert "Instagram (sin confirmar)" in dialogo.aviso_publicado.text()
    preguntas = _confirmar(monkeypatch, QMessageBox.StandardButton.Cancel)
    dialogo.boton_publicar.click()
    assert "Ya publicado antes en: YouTube." in preguntas[0]
    assert "Sin confirmar en: Instagram" in preguntas[0]
    assert "compruébalo" in preguntas[0]


# --- X y Facebook en el diálogo Publicar ---


def _dialogo_listo(qtbot, video, ajustes, llavero_falso, proveedor=None, capturado=None,
                   marcadas=(T, Y, I, X, F), pagina=Pagina("111", "Mi página")):
    _listo(ajustes, llavero_falso)
    ajustes.plataformas_redes = list(marcadas)
    if pagina is not None:
        ajustes.pagina_facebook = pagina
    dialogo, proveedor = _dialogo(qtbot, video, ajustes, proveedor, capturado)
    _esperar_consultas(qtbot)
    return dialogo, proveedor


def test_texto_de_x_precargado_con_contador_y_regenerado(qtbot, video, ajustes,
                                                         llavero_falso):
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    assert dialogo.campo_x.toPlainText() == "Título X\n\n#ia #pymes"
    assert dialogo.contador_x.text() == "20/280"
    # Mientras no se toca, sigue al título y a los hashtags.
    dialogo.campo_titulo.setText("Otro")
    dialogo.campo_hashtags.setText("#uno")
    assert dialogo.campo_x.toPlainText() == "Otro\n\n#uno"
    assert dialogo.contador_x.text() == "10/280"
    assert dialogo.publicacion().texto_x == "Otro\n\n#uno"
    # Editado a mano, ya no se pisa.
    dialogo.campo_x.setPlainText("Mi post 👍 https://example.com/una/ruta/larga")
    assert dialogo.contador_x.text() == f"{longitud_x(dialogo.campo_x.toPlainText())}/280"
    dialogo.campo_titulo.setText("Otro más")
    assert dialogo.campo_x.toPlainText().startswith("Mi post")
    assert dialogo.publicacion().texto_x.startswith("Mi post")
    # Vacío: vuelve a seguir al título.
    dialogo.campo_x.setPlainText("")
    dialogo.campo_titulo.setText("Tercero")
    assert dialogo.campo_x.toPlainText() == "Tercero\n\n#uno"


def test_texto_de_x_largo_sin_premium_bloquea_y_con_premium_no(qtbot, video, ajustes,
                                                              llavero_falso):
    dialogo, _p = _dialogo_listo(qtbot, video, ajustes, llavero_falso)
    assert dialogo.boton_publicar.isEnabled()
    dialogo.campo_x.setPlainText("palabra " * 40)
    assert dialogo.contador_x.text() == "319/280"
    assert "color" in dialogo.contador_x.styleSheet()
    assert not dialogo.boton_publicar.isEnabled()
    assert "280" in dialogo.estados[X].text()
    # Sin X marcada, el texto de X no importa.
    dialogo.casillas[X].setChecked(False)
    assert dialogo.boton_publicar.isEnabled()
    dialogo.casillas[X].setChecked(True)
    ajustes.x_premium = True
    dialogo.refrescar_servicio()
    _esperar_consultas(qtbot)
    assert dialogo.boton_publicar.isEnabled()
    assert dialogo.contador_x.styleSheet() == ""
    assert dialogo.opciones().x_premium is True


def test_x_deshabilitada_por_duracion_sin_premium(qtbot, video, ajustes, llavero_falso,
                                                   monkeypatch):
    monkeypatch.setattr(dialogo_publicar, "medir_duracion", lambda v: 167.4)
    dialogo, _p = _dialogo_listo(qtbot, video, ajustes, llavero_falso)
    qtbot.waitUntil(lambda: dialogo.duracion is not None, timeout=3000)
    assert not dialogo.casillas[X].isEnabled()
    assert not dialogo.casillas[X].isChecked()
    assert dialogo.estados[X].text() == (
        "X sin Premium admite vídeos de hasta 2:20; este dura 2:48.")
    assert X not in dialogo.plataformas()
    assert dialogo.boton_publicar.isEnabled()  # las demás siguen
    # Con Premium vuelve, y marcada como estaba.
    ajustes.x_premium = True
    dialogo.refrescar_servicio()
    _esperar_consultas(qtbot)
    assert dialogo.casillas[X].isEnabled() and dialogo.casillas[X].isChecked()
    assert "2:20" not in dialogo.estados[X].text()


def test_x_deshabilitada_por_tamano_sin_premium(qtbot, tmp_path, ajustes, llavero_falso):
    grande = tmp_path / "grande_limpio.mp4"
    with grande.open("wb") as f:
        f.truncate(600 * MB)  # disperso: no ocupa disco de verdad
    dialogo, _p = _dialogo_listo(qtbot, grande, ajustes, llavero_falso)
    qtbot.waitUntil(lambda: dialogo.duracion is not None, timeout=3000)
    assert not dialogo.casillas[X].isEnabled()
    assert "512 MB" in dialogo.estados[X].text() and "600 MB" in dialogo.estados[X].text()


def test_x_espera_a_la_duracion_sin_bloquear_la_ventana(qtbot, video, ajustes, llavero_falso,
                                                        monkeypatch):
    import threading
    import time

    soltar = threading.Event()

    def lenta(v):
        soltar.wait(5)
        return 20.0

    monkeypatch.setattr(dialogo_publicar, "medir_duracion", lenta)
    _listo(ajustes, llavero_falso)
    ajustes.plataformas_redes = [X]
    inicio = time.monotonic()
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    assert time.monotonic() - inicio < 1.0  # ffprobe no bloquea la ventana
    assert dialogo.duracion is None
    assert not dialogo.casillas[X].isEnabled()
    assert "Comprobando" in dialogo.estados[X].text()
    assert not dialogo.boton_publicar.isEnabled()
    soltar.set()
    qtbot.waitUntil(lambda: dialogo.duracion == 20.0, timeout=3000)
    assert dialogo.casillas[X].isEnabled() and dialogo.casillas[X].isChecked()
    _esperar_consultas(qtbot)
    assert dialogo.boton_publicar.isEnabled()


def test_facebook_sin_pagina_lo_explica_y_no_publica(qtbot, video, ajustes, llavero_falso):
    proveedor = ProveedorFalso(paginas=[Pagina("1", "Una"), Pagina("2", "Otra")])
    dialogo, _p = _dialogo_listo(qtbot, video, ajustes, llavero_falso, proveedor,
                                 marcadas=(T, F), pagina=None)
    assert dialogo.casillas[F].isChecked()
    assert "página de Facebook" in dialogo.estados[F].text()
    assert "Redes" in dialogo.estados[F].text()
    assert not dialogo.boton_publicar.isEnabled()
    dialogo.casillas[F].setChecked(False)
    assert dialogo.boton_publicar.isEnabled()
    dialogo.casillas[F].setChecked(True)
    ajustes.pagina_facebook = Pagina("2", "Otra")
    dialogo.refrescar_servicio()
    _esperar_consultas(qtbot)
    assert dialogo.boton_publicar.isEnabled()


def test_una_sola_pagina_de_facebook_se_elige_sola(qtbot, video, ajustes, llavero_falso):
    proveedor = ProveedorFalso(paginas=[Pagina("555", "La única")])
    dialogo, _p = _dialogo_listo(qtbot, video, ajustes, llavero_falso, proveedor,
                                 marcadas=(F,), pagina=None)
    assert ajustes.pagina_facebook == Pagina("555", "La única")
    assert dialogo.boton_publicar.isEnabled()
    assert "página de Facebook" not in dialogo.estados[F].text()


def test_x_y_facebook_llegan_al_proveedor_con_sus_opciones(qtbot, video, ajustes,
                                                          llavero_falso, monkeypatch):
    capturado: dict = {}
    dialogo, proveedor = _dialogo_listo(qtbot, video, ajustes, llavero_falso,
                                        capturado=capturado, marcadas=(Y, X, F))
    dialogo.campo_x.setPlainText("Post propio para X")
    dialogo.combo_facebook.setCurrentIndex(dialogo.combo_facebook.findData("video"))
    preguntas = _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=5000) as senal:
        dialogo.boton_publicar.click()
    assert "X: Post público" in preguntas[0]
    assert "Facebook: Vídeo normal" in preguntas[0]
    assert list(senal.args[0]) == [Y, X, F]
    publicaciones = [c for c in proveedor.llamadas if c[0] == "publicar"]
    assert [c[1] for c in publicaciones] == [Y, X, F]
    pub, opciones = publicaciones[1][2], publicaciones[1][3]
    assert pub.texto_x == "Post propio para X"
    assert opciones.facebook_modo == ModoFacebook.VIDEO and opciones.x_premium is False
    assert capturado["datos"] == {"perfil": "mi_perfil", "pagina_facebook": "111"}
    assert ajustes.plataformas_redes == [Y, X, F]
    assert ajustes.facebook_modo == ModoFacebook.VIDEO
    log = _log(dialogo)
    assert "Texto de X" in log and "Página de Facebook: sí" in log


def test_borrador_de_facebook_se_explica_y_se_anota(qtbot, video, ajustes, llavero_falso,
                                                    monkeypatch):
    proveedor = ProveedorFalso(respuestas={F: Resultado(F, ok=True)})
    dialogo, _p = _dialogo_listo(qtbot, video, ajustes, llavero_falso, proveedor,
                                 marcadas=(F,))
    dialogo.combo_facebook.setCurrentIndex(dialogo.combo_facebook.findData("borrador"))
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=5000):
        dialogo.boton_publicar.click()
    assert "Facebook" in dialogo.estados[F].text() and "borrador" in dialogo.estados[F].text()
    assert "Facebook (borrador)" in dialogo.aviso_publicado.text()


# --- cuentas conectadas en el diálogo Publicar ---


def test_cuentas_no_conectadas_se_deshabilitan_y_las_demas_muestran_la_cuenta(
        qtbot, video, ajustes, llavero_falso):
    proveedor = ProveedorFalso(cuentas_conectadas=_cuentas_variadas())
    dialogo, _p = _dialogo_listo(qtbot, video, ajustes, llavero_falso, proveedor)
    assert proveedor.consultas and proveedor.consultas[0] == "cuentas"
    assert not dialogo.casillas[Y].isEnabled() and not dialogo.casillas[Y].isChecked()
    assert dialogo.estados[Y].text() == "No conectada en Upload-Post"
    assert dialogo.casillas[I].isEnabled() and dialogo.casillas[I].isChecked()
    assert "Reconecta" in dialogo.estados[I].text()
    assert dialogo.estados[T].text() == "@yo_tt"
    assert dialogo.boton_publicar.isEnabled()
    # Se guardan para la próxima vez (p. ej. sin conexión).
    assert ajustes.cuentas_guardadas().cuentas == _cuentas_variadas()


def test_sin_conexion_se_usa_lo_ultimo_que_se_supo(qtbot, video, ajustes, llavero_falso):
    _listo(ajustes, llavero_falso)
    ajustes.guardar_cuentas(_cuentas_variadas())
    proveedor = ProveedorFalso(cuentas_conectadas=ErrorConsulta(
        "No se pudo conectar con el servicio (ConnectError)."))
    dialogo, _p = _dialogo_listo(qtbot, video, ajustes, llavero_falso, proveedor)
    assert not dialogo.casillas[Y].isEnabled()
    assert "Reconecta" in dialogo.estados[I].text()
    assert "comprobar las cuentas" in dialogo.etiqueta_servicio.text()
    assert dialogo.boton_publicar.isEnabled()


def test_sin_conexion_ni_nada_guardado_todo_sigue_usable(qtbot, video, ajustes,
                                                         llavero_falso):
    proveedor = ProveedorFalso(cuentas_conectadas=ErrorConsulta("sin red"))
    dialogo, _p = _dialogo_listo(qtbot, video, ajustes, llavero_falso, proveedor)
    assert all(c.isEnabled() for c in dialogo.casillas.values())
    assert [p for p, c in dialogo.casillas.items() if c.isChecked()] == list(ORDEN)
    assert dialogo.boton_publicar.isEnabled()


def test_sin_clave_no_se_consultan_las_cuentas(qtbot, video, ajustes, llavero_falso):
    dialogo, proveedor = _dialogo(qtbot, video, ajustes)
    _esperar_consultas(qtbot)
    assert proveedor.consultas == []


def test_el_registro_de_la_publicacion_anota_las_cuentas(qtbot, video, ajustes,
                                                         llavero_falso, monkeypatch):
    proveedor = ProveedorFalso(cuentas_conectadas=_cuentas_variadas())
    dialogo, _p = _dialogo_listo(qtbot, video, ajustes, llavero_falso, proveedor,
                                 marcadas=(T,))
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=5000):
        dialogo.boton_publicar.click()
    log = _log(dialogo)
    assert "Cuentas (comprobadas" in log
    assert "TikTok @yo_tt" in log and "YouTube no conectada" in log
    assert "Instagram @yo_ig (reconectar)" in log
    assert CLAVE not in log and "mi_perfil" not in log


def test_los_resultados_no_se_pisan_con_la_consulta_de_cuentas(qtbot, video, ajustes,
                                                                llavero_falso, monkeypatch):
    dialogo, _p = _dialogo_listo(qtbot, video, ajustes, llavero_falso, marcadas=(T,))
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=5000):
        dialogo.boton_publicar.click()
    assert "Publicado" in dialogo.estados[T].text()
    dialogo.refrescar_servicio()  # p. ej. al volver de Redes…
    _esperar_consultas(qtbot)
    assert "Publicado" in dialogo.estados[T].text()
    assert dialogo.estados[Y].text() == "@yo_youtube"
