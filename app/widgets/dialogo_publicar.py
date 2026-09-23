from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from videopipeline.caption import Caption
from videopipeline.i18n import _
from videopipeline.redes import proveedor as proveedores
from videopipeline.redes import publicador, registro
from videopipeline.redes.modelo import (
    ETIQUETAS_INSTAGRAM,
    ETIQUETAS_TIKTOK,
    ORDEN,
    ModoInstagram,
    ModoTikTok,
    Opciones,
    Plataforma,
    Publicacion,
    Resultado,
)
from videopipeline.redes.publicador import Estado
from videopipeline.redes.textos import MAX_TITULO_YOUTUBE

from .. import credenciales
from ..settings import Ajustes

COLOR_OK = "#43a047"
COLOR_ERROR = "#e53935"
COLOR_AVISO = "#b8860b"

Fabrica = Callable[[str, str, dict], proveedores.Proveedor]


class HiloPublicacion(QThread):
    """Ejecuta `publicador.publicar` fuera del hilo de la interfaz."""

    progreso = Signal(str, str, object)  # plataforma, estado, Resultado | None
    terminado = Signal(object)  # dict[Plataforma, Resultado]

    def __init__(self, proveedor, publicacion: Publicacion, opciones: Opciones,
                 plataformas: list[Plataforma], nombre_proveedor: str, parent=None):
        super().__init__(parent)
        self._proveedor = proveedor
        self._publicacion = publicacion
        self._opciones = opciones
        self._plataformas = plataformas
        self._nombre_proveedor = nombre_proveedor

    def run(self) -> None:
        resultados: dict = {}
        try:
            resultados = publicador.publicar(
                self._proveedor, self._publicacion, self._opciones, self._plataformas,
                progreso=lambda p, e, r: self.progreso.emit(p.value, e.value, r),
                nombre_proveedor=self._nombre_proveedor,
                cancelado=self.isInterruptionRequested,
            )
        except Exception:  # publicador aísla los fallos; esto es solo un seguro
            resultados = {}
        finally:
            self._proveedor = None  # suelta la clave que guarda el proveedor
        self.terminado.emit(resultados)


class DialogoPublicar(QDialog):
    """Revisa textos, elige plataformas y modos, y publica tras confirmar."""

    publicacion_terminada = Signal(object)  # dict[Plataforma, Resultado]
    configurar_redes = Signal()

    def __init__(self, video: Path, caption: Caption, ajustes: Ajustes,
                 llavero=credenciales, fabrica: Fabrica | None = None, parent=None):
        super().__init__(parent)
        self.video = Path(video)
        self.ajustes = ajustes
        self.llavero = llavero
        self.fabrica = fabrica or (lambda nombre, clave, datos: proveedores.crear(
            nombre, clave, datos))
        self._hilo: HiloPublicacion | None = None
        self.resultados: dict[Plataforma, Resultado] = {}
        self.setWindowTitle(_("Publicar en redes"))
        self.setMinimumWidth(640)

        raiz = QVBoxLayout(self)
        cabecera = QLabel(self.video.name)
        cabecera.setStyleSheet("font-weight: bold;")
        raiz.addWidget(cabecera)
        self.aviso_publicado = QLabel()
        self.aviso_publicado.setWordWrap(True)
        self.aviso_publicado.setStyleSheet(f"color: {COLOR_AVISO};")
        raiz.addWidget(self.aviso_publicado)

        grupo_textos = QGroupBox(_("Textos"))
        formulario = QFormLayout(grupo_textos)
        formulario.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.campo_titulo = QLineEdit(caption.titulo)
        self.campo_titulo.setCursorPosition(0)
        self.contador_titulo = QLabel()
        fila_titulo = QHBoxLayout()
        fila_titulo.addWidget(self.campo_titulo, 1)
        fila_titulo.addWidget(self.contador_titulo)
        formulario.addRow(_("Título:"), fila_titulo)
        self.campo_caption = QPlainTextEdit(caption.caption)
        self.campo_caption.setMinimumHeight(120)
        formulario.addRow(_("Caption:"), self.campo_caption)
        self.campo_hashtags = QLineEdit(caption.hashtags_texto)
        self.campo_hashtags.setCursorPosition(0)
        formulario.addRow(_("Hashtags:"), self.campo_hashtags)
        self._palabras_clave = tuple(caption.palabras_clave)
        raiz.addWidget(grupo_textos)

        grupo_plataformas = QGroupBox(_("Plataformas (en este orden)"))
        rejilla = QGridLayout(grupo_plataformas)
        rejilla.setColumnStretch(2, 1)
        self.casillas: dict[Plataforma, QCheckBox] = {}
        self.estados: dict[Plataforma, QLabel] = {}
        marcadas = set(ajustes.plataformas_redes)
        self.combo_tiktok = QComboBox()
        for modo in ModoTikTok:
            self.combo_tiktok.addItem(_(ETIQUETAS_TIKTOK[modo]), modo.value)
        self.combo_tiktok.setCurrentIndex(self.combo_tiktok.findData(ajustes.tiktok_modo.value))
        self.combo_instagram = QComboBox()
        for modo in ModoInstagram:
            self.combo_instagram.addItem(_(ETIQUETAS_INSTAGRAM[modo]), modo.value)
        self.combo_instagram.setCurrentIndex(
            self.combo_instagram.findData(ajustes.instagram_modo.value))
        modo_por_plataforma = {
            Plataforma.TIKTOK: self.combo_tiktok,
            Plataforma.YOUTUBE: QLabel(_("Short público")),
            Plataforma.INSTAGRAM: self.combo_instagram,
        }
        for fila, plataforma in enumerate(ORDEN):
            casilla = QCheckBox(plataforma.nombre)
            casilla.setChecked(plataforma in marcadas)
            casilla.toggled.connect(self._refrescar)
            estado = QLabel()
            estado.setOpenExternalLinks(True)
            estado.setWordWrap(True)
            self.casillas[plataforma] = casilla
            self.estados[plataforma] = estado
            rejilla.addWidget(casilla, fila, 0)
            rejilla.addWidget(modo_por_plataforma[plataforma], fila, 1)
            rejilla.addWidget(estado, fila, 2)
        raiz.addWidget(grupo_plataformas)

        self.barra = QProgressBar()
        self.barra.setRange(0, 0)
        self.barra.setTextVisible(False)
        self.barra.setMaximumHeight(6)
        self.barra.hide()
        raiz.addWidget(self.barra)

        fila_servicio = QHBoxLayout()
        self.etiqueta_servicio = QLabel()
        self.etiqueta_servicio.setWordWrap(True)
        self.boton_redes = QPushButton(_("Redes…"))
        self.boton_redes.clicked.connect(self.configurar_redes)
        fila_servicio.addWidget(self.etiqueta_servicio, 1)
        fila_servicio.addWidget(self.boton_redes)
        raiz.addLayout(fila_servicio)

        botones = QHBoxLayout()
        botones.addStretch(1)
        self.boton_cerrar = QPushButton(_("Cerrar"))
        self.boton_cerrar.clicked.connect(self.reject)
        self.boton_publicar = QPushButton(_("Publicar"))
        self.boton_publicar.setDefault(True)
        self.boton_publicar.clicked.connect(self.publicar)
        botones.addWidget(self.boton_cerrar)
        botones.addWidget(self.boton_publicar)
        raiz.addLayout(botones)

        self.campo_titulo.textChanged.connect(self._refrescar)
        self.refrescar_servicio()
        self._refrescar_aviso()

    # --- estado ---

    @property
    def publicando(self) -> bool:
        return self._hilo is not None

    def plataformas(self) -> list[Plataforma]:
        return [p for p in ORDEN if self.casillas[p].isChecked()]

    def opciones(self) -> Opciones:
        return Opciones(
            tiktok_modo=ModoTikTok(self.combo_tiktok.currentData()),
            instagram_modo=ModoInstagram(self.combo_instagram.currentData()),
            youtube_categoria=self.ajustes.youtube_categoria,
        )

    def publicacion(self) -> Publicacion:
        return Publicacion(
            video=self.video,
            titulo=self.campo_titulo.text().strip(),
            caption=self.campo_caption.toPlainText().strip(),
            hashtags=tuple(self.campo_hashtags.text().split()),
            palabras_clave=self._palabras_clave,
        )

    def _listo(self) -> tuple[bool, str]:
        nombre = self.ajustes.proveedor_redes
        if not self._hay_clave:
            return False, _("Falta la API key del servicio: guárdala en Redes…")
        if proveedores.usa_perfil(nombre) and not self.ajustes.perfil_redes:
            return False, _("Falta el perfil del servicio: escríbelo en Redes…")
        return True, ""

    def refrescar_servicio(self) -> None:
        """Vuelve a leer ajustes y Llavero (tras cerrar el diálogo Redes…)."""
        nombre = self.ajustes.proveedor_redes
        self._hay_clave = self.llavero.hay_clave(nombre)
        listo, motivo = self._listo()
        if listo:
            perfil = self.ajustes.perfil_redes
            texto = _("Vía {servicio}").format(servicio=proveedores.nombre_visible(nombre))
            if perfil:
                texto += " · " + _("perfil «{perfil}»").format(perfil=perfil)
            self.etiqueta_servicio.setText(texto)
            self.etiqueta_servicio.setStyleSheet("")
        else:
            self.etiqueta_servicio.setText(motivo)
            self.etiqueta_servicio.setStyleSheet(f"color: {COLOR_AVISO};")
        self._refrescar()

    def _refrescar(self, *args) -> None:
        largo = len(self.campo_titulo.text().strip())
        self.contador_titulo.setText(f"{largo}/{MAX_TITULO_YOUTUBE}")
        self.contador_titulo.setStyleSheet(
            f"color: {COLOR_AVISO};" if largo > MAX_TITULO_YOUTUBE else "")
        listo, _motivo = self._listo()
        self.boton_publicar.setEnabled(
            listo and not self.publicando and bool(self.plataformas())
            and bool(self.campo_titulo.text().strip()))

    def _refrescar_aviso(self) -> None:
        ultimas = registro.ultimas(self.video)
        if not ultimas:
            self.aviso_publicado.hide()
            return
        partes = []
        for plataforma in ORDEN:
            entrada = ultimas.get(plataforma)
            if entrada is None:
                continue
            try:
                fecha = datetime.fromisoformat(entrada.fecha).strftime("%d/%m/%Y %H:%M")
            except ValueError:
                fecha = entrada.fecha
            nombre = plataforma.nombre
            if plataforma == Plataforma.TIKTOK and entrada.modo == ModoTikTok.BORRADOR.value:
                nombre = _("{plataforma} (borrador)").format(plataforma=nombre)
            partes.append(f"{nombre} {fecha}")
        self.aviso_publicado.setText(
            _("⚠ Este vídeo ya se publicó: {lista}. Si vuelves a publicarlo, "
              "saldrá repetido.").format(lista=", ".join(partes)))
        self.aviso_publicado.show()

    # --- publicar ---

    def _resumen(self) -> str:
        opciones = self.opciones()
        lineas = []
        for plataforma in self.plataformas():
            if plataforma == Plataforma.TIKTOK:
                modo = _(ETIQUETAS_TIKTOK[opciones.tiktok_modo])
            elif plataforma == Plataforma.INSTAGRAM:
                modo = _(ETIQUETAS_INSTAGRAM[opciones.instagram_modo])
            else:
                modo = _("Short público")
            lineas.append(f"• {plataforma.nombre}: {modo}")
        return "\n".join(lineas)

    def _confirmar(self) -> bool:
        repetidas = registro.ya_publicado(self.video) & set(self.plataformas())
        texto = _("Se publicará «{titulo}» en:\n\n{resumen}").format(
            titulo=self.campo_titulo.text().strip(), resumen=self._resumen())
        if repetidas:
            texto += "\n\n" + _("Ya publicado antes en: {lista}.").format(
                lista=", ".join(p.nombre for p in ORDEN if p in repetidas))
        texto += "\n\n" + _("¿Publicar ahora?")
        respuesta = QMessageBox.question(
            self, _("Publicar en redes"), texto,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return respuesta == QMessageBox.StandardButton.Yes

    def publicar(self) -> None:
        if self.publicando or not self.boton_publicar.isEnabled():
            return
        if not self._confirmar():
            return
        nombre = self.ajustes.proveedor_redes
        try:
            clave = self.llavero.leer(nombre)
        except credenciales.ErrorLlavero as e:
            QMessageBox.warning(self, _("Llavero"), str(e))
            return
        if not clave:
            self.refrescar_servicio()
            return
        proveedor = self.fabrica(nombre, clave, self.ajustes.ajustes_proveedor())
        del clave
        plataformas = self.plataformas()
        self.ajustes.plataformas_redes = plataformas
        self.ajustes.tiktok_modo = ModoTikTok(self.combo_tiktok.currentData())
        self.ajustes.instagram_modo = ModoInstagram(self.combo_instagram.currentData())
        for plataforma in ORDEN:
            self.estados[plataforma].setText(_("En cola") if plataforma in plataformas else "")
            self.estados[plataforma].setStyleSheet("")
        self._hilo = HiloPublicacion(proveedor, self.publicacion(), self.opciones(),
                                     plataformas, nombre, self)
        self._hilo.progreso.connect(self._al_progresar)
        self._hilo.terminado.connect(self._al_terminar)
        self._bloquear(True)
        self._hilo.start()

    def _bloquear(self, bloqueado: bool) -> None:
        for widget in (self.campo_titulo, self.campo_caption, self.campo_hashtags,
                       self.combo_tiktok, self.combo_instagram, self.boton_redes,
                       self.boton_cerrar, *self.casillas.values()):
            widget.setEnabled(not bloqueado)
        self.barra.setVisible(bloqueado)
        self._refrescar()

    def _al_progresar(self, plataforma: str, estado: str, resultado) -> None:
        plataforma = Plataforma(plataforma)
        etiqueta = self.estados[plataforma]
        estado = Estado(estado)
        if estado == Estado.SUBIENDO:
            etiqueta.setText(_("Subiendo…"))
            etiqueta.setStyleSheet("")
        elif estado == Estado.PROCESANDO:
            etiqueta.setText(_("Procesando en el servicio…"))
            etiqueta.setStyleSheet("")
        else:
            self._mostrar_resultado(plataforma, resultado)

    def _mostrar_resultado(self, plataforma: Plataforma, resultado: Resultado) -> None:
        etiqueta = self.estados[plataforma]
        if resultado.ok:
            if resultado.url:
                texto = _('✓ Publicado · <a href="{url}">Abrir</a>').format(
                    url=html.escape(resultado.url, quote=True))
            elif (plataforma == Plataforma.TIKTOK
                  and self.opciones().tiktok_modo == ModoTikTok.BORRADOR):
                texto = html.escape(_("✓ En borradores: termínalo en la app de TikTok"))
            else:
                texto = html.escape(_("✓ Publicado"))
            color = COLOR_OK
        elif resultado.pendiente:
            texto, color = html.escape("⏳ " + resultado.error), COLOR_AVISO
        else:
            texto, color = html.escape("✗ " + (resultado.error or _("Error"))), COLOR_ERROR
        etiqueta.setText(texto)
        etiqueta.setToolTip(resultado.error)
        etiqueta.setStyleSheet(f"color: {color};")

    def _al_terminar(self, resultados: dict) -> None:
        hilo, self._hilo = self._hilo, None
        if hilo is not None:
            hilo.wait()
            hilo.deleteLater()
        self.resultados = dict(resultados)
        for plataforma, resultado in self.resultados.items():
            self._mostrar_resultado(plataforma, resultado)
            if resultado.ok:  # lo que ya salió no se vuelve a marcar
                self.casillas[plataforma].setChecked(False)
        self._bloquear(False)
        self._refrescar_aviso()
        self.publicacion_terminada.emit(self.resultados)

    # --- cierre ---

    def reject(self) -> None:
        if self.publicando:
            return  # la subida sigue: no se abandona a medias
        super().reject()

    def closeEvent(self, evento) -> None:
        if self.publicando:
            evento.ignore()
            return
        super().closeEvent(evento)
