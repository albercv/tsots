"""Publicar los shorts de un vídeo largo en lote, cada uno con su fecha (sin red)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QDateTime, QSettings
from PySide6.QtWidgets import QMessageBox

from app import credenciales, segundo_plano
from app.settings import Ajustes
from app.widgets import dialogo_publicar
from app.widgets.dialogo_publicar_shorts import DialogoPublicarShorts
from tests.redes_falsos import ProveedorFalso
from videopipeline import linkedin, shorts
from videopipeline.caption import Caption, escribir_md
from videopipeline.redes import registro
from videopipeline.redes.modelo import Plataforma, Resultado
from videopipeline.redes.proveedor import PROVEEDOR_POR_DEFECTO

T, Y, X = Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.X
MADRID = ZoneInfo("Europe/Madrid")
AHORA = datetime(2026, 11, 1, 22, 40, tzinfo=MADRID)
DURACIONES = {"01 - Uno.mp4": 70.0, "02 - Dos.mp4": 150.0, "03 - Tres.mp4": 90.0}


@pytest.fixture(autouse=True)
def sin_hilos_colgando(qtbot):
    yield
    qtbot.waitUntil(lambda: dialogo_publicar.hilos_vivos() == 0, timeout=10000)
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=10000)


@pytest.fixture
def ajustes(tmp_path) -> Ajustes:
    ajustes = Ajustes(QSettings(str(tmp_path / "t.ini"), QSettings.Format.IniFormat))
    ajustes.perfil_redes = "mi_perfil"
    credenciales.guardar(PROVEEDOR_POR_DEFECTO, "clave")
    return ajustes


@pytest.fixture
def carpeta(tmp_path) -> Path:
    """Tres shorts: el 3.º sin `.md`; el 2.º dura más de lo que admite X."""
    carpeta = tmp_path / "charla"
    carpeta.mkdir()
    candidatos = []
    for i, nombre in enumerate(DURACIONES, 1):
        (carpeta / nombre).write_bytes(b"MP4")
        if i < 3:
            escribir_md(Caption(f"SEO {i}", f"Cuerpo {i}", [f"#tag{i}"], ["clave"]),
                        (carpeta / nombre).with_suffix(".md"))
        candidatos.append({"archivo": nombre, "titulo": f"Titulo {i}", "inicio": 10.0,
                           "fin": 10.0 + DURACIONES[nombre], "descarte": ""})
    candidatos.append({"archivo": "", "titulo": "flojo", "inicio": 0, "fin": 70,
                       "descarte": "flojo"})
    (carpeta / "shorts.json").write_text(json.dumps({"candidatos": candidatos}))
    return carpeta


def _dialogo(qtbot, carpeta, ajustes, proveedor=None):
    proveedor = proveedor or ProveedorFalso()
    dialogo = DialogoPublicarShorts(
        shorts.listar(carpeta), ajustes, fabrica=lambda nombre, clave, datos: proveedor,
        medir=lambda mp4: DURACIONES[Path(mp4).name], ahora=lambda: AHORA, zona=MADRID)
    qtbot.addWidget(dialogo)
    qtbot.waitUntil(lambda: dialogo.boton_publicar.isEnabled(), timeout=5000)
    return dialogo, proveedor


def _confirmar(monkeypatch):
    preguntas = []

    def pregunta(*args, **kwargs):
        preguntas.append(args[2])
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr("app.widgets.dialogo_publicar.QMessageBox.question", pregunta)
    monkeypatch.setattr("app.widgets.dialogo_publicar_shorts.QMessageBox.question", pregunta)
    return preguntas


def _poner(fila, fecha: datetime) -> None:
    fila.campo.setDateTime(QDateTime(fecha.date(), fecha.time()))


def test_listar_lee_el_json_con_y_sin_md(carpeta):
    cortos = shorts.listar(carpeta)
    assert [c.mp4.name for c in cortos] == list(DURACIONES)
    assert [c.duracion for c in cortos] == [70.0, 150.0, 90.0]
    assert cortos[0].caption.titulo == "SEO 1" and cortos[2].caption is None
    (carpeta / "02 - Dos.mp4").unlink()  # un short borrado a mano no se ofrece
    assert [c.mp4.name for c in shorts.listar(carpeta)] == ["01 - Uno.mp4", "03 - Tres.mp4"]
    (carpeta / "shorts.json").write_text("{no es json")
    assert shorts.listar(carpeta) == []


def test_el_dialogo_lista_los_shorts_y_deshabilita_los_que_no_tienen_md(
        qtbot, carpeta, ajustes, llavero_falso):
    dialogo, _p = _dialogo(qtbot, carpeta, ajustes)
    uno, dos, tres = dialogo.filas
    assert uno.casilla.isChecked() and dos.casilla.isChecked()
    assert not tres.casilla.isEnabled() and not tres.casilla.isChecked()
    assert "sin caption" in tres.estado.text()
    assert "Titulo 1" in uno.casilla.text()
    # Fechas escalonadas un día por fila a partir de la fecha por defecto.
    assert uno.campo.dateTime().toPython() == datetime(2026, 11, 2, 0, 0)
    assert dialogo._fecha_de(dos.campo) == datetime(2026, 11, 3, 0, 0, tzinfo=MADRID)
    assert dialogo.boton_publicar.text() == "Programar 2 shorts"


def test_envia_cada_short_con_su_fecha_y_apunta_su_registro(
        qtbot, carpeta, ajustes, llavero_falso, monkeypatch):
    cuando = datetime(2026, 11, 5, 18, 0, tzinfo=MADRID)
    proveedor = ProveedorFalso(respuestas={
        p: Resultado(p, ok=True, programada=cuando, referencia=f"j-{p.value}")
        for p in (T, Y)})
    dialogo, _p = _dialogo(qtbot, carpeta, ajustes, proveedor)
    dialogo.casillas[Plataforma.INSTAGRAM].setChecked(False)
    uno, dos, _tres = dialogo.filas
    fechas = [AHORA + timedelta(days=3), AHORA + timedelta(days=5, hours=1)]
    fechas = [f.replace(minute=0, second=0, microsecond=0) for f in fechas]
    _poner(uno, fechas[0])
    _poner(dos, fechas[1])
    preguntas = _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=10000):
        dialogo.boton_publicar.click()
    assert len(preguntas) == 1 and "Titulo 1" in preguntas[0]
    # Uno detrás de otro, cada uno con su fecha y sus textos.
    llamadas = [(c[1], c[2].video.name, c[2].titulo, c[3].programada)
                for c in proveedor.llamadas]
    assert llamadas == [
        (T, "01 - Uno.mp4", "SEO 1", fechas[0]), (Y, "01 - Uno.mp4", "SEO 1", fechas[0]),
        (T, "02 - Dos.mp4", "SEO 2", fechas[1]), (Y, "02 - Dos.mp4", "SEO 2", fechas[1])]
    assert proveedor.llamadas[0][2].caption == "Cuerpo 1"
    assert proveedor.llamadas[0][2].hashtags == ("#tag1",)
    assert proveedor.llamadas[0][2].texto_x.startswith("SEO 1")
    # Cada short con su registro; el que no se envió, sin él.
    assert {e.plataforma for e in registro.leer(carpeta / "01 - Uno.mp4")} == {T, Y}
    assert {e.plataforma for e in registro.leer(carpeta / "02 - Dos.mp4")} == {T, Y}
    assert registro.leer(carpeta / "03 - Tres.mp4") == []
    assert "Programados 2 de 2" in dialogo.etiqueta_estado.text()
    assert "Programado" in dialogo.filas[0].estado.text()
    assert not dialogo.publicando and dialogo.casillas[T].isEnabled() is True
    assert dialogo.perfil_usado == "mi_perfil"


def test_x_se_bloquea_por_short_largo_sin_premium(qtbot, carpeta, ajustes, llavero_falso,
                                                  monkeypatch):
    dialogo, proveedor = _dialogo(qtbot, carpeta, ajustes)
    for p in Plataforma:
        dialogo.casillas[p].setChecked(p in (T, X))
    uno, dos, _tres = dialogo.filas
    assert "X sin Premium" in dos.estado.text() and "X sin Premium" not in uno.estado.text()
    assert dialogo.boton_publicar.isEnabled()  # al largo solo le falta X
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=10000):
        dialogo.boton_publicar.click()
    enviados = [(c[1], c[2].video.name) for c in proveedor.llamadas]
    assert enviados == [(T, "01 - Uno.mp4"), (X, "01 - Uno.mp4"), (T, "02 - Dos.mp4")]


def test_un_short_solo_con_x_demasiado_largo_impide_publicar(qtbot, carpeta, ajustes,
                                                             llavero_falso):
    dialogo, _p = _dialogo(qtbot, carpeta, ajustes)
    for p in Plataforma:
        dialogo.casillas[p].setChecked(p == X)
    assert not dialogo.boton_publicar.isEnabled()
    dialogo.filas[1].casilla.setChecked(False)  # sin el largo, ya se puede
    assert dialogo.boton_publicar.isEnabled()


def test_fecha_invalida_o_ninguno_marcado_deshabilita_y_se_dice(qtbot, carpeta, ajustes,
                                                                llavero_falso):
    dialogo, _p = _dialogo(qtbot, carpeta, ajustes)
    uno = dialogo.filas[0]
    _poner(uno, AHORA + timedelta(minutes=10))
    assert not dialogo.boton_publicar.isEnabled() and "15 minutos" in uno.estado.text()
    uno.casilla.setChecked(False)  # un short sin marcar no cuenta
    assert dialogo.boton_publicar.isEnabled()
    dialogo.filas[1].casilla.setChecked(False)
    assert not dialogo.boton_publicar.isEnabled()


def test_cancelar_la_confirmacion_no_envia_nada(qtbot, carpeta, ajustes, llavero_falso,
                                                monkeypatch):
    dialogo, proveedor = _dialogo(qtbot, carpeta, ajustes)
    monkeypatch.setattr("app.widgets.dialogo_publicar_shorts.QMessageBox.question",
                        lambda *a, **k: QMessageBox.StandardButton.Cancel)
    dialogo.boton_publicar.click()
    assert proveedor.llamadas == [] and not dialogo.publicando
    assert "no se ha enviado nada" in dialogo.etiqueta_estado.text()


def test_avisa_de_un_short_ya_publicado(qtbot, carpeta, ajustes, llavero_falso, monkeypatch):
    registro.anotar(carpeta / "02 - Dos.mp4", T, "https://t/1", "prov", "público")
    dialogo, _p = _dialogo(qtbot, carpeta, ajustes)
    assert "ya se publicó" in dialogo.filas[1].estado.text()
    preguntas = _confirmar(monkeypatch)
    monkeypatch.setattr(dialogo, "fabrica", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    dialogo.boton_publicar.click()
    assert "Ya publicado o programado antes" in preguntas[0] and "Titulo 2" in preguntas[0]


def test_linkedin_no_se_ofrece_ni_se_envia(qtbot, carpeta, ajustes, llavero_falso,
                                           monkeypatch):
    linkedin_ = Plataforma.LINKEDIN
    ajustes.plataformas_redes = [T, linkedin_]
    # Ni aunque el primer short tuviera un post de LinkedIn al lado.
    md, fotos = linkedin.rutas(carpeta / "01 - Uno.mp4")
    fotos.mkdir()
    (fotos / "01_portada.png").write_bytes(b"PNG")
    md.write_text("Post", encoding="utf-8")
    dialogo, proveedor = _dialogo(qtbot, carpeta, ajustes)
    assert dialogo.casillas[linkedin_].isHidden() and dialogo.estados[linkedin_].isHidden()
    assert not dialogo.casillas[linkedin_].isChecked()
    assert dialogo.plataformas() == [T]
    _confirmar(monkeypatch)
    with qtbot.waitSignal(dialogo.publicacion_terminada, timeout=10000):
        dialogo.boton_publicar.click()
    assert {c[1] for c in proveedor.llamadas} == {T}
    # Y no la quita de las elegidas: es del vídeo largo.
    assert ajustes.plataformas_redes == [T, linkedin_]


def test_shorts_abre_con_el_perfil_del_video_largo(qtbot, carpeta, ajustes):
    ajustes.anadir_perfil(PROVEEDOR_POR_DEFECTO, "six")
    dialogo = DialogoPublicarShorts(
        shorts.listar(carpeta), ajustes, fabrica=lambda n, c, d: ProveedorFalso(),
        medir=lambda mp4: DURACIONES[Path(mp4).name], ahora=lambda: AHORA, zona=MADRID,
        perfil="six")
    qtbot.addWidget(dialogo)
    assert ajustes.perfil_redes == "six"
    assert dialogo.selector_perfil.currentText() == "six"


def test_el_dialogo_de_shorts_cabe_en_la_pantalla_y_publicar_se_ve(qtbot, carpeta, ajustes,
                                                                    monkeypatch):
    """La lista de shorts va dentro de la zona con scroll: el diálogo no pasa
    del alto útil y los botones quedan fijos abajo."""
    from PySide6.QtCore import QPoint, QRect

    class PantallaBaja:
        def availableGeometry(self):
            return QRect(0, 0, 1440, 400)

    monkeypatch.setattr(DialogoPublicarShorts, "screen", lambda self: PantallaBaja())
    dialogo, _ = _dialogo(qtbot, carpeta, ajustes)
    assert dialogo.contenido.sizeHint().height() > 400
    dialogo.show()
    qtbot.waitExposed(dialogo)
    assert dialogo.height() <= 400
    abajo = dialogo.boton_publicar.mapTo(dialogo, QPoint(0, dialogo.boton_publicar.height()))
    assert abajo.y() <= dialogo.height()
