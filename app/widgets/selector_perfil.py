"""Combo con los perfiles de publicación del proveedor activo."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox

from app.settings import Ajustes
from videopipeline.i18n import _


class SelectorPerfil(QComboBox):
    # Solo cuando el usuario elige otro perfil: `activated` no salta al recargar.
    perfil_elegido = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._marcado: str | None = None
        # Un nombre largo se recorta en vez de ensanchar la ventana.
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(14)
        self.activated.connect(self._al_activar)

    def recargar(self, ajustes: Ajustes) -> None:
        perfiles = ajustes.perfiles_de(ajustes.proveedor_redes)
        self.clear()
        self._marcado = None
        if not perfiles:
            self.addItem(_("Sin perfil: añádelo en Redes…"), None)
            self.model().item(0).setEnabled(False)
            return
        for perfil in perfiles:
            self.addItem(perfil, perfil)
        self._marcado = ajustes.perfil_redes
        # Sin el activo en la lista no se marca ninguno: la cabecera no enseña
        # un perfil que no es el activo.
        self.setCurrentIndex(self.findData(self._marcado))

    def _al_activar(self, indice: int) -> None:
        perfil = self.itemData(indice)
        if perfil is not None and perfil != self._marcado:
            self._marcado = perfil
            self.perfil_elegido.emit(perfil)
