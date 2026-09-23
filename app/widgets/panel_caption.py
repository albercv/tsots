from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from videopipeline.caption import Caption
from videopipeline.i18n import _


class PanelCaption(QWidget):
    """Muestra el caption SEO del trabajo seleccionado, lo copia por bloques y
    da paso a publicarlo en redes."""

    publicar = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._caption: Caption | None = None
        self._video: Path | None = None
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        grupo = QGroupBox(_("Caption SEO"))
        layout = QVBoxLayout(grupo)
        self.etiqueta_titulo = QLabel()
        self.etiqueta_titulo.setStyleSheet("font-weight: bold;")
        self.etiqueta_titulo.setWordWrap(True)
        self.etiqueta_titulo.setTextFormat(Qt.TextFormat.PlainText)
        self.texto_caption = QTextEdit()
        self.texto_caption.setReadOnly(True)
        self.texto_caption.setFixedHeight(110)
        self.etiqueta_hashtags = QLabel()
        self.etiqueta_hashtags.setWordWrap(True)
        self.etiqueta_hashtags.setStyleSheet("color: #1e88e5;")
        self.etiqueta_hashtags.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.etiqueta_titulo)
        layout.addWidget(self.texto_caption)
        layout.addWidget(self.etiqueta_hashtags)
        botones = QHBoxLayout()
        self.boton_copiar_titulo = QPushButton(_("Copiar título"))
        self.boton_copiar_caption = QPushButton(_("Copiar caption"))
        self.boton_copiar_hashtags = QPushButton(_("Copiar hashtags"))
        self.boton_copiar_todo = QPushButton(_("Copiar todo"))
        self.boton_copiar_titulo.clicked.connect(
            lambda: self._copiar(lambda c: c.titulo))
        self.boton_copiar_caption.clicked.connect(
            lambda: self._copiar(lambda c: c.caption))
        self.boton_copiar_hashtags.clicked.connect(
            lambda: self._copiar(lambda c: c.hashtags_texto))
        self.boton_copiar_todo.clicked.connect(
            lambda: self._copiar(lambda c: c.texto_completo()))
        for boton in (self.boton_copiar_titulo, self.boton_copiar_caption,
                      self.boton_copiar_hashtags, self.boton_copiar_todo):
            botones.addWidget(boton)
        layout.addLayout(botones)
        fila_redes = QHBoxLayout()
        fila_redes.addStretch(1)
        self.boton_publicar = QPushButton(_("Publicar…"))
        self.boton_publicar.setToolTip(_("Publicar en TikTok, YouTube e Instagram"))
        self.boton_publicar.clicked.connect(self.publicar)
        fila_redes.addWidget(self.boton_publicar)
        layout.addLayout(fila_redes)
        raiz.addWidget(grupo)
        self.hide()

    @property
    def caption(self) -> Caption | None:
        return self._caption

    @property
    def video(self) -> Path | None:
        return self._video

    def mostrar(self, caption: Caption | None, video: Path | None = None) -> None:
        self._caption = caption
        self._video = Path(video) if video else None
        self.boton_publicar.setEnabled(caption is not None and self._video is not None)
        if caption is None:
            self.hide()
            return
        self.etiqueta_titulo.setText(caption.titulo)
        self.texto_caption.setPlainText(caption.caption)
        self.etiqueta_hashtags.setText(caption.hashtags_texto)
        self.show()

    def _copiar(self, extraer: Callable[[Caption], str]) -> None:
        if self._caption is None:
            return
        QApplication.clipboard().setText(extraer(self._caption))
