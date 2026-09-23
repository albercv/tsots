from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from videopipeline import glosario
from videopipeline.i18n import _


class DialogoGlosario(QDialog):
    """Lista de términos propios para la transcripción (ver glosario.py)."""

    def __init__(self, texto_inicial: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Términos"))
        self.resize(560, 380)
        layout = QVBoxLayout(self)
        ayuda = QLabel(
            _(
                "Una línea por término: marcas, productos, nombres propios. "
                "Whisper los recibe como pista y el caption respeta su "
                "ortografía. Después de «=», las formas en que Whisper se "
                "equivoca, separadas por comas: se corrigen al transcribir. "
                "Las líneas con # son comentarios."
            )
        )
        ayuda.setWordWrap(True)
        layout.addWidget(ayuda)
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(texto_inicial)
        self.editor.setPlaceholderText(
            "Claude Code = Cloud Code, Claus Code\n"
            "Anthropic\n"
            "Evolve2Digital = evolve to digital"
        )
        layout.addWidget(self.editor, 1)
        self.resumen = QLabel("")
        layout.addWidget(self.resumen)
        self.aviso = QLabel("")
        self.aviso.setStyleSheet("color: #b8860b;")
        self.aviso.setWordWrap(True)
        layout.addWidget(self.aviso)
        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)
        self.editor.textChanged.connect(self._actualizar_resumen)
        self._actualizar_resumen()

    def texto(self) -> str:
        return self.editor.toPlainText().strip()

    def _actualizar_resumen(self) -> None:
        g = glosario.parsear(self.editor.toPlainText())
        self.resumen.setText(
            _("Términos: {terminos} · Correcciones: {correcciones}").format(
                terminos=g.n_terminos, correcciones=g.n_correcciones)
        )
        fuera = glosario.recortados(g)
        self.aviso.setText(
            _("Los últimos {n} términos no caben en la pista para Whisper. "
              "Se siguen usando en las correcciones y en el caption.").format(n=fuera)
            if fuera else ""
        )
