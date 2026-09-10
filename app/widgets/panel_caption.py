from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
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


class PanelCaption(QWidget):
    """Muestra el caption SEO del trabajo seleccionado y lo copia por bloques."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._caption: Caption | None = None
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        grupo = QGroupBox("Caption SEO")
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
        self.boton_copiar_titulo = QPushButton("Copiar título")
        self.boton_copiar_caption = QPushButton("Copiar caption")
        self.boton_copiar_hashtags = QPushButton("Copiar hashtags")
        self.boton_copiar_todo = QPushButton("Copiar todo")
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
        raiz.addWidget(grupo)
        self.hide()

    def mostrar(self, caption: Caption | None) -> None:
        self._caption = caption
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
