from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from videopipeline.i18n import _
from videopipeline.redes import proveedor as proveedores
from videopipeline.redes.modelo import (
    CATEGORIAS_YOUTUBE,
    ETIQUETAS_INSTAGRAM,
    ETIQUETAS_TIKTOK,
    ModoInstagram,
    ModoTikTok,
)

from .. import credenciales
from ..settings import Ajustes

COLOR_OK = "#43a047"
COLOR_AVISO = "#b8860b"


class DialogoRedes(QDialog):
    """Servicio de publicación, perfil, API key (al Llavero) y modos por defecto.

    La clave se escribe aquí y va directa al Llavero: el diálogo nunca la
    muestra ni la lee de vuelta; solo comprueba si existe.
    """

    def __init__(self, ajustes: Ajustes, llavero=credenciales, parent=None):
        super().__init__(parent)
        self.ajustes = ajustes
        self.llavero = llavero
        self.setWindowTitle(_("Redes sociales"))
        self.setMinimumWidth(520)
        raiz = QVBoxLayout(self)

        ayuda = QLabel(_(
            "TSOTS publica a través de un servicio que ya tiene permiso de "
            "TikTok, YouTube e Instagram. Crea una cuenta en el servicio, "
            "conecta allí tus redes y pega aquí su API key: se guarda en el "
            "Llavero de macOS, nunca en la app."))
        ayuda.setWordWrap(True)
        raiz.addWidget(ayuda)

        grupo_cuenta = QGroupBox(_("Cuenta"))
        formulario = QFormLayout(grupo_cuenta)
        formulario.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.combo_proveedor = QComboBox()
        for nombre in proveedores.PROVEEDORES:
            self.combo_proveedor.addItem(proveedores.nombre_visible(nombre), nombre)
        self.combo_proveedor.setCurrentIndex(
            max(0, self.combo_proveedor.findData(ajustes.proveedor_redes)))
        formulario.addRow(_("Servicio:"), self.combo_proveedor)

        self.campo_perfil = QLineEdit()
        self.campo_perfil.setPlaceholderText(_("Nombre del perfil en el servicio"))
        self.campo_perfil.setToolTip(_(
            "El perfil del servicio donde conectaste TikTok, YouTube e Instagram."))
        formulario.addRow(_("Perfil:"), self.campo_perfil)

        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo_clave.setPlaceholderText(_("Pega la API key para guardarla"))
        formulario.addRow(_("API key:"), self.campo_clave)

        fila_estado = QHBoxLayout()
        self.etiqueta_clave = QLabel()
        self.boton_olvidar = QPushButton(_("Olvidar clave"))
        self.boton_olvidar.clicked.connect(self._olvidar_clave)
        fila_estado.addWidget(self.etiqueta_clave, 1)
        fila_estado.addWidget(self.boton_olvidar)
        formulario.addRow("", fila_estado)
        raiz.addWidget(grupo_cuenta)

        grupo_defecto = QGroupBox(_("Al publicar, por defecto"))
        formulario_defecto = QFormLayout(grupo_defecto)
        formulario_defecto.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.combo_tiktok = QComboBox()
        for modo in ModoTikTok:
            self.combo_tiktok.addItem(_(ETIQUETAS_TIKTOK[modo]), modo.value)
        self.combo_tiktok.setCurrentIndex(
            self.combo_tiktok.findData(ajustes.tiktok_modo.value))
        formulario_defecto.addRow("TikTok:", self.combo_tiktok)
        self.combo_instagram = QComboBox()
        for modo in ModoInstagram:
            self.combo_instagram.addItem(_(ETIQUETAS_INSTAGRAM[modo]), modo.value)
        self.combo_instagram.setCurrentIndex(
            self.combo_instagram.findData(ajustes.instagram_modo.value))
        formulario_defecto.addRow("Instagram:", self.combo_instagram)
        self.combo_categoria = QComboBox()
        for codigo, nombre in CATEGORIAS_YOUTUBE.items():
            self.combo_categoria.addItem(_(nombre), codigo)
        indice = self.combo_categoria.findData(ajustes.youtube_categoria)
        if indice < 0:  # categoría guardada que no está en la lista
            self.combo_categoria.addItem(ajustes.youtube_categoria, ajustes.youtube_categoria)
            indice = self.combo_categoria.count() - 1
        self.combo_categoria.setCurrentIndex(indice)
        formulario_defecto.addRow(_("Categoría de YouTube:"), self.combo_categoria)
        raiz.addWidget(grupo_defecto)

        botones = QDialogButtonBox()
        self.boton_guardar = botones.addButton(_("Guardar"),
                                               QDialogButtonBox.ButtonRole.AcceptRole)
        self.boton_guardar.setDefault(True)
        botones.addButton(_("Cancelar"), QDialogButtonBox.ButtonRole.RejectRole)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        raiz.addWidget(botones)

        self.combo_proveedor.currentIndexChanged.connect(self._al_cambiar_proveedor)
        self._al_cambiar_proveedor()

    @property
    def proveedor(self) -> str:
        return str(self.combo_proveedor.currentData())

    def _al_cambiar_proveedor(self, *args) -> None:
        usa_perfil = proveedores.usa_perfil(self.proveedor)
        self.campo_perfil.setEnabled(usa_perfil)
        self.campo_perfil.setText(self.ajustes.perfil_de(self.proveedor))
        self.campo_clave.clear()
        self._refrescar_clave()

    def _refrescar_clave(self) -> None:
        guardada = self.llavero.hay_clave(self.proveedor)
        if guardada:
            self.etiqueta_clave.setText(_("✓ Guardada en el Llavero"))
            self.etiqueta_clave.setStyleSheet(f"color: {COLOR_OK};")
        else:
            self.etiqueta_clave.setText(_("Sin clave guardada"))
            self.etiqueta_clave.setStyleSheet(f"color: {COLOR_AVISO};")
        self.boton_olvidar.setEnabled(guardada)

    def _olvidar_clave(self) -> None:
        try:
            self.llavero.borrar(self.proveedor)
        except credenciales.ErrorLlavero as e:
            QMessageBox.warning(self, _("Llavero"), str(e))
        self._refrescar_clave()

    def accept(self) -> None:
        clave = self.campo_clave.text().strip()
        if clave:
            try:
                self.llavero.guardar(self.proveedor, clave)
            except credenciales.ErrorLlavero as e:
                QMessageBox.warning(self, _("Llavero"), str(e))
                return
            finally:
                self.campo_clave.clear()
        self.ajustes.proveedor_redes = self.proveedor
        self.ajustes.guardar_perfil(self.proveedor, self.campo_perfil.text())
        self.ajustes.tiktok_modo = ModoTikTok(self.combo_tiktok.currentData())
        self.ajustes.instagram_modo = ModoInstagram(self.combo_instagram.currentData())
        self.ajustes.youtube_categoria = str(self.combo_categoria.currentData())
        super().accept()
