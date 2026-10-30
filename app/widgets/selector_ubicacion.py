"""Ubicación de las publicaciones: el selector que comparten el diálogo
Redes… (la de siempre) y el diálogo Publicar (la de un solo vídeo), y dónde
se guarda la de siempre: la ciudad en los ajustes y el lugar de TikTok, que
es de la cuenta, en el Llavero."""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from videopipeline.i18n import _
from videopipeline.redes.modelo import Ciudad, Cuenta, Lugar, Ubicacion, elegir_lugar

from .. import credenciales, segundo_plano
from ..cuentas import COLOR_AVISO, COLOR_SECUNDARIO

# Recibe el texto a buscar (en el hilo de la interfaz, donde puede leer los
# controles) y devuelve el trabajo que corre en segundo plano y nunca lanza:
# `() -> (lugares | None, motivo)`.
PrepararBusqueda = Callable[[str], Callable[[], "tuple[list[Lugar] | None, str]"]]


def ubicacion_guardada(ajustes, llavero, proveedor: str, perfil: str) -> Ubicacion:
    """La de siempre: la ciudad de los ajustes y, si se eligió, el lugar de
    TikTok de esa cuenta, del Llavero. Lee un secreto: solo al pulsar
    Cambiar… o Publicar, nunca al abrir un diálogo."""
    ciudad = ajustes.ciudad
    if ciudad is None:
        return Ubicacion()
    try:
        lugar = llavero.leer_lugar_tiktok(proveedor, perfil, ciudad.name)
    except Exception:  # sin el lugar, TikTok lo busca al publicar: nunca bloquea
        lugar = None
    return Ubicacion(ciudad, lugar)


def guardar_ubicacion(ajustes, llavero, proveedor: str, perfil: str,
                      ubicacion: Ubicacion) -> None:
    """Guarda la de siempre. Sin lugar de TikTok elegido, olvida el que hubiera
    para esa ciudad. Lanza `credenciales.ErrorLlavero` si el Llavero falla."""
    ajustes.ciudad = ubicacion.ciudad
    if ubicacion.ciudad is not None:
        llavero.guardar_lugar_tiktok(proveedor, perfil, ubicacion.ciudad.name, ubicacion.tiktok)


def describir_ubicacion(ubicacion: Ubicacion, redes=None) -> str:
    """«Madrid (TikTok, Instagram, X)» o «Sin ubicación». `redes`: solo esas."""
    con = [p for p in ubicacion.plataformas() if redes is None or p in redes]
    if not con:
        return _("Sin ubicación")
    return _("{lugar} ({redes})").format(
        lugar=ubicacion.visible, redes=", ".join(p.nombre for p in con))


def aviso_permiso_tiktok(cuenta: Cuenta | None, servicio: str) -> str:
    """Aviso si la cuenta de TikTok no tiene permiso para ubicaciones, o ""."""
    if cuenta is None or cuenta.ubicacion is not False:
        return ""
    return _("⚠ Reconecta TikTok en {servicio}: tu cuenta no tiene permiso para "
             "etiquetar ubicaciones.").format(servicio=servicio)


class SelectorUbicacion(QWidget):
    """Una ciudad del catálogo (o ninguna) y el lugar de TikTok elegido entre
    los que devuelve la búsqueda. Solo muestra nombres: los IDs de Instagram
    y X salen de la ciudad, y el de TikTok es privado. Sin lugar de TikTok
    elegido, al publicar se usa el primero que se llame como la ciudad."""

    def __init__(self, ubicacion: Ubicacion, preparar_busqueda: PrepararBusqueda,
                 parent=None):
        super().__init__(parent)
        self._preparar_busqueda = preparar_busqueda
        self._busqueda_n = 0
        self._aviso_permiso = ""
        formulario = QFormLayout(self)
        formulario.setContentsMargins(0, 0, 0, 0)
        formulario.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.combo_ciudad = QComboBox()
        for ciudad in Ciudad:
            self.combo_ciudad.addItem(ciudad.nombre, ciudad)
        self.combo_ciudad.addItem(_("Sin ubicación"), None)
        formulario.addRow(_("Ciudad:"), self.combo_ciudad)

        self.combo_tiktok = QComboBox()
        self.boton_buscar = QPushButton(_("Buscar en TikTok"))
        self.boton_buscar.setToolTip(_(
            "Pregunta al servicio qué lugares de TikTok se llaman así, para elegir uno"))
        fila = QHBoxLayout()
        fila.addWidget(self.combo_tiktok, 1)
        fila.addWidget(self.boton_buscar)
        formulario.addRow("TikTok:", fila)
        self.aviso_tiktok = QLabel()
        self.aviso_tiktok.setWordWrap(True)
        self.aviso_tiktok.setStyleSheet(f"color: {COLOR_AVISO};")
        self.aviso_tiktok.hide()
        formulario.addRow("", self.aviso_tiktok)

        self.etiqueta_redes = QLabel()
        self.etiqueta_redes.setWordWrap(True)
        formulario.addRow("", self.etiqueta_redes)
        ayuda = QLabel(_(
            "YouTube y Facebook no admiten ubicación. El lugar de TikTok es de tu "
            "cuenta: se guarda solo en el Llavero de macOS."))
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet(f"color: {COLOR_SECUNDARIO};")
        formulario.addRow("", ayuda)

        self.combo_ciudad.currentIndexChanged.connect(self._al_cambiar_ciudad)
        self.boton_buscar.clicked.connect(self._buscar)
        self.poner(ubicacion)

    def poner(self, ubicacion: Ubicacion) -> None:
        indice = next((i for i in range(self.combo_ciudad.count())
                       if self.combo_ciudad.itemData(i) is ubicacion.ciudad),
                      self.combo_ciudad.count() - 1)
        self.combo_ciudad.blockSignals(True)
        self.combo_ciudad.setCurrentIndex(indice)
        self.combo_ciudad.blockSignals(False)
        self._al_cambiar_ciudad()
        if ubicacion.ciudad is not None and ubicacion.tiktok is not None:
            self._poner_lugares([ubicacion.tiktok], ubicacion.tiktok)

    def ubicacion(self) -> Ubicacion:
        ciudad = self._ciudad()
        lugar = self.combo_tiktok.currentData()
        if ciudad is None or not isinstance(lugar, Lugar):
            lugar = None
        return Ubicacion(ciudad, lugar)

    def poner_cuenta_tiktok(self, cuenta: Cuenta | None, servicio: str) -> None:
        """Avisa si la cuenta de TikTok no tiene permiso para ubicaciones."""
        self._aviso_permiso = aviso_permiso_tiktok(cuenta, servicio)
        self._avisar_tiktok("")

    # --- detalles ---

    def _ciudad(self) -> Ciudad | None:
        dato = self.combo_ciudad.currentData()
        return dato if isinstance(dato, Ciudad) else None

    def _automatico(self) -> str:
        ciudad = self._ciudad()
        if ciudad is None:
            return _("Sin ubicación en TikTok")
        return _("Automático: el lugar que se llame «{nombre}»").format(nombre=ciudad.nombre)

    def _al_cambiar_ciudad(self, *args) -> None:
        # Los lugares de TikTok de otra ciudad ya no valen.
        self._busqueda_n += 1
        hay = self._ciudad() is not None
        self.combo_tiktok.setEnabled(hay)
        self.boton_buscar.setEnabled(hay)
        self._poner_lugares([], None)
        self._avisar_tiktok("")
        redes = self.ubicacion().plataformas()
        self.etiqueta_redes.setText(
            _("Se etiqueta en: {redes}.").format(redes=", ".join(p.nombre for p in redes))
            if redes else _("No se etiqueta en ninguna red."))

    def _poner_lugares(self, lugares: list[Lugar], elegido: Lugar | None) -> None:
        self.combo_tiktok.clear()
        self.combo_tiktok.addItem(self._automatico(), None)
        for lugar in lugares:
            self.combo_tiktok.addItem(lugar.visible, lugar)
        indice = next((i for i, lugar in enumerate(lugares, start=1) if lugar == elegido), 0)
        self.combo_tiktok.setCurrentIndex(indice)

    def _avisar_tiktok(self, texto: str) -> None:
        texto = texto or (self._aviso_permiso if self._ciudad() is not None else "")
        self.aviso_tiktok.setText(texto)
        self.aviso_tiktok.setVisible(bool(texto))

    def _buscar(self) -> None:
        ciudad = self._ciudad()
        if ciudad is None:
            return
        texto = ciudad.nombre
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
            return  # llegó tarde: cambió la ciudad o hay otra búsqueda
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


class DialogoUbicacion(QDialog):
    """El selector en su propia ventana: la ubicación de siempre (Redes…)
    o la de un solo vídeo (Publicar)."""

    def __init__(self, ubicacion: Ubicacion, preparar_busqueda: PrepararBusqueda,
                 titulo: str, nota: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(520)
        raiz = QVBoxLayout(self)
        nota = QLabel(nota)
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
