"""Cabecera de la ventana principal: logo, nombre de la app y lema."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from videopipeline.i18n import _

# Misma imagen que el icono de la ventana: la marca de la oveja con fondo
# transparente. docs/img/logo.png no sirve aquí: es RGB con fondo blanco y el
# nombre en tinta oscura, que desaparece en modo oscuro.
RUTA_LOGO = Path(__file__).resolve().parent.parent / "recursos" / "icon_512.png"
NOMBRE_APP = "The Silence of the Shorts"
LADO_LOGO = 44  # px lógicos
# Tamaños relativos a la fuente del sistema (13 pt en macOS).
ESCALA_TITULO = 1.45
ESCALA_LEMA = 0.92
# Opacidad del separador inferior sobre el color de texto de la paleta.
ALFA_SEPARADOR = 40


def pixmap_logo(imagen: QImage, lado: int, dpr: float) -> QPixmap:
    """Escala la imagen a `lado` px lógicos con la densidad de la pantalla
    (Retina = 2) para que se vea nítida."""
    fisico = max(1, round(lado * dpr))
    escalada = imagen.scaled(
        fisico, fisico,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixmap = QPixmap.fromImage(escalada)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


class Cabecera(QWidget):
    def __init__(self, ruta_logo: Path = RUTA_LOGO, parent=None):
        super().__init__(parent)
        # Un PNG ausente o corrupto da una QImage nula: la cabecera sigue sin logo.
        self._imagen = QImage(str(ruta_logo))
        self._dpr_logo = 0.0

        self.logo = QLabel()
        self.logo.setFixedSize(LADO_LOGO, LADO_LOGO)
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo.setAccessibleName(_("Logo de {app}").format(app=NOMBRE_APP))
        self.logo.setVisible(not self._imagen.isNull())

        self.titulo = QLabel(NOMBRE_APP)
        fuente_titulo = QFont(self.font())
        fuente_titulo.setPointSizeF(self.font().pointSizeF() * ESCALA_TITULO)
        fuente_titulo.setWeight(QFont.Weight.Bold)
        self.titulo.setFont(fuente_titulo)

        self.lema = QLabel(_("Edita en silencio. Crea a lo grande."))
        fuente_lema = QFont(self.font())
        fuente_lema.setPointSizeF(self.font().pointSizeF() * ESCALA_LEMA)
        self.lema.setFont(fuente_lema)
        # Gris secundario del sistema, adaptado a claro/oscuro.
        self.lema.setForegroundRole(QPalette.ColorRole.PlaceholderText)

        textos = QVBoxLayout()
        textos.setContentsMargins(0, 0, 0, 0)
        textos.setSpacing(0)
        textos.addStretch(1)
        textos.addWidget(self.titulo)
        textos.addWidget(self.lema)
        textos.addStretch(1)

        fila = QHBoxLayout(self)
        fila.setContentsMargins(2, 0, 2, 10)
        fila.setSpacing(12)
        fila.addWidget(self.logo)
        fila.addLayout(textos, 1)

        self._actualizar_logo()

    def _actualizar_logo(self) -> None:
        if self._imagen.isNull():
            return
        dpr = self.devicePixelRatioF()
        if dpr == self._dpr_logo:
            return
        self._dpr_logo = dpr
        self.logo.setPixmap(pixmap_logo(self._imagen, LADO_LOGO, dpr))

    def event(self, evento) -> bool:
        # Al mover la ventana entre una pantalla Retina y una normal.
        if evento.type() in (QEvent.Type.DevicePixelRatioChange, QEvent.Type.Show):
            self._actualizar_logo()
        return super().event(evento)

    def paintEvent(self, evento) -> None:
        # Separador fino abajo, derivado del color de texto: vale en claro y oscuro.
        color = QColor(self.palette().color(QPalette.ColorRole.WindowText))
        color.setAlpha(ALFA_SEPARADOR)
        pintor = QPainter(self)
        pintor.fillRect(0, self.height() - 1, self.width(), 1, color)
        pintor.end()
