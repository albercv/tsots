"""Secciones plegables para la columna de opciones y el acordeón que las une."""
from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget

# Opacidad del separador entre secciones sobre el color de texto de la paleta
# (la misma que el separador de la cabecera).
ALFA_SEPARADOR = 40


class SeccionPlegable(QWidget):
    """Cabecera pulsable (flecha de despliegue + título) y un `contenido`
    donde el llamante monta su layout, como haría con un QGroupBox."""

    pulsada = Signal()

    def __init__(self, titulo: str, parent=None):
        super().__init__(parent)
        self.cabecera = QToolButton()
        self.cabecera.setText(titulo)
        self.cabecera.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.cabecera.setAutoRaise(True)
        self.cabecera.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.cabecera.setCursor(Qt.CursorShape.PointingHandCursor)
        fuente = QFont(self.cabecera.font())
        fuente.setWeight(QFont.Weight.DemiBold)
        self.cabecera.setFont(fuente)
        self.cabecera.clicked.connect(self.pulsada)

        self.contenido = QWidget()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 3)
        layout.setSpacing(0)
        layout.addWidget(self.cabecera)
        layout.addWidget(self.contenido)
        self.expandir(False)

    def esta_abierta(self) -> bool:
        return not self.contenido.isHidden()

    def expandir(self, abierta: bool) -> None:
        self.contenido.setVisible(abierta)
        self.cabecera.setArrowType(
            Qt.ArrowType.DownArrow if abierta else Qt.ArrowType.RightArrow
        )

    # El ancho cuenta el contenido aunque esté plegado: la columna no salta
    # al abrir otra sección ni recorta la que se abre.
    def _con_ancho_del_contenido(self, propio: QSize, del_contenido: QSize) -> QSize:
        return QSize(max(propio.width(), del_contenido.width()), propio.height())

    def minimumSizeHint(self) -> QSize:
        return self._con_ancho_del_contenido(
            super().minimumSizeHint(), self.contenido.minimumSizeHint()
        )

    def sizeHint(self) -> QSize:
        return self._con_ancho_del_contenido(
            super().sizeHint(), self.contenido.sizeHint()
        )

    def paintEvent(self, evento) -> None:
        # Separador fino abajo, derivado del color de texto: vale en claro y
        # oscuro sin colores fijos.
        color = QColor(self.palette().color(QPalette.ColorRole.WindowText))
        color.setAlpha(ALFA_SEPARADOR)
        pintor = QPainter(self)
        pintor.fillRect(0, self.height() - 1, self.width(), 1, color)
        pintor.end()


class Acordeon(QObject):
    """Mantiene exactamente una sección abierta: abrir una cierra la otra y
    pulsar la abierta la deja como está."""

    cambiada = Signal(object)  # SeccionPlegable abierta

    def __init__(self, parent=None):
        super().__init__(parent)
        self._secciones: list[SeccionPlegable] = []

    def anadir(self, seccion: SeccionPlegable) -> None:
        self._secciones.append(seccion)
        seccion.pulsada.connect(lambda s=seccion: self.abrir(s))
        if len(self._secciones) == 1:
            seccion.expandir(True)

    def abierta(self) -> SeccionPlegable | None:
        return next((s for s in self._secciones if s.esta_abierta()), None)

    def abrir(self, seccion: SeccionPlegable) -> None:
        if seccion.esta_abierta():
            return
        for otra in self._secciones:
            if otra is not seccion:
                otra.expandir(False)
        seccion.expandir(True)
        self.cambiada.emit(seccion)
