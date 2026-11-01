"""Ventana Programadas…: calendario de mes y cancelar (sin red ni Llavero real)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton

from app import credenciales, segundo_plano
from app.settings import Ajustes
from app.widgets import dialogo_programadas
from app.widgets.dialogo_programadas import DialogoProgramadas, agrupar
from tests.redes_falsos import ProveedorFalso
from videopipeline.redes import registro
from videopipeline.redes.modelo import ModoTikTok, Plataforma, Programada
from videopipeline.redes.proveedor import PROVEEDOR_POR_DEFECTO, ErrorConsulta

T, Y, I = Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM
MADRID = ZoneInfo("Europe/Madrid")
AHORA = datetime(2026, 11, 1, 21, 40, tzinfo=timezone.utc)  # 22:40 en Madrid, el 1


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


UNO_T = Programada("j1", _utc(2026, 11, 3, 17, 0), (T,), "Uno",
                   {T: ModoTikTok.BORRADOR.value})
UNO_Y = Programada("j2", _utc(2026, 11, 3, 17, 0), (Y,), "Uno")
DOS = Programada("j3", _utc(2026, 11, 3, 23, 30), (I,), "Dos")  # 00:30 del 4 en Madrid
DICIEMBRE = Programada("j4", _utc(2026, 12, 10, 11, 0), (T, Y), "Web")


@pytest.fixture(autouse=True)
def sin_tareas_colgando(qtbot):
    yield
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=10000)


@pytest.fixture
def ajustes(tmp_path) -> Ajustes:
    return Ajustes(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))


def _listo(ajustes):
    ajustes.perfil_redes = "mi_perfil"
    credenciales.guardar(PROVEEDOR_POR_DEFECTO, "clave")


def _dialogo(qtbot, ajustes, proveedor):
    dialogo = DialogoProgramadas(ajustes, fabrica=lambda nombre, clave, datos: proveedor,
                                 zona=MADRID, ahora=lambda: AHORA)
    qtbot.addWidget(dialogo)
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=5000)
    return dialogo


def _textos(celda) -> list[str]:
    return [b.text() for b in celda.findChildren(QPushButton)]


def _responder(monkeypatch, respuesta=QMessageBox.StandardButton.Yes):
    preguntas = []

    def pregunta(*args, **kwargs):
        preguntas.append(args[2])
        return respuesta

    monkeypatch.setattr("app.widgets.dialogo_programadas.QMessageBox.question", pregunta)
    return preguntas


def test_agrupar_por_titulo_y_hora_en_el_dia_local():
    grupos = agrupar([DOS, UNO_Y, UNO_T], MADRID)
    assert sorted(grupos) == [date(2026, 11, 3), date(2026, 11, 4)]
    [uno] = grupos[date(2026, 11, 3)]
    assert uno.titulo == "Uno" and uno.fecha == datetime(2026, 11, 3, 18, 0, tzinfo=MADRID)
    assert uno.plataformas == [T, Y]
    assert [t.referencia for t in uno.trabajos] == ["j1", "j2"]
    [dos] = grupos[date(2026, 11, 4)]
    assert dos.fecha.hour == 0 and dos.fecha.minute == 30


def test_calendario_pinta_y_navega(qtbot, ajustes, llavero_falso):
    _listo(ajustes)
    proveedor = ProveedorFalso(pendientes=[UNO_T, UNO_Y, DOS, DICIEMBRE])
    dialogo = _dialogo(qtbot, ajustes, proveedor)
    assert proveedor.consultas == ["programadas"]
    assert dialogo.etiqueta_mes.text() == "Noviembre 2026"
    assert _textos(dialogo.celdas[date(2026, 11, 3)]) == ["18:00 · TT YT\nUno"]
    assert _textos(dialogo.celdas[date(2026, 11, 4)]) == ["00:30 · IG\nDos"]
    assert _textos(dialogo.celdas[date(2026, 11, 5)]) == []
    [etiqueta] = dialogo.celdas[date(2026, 11, 3)].findChildren(QPushButton)
    assert etiqueta.toolTip() == "18:00 · TikTok, YouTube · Uno"
    assert "Europe/Madrid" in dialogo.etiqueta_zona.text()
    # La primera fila empieza en lunes: el 26 de octubre.
    assert min(dialogo.celdas) == date(2026, 10, 26)
    dialogo.boton_siguiente.click()
    assert dialogo.etiqueta_mes.text() == "Diciembre 2026"
    assert _textos(dialogo.celdas[date(2026, 12, 10)]) == ["12:00 · TT YT\nWeb"]
    dialogo.boton_anterior.click()
    dialogo.boton_anterior.click()
    assert dialogo.etiqueta_mes.text() == "Octubre 2026"
    assert proveedor.consultas == ["programadas"]  # navegar no vuelve a consultar
    dialogo.boton_actualizar.click()
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=5000)
    assert proveedor.consultas == ["programadas", "programadas"]


def test_muchas_en_un_dia_muestra_mas(qtbot, ajustes, llavero_falso):
    _listo(ajustes)
    muchas = [Programada(f"j{h}", _utc(2026, 11, 3, h, 0), (T,), f"V{h}") for h in range(8, 13)]
    dialogo = _dialogo(qtbot, ajustes, ProveedorFalso(pendientes=muchas))
    textos = _textos(dialogo.celdas[date(2026, 11, 3)])
    assert len(textos) == 4 and textos[-1] == "+2 más"


def test_lista_poda_el_indice_local_solo_lo_pasado(qtbot, ajustes, llavero_falso, tmp_path):
    _listo(ajustes)
    ajustes.anotar_programada("j1", tmp_path / "a.mp4", UNO_T.fecha)
    ajustes.anotar_programada("ya-salio", tmp_path / "b.mp4", AHORA - timedelta(hours=1))
    # Aunque la lista no la traiga (otro perfil, retraso del servicio), una
    # futura se queda.
    ajustes.anotar_programada("futura", tmp_path / "c.mp4", AHORA + timedelta(days=3))
    _dialogo(qtbot, ajustes, ProveedorFalso(pendientes=[UNO_T]))
    assert ajustes.programadas_locales() == {"j1": str(tmp_path / "a.mp4"),
                                             "futura": str(tmp_path / "c.mp4")}


def test_error_de_consulta_se_muestra(qtbot, ajustes, llavero_falso):
    _listo(ajustes)
    dialogo = _dialogo(qtbot, ajustes, ProveedorFalso(pendientes=ErrorConsulta("sin red")))
    assert "sin red" in dialogo.etiqueta_estado.text()
    assert all(not _textos(c) for c in dialogo.celdas.values())


def test_sin_clave_lo_dice_y_no_consulta(qtbot, ajustes, llavero_falso):
    ajustes.perfil_redes = "mi_perfil"
    proveedor = ProveedorFalso(pendientes=[UNO_T])
    dialogo = _dialogo(qtbot, ajustes, proveedor)
    assert "API key" in dialogo.etiqueta_estado.text()
    assert proveedor.consultas == []


def test_cancelar_quita_la_etiqueta_y_limpia_registro(qtbot, ajustes, llavero_falso,
                                                       monkeypatch, tmp_path):
    _listo(ajustes)
    video = tmp_path / "v.mp4"
    registro.anotar(video, T, "", "p", programada=UNO_T.fecha, referencia="j1")
    registro.anotar(video, Y, "", "p", programada=UNO_Y.fecha, referencia="j2")
    ajustes.anotar_programada("j1", video, UNO_T.fecha)
    proveedor = ProveedorFalso(pendientes=[UNO_T, UNO_Y])
    dialogo = _dialogo(qtbot, ajustes, proveedor)
    # Pulsar la etiqueta abre el detalle de su grupo.
    abiertos = []
    monkeypatch.setattr(QDialog, "exec", lambda self: abiertos.append(self) or 0)
    [etiqueta] = dialogo.celdas[date(2026, 11, 3)].findChildren(QPushButton)
    etiqueta.click()
    [detalle] = abiertos
    botones = {b.text(): b for b in detalle.findChildren(QPushButton)}
    assert "Cancelar todas" in botones
    detalle.show()
    preguntas = _responder(monkeypatch)
    detalle.findChildren(QPushButton, "cancelar_j1")[0].click()
    assert not detalle.isVisible()
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=5000)
    assert "TikTok" in preguntas[0] and "03/11 a las 18:00" in preguntas[0]
    assert "cancelar:j1" in proveedor.consultas
    assert _textos(dialogo.celdas[date(2026, 11, 3)]) == ["18:00 · YT\nUno"]
    assert [e.referencia for e in registro.leer(video)] == ["j2"]
    assert "j1" not in ajustes.programadas_locales()


def test_cancelar_todas(qtbot, ajustes, llavero_falso, monkeypatch):
    _listo(ajustes)
    proveedor = ProveedorFalso(pendientes=[UNO_T, UNO_Y])
    dialogo = _dialogo(qtbot, ajustes, proveedor)
    _responder(monkeypatch)
    dialogo.cancelar([UNO_T, UNO_Y])
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=5000)
    assert [c for c in proveedor.consultas if c.startswith("cancelar")] == [
        "cancelar:j1", "cancelar:j2"]
    assert _textos(dialogo.celdas[date(2026, 11, 3)]) == []
    assert "2" in dialogo.etiqueta_estado.text()


def test_mas_abre_todas_las_del_dia(qtbot, ajustes, llavero_falso, monkeypatch):
    _listo(ajustes)
    muchas = [Programada(f"j{h}", _utc(2026, 11, 3, h, 0), (T,), f"V{h}") for h in range(8, 13)]
    dialogo = _dialogo(qtbot, ajustes, ProveedorFalso(pendientes=muchas))
    abiertos = []
    monkeypatch.setattr(QDialog, "exec", lambda self: abiertos.append(self) or 0)
    dialogo.celdas[date(2026, 11, 3)].findChildren(QPushButton)[-1].click()
    [detalle] = abiertos
    assert len(detalle.findChildren(QPushButton, None)) == 5 + 2  # 5 Cancelar + todas + Cerrar


def test_cancelar_pide_confirmacion_y_no_cierra_el_detalle(qtbot, ajustes, llavero_falso,
                                                           monkeypatch):
    _listo(ajustes)
    proveedor = ProveedorFalso(pendientes=[UNO_T])
    dialogo = _dialogo(qtbot, ajustes, proveedor)
    _responder(monkeypatch, QMessageBox.StandardButton.No)
    [grupo] = agrupar([UNO_T], MADRID)[date(2026, 11, 3)]
    detalle = dialogo.detalle([grupo])
    detalle.show()
    detalle.findChildren(QPushButton, "cancelar_j1")[0].click()
    assert detalle.isVisible()
    detalle.close()
    assert dialogo.cancelar([UNO_T]) is False
    assert not [c for c in proveedor.consultas if c.startswith("cancelar")]
    assert _textos(dialogo.celdas[date(2026, 11, 3)]) == ["18:00 · TT\nUno"]


def test_cancelar_falla_deja_la_etiqueta_y_avisa(qtbot, ajustes, llavero_falso, monkeypatch):
    _listo(ajustes)
    proveedor = ProveedorFalso(pendientes=[UNO_T], al_cancelar=ErrorConsulta("ocupado"))
    dialogo = _dialogo(qtbot, ajustes, proveedor)
    _responder(monkeypatch)
    avisos = []
    monkeypatch.setattr("app.widgets.dialogo_programadas.QMessageBox.warning",
                        lambda *a, **k: avisos.append(a[2]))
    dialogo.cancelar([UNO_T])
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=5000)
    assert avisos and "ocupado" in avisos[0]
    assert _textos(dialogo.celdas[date(2026, 11, 3)]) == ["18:00 · TT\nUno"]
    assert "ocupado" in dialogo.etiqueta_estado.text()


def test_ya_no_programada_no_borra_el_aviso_de_duplicado(qtbot, ajustes, llavero_falso,
                                                         monkeypatch, tmp_path):
    """Un 404 al cancelar puede ser que ya se publicó: el registro se queda."""
    _listo(ajustes)
    video = tmp_path / "v.mp4"
    registro.anotar(video, T, "", "p", programada=UNO_T.fecha, referencia="j1")
    ajustes.anotar_programada("j1", video, UNO_T.fecha)
    proveedor = ProveedorFalso(pendientes=[UNO_T])
    dialogo = _dialogo(qtbot, ajustes, proveedor)
    proveedor.pendientes = []  # salió mientras la ventana estaba abierta
    _responder(monkeypatch)
    dialogo.cancelar([UNO_T])
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=5000)
    assert _textos(dialogo.celdas[date(2026, 11, 3)]) == []
    assert "puede que ya se hayan publicado" in dialogo.etiqueta_estado.text()
    assert [e.referencia for e in registro.leer(video)] == ["j1"]
    assert ajustes.programadas_locales() == {}


def test_no_se_cierra_mientras_cancela(qtbot, ajustes, llavero_falso, monkeypatch):
    _listo(ajustes)
    dialogo = _dialogo(qtbot, ajustes, ProveedorFalso(pendientes=[UNO_T]))
    dialogo.show()
    dialogo._cancelando = True  # simula una cancelación en marcha
    dialogo.reject()
    assert dialogo.isVisible()
    dialogo._cancelando = False
    dialogo.reject()
    assert not dialogo.isVisible()


def test_cancelar_mientras_consulta_lo_dice(qtbot, ajustes, llavero_falso, monkeypatch):
    _listo(ajustes)
    proveedor = ProveedorFalso(pendientes=[UNO_T])
    dialogo = _dialogo(qtbot, ajustes, proveedor)
    avisos = []
    monkeypatch.setattr("app.widgets.dialogo_programadas.QMessageBox.information",
                        lambda *a, **k: avisos.append(a[2]))
    dialogo._ocupado = True  # simula una consulta en marcha
    assert dialogo.cancelar([UNO_T]) is False
    assert avisos and "Espera" in avisos[0]
    dialogo._ocupado = False
