"""Ubicación de las publicaciones: el selector que comparten el diálogo
Redes… (la de siempre) y el diálogo Publicar (la de un solo vídeo)."""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from videopipeline.i18n import _
from videopipeline.redes.modelo import (
    Cuenta,
    Lugar,
    Ubicacion,
    elegir_lugar,
    id_instagram_valido,
    id_x_valido,
)

from .. import segundo_plano
from ..cuentas import COLOR_AVISO, COLOR_SECUNDARIO

# Recibe el texto a buscar (en el hilo de la interfaz, donde puede leer los
# controles) y devuelve el trabajo que corre en segundo plano y nunca lanza:
# `() -> (lugares | None, motivo)`.
PrepararBusqueda = Callable[[str], Callable[[], "tuple[list[Lugar] | None, str]"]]


class SelectorUbicacion(QWidget):
    """Un lugar escrito («Madrid»), el lugar de TikTok elegido entre los
    que devuelve la búsqueda y los IDs de Instagram y X. Sin lugar de TikTok
    elegido, al publicar se usa el primero que se llame igual que el escrito."""

    def __init__(self, ubicacion: Ubicacion, preparar_busqueda: PrepararBusqueda,
                 parent=None):
        super().__init__(parent)
        self._preparar_busqueda = preparar_busqueda
        self._busqueda_n = 0
        self._aviso_permiso = ""
        formulario = QFormLayout(self)
        formulario.setContentsMargins(0, 0, 0, 0)
        formulario.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.campo_nombre = QLineEdit()
        self.campo_nombre.setPlaceholderText(_("Ciudad o lugar, p. ej. Madrid"))
        self.boton_buscar = QPushButton(_("Buscar en TikTok"))
        self.boton_buscar.setToolTip(_(
            "Pregunta al servicio qué lugares de TikTok se llaman así, para elegir uno"))
        self.boton_quitar = QPushButton(_("Quitar"))
        self.boton_quitar.setToolTip(_("Publicar sin ubicación"))
        fila = QHBoxLayout()
        fila.addWidget(self.campo_nombre, 1)
        fila.addWidget(self.boton_buscar)
        fila.addWidget(self.boton_quitar)
        formulario.addRow(_("Lugar:"), fila)

        self.combo_tiktok = QComboBox()
        formulario.addRow("TikTok:", self.combo_tiktok)
        self.aviso_tiktok = QLabel()
        self.aviso_tiktok.setWordWrap(True)
        self.aviso_tiktok.setStyleSheet(f"color: {COLOR_AVISO};")
        self.aviso_tiktok.hide()
        formulario.addRow("", self.aviso_tiktok)

        self.campo_instagram = QLineEdit()
        self.campo_instagram.setPlaceholderText(_(
            "ID numérico de una página o lugar de Facebook (opcional)"))
        formulario.addRow("Instagram:", self.campo_instagram)
        self.campo_x = QLineEdit()
        self.campo_x.setPlaceholderText(_("ID del lugar en X (opcional)"))
        formulario.addRow("X:", self.campo_x)
        self.aviso_ids = QLabel()
        self.aviso_ids.setWordWrap(True)
        self.aviso_ids.setStyleSheet(f"color: {COLOR_AVISO};")
        self.aviso_ids.hide()
        formulario.addRow("", self.aviso_ids)
        ayuda = QLabel(_(
            "YouTube y Facebook no admiten ubicación. Instagram y X solo la llevan si "
            "pones su ID."))
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet(f"color: {COLOR_SECUNDARIO};")
        formulario.addRow("", ayuda)

        self.campo_nombre.textChanged.connect(self._al_editar_nombre)
        self.boton_buscar.clicked.connect(self._buscar)
        self.boton_quitar.clicked.connect(lambda: self.poner(Ubicacion()))
        self.campo_instagram.textChanged.connect(self._refrescar_ids)
        self.campo_x.textChanged.connect(self._refrescar_ids)
        self.poner(ubicacion)

    def poner(self, ubicacion: Ubicacion) -> None:
        self._busqueda_n += 1  # una búsqueda en marcha ya no vale
        self.boton_buscar.setEnabled(True)
        self.campo_nombre.setText(ubicacion.nombre)
        lugar = ubicacion.tiktok
        self._poner_lugares([lugar] if lugar else [], lugar)
        self.campo_instagram.setText(ubicacion.instagram_id)
        self.campo_x.setText(ubicacion.x_id)
        self._avisar_tiktok("")

    def ubicacion(self) -> Ubicacion:
        lugar = self.combo_tiktok.currentData()
        return Ubicacion(self.campo_nombre.text().strip(),
                         lugar if isinstance(lugar, Lugar) else None,
                         self.campo_instagram.text().strip(), self.campo_x.text().strip())

    def poner_cuenta_tiktok(self, cuenta: Cuenta | None, servicio: str) -> None:
        """Avisa si la cuenta de TikTok no tiene permiso para ubicaciones."""
        self._aviso_permiso = ""
        if cuenta is not None and cuenta.ubicacion is False:
            self._aviso_permiso = _(
                "⚠ Reconecta TikTok en {servicio}: tu cuenta no tiene permiso para "
                "etiquetar ubicaciones.").format(servicio=servicio)
        self._avisar_tiktok("")

    # --- detalles ---

    def _automatico(self) -> str:
        nombre = self.campo_nombre.text().strip()
        if not nombre:
            return _("Sin ubicación en TikTok")
        return _("Automático: el lugar que se llame «{nombre}»").format(nombre=nombre)

    def _poner_lugares(self, lugares: list[Lugar], elegido: Lugar | None) -> None:
        self.combo_tiktok.clear()
        self.combo_tiktok.addItem(self._automatico(), None)
        for lugar in lugares:
            self.combo_tiktok.addItem(lugar.visible, lugar)
        indice = next((i for i, lugar in enumerate(lugares, start=1) if lugar == elegido), 0)
        self.combo_tiktok.setCurrentIndex(indice)

    def _avisar_tiktok(self, texto: str) -> None:
        texto = texto or self._aviso_permiso
        self.aviso_tiktok.setText(texto)
        self.aviso_tiktok.setVisible(bool(texto))

    def _al_editar_nombre(self, *args) -> None:
        # Los lugares de otra búsqueda ya no valen para el nombre nuevo.
        self._busqueda_n += 1
        self.boton_buscar.setEnabled(True)
        self._poner_lugares([], None)
        self._avisar_tiktok("")

    def _buscar(self) -> None:
        texto = self.campo_nombre.text().strip()
        if not texto:
            self._avisar_tiktok(_("Escribe el lugar que quieres buscar."))
            return
        self._busqueda_n += 1
        numero = self._busqueda_n
        trabajo = self._preparar_busqueda(texto)
        self.boton_buscar.setEnabled(False)
        self._avisar_tiktok(_("Buscando…"))
        segundo_plano.en_segundo_plano(lambda: (numero, texto, trabajo()), self._al_buscar,
                                       "tsots-lugares")

    def _al_buscar(self, resultado) -> None:
        if isinstance(resultado, BaseException):  # el trabajo no lanza; por si acaso
            resultado = (self._busqueda_n, "", (None, type(resultado).__name__))
        numero, texto, (lugares, motivo) = resultado
        if numero != self._busqueda_n:
            return  # llegó tarde: el nombre cambió o hay otra búsqueda
        self.boton_buscar.setEnabled(True)
        if lugares is None:
            self._avisar_tiktok(motivo)
            return
        elegido = elegir_lugar(lugares, texto)
        self._poner_lugares(lugares, elegido)
        if not lugares:
            self._avisar_tiktok(_("TikTok no encuentra «{texto}».").format(texto=texto))
        elif elegido is None:
            self._avisar_tiktok(_(
                "Elige uno de la lista: ninguno se llama «{texto}». Sin elegir, TikTok se "
                "publica sin ubicación.").format(texto=texto))
        else:
            self._avisar_tiktok("")

    def _refrescar_ids(self, *args) -> None:
        avisos = []
        instagram = self.campo_instagram.text().strip()
        if instagram and not id_instagram_valido(instagram):
            avisos.append(_("⚠ El ID de Instagram solo tiene números: no se enviará."))
        x = self.campo_x.text().strip()
        if x and not id_x_valido(x):
            avisos.append(_("⚠ El ID de X es hexadecimal (p. ej. 01a9a39529b27f36): "
                            "no se enviará."))
        self.aviso_ids.setText("\n".join(avisos))
        self.aviso_ids.setVisible(bool(avisos))


class DialogoUbicacion(QDialog):
    """La ubicación de un solo vídeo, desde el diálogo Publicar."""

    def __init__(self, ubicacion: Ubicacion, preparar_busqueda: PrepararBusqueda,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Ubicación de este vídeo"))
        self.setMinimumWidth(520)
        raiz = QVBoxLayout(self)
        nota = QLabel(_("Solo para este vídeo. La de siempre se cambia en Redes…."))
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color: {COLOR_SECUNDARIO};")
        raiz.addWidget(nota)
        self.selector = SelectorUbicacion(ubicacion, preparar_busqueda, self)
        raiz.addWidget(self.selector)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        raiz.addWidget(botones)

    def ubicacion(self) -> Ubicacion:
        return self.selector.ubicacion()
