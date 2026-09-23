"""Ajustes de redes, diálogo Redes… y diálogo Publicar (sin red ni Llavero real)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLineEdit, QMessageBox

from app import credenciales
from app.settings import Ajustes
from app.widgets.dialogo_publicar import DialogoPublicar
from app.widgets.dialogo_redes import DialogoRedes
from tests.redes_falsos import ProveedorFalso
from videopipeline.caption import Caption
from videopipeline.redes import registro
from videopipeline.redes.modelo import (
    ORDEN,
    ModoInstagram,
    ModoTikTok,
    Plataforma,
    Resultado,
)
from videopipeline.redes.proveedor import PROVEEDOR_POR_DEFECTO

T, Y, I = Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM
CLAVE = "clave-de-prueba-42"


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


# --- ajustes ---


def test_ajustes_redes_por_defecto(ajustes):
    assert ajustes.proveedor_redes == PROVEEDOR_POR_DEFECTO
    assert ajustes.perfil_redes == ""
    assert ajustes.youtube_categoria == "22"
    assert ajustes.tiktok_modo == ModoTikTok.BORRADOR
    assert ajustes.instagram_modo == ModoInstagram.PRUEBA
    assert ajustes.plataformas_redes == list(ORDEN)


def test_ajustes_redes_persisten(tmp_path):
    ruta = str(tmp_path / "p.ini")
    a = Ajustes(QSettings(ruta, QSettings.Format.IniFormat))
    a.perfil_redes = " yo "
    a.youtube_categoria = "28"
    a.tiktok_modo = ModoTikTok.PUBLICO
    a.instagram_modo = ModoInstagram.NORMAL
    a.plataformas_redes = [I, T]
    a._q.sync()
    b = Ajustes(QSettings(ruta, QSettings.Format.IniFormat))
    assert b.perfil_redes == "yo"
    assert b.ajustes_proveedor() == {"perfil": "yo"}
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
    assert ajustes.proveedor_redes == PROVEEDOR_POR_DEFECTO
    assert ajustes.tiktok_modo == ModoTikTok.BORRADOR
    assert ajustes.instagram_modo == ModoInstagram.PRUEBA


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
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    assert list(dialogo.casillas) == [T, Y, I]
    assert [c.text() for c in dialogo.casillas.values()] == ["TikTok", "YouTube", "Instagram"]
    assert all(c.isChecked() for c in dialogo.casillas.values())
    opciones = dialogo.opciones()
    assert opciones.tiktok_modo == ModoTikTok.PUBLICO
    assert opciones.instagram_modo == ModoInstagram.PRUEBA
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
                         "datos": {"perfil": "mi_perfil"}}
    resultados = senal.args[0]
    assert list(resultados) == [T, Y, I]
    assert [c[1] for c in proveedor.llamadas] == [T, Y, I]
    assert "borradores" in dialogo.estados[T].text()
    assert "✗" in dialogo.estados[Y].text()
    assert "&lt;agotada&gt;" in dialogo.estados[Y].text()  # texto del servicio escapado
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
