from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QLabel

from videopipeline.i18n import _

EXTENSIONES = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


class ZonaDrop(QLabel):
    archivos_soltados = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText(_("Arrastra vídeos aquí\n(o haz clic para abrir)"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self.setStyleSheet(
            "QLabel { border: 2px dashed #888; border-radius: 8px; "
            "padding: 16px; color: #666; }"
        )

    def _procesar_mime(self, mime: QMimeData) -> None:
        rutas = [
            Path(url.toLocalFile())
            for url in mime.urls()
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in EXTENSIONES
        ]
        if rutas:
            self.archivos_soltados.emit(rutas)

    def dragEnterEvent(self, evento) -> None:
        if evento.mimeData().hasUrls():
            evento.acceptProposedAction()

    def dropEvent(self, evento) -> None:
        self._procesar_mime(evento.mimeData())
        evento.acceptProposedAction()

    def mousePressEvent(self, evento) -> None:
        patron = _("Vídeos (") + " ".join(
            f"*{e}" for e in sorted(EXTENSIONES)
        ) + ")"
        rutas, _filtro = QFileDialog.getOpenFileNames(
            self, _("Elegir vídeos"), "", patron
        )
        if rutas:
            self.archivos_soltados.emit([Path(r) for r in rutas])
