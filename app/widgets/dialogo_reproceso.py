from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from videopipeline.i18n import _
from videopipeline.reproceso_plan import Consulta, Decisiones

COLOR_AVISO = "color: #b8860b;"


class DialogoReproceso(QDialog):
    """Avisa de los pasos que cada vídeo ya tiene antes de procesar.

    Por defecto se mantiene todo (R6): nada se rehace si no se marca."""

    def __init__(
        self,
        consultas: dict[str, tuple[str, list[Consulta]]],
        hay_vertical: set[str],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(_("Pasos ya hechos"))
        self.resize(620, 480)
        # Por ficha: casilla «Rehacer» de cada paso, y «Regenerar el vertical».
        self.casillas_rehacer: dict[str, dict[str, QCheckBox]] = {}
        self.casillas_vertical: dict[str, QCheckBox] = {}

        layout = QVBoxLayout(self)
        ayuda = QLabel(_(
            "Estos vídeos ya tienen pasos hechos. Se mantienen tal como "
            "están; marca «Rehacer» en los que quieras volver a hacer."))
        ayuda.setWordWrap(True)
        layout.addWidget(ayuda)

        contenido = QWidget()
        bloques = QVBoxLayout(contenido)
        for ficha_id, (nombre, lista) in consultas.items():
            bloques.addWidget(self._bloque(
                ficha_id, nombre, lista, ficha_id in hay_vertical))
        bloques.addStretch(1)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QScrollArea.Shape.NoFrame)
        desplazable.setWidget(contenido)
        layout.addWidget(desplazable, 1)

        self.check_todos = QCheckBox(_("Aplicar a todos los vídeos"))
        self.check_todos.setVisible(len(consultas) > 1)  # con uno no hay a quién
        self.check_todos.toggled.connect(self._aplicar_a_todos)
        layout.addWidget(self.check_todos)
        primero = next(iter(consultas), None)
        for casilla in self._casillas_de(primero):
            casilla.toggled.connect(self._aplicar_a_todos)

        self.botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setText(_("Procesar"))
        self.botones.accepted.connect(self.accept)
        self.botones.rejected.connect(self.reject)
        layout.addWidget(self.botones)

    def _bloque(self, ficha_id: str, nombre: str, lista: list[Consulta],
                con_vertical: bool) -> QGroupBox:
        grupo = QGroupBox(nombre)
        layout = QVBoxLayout(grupo)
        casillas = self.casillas_rehacer[ficha_id] = {}
        for consulta in lista:
            texto = QLabel(consulta.texto)
            texto.setWordWrap(True)
            layout.addWidget(texto)
            if consulta.tipo == "bloqueado":
                texto.setStyleSheet(COLOR_AVISO)
            elif consulta.tipo in ("hecho", "otros_ajustes"):
                for cambio in consulta.cambios:
                    layout.addWidget(QLabel(f"    • {cambio}"))
                casillas[consulta.paso] = QCheckBox(_("Rehacer"))
                layout.addWidget(casillas[consulta.paso])
        if con_vertical:
            self.casillas_vertical[ficha_id] = QCheckBox(
                _("Regenerar también el vertical"))
            layout.addWidget(self.casillas_vertical[ficha_id])
        return grupo

    def _casillas_de(self, ficha_id: str | None) -> list[QCheckBox]:
        casillas = list(self.casillas_rehacer.get(ficha_id, {}).values())
        if ficha_id in self.casillas_vertical:
            casillas.append(self.casillas_vertical[ficha_id])
        return casillas

    def _aplicar_a_todos(self, *args) -> None:
        """Copia las marcas del primer vídeo a los demás en los pasos que tienen
        en común; mientras está activa, los demás no se tocan a mano."""
        activa = self.check_todos.isChecked()
        primero, *demas = self.casillas_rehacer
        modelo = self.casillas_rehacer[primero]
        for ficha_id in demas:
            for paso, casilla in self.casillas_rehacer[ficha_id].items():
                casilla.setEnabled(not activa)
                if activa and paso in modelo:
                    casilla.setChecked(modelo[paso].isChecked())
            if ficha_id in self.casillas_vertical:
                casilla = self.casillas_vertical[ficha_id]
                casilla.setEnabled(not activa)
                if activa and primero in self.casillas_vertical:
                    casilla.setChecked(self.casillas_vertical[primero].isChecked())

    def decisiones(self) -> dict[str, Decisiones]:
        return {
            ficha_id: Decisiones(
                rehacer=frozenset(p for p, c in casillas.items() if c.isChecked()),
                regenerar_vertical=(ficha_id in self.casillas_vertical
                                    and self.casillas_vertical[ficha_id].isChecked()),
            )
            for ficha_id, casillas in self.casillas_rehacer.items()
        }


def preguntar_reproceso(padre, consultas, hay_vertical) -> dict[str, Decisiones] | None:
    """Las decisiones del usuario, o None si cancela."""
    dialogo = DialogoReproceso(consultas, hay_vertical, padre)
    return dialogo.decisiones() if dialogo.exec() else None
