"""Icono «i» que muestra una tarjeta de ayuda al pasar el ratón, pulsarlo o
enfocarlo con el teclado (Espacio/Intro). Los colores salen de la paleta: vale
en claro y oscuro."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

LADO_ICONO = 16
ANCHO_TARJETA = 300  # px lógicos, texto incluido
SOMBRA = 12          # margen transparente donde se pinta la sombra
RADIO = 10


class _Tarjeta(QWidget):
    """Ventana flotante sin marco, con fondo redondeado y sombra pintados."""

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.titulo = QLabel()
        fuente = QFont(self.font())
        fuente.setWeight(QFont.Weight.Bold)
        self.titulo.setFont(fuente)
        self.titulo.setWordWrap(True)
        self.parrafos = QVBoxLayout()  # una etiqueta por línea del cuerpo
        self.parrafos.setSpacing(5)
        lista = QVBoxLayout(self)
        lista.setContentsMargins(SOMBRA + 14, SOMBRA + 12, SOMBRA + 14, SOMBRA + 12)
        lista.setSpacing(6)
        lista.addWidget(self.titulo)
        lista.addLayout(self.parrafos)
        self.setFixedWidth(ANCHO_TARJETA + 2 * SOMBRA)

    def poner(self, titulo: str, cuerpo: str) -> None:
        self.titulo.setText(titulo)
        while self.parrafos.count():
            self.parrafos.takeAt(0).widget().deleteLater()
        for linea in cuerpo.split("\n"):
            etiqueta = QLabel(linea.replace(" %", "\u00a0%"))  # que % no quede solo
            etiqueta.setWordWrap(True)
            self.parrafos.addWidget(etiqueta)
        self.setFixedHeight(self.layout().heightForWidth(self.width()))

    def paintEvent(self, evento) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        caja = QRectF(self.rect()).adjusted(SOMBRA, SOMBRA, -SOMBRA, -SOMBRA)
        for i in range(SOMBRA, 0, -1):  # sombra: capas cada vez más tenues
            p.setBrush(QColor(0, 0, 0, 3))
            p.drawRoundedRect(caja.adjusted(-i, -i + 3, i, i + 3), RADIO + i, RADIO + i)
        paleta = self.palette()
        p.setBrush(paleta.color(QPalette.ColorRole.Base))
        borde = QColor(paleta.color(QPalette.ColorRole.WindowText))
        borde.setAlpha(50)
        p.setPen(borde)
        p.drawRoundedRect(caja.adjusted(.5, .5, -.5, -.5), RADIO, RADIO)
        p.end()


class IconoInfo(QWidget):
    def __init__(self, titulo: str, cuerpo: str, parent=None):
        super().__init__(parent)
        self.titulo, self.cuerpo = titulo, cuerpo
        self._tarjeta: _Tarjeta | None = None
        self._encima = False
        self.setFixedSize(LADO_ICONO, LADO_ICONO)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setAccessibleName(titulo)
        self.setAccessibleDescription(cuerpo)

    def tarjeta_visible(self) -> bool:
        return self._tarjeta is not None and self._tarjeta.isVisible()

    def mostrar(self) -> None:
        if self._tarjeta is None:
            self._tarjeta = _Tarjeta()
        t = self._tarjeta
        t.poner(self.titulo, self.cuerpo)
        pantalla = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        origen = self.mapToGlobal(self.rect().bottomLeft())
        x = origen.x() - SOMBRA - LADO_ICONO // 2
        y = origen.y() - SOMBRA + 4
        if y + t.height() > pantalla.bottom():  # sin sitio abajo: encima del icono
            y = self.mapToGlobal(self.rect().topLeft()).y() - t.height() + SOMBRA - 4
        x = max(pantalla.left(), min(x, pantalla.right() - t.width()))
        t.move(x, max(pantalla.top(), y))
        t.show()
        QApplication.instance().installEventFilter(self)

    def ocultar(self) -> None:
        QApplication.instance().removeEventFilter(self)
        if self._tarjeta is not None:
            self._tarjeta.hide()

    def eventFilter(self, objeto: QObject, evento: QEvent) -> bool:
        # Clic fuera del icono: cierra (p. ej. tarjeta abierta con el teclado).
        if evento.type() == QEvent.Type.MouseButtonPress and objeto is not self:
            self.ocultar()
        return False

    def enterEvent(self, evento) -> None:
        self._encima = True
        self.update()
        self.mostrar()

    def leaveEvent(self, evento) -> None:
        self._encima = False
        self.update()
        self.ocultar()

    def mousePressEvent(self, evento) -> None:
        self.mostrar()

    def focusInEvent(self, evento) -> None:
        super().focusInEvent(evento)
        self.update()

    def focusOutEvent(self, evento) -> None:
        super().focusOutEvent(evento)
        self.update()
        self.ocultar()

    def hideEvent(self, evento) -> None:
        self.ocultar()

    def keyPressEvent(self, evento) -> None:
        if evento.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.mostrar()
        elif evento.key() == Qt.Key.Key_Escape:
            self.ocultar()
        else:
            super().keyPressEvent(evento)

    def paintEvent(self, evento) -> None:
        paleta = self.palette()
        activo = self._encima or self.hasFocus() or self.tarjeta_visible()
        color = paleta.color(
            QPalette.ColorRole.Highlight if activo else QPalette.ColorRole.PlaceholderText
        )
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(color)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        fuente = QFont(self.font())
        fuente.setPixelSize(LADO_ICONO - 6)
        fuente.setWeight(QFont.Weight.Bold)
        p.setFont(fuente)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "i")
        p.end()


def etiqueta_con_info(texto: str, icono: IconoInfo) -> QWidget:
    """Texto de fila de formulario con el icono pegado a su derecha."""
    caja = QWidget()
    fila = QHBoxLayout(caja)
    fila.setContentsMargins(0, 0, 0, 0)
    fila.setSpacing(5)
    fila.addStretch(1)
    fila.addWidget(QLabel(texto))
    fila.addWidget(icono, 0, Qt.AlignmentFlag.AlignVCenter)
    caja.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    # La lógica de habilitados de PanelOpciones deja esto siempre activo.
    caja.setProperty("ayuda", True)
    icono.setProperty("ayuda", True)
    return caja
