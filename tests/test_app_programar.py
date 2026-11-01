"""Programar desde el diálogo Publicar (sin red ni Llavero real)."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QDateTime, QSettings
from PySide6.QtWidgets import QMessageBox

from app import credenciales, segundo_plano
from app.settings import Ajustes
from app.widgets import dialogo_publicar
from app.widgets.dialogo_publicar import DialogoPublicar
from tests.redes_falsos import ProveedorFalso
from videopipeline.caption import Caption
from videopipeline.redes import registro
from videopipeline.redes.modelo import Plataforma, Resultado
from videopipeline.redes.proveedor import PROVEEDOR_POR_DEFECTO

T, Y, I = Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM
MADRID = ZoneInfo("Europe/Madrid")
AHORA = datetime(2026, 11, 1, 22, 40, tzinfo=MADRID)
CUANDO = datetime(2026, 11, 3, 18, 0, tzinfo=MADRID)


@pytest.fixture(autouse=True)
def sin_hilos_colgando(qtbot, monkeypatch):
    monkeypatch.setattr(dialogo_publicar, "medir_duracion", lambda video: 30.0)
    yield
    qtbot.waitUntil(lambda: dialogo_publicar.hilos_vivos() == 0, timeout=10000)
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=10000)


@pytest.fixture
def ajustes(tmp_path) -> Ajustes:
    return Ajustes(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))


@pytest.fixture
def video(tmp_path) -> Path:
    ruta = tmp_path / "clip_limpio.mp4"
    ruta.write_bytes(b"MP4")
    return ruta


def _dialogo(qtbot, video, ajustes, proveedor=None):
    proveedor = proveedor or ProveedorFalso()
    dialogo = DialogoPublicar(
        video, Caption(titulo="Título X", caption="Cuerpo", hashtags=["#ia"],
                       palabras_clave=["ia"]),
        ajustes, fabrica=lambda nombre, clave, datos: proveedor,
        ahora=lambda: AHORA, zona=MADRID)
    qtbot.addWidget(dialogo)
    return dialogo, proveedor


def _listo(ajustes):
    ajustes.perfil_redes = "mi_perfil"
    credenciales.guardar(PROVEEDOR_POR_DEFECTO, "clave")


def _confirmar(monkeypatch):
    preguntas = []

    def pregunta(*args, **kwargs):
        preguntas.append(args[2])
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr("app.widgets.dialogo_publicar.QMessageBox.question", pregunta)
    return preguntas


def _poner(dialogo, fecha: datetime) -> None:
    dialogo.campo_fecha.setDateTime(QDateTime(fecha.date(), fecha.time()))


def test_ajustes_programadas_locales(ajustes, video):
    assert ajustes.programadas_locales() == {}
    ajustes.anotar_programada("j1", video, CUANDO)
    ajustes.anotar_programada("j2", video, AHORA + timedelta(days=30))
    assert ajustes.programadas_locales() == {"j1": str(video), "j2": str(video)}
    assert ajustes.olvidar_programada("j1") == str(video)
    assert ajustes.olvidar_programada("j1") == ""
    ajustes.anotar_programada("j1", video, CUANDO)
    # Solo se olvidan las que ya pasaron.
    ajustes.podar_programadas(CUANDO + timedelta(minutes=1))
    assert ajustes.programadas_locales() == {"j2": str(video)}
    ajustes._q.setValue("redes/programadas", "{no es json")
    assert ajustes.programadas_locales() == {}


def test_por_defecto_ahora_con_fecha_inicial(qtbot, video, ajustes, llavero_falso):
    _listo(ajustes)
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    assert dialogo.radio_ahora.isChecked() and not dialogo.radio_programar.isChecked()
    assert not dialogo.campo_fecha.isEnabled()
    assert dialogo.programada() is None
    assert dialogo.boton_publicar.text() == "Publicar"
    # La siguiente hora en punto a más de una hora vista.
    assert dialogo.campo_fecha.dateTime().toPython() == datetime(2026, 11, 2, 0, 0)
    assert dialogo.opciones().programada is None


def test_programar_cambia_el_boton_y_valida_la_fecha(qtbot, video, ajustes, llavero_falso):
    _listo(ajustes)
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    dialogo.radio_programar.setChecked(True)
    assert dialogo.boton_publicar.text() == "Programar"
    assert dialogo.campo_fecha.isEnabled() and dialogo.boton_publicar.isEnabled()
    assert dialogo.aviso_fecha.isHidden()
    _poner(dialogo, AHORA + timedelta(minutes=10))
    assert not dialogo.boton_publicar.isEnabled()
    assert "15 minutos" in dialogo.aviso_fecha.text() and not dialogo.aviso_fecha.isHidden()
    _poner(dialogo, AHORA + timedelta(days=366))
    assert not dialogo.boton_publicar.isEnabled() and "un año" in dialogo.aviso_fecha.text()
    _poner(dialogo, CUANDO)
    assert dialogo.boton_publicar.isEnabled() and dialogo.aviso_fecha.isHidden()
    assert dialogo.programada() == CUANDO
    assert dialogo.opciones().programada == CUANDO
    dialogo.radio_ahora.setChecked(True)
    assert dialogo.boton_publicar.text() == "Publicar" and dialogo.programada() is None
    _poner(dialogo, AHORA)  # con «Ahora», la fecha no importa
    assert dialogo.boton_publicar.isEnabled()


def test_programar_envia_la_fecha_y_muestra_programado(qtbot, video, ajustes, llavero_falso,
                                                       monkeypatch):
    _listo(ajustes)
    proveedor = ProveedorFalso(respuestas={
        T: Resultado(T, ok=True, programada=CUANDO, referencia="j1"),
        Y: Resultado(Y, ok=True, programada=CUANDO, referencia="j2")})
    dialogo, _p = _dialogo(qtbot, video, ajustes, proveedor)
    dialogo.casillas[I].setChecked(False)
    dialogo.radio_programar.setChecked(True)
    _poner(dialogo, CUANDO)
    preguntas = _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=5000):
        dialogo.boton_publicar.click()
        assert not dialogo.radio_ahora.isEnabled() and not dialogo.campo_fecha.isEnabled()
    assert "¿Programar para el 03/11/2026 a las 18:00?" in preguntas[0]
    assert "Se programará «Título X»" in preguntas[0]
    assert [c[3].programada for c in proveedor.llamadas] == [CUANDO, CUANDO]
    assert "Programado para el 03/11 18:00" in dialogo.estados[T].text()
    assert "Programado en 2 de 2" in dialogo.etiqueta_estado.text()
    assert not dialogo.casillas[T].isChecked() and not dialogo.casillas[Y].isChecked()
    assert ajustes.programadas_locales() == {"j1": str(video), "j2": str(video)}
    assert "TikTok (programado para el 03/11/2026 18:00)" in dialogo.aviso_publicado.text()
    assert {e.referencia for e in registro.leer(video)} == {"j1", "j2"}


def test_si_la_hora_se_queda_corta_en_la_confirmacion_no_envia(
        qtbot, video, ajustes, llavero_falso, monkeypatch):
    _listo(ajustes)
    momentos = [AHORA]
    dialogo, proveedor = _dialogo(qtbot, video, ajustes)
    dialogo._ahora = lambda: momentos[-1]
    dialogo.radio_programar.setChecked(True)
    _poner(dialogo, AHORA + timedelta(minutes=20))

    def pregunta(*args, **kwargs):
        momentos.append(AHORA + timedelta(minutes=10))  # la confirmación se quedó abierta
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr("app.widgets.dialogo_publicar.QMessageBox.question", pregunta)
    dialogo.boton_publicar.click()
    assert proveedor.llamadas == [] and not dialogo.publicando
    assert "15 minutos" in dialogo.etiqueta_estado.text()


def test_zona_sin_nombre_usa_el_desfase_de_la_fecha_elegida(qtbot, video, ajustes,
                                                             llavero_falso):
    from datetime import timezone
    _listo(ajustes)
    dialogo = DialogoPublicar(
        video, Caption(titulo="t", caption="c", hashtags=[], palabras_clave=[]), ajustes,
        fabrica=lambda *a: ProveedorFalso(), ahora=lambda: AHORA,
        zona=timezone(timedelta(hours=1)))
    qtbot.addWidget(dialogo)
    dialogo.radio_programar.setChecked(True)
    _poner(dialogo, CUANDO)
    programada = dialogo.programada()
    assert programada.tzinfo is not None
    assert programada.replace(tzinfo=None) == CUANDO.replace(tzinfo=None)


def test_confirmacion_dice_lo_ya_programado(qtbot, video, ajustes, llavero_falso,
                                            monkeypatch):
    _listo(ajustes)
    registro.anotar(video, T, "", "prov", "borrador", programada=CUANDO, referencia="j1")
    dialogo, _p = _dialogo(qtbot, video, ajustes)
    preguntas = _confirmar(monkeypatch)
    monkeypatch.setattr(dialogo, "fabrica", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    dialogo.boton_publicar.click()
    assert "Ya programado en: TikTok (03/11/2026 18:00)" in preguntas[0]
    assert "Ya publicado antes" not in preguntas[0]
