from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)


class DialogoMarca(QDialog):
    """Texto libre que se añade al prompt del caption SEO."""

    def __init__(self, texto_inicial: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contexto de marca")
        self.resize(520, 320)
        layout = QVBoxLayout(self)
        ayuda = QLabel(
            "Quién eres, a quién hablas, tono, llamada a la acción habitual, "
            "hashtags que quieres siempre. Se envía al modelo con cada vídeo."
        )
        ayuda.setWordWrap(True)
        layout.addWidget(ayuda)
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(texto_inicial)
        self.editor.setPlaceholderText(
            "Ej.: Soy Alberto, consultor de IA para pymes (Evolve2Digital). "
            "Tono directo y cercano. CTA: sígueme para más. Hashtags fijos: "
            "#evolve2digital #iaparapymes"
        )
        layout.addWidget(self.editor, 1)
        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

    def texto(self) -> str:
        return self.editor.toPlainText().strip()
