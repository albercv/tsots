from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from videopipeline.edicion import broll
from videopipeline.i18n import _

from .. import credenciales
from ..cuentas import COLOR_AVISO, COLOR_OK

PROVEEDOR = "pixabay"


class DialogoPixabay(QDialog):
    """Clave gratuita de Pixabay para el B-roll de «Editar con Claude».

    La clave va directa al Llavero y nunca se muestra ni se lee de vuelta:
    solo se comprueba si existe. La prueba es una búsqueda con timeout, en
    primer plano con cursor de espera (shortcut: bloquea la interfaz unos
    segundos como mucho; pasar a segundo plano si molesta).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Clave de Pixabay"))
        self.setMinimumWidth(460)
        raiz = QVBoxLayout(self)
        ayuda = QLabel(_(
            "La clave de Pixabay es gratis: inicia sesión y cópiala en "
            '<a href="https://pixabay.com/api/docs/">https://pixabay.com/api/docs/</a>. '
            "Se guarda en el Llavero de macOS y sirve para el B-roll "
            "(vídeos de apoyo) de «Editar con Claude»."))
        ayuda.setWordWrap(True)
        ayuda.setTextFormat(Qt.TextFormat.RichText)
        ayuda.setOpenExternalLinks(True)
        raiz.addWidget(ayuda)

        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo_clave.setPlaceholderText(_("Pega aquí la clave de Pixabay"))
        raiz.addWidget(self.campo_clave)
        self.estado = QLabel()
        raiz.addWidget(self.estado)

        self.boton_guardar = QPushButton(_("Comprobar y guardar"))
        self.boton_guardar.clicked.connect(self._comprobar_y_guardar)
        self.boton_borrar = QPushButton(_("Borrar"))
        self.boton_borrar.clicked.connect(self._borrar)
        boton_cerrar = QPushButton(_("Cerrar"))
        boton_cerrar.clicked.connect(self.accept)
        fila = QHBoxLayout()
        fila.addWidget(self.boton_guardar)
        fila.addWidget(self.boton_borrar)
        fila.addStretch(1)
        fila.addWidget(boton_cerrar)
        raiz.addLayout(fila)
        self._refrescar()

    def _refrescar(self) -> None:
        guardada = credenciales.hay_clave(PROVEEDOR)
        self.estado.setText(_("Guardada") if guardada else _("Sin clave"))
        self.estado.setStyleSheet(f"color: {COLOR_OK if guardada else COLOR_AVISO};")
        self.boton_borrar.setEnabled(guardada)

    def _comprobar_y_guardar(self) -> None:
        clave = self.campo_clave.text().strip()
        if not clave:
            return
        try:
            if not credenciales.clave_valida(clave):
                credenciales.guardar(PROVEEDOR, clave)  # lanza con el motivo
            QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                buena = broll.probar_clave(clave)
            finally:
                QGuiApplication.restoreOverrideCursor()
            if not buena:
                QMessageBox.warning(self, _("Pixabay"), _(
                    "Pixabay no aceptó esa clave (o no hay conexión). "
                    "No se ha guardado nada."))
                return
            credenciales.guardar(PROVEEDOR, clave)
        except credenciales.ErrorLlavero as e:
            QMessageBox.warning(self, _("Llavero"), str(e))
            return
        self.campo_clave.clear()
        self._refrescar()

    def _borrar(self) -> None:
        try:
            credenciales.borrar(PROVEEDOR)
        except credenciales.ErrorLlavero as e:
            QMessageBox.warning(self, _("Llavero"), str(e))
        self._refrescar()
