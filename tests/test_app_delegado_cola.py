"""La segunda línea de la cola con el avance de «Editar con Claude»."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QListView, QStyleOptionViewItem

from app.queue_model import ROL_EDICION, ModeloCola
from app.widgets.delegado_cola import DelegadoCola, texto_edicion
from videopipeline.edicion.estado import EstadoEdicion


def _estado(**cambios) -> EstadoEdicion:
    base = dict(total=15, hechos=2, errores=1, en_cola=11, actual="04 - Automatización",
                fase="montando", porcentaje=24.0, restante_s=1190.0, agente_activo=True,
                con_error=("01 - A",))
    return EstadoEdicion(**{**base, **cambios})


def test_texto_en_marcha():
    assert texto_edicion(_estado()) == (
        "Claude 4 de 15 · 04 - Automatización: montando el vídeo · faltan ~20 min")


def test_texto_entre_dos_shorts():
    texto = texto_edicion(_estado(actual=None, fase=None, restante_s=600.0))
    assert texto == "Claude: 3 de 15 hechos · faltan ~10 min"


def test_texto_sin_agente_en_marcha():
    texto = texto_edicion(_estado(actual=None, fase=None, agente_activo=False))
    assert "11 en cola" in texto and "al terminar la cola" in texto


def test_texto_tanda_terminada():
    assert texto_edicion(_estado(hechos=14, errores=1, en_cola=0, actual=None, fase=None,
                                 restante_s=None, porcentaje=100.0)) == (
        "Claude: 14 editados · 1 con error")
    assert texto_edicion(_estado(hechos=15, errores=0, en_cola=0, actual=None, fase=None,
                                 restante_s=None, porcentaje=100.0,
                                 con_error=())) == "Claude: 15 editados"


def test_rol_y_tooltip_de_la_fila(qtbot):
    modelo = ModeloCola()
    modelo.anadir([(Path("/v/Episodio20.mp4"), None)])
    indice = modelo.index(0)
    assert indice.data(ROL_EDICION) is None
    modelo.actualizar(0, edicion=_estado())
    assert indice.data(ROL_EDICION) == _estado()
    assert "01 - A" in indice.data(0x03)  # ToolTipRole


def test_fila_con_edicion_es_mas_alta(qtbot):
    vista = QListView()
    qtbot.addWidget(vista)
    modelo = ModeloCola()
    vista.setModel(modelo)
    delegado = DelegadoCola(vista)
    modelo.anadir([(Path("/v/Episodio20.mp4"), None)])
    opcion = QStyleOptionViewItem()
    normal: QSize = delegado.sizeHint(opcion, modelo.index(0))
    modelo.actualizar(0, edicion=_estado())
    alta = delegado.sizeHint(opcion, modelo.index(0))
    assert alta.height() >= normal.height() + DelegadoCola.ALTO_BARRA
