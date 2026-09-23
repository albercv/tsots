"""Ajustes de redes, diálogo Redes… y diálogo Publicar (sin red ni Llavero real)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLineEdit, QMessageBox

from app import credenciales
from app.settings import Ajustes
from app.widgets import dialogo_publicar
from app.widgets.dialogo_publicar import DialogoPublicar
from app.widgets.dialogo_redes import DialogoRedes
from tests.redes_falsos import ProveedorFalso
from videopipeline.caption import Caption
from videopipeline.redes import publicador, registro
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


@pytest.fixture(autouse=True)
def sin_hilos_colgando(qtbot):
    """Ningún test acaba con una publicación en marcha."""
    yield
    qtbot.waitUntil(lambda: dialogo_publicar.hilos_vivos() == 0, timeout=10000)


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
    assert dialogo.estados[I].text() == ""
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
    for p in ORDEN:
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
