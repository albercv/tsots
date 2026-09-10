from __future__ import annotations

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
        self.texto_caption = QTextEdit()
        self.texto_caption.setReadOnly(True)
        self.texto_caption.setFixedHeight(110)
        self.etiqueta_hashtags = QLabel()
        self.etiqueta_hashtags.setWordWrap(True)
        self.etiqueta_hashtags.setStyleSheet("color: #1e88e5;")
        layout.addWidget(self.etiqueta_titulo)
        layout.addWidget(self.texto_caption)
        layout.addWidget(self.etiqueta_hashtags)
        botones = QHBoxLayout()
        self.boton_copiar_titulo = QPushButton("Copiar título")
        self.boton_copiar_caption = QPushButton("Copiar caption")
        self.boton_copiar_hashtags = QPushButton("Copiar hashtags")
        self.boton_copiar_todo = QPushButton("Copiar todo")
        self.boton_copiar_titulo.clicked.connect(
            lambda: self._copiar(self._caption.titulo))
        self.boton_copiar_caption.clicked.connect(
            lambda: self._copiar(self._caption.caption))
        self.boton_copiar_hashtags.clicked.connect(
            lambda: self._copiar(self._caption.hashtags_texto))
        self.boton_copiar_todo.clicked.connect(
            lambda: self._copiar(self._caption.texto_completo()))
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

    def _copiar(self, texto: str) -> None:
        if self._caption is not None:
            QApplication.clipboard().setText(texto)
