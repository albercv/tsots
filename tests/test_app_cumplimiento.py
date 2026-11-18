"""Publicar en TikTok en directo como pide TikTok, y el contenido comercial (sin red)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QMessageBox

from app import credenciales, segundo_plano
from app.settings import Ajustes
from app.widgets import dialogo_publicar
from app.widgets.dialogo_publicar import DialogoPublicar
from app.widgets.dialogo_publicar_shorts import DialogoPublicarShorts
from tests.redes_falsos import ProveedorFalso
from videopipeline import shorts
from videopipeline.caption import Caption, escribir_md
from videopipeline.redes import portada_video
from videopipeline.redes.modelo import PRIVACIDADES_TIKTOK, AjustesTikTok, ModoTikTok, Plataforma
from videopipeline.redes.proveedor import PROVEEDOR_POR_DEFECTO, ErrorConsulta

T, Y, I, F = Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM, Plataforma.FACEBOOK
MADRID = ZoneInfo("Europe/Madrid")
URL_MUSICA = "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en"
URL_MARCA = "https://www.tiktok.com/legal/page/global/bc-policy/en"
ELIGE = "Elige quién puede verlo…"


@pytest.fixture(autouse=True)
def sin_hilos_colgando(qtbot):
    yield
    qtbot.waitUntil(lambda: dialogo_publicar.hilos_vivos() == 0, timeout=10000)
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=10000)


@pytest.fixture(autouse=True)
def portadas(monkeypatch) -> list[Path]:
    """Sin ffprobe ni OpenCV: la portada es un fotograma negro en el segundo 1.5.
    Devuelve los vídeos de los que se pidió."""
    pedidas: list[Path] = []

    def elegir(video, duracion=None, leer=None):
        pedidas.append(Path(video))
        return 1.5, np.zeros((32, 18, 3), np.uint8)

    monkeypatch.setattr(portada_video, "elegir", elegir)
    return pedidas


@pytest.fixture
def ajustes(tmp_path) -> Ajustes:
    ajustes = Ajustes(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    ajustes.perfil_redes = "mi_perfil"
    ajustes.plataformas_redes = [T, Y, I]
    credenciales.guardar(PROVEEDOR_POR_DEFECTO, "clave")
    return ajustes


@pytest.fixture
def video(tmp_path) -> Path:
    ruta = tmp_path / "clip_limpio.mp4"
    ruta.write_bytes(b"MP4")
    return ruta


def _esperar(qtbot) -> None:
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=5000)


def _dialogo(qtbot, video, ajustes, proveedor=None, duracion=30.0):
    proveedor = proveedor or ProveedorFalso()
    dialogo = DialogoPublicar(
        video, Caption("Título", "Cuerpo", ["#ia"], ["ia"]), ajustes,
        fabrica=lambda nombre, clave, datos: proveedor, medir=lambda v: duracion)
    qtbot.addWidget(dialogo)
    _esperar(qtbot)
    return dialogo, proveedor


def _elegir(combo, valor) -> None:
    combo.setCurrentIndex(combo.findData(valor))


def _directo(qtbot, dialogo) -> None:
    _elegir(dialogo.combo_tiktok, ModoTikTok.PUBLICO.value)
    _esperar(qtbot)


def _textos(combo) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def _sin_etiquetas(texto: str) -> str:
    return re.sub(r"<[^>]+>", "", texto)


def _confirmar(monkeypatch) -> None:
    for modulo in ("dialogo_publicar", "dialogo_publicar_shorts"):
        monkeypatch.setattr(f"app.widgets.{modulo}.QMessageBox.question",
                            lambda *a, **k: QMessageBox.StandardButton.Yes)


def test_tiktok_directo_pide_privacidad(qtbot, video, ajustes):
    dialogo, proveedor = _dialogo(qtbot, video, ajustes)
    assert dialogo.grupo_tiktok.isHidden()  # en borrador no se pide nada
    assert "ajustes_tiktok" not in proveedor.consultas
    assert dialogo.boton_publicar.isEnabled()
    _elegir(dialogo.combo_tiktok, ModoTikTok.PUBLICO.value)
    assert dialogo.estados[T].text() == "Cargando los permisos de TikTok…"
    assert not dialogo.boton_publicar.isEnabled()
    _esperar(qtbot)
    assert proveedor.consultas.count("ajustes_tiktok") == 1
    assert not dialogo.grupo_tiktok.isHidden()
    assert dialogo.etiqueta_cuenta_tiktok.text() == "Se publicará en: @yo_tiktok"
    combo = dialogo.combo_privacidad_tiktok
    assert _textos(combo) == [ELIGE, "Todo el mundo", "Seguidores", "Amigos", "Solo yo"]
    assert combo.currentIndex() == 0 and combo.currentData() == ""
    assert not dialogo.boton_publicar.isEnabled()
    assert dialogo.estados[T].text() == "Elige quién puede verlo en TikTok"
    _elegir(combo, "SELF_ONLY")
    assert dialogo.boton_publicar.isEnabled()
    # Volver a borrador y a directo no lo pide otra vez ni olvida la elección.
    _elegir(dialogo.combo_tiktok, ModoTikTok.BORRADOR.value)
    assert dialogo.grupo_tiktok.isHidden()
    _directo(qtbot, dialogo)
    assert proveedor.consultas.count("ajustes_tiktok") == 1
    assert combo.currentData() == "SELF_ONLY" and dialogo.boton_publicar.isEnabled()


def test_tiktok_combo_solo_privacidades_de_la_cuenta(qtbot, video, ajustes):
    proveedor = ProveedorFalso(ajustes_tiktok=AjustesTikTok(
        privacidades=("FOLLOWER_OF_CREATOR", "SELF_ONLY")))
    dialogo, _p = _dialogo(qtbot, video, ajustes, proveedor)
    _directo(qtbot, dialogo)
    combo = dialogo.combo_privacidad_tiktok
    assert combo.count() == 3
    assert _textos(combo) == [ELIGE, "Seguidores", "Solo yo"]
    assert [combo.itemData(i) for i in range(3)] == ["", "FOLLOWER_OF_CREATOR", "SELF_ONLY"]


def test_tiktok_casillas_desmarcadas_y_deshabilitadas_si_la_cuenta_las_apaga(
        qtbot, video, ajustes):
    proveedor = ProveedorFalso(ajustes_tiktok=AjustesTikTok(
        privacidades=tuple(PRIVACIDADES_TIKTOK), comentarios_off=True, stitch_off=True))
    dialogo, _p = _dialogo(qtbot, video, ajustes, proveedor)
    casillas = (dialogo.casilla_comentarios_tiktok, dialogo.casilla_duos_tiktok,
                dialogo.casilla_stitch_tiktok)
    assert [c.text() for c in casillas] == [
        "Permitir comentarios", "Permitir dúos", "Permitir stitch"]
    _directo(qtbot, dialogo)
    assert not any(c.isChecked() for c in casillas)
    assert [c.isEnabled() for c in casillas] == [False, True, False]
    assert [c.toolTip() for c in casillas] == [
        "Desactivado en tu cuenta de TikTok", "", "Desactivado en tu cuenta de TikTok"]


def test_tiktok_permisos_con_error_bloquean_directo_pero_no_borrador(qtbot, video, ajustes):
    error = "Reconecta tu cuenta de TikTok en Upload-Post."
    proveedor = ProveedorFalso(ajustes_tiktok=ErrorConsulta(error))
    dialogo, _p = _dialogo(qtbot, video, ajustes, proveedor)
    _directo(qtbot, dialogo)
    assert dialogo.estados[T].text() == error
    assert not dialogo.boton_publicar.isEnabled()
    _elegir(dialogo.combo_tiktok, ModoTikTok.BORRADOR.value)
    assert dialogo.boton_publicar.isEnabled()
    # Tras un error, volver a elegir el modo directo lo pide otra vez.
    proveedor.ajustes_tiktok_ = AjustesTikTok(privacidades=tuple(PRIVACIDADES_TIKTOK))
    _directo(qtbot, dialogo)
    assert proveedor.consultas.count("ajustes_tiktok") == 2
    assert dialogo.estados[T].text() == "Elige quién puede verlo en TikTok"


def test_tiktok_duracion_mayor_que_la_cuenta_desmarca(qtbot, video, ajustes):
    proveedor = ProveedorFalso(ajustes_tiktok=AjustesTikTok(
        privacidades=tuple(PRIVACIDADES_TIKTOK), max_segundos=60))
    dialogo, _p = _dialogo(qtbot, video, ajustes, proveedor, duracion=90.0)
    _directo(qtbot, dialogo)
    casilla = dialogo.casillas[T]
    assert not casilla.isEnabled() and not casilla.isChecked()
    assert dialogo.estados[T].text() == (
        "Este vídeo dura más de lo que tu cuenta de TikTok permite publicar (1:00)")
    assert dialogo.grupo_tiktok.isHidden()
    assert dialogo.boton_publicar.isEnabled()  # YouTube e Instagram siguen
    # En borrador no hay ese límite: vuelve marcada.
    _elegir(dialogo.combo_tiktok, ModoTikTok.BORRADOR.value)
    assert casilla.isEnabled() and casilla.isChecked()


def test_tiktok_permisos_se_vuelven_a_pedir_al_cerrar_redes(qtbot, video, ajustes):
    proveedor = ProveedorFalso(ajustes_tiktok=ErrorConsulta(
        "Reconecta tu cuenta de TikTok en Upload-Post."))
    dialogo, _p = _dialogo(qtbot, video, ajustes, proveedor)
    _directo(qtbot, dialogo)
    assert not dialogo.boton_publicar.isEnabled()
    # Reconecta TikTok (otra cuenta, mismo perfil) y vuelve de Redes….
    proveedor.ajustes_tiktok_ = AjustesTikTok(privacidades=("SELF_ONLY",), duos_off=True)
    dialogo.refrescar_servicio()
    _esperar(qtbot)
    assert proveedor.consultas.count("ajustes_tiktok") == 2
    assert _textos(dialogo.combo_privacidad_tiktok) == [ELIGE, "Solo yo"]
    assert not dialogo.casilla_duos_tiktok.isEnabled()
    assert dialogo.estados[T].text() == "Elige quién puede verlo en TikTok"


def test_contenido_de_marca_vacia_solo_yo(qtbot, video, ajustes):
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    _directo(qtbot, dialogo)
    combo = dialogo.combo_privacidad_tiktok
    _elegir(combo, "SELF_ONLY")
    solo_yo = combo.findData("SELF_ONLY")
    assert dialogo.boton_publicar.isEnabled()
    dialogo.casilla_comercial.setChecked(True)
    dialogo.casilla_de_marca.setChecked(True)
    assert combo.currentIndex() == 0
    assert not combo.model().item(solo_yo).isEnabled()
    assert combo.itemData(solo_yo, Qt.ItemDataRole.ToolTipRole) == (
        "El contenido de marca no puede ser privado")
    assert not dialogo.boton_publicar.isEnabled()
    assert dialogo.estados[T].text() == "Elige quién puede verlo en TikTok"
    _elegir(combo, "FOLLOWER_OF_CREATOR")
    assert dialogo.boton_publicar.isEnabled()
    dialogo.casilla_de_marca.setChecked(False)
    assert combo.model().item(solo_yo).isEnabled()
    assert not combo.itemData(solo_yo, Qt.ItemDataRole.ToolTipRole)


def test_comercial_sin_casillas_bloquea(qtbot, video, ajustes):
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    assert not dialogo.casilla_comercial.isChecked()
    assert not dialogo.casilla_tu_marca.isEnabled() and not dialogo.casilla_de_marca.isEnabled()
    assert dialogo.boton_publicar.isEnabled()
    dialogo.casilla_comercial.setChecked(True)
    assert dialogo.casilla_tu_marca.isEnabled() and dialogo.casilla_de_marca.isEnabled()
    assert not dialogo.boton_publicar.isEnabled()
    assert ("Indica si promocionas algo tuyo, de un tercero o ambos"
            in dialogo.etiqueta_comercial.text())
    dialogo.casilla_tu_marca.setChecked(True)
    assert dialogo.boton_publicar.isEnabled()
    assert "Indica si" not in dialogo.etiqueta_comercial.text()


def test_textos_de_etiqueta_y_consentimiento(qtbot, video, ajustes):
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    _directo(qtbot, dialogo)
    consentimiento = dialogo.etiqueta_consentimiento_tiktok
    assert consentimiento.openExternalLinks()
    assert _sin_etiquetas(consentimiento.text()) == (
        "Al publicar, aceptas la Confirmación de uso de música de TikTok")
    assert URL_MUSICA in consentimiento.text() and URL_MARCA not in consentimiento.text()
    dialogo.casilla_comercial.setChecked(True)
    dialogo.casilla_tu_marca.setChecked(True)
    assert 'Se etiquetará como "Contenido promocional"' in dialogo.etiqueta_comercial.text()
    dialogo.casilla_de_marca.setChecked(True)
    assert 'Se etiquetará como "Colaboración pagada"' in dialogo.etiqueta_comercial.text()
    assert "Contenido promocional" not in dialogo.etiqueta_comercial.text()
    assert _sin_etiquetas(consentimiento.text()) == (
        "Al publicar, aceptas la Política de contenido de marca y la Confirmación de uso "
        "de música de TikTok")
    assert URL_MUSICA in consentimiento.text() and URL_MARCA in consentimiento.text()
    dialogo.casilla_tu_marca.setChecked(False)
    assert 'Se etiquetará como "Colaboración pagada"' in dialogo.etiqueta_comercial.text()


def test_aviso_borrador_y_aviso_instagram(qtbot, video, ajustes):
    dialogo, _p = _dialogo(qtbot, video, ajustes)  # TikTok en borrador
    dialogo.casilla_comercial.setChecked(True)
    dialogo.casilla_tu_marca.setChecked(True)
    texto = dialogo.etiqueta_comercial.text()
    assert "Márcalo en la app de TikTok" in texto
    assert "Se etiquetará" not in texto and "Instagram o Facebook" not in texto
    dialogo.casilla_de_marca.setChecked(True)
    assert ("Añade la etiqueta de colaboración pagada desde la app de Instagram o Facebook"
            in dialogo.etiqueta_comercial.text())
    dialogo.casillas[I].setChecked(False)
    assert "Instagram o Facebook" not in dialogo.etiqueta_comercial.text()
    dialogo.casillas[F].setChecked(True)
    assert "Instagram o Facebook" in dialogo.etiqueta_comercial.text()


def test_opciones_lleva_las_elecciones(qtbot, video, ajustes):
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    opciones = dialogo.opciones()
    assert (opciones.tiktok_privacidad, opciones.tiktok_comentarios, opciones.tiktok_duos,
            opciones.tiktok_stitch, opciones.tu_marca, opciones.contenido_de_marca,
            opciones.idioma) == ("", False, False, False, False, False, "")
    _directo(qtbot, dialogo)
    _elegir(dialogo.combo_privacidad_tiktok, "FOLLOWER_OF_CREATOR")
    dialogo.casilla_comentarios_tiktok.setChecked(True)
    dialogo.casilla_stitch_tiktok.setChecked(True)
    dialogo.casilla_comercial.setChecked(True)
    dialogo.casilla_de_marca.setChecked(True)
    opciones = dialogo.opciones()
    assert opciones.tiktok_modo == ModoTikTok.PUBLICO
    assert opciones.tiktok_privacidad == "FOLLOWER_OF_CREATOR"
    assert (opciones.tiktok_comentarios, opciones.tiktok_duos, opciones.tiktok_stitch) == (
        True, False, True)
    assert (opciones.tu_marca, opciones.contenido_de_marca) == (False, True)
    # Sin «Contenido comercial», las casillas de debajo no cuentan.
    dialogo.casilla_comercial.setChecked(False)
    assert (dialogo.opciones().tu_marca, dialogo.opciones().contenido_de_marca) == (
        False, False)


def test_no_se_recuerda_entre_publicaciones(qtbot, video, ajustes, monkeypatch):
    dialogo, proveedor = _dialogo(qtbot, video, ajustes)
    _directo(qtbot, dialogo)
    _elegir(dialogo.combo_privacidad_tiktok, "PUBLIC_TO_EVERYONE")
    dialogo.casilla_duos_tiktok.setChecked(True)
    dialogo.casilla_comercial.setChecked(True)
    dialogo.casilla_tu_marca.setChecked(True)
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=10000):
        dialogo.boton_publicar.click()
    tiktok = [c for c in proveedor.llamadas if c[0] == "publicar" and c[1] == T]
    assert tiktok[0][3].tiktok_privacidad == "PUBLIC_TO_EVERYONE"
    assert tiktok[0][3].tiktok_duos and tiktok[0][3].tu_marca
    assert tiktok[0][2].portada == 1.5
    assert "TikTok puede tardar unos minutos en mostrarlo" in dialogo.resumen.text()
    assert "minutos" not in dialogo.estados[Y].text()

    otro, _p = _dialogo(qtbot, video, ajustes)
    assert otro.combo_tiktok.currentData() == ModoTikTok.PUBLICO.value  # el modo sí
    _esperar(qtbot)
    assert otro.combo_privacidad_tiktok.currentIndex() == 0
    assert otro.combo_privacidad_tiktok.currentText() == ELIGE
    assert not any(c.isChecked() for c in (
        otro.casilla_comentarios_tiktok, otro.casilla_duos_tiktok, otro.casilla_stitch_tiktok))
    assert not otro.casilla_comercial.isChecked()
    assert not otro.casilla_tu_marca.isChecked() and not otro.casilla_de_marca.isChecked()


def test_vista_previa_de_la_portada(qtbot, video, ajustes, portadas, monkeypatch):
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    assert portadas == [video]
    assert not dialogo.vista_portada.isHidden()
    imagen = dialogo.vista_portada.pixmap()
    assert not imagen.isNull()
    assert imagen.width() <= 90 and imagen.height() <= 160
    # Sin fotograma elegido, no se muestra.
    monkeypatch.setattr(portada_video, "elegir", lambda *a, **k: None)
    otro, _p = _dialogo(qtbot, video, ajustes)
    assert otro.vista_portada.isHidden()


@pytest.fixture
def carpeta(tmp_path) -> Path:
    carpeta = tmp_path / "charla"
    carpeta.mkdir()
    candidatos = []
    for i, nombre in enumerate(("01 - Uno.mp4", "02 - Dos.mp4"), 1):
        (carpeta / nombre).write_bytes(b"MP4")
        escribir_md(Caption(f"SEO {i}", f"Cuerpo {i}", [f"#tag{i}"], ["clave"]),
                    (carpeta / nombre).with_suffix(".md"))
        candidatos.append({"archivo": nombre, "titulo": f"Titulo {i}", "inicio": 10.0,
                           "fin": 50.0, "descarte": ""})
    (carpeta / "shorts.json").write_text(json.dumps({"candidatos": candidatos}))
    return carpeta


def test_publicar_shorts_aplica_las_elecciones_a_cada_short(
        qtbot, carpeta, ajustes, portadas, monkeypatch):
    ajustes.plataformas_redes = [T, Y]
    proveedor = ProveedorFalso()
    dialogo = DialogoPublicarShorts(
        shorts.listar(carpeta), ajustes, fabrica=lambda nombre, clave, datos: proveedor,
        medir=lambda mp4: 40.0, ahora=lambda: datetime(2026, 11, 1, 22, 40, tzinfo=MADRID),
        zona=MADRID)
    qtbot.addWidget(dialogo)
    _esperar(qtbot)
    uno, dos = dialogo.filas
    assert portadas == [uno.corto.mp4]
    # La vista previa sigue al primer short marcado.
    uno.casilla.setChecked(False)
    _esperar(qtbot)
    assert portadas[-1] == dos.corto.mp4
    uno.casilla.setChecked(True)
    _esperar(qtbot)
    assert portadas[-1] == uno.corto.mp4
    _directo(qtbot, dialogo)
    assert not dialogo.boton_publicar.isEnabled()  # falta la privacidad
    _elegir(dialogo.combo_privacidad_tiktok, "MUTUAL_FOLLOW_FRIENDS")
    dialogo.casilla_duos_tiktok.setChecked(True)
    dialogo.casilla_comercial.setChecked(True)
    dialogo.casilla_tu_marca.setChecked(True)
    assert dialogo.boton_publicar.isEnabled()
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=10000):
        dialogo.boton_publicar.click()
    publicadas = [c for c in proveedor.llamadas if c[0] == "publicar"]
    tiktok = [c for c in publicadas if c[1] == T]
    assert [c[2].video.name for c in tiktok] == ["01 - Uno.mp4", "02 - Dos.mp4"]
    assert {(o.tiktok_privacidad, o.tiktok_comentarios, o.tiktok_duos, o.tiktok_stitch,
             o.tu_marca, o.contenido_de_marca) for _n, _p, _pub, o in tiktok} == {
        ("MUTUAL_FOLLOW_FRIENDS", False, True, False, True, False)}
    assert all(c[2].portada == 1.5 for c in publicadas)


def test_publicar_shorts_quita_tiktok_del_short_mas_largo_que_la_cuenta(
        qtbot, carpeta, ajustes, monkeypatch):
    ajustes.plataformas_redes = [T, Y]
    proveedor = ProveedorFalso(ajustes_tiktok=AjustesTikTok(
        privacidades=tuple(PRIVACIDADES_TIKTOK), max_segundos=60))
    duraciones = {"01 - Uno.mp4": 40.0, "02 - Dos.mp4": 90.0}
    dialogo = DialogoPublicarShorts(
        shorts.listar(carpeta), ajustes, fabrica=lambda nombre, clave, datos: proveedor,
        medir=lambda mp4: duraciones[Path(mp4).name],
        ahora=lambda: datetime(2026, 11, 1, 22, 40, tzinfo=MADRID), zona=MADRID)
    qtbot.addWidget(dialogo)
    _esperar(qtbot)
    _directo(qtbot, dialogo)
    _elegir(dialogo.combo_privacidad_tiktok, "SELF_ONLY")
    uno, dos = dialogo.filas
    assert uno.estado.text() == ""
    assert dos.estado.text() == (
        "Este vídeo dura más de lo que tu cuenta de TikTok permite publicar (1:00)")
    assert dialogo.boton_publicar.isEnabled()  # al 2.º le queda YouTube
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=10000):
        dialogo.boton_publicar.click()
    assert [(c[1], c[2].video.name) for c in proveedor.llamadas if c[0] == "publicar"] == [
        (T, "01 - Uno.mp4"), (Y, "01 - Uno.mp4"), (Y, "02 - Dos.mp4")]


def test_opciones_lleva_el_idioma_recibido(qtbot, video, ajustes):
    dialogo = DialogoPublicar(
        video, Caption("T", "C", [], []), ajustes, idioma="en",
        fabrica=lambda n, c, d: ProveedorFalso(), medir=lambda v: 30.0)
    qtbot.addWidget(dialogo)
    assert dialogo.opciones().idioma == "en"
