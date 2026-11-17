"""Pinta cada fila de la cola como siempre y, si sus shorts se están editando
con Claude (o se acaban de editar), una segunda línea con una barra de avance
y el estado: cuántos van, en qué fase está el actual y cuánto falta."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QStyleOptionViewItem,
)

from ..queue_model import ROL_EDICION
from videopipeline.edicion.estado import EstadoEdicion, minutos
from videopipeline.i18n import N_, _

_FASES = {
    "preparando": N_("preparando"),
    "decide": N_("Claude decide"),
    "validando": N_("validando"),
    "montando": N_("montando el vídeo"),
    "revisando": N_("revisando"),
}


def texto_edicion(e: EstadoEdicion) -> str:
    """La línea de estado que va junto a la barra."""
    if e.restante_s is None:  # tanda terminada
        texto = _("Claude: {n} editados").format(n=e.hechos)
        if e.errores:
            texto += " · " + _("{n} con error").format(n=e.errores)
        return texto
    if not e.agente_activo:
        return _("Claude: {n} en cola · empieza al terminar la cola o al abrir la "
                 "app").format(n=e.en_cola)
    faltan = _("faltan ~{min} min").format(min=minutos(e.restante_s))
    if e.actual is None:  # entre dos shorts
        return _("Claude: {hechos} de {total} hechos · {faltan}").format(
            hechos=e.hechos + e.errores, total=e.total, faltan=faltan)
    return _("Claude {i} de {total} · {short}: {fase} · {faltan}").format(
        i=e.hechos + e.errores + 1, total=e.total, short=e.actual,
        fase=_(_FASES.get(e.fase or "", "")), faltan=faltan)


class DelegadoCola(QStyledItemDelegate):
    ALTO_BARRA = 22  # alto de la segunda línea
    ANCHO_BARRA = 110

    def sizeHint(self, opcion: QStyleOptionViewItem, indice) -> QSize:
        tamano = super().sizeHint(opcion, indice)
        if indice.data(ROL_EDICION) is not None:
            tamano.setHeight(tamano.height() + self.ALTO_BARRA)
        return tamano

    def paint(self, pintor, opcion: QStyleOptionViewItem, indice) -> None:
        estado = indice.data(ROL_EDICION)
        if estado is None:
            super().paint(pintor, opcion, indice)
            return
        estilo = opcion.widget.style() if opcion.widget else QApplication.style()
        # Fondo (selección, hover) de toda la fila, y la línea de siempre arriba.
        fondo = QStyleOptionViewItem(opcion)
        self.initStyleOption(fondo, indice)
        fondo.text = ""
        estilo.drawControl(QStyle.ControlElement.CE_ItemViewItem, fondo, pintor, opcion.widget)
        arriba = QStyleOptionViewItem(opcion)
        arriba.rect = opcion.rect.adjusted(0, 0, 0, -self.ALTO_BARRA)
        super().paint(pintor, arriba, indice)
        abajo = QRect(opcion.rect.left() + 8, opcion.rect.bottom() - self.ALTO_BARRA + 4,
                      opcion.rect.width() - 16, self.ALTO_BARRA - 8)
        barra = QStyleOptionProgressBar()
        barra.rect = QRect(abajo.left(), abajo.top(), self.ANCHO_BARRA, abajo.height())
        barra.minimum, barra.maximum = 0, 100
        barra.progress = round(estado.porcentaje)
        barra.textVisible = False
        barra.state = QStyle.StateFlag.State_Enabled
        estilo.drawControl(QStyle.ControlElement.CE_ProgressBar, barra, pintor)
        texto_rect = abajo.adjusted(self.ANCHO_BARRA + 8, -2, 0, 2)
        texto = opcion.fontMetrics.elidedText(
            texto_edicion(estado), Qt.TextElideMode.ElideMiddle, texto_rect.width())
        pintor.save()
        if opcion.state & QStyle.StateFlag.State_Selected:
            pintor.setPen(opcion.palette.highlightedText().color())
        else:
            pintor.setPen(opcion.palette.text().color())
        pintor.drawText(texto_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                        texto)
        pintor.restore()
