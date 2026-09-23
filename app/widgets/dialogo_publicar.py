from __future__ import annotations

import html
import logging
import platform as plataforma_sistema
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QProcess, Qt, QThread, Signal
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
from videopipeline.redes import diario, limites, publicador, registro
from videopipeline.redes.modelo import (
    ETIQUETAS_FACEBOOK,
    ETIQUETAS_INSTAGRAM,
    ETIQUETAS_TIKTOK,
    ORDEN,
    Cuenta,
    ModoFacebook,
    ModoInstagram,
    ModoTikTok,
    Opciones,
    Plataforma,
    Publicacion,
    Resultado,
)
from videopipeline.redes.publicador import Estado
from videopipeline.redes.textos import (
    MAX_TEXTO_X,
    MAX_TITULO_YOUTUBE,
    longitud_x,
    texto_x_por_defecto,
)
from videopipeline.steps import duracion_video

from .. import credenciales, segundo_plano
from .. import cuentas as consulta_cuentas
from ..cuentas import COLOR_AVISO, COLOR_ERROR, COLOR_OK, COLOR_SECUNDARIO
from ..settings import Ajustes

# Duración del vídeo (ffprobe). Se llama fuera del hilo de la interfaz; los
# tests la sustituyen.
medir_duracion = duracion_video

# Lo que escriben el diálogo y su hilo va al registro de la publicación
# (`logs/publicacion_<vídeo>_<fecha>.log`) mientras hay un `Diario` abierto.
log = logging.getLogger(diario.NOMBRE_LOGGER + ".publicacion")

Fabrica = Callable[[str, str, dict], proveedores.Proveedor]


def revelar_en_finder(ruta: Path) -> None:
    """Muestra el fichero seleccionado en una ventana del Finder."""
    QProcess.startDetached("/usr/bin/open", ["-R", str(ruta)])


# Hilos de publicación en marcha. No cuelgan del diálogo: si el diálogo se
# destruyera con una subida en curso, Qt abortaría la app («QThread:
# Destroyed while thread is still running»). Se sueltan al terminar.
_HILOS_VIVOS: set["HiloPublicacion"] = set()


def _retener(hilo: "HiloPublicacion") -> None:
    _HILOS_VIVOS.add(hilo)
    hilo.finished.connect(lambda: _soltar(hilo))


def _soltar(hilo: "HiloPublicacion") -> None:
    hilo.wait()  # `finished` llega justo antes de que el hilo salga del todo
    if hilo.diario is not None and hilo.diario.abierto:
        # El diálogo no llegó a cerrarlo (p. ej. se destruyó antes): lo cierra el hilo.
        log.info("Fin (hilo terminado sin diálogo)")
        hilo.diario.cerrar()
    _HILOS_VIVOS.discard(hilo)
    hilo.deleteLater()


def hilos_vivos() -> int:
    return len(_HILOS_VIVOS)


def esperar_hilos(milisegundos: int = 5000) -> None:
    """Al salir de la app: pide parar a los hilos y los espera. Una subida no
    se puede cortar a medias; si no acaba a tiempo se termina a la fuerza
    antes de que Qt aborte al destruirlo en marcha."""
    for hilo in list(_HILOS_VIVOS):
        hilo.requestInterruption()
    for hilo in list(_HILOS_VIVOS):
        if not hilo.wait(milisegundos):
            log.warning("Salida de la app con la publicación en marcha: se corta.")
            hilo.terminate()
            hilo.wait()
        if hilo.diario is not None:
            hilo.diario.cerrar()
        _HILOS_VIVOS.discard(hilo)


class HiloPublicacion(QThread):
    """Ejecuta `publicador.publicar` fuera del hilo de la interfaz."""

    progreso = Signal(str, str, object)  # plataforma, estado, Resultado | None
    terminado = Signal(object)  # dict[Plataforma, Resultado]

    def __init__(self, proveedor, publicacion: Publicacion, opciones: Opciones,
                 plataformas: list[Plataforma], nombre_proveedor: str,
                 diario_publicacion: diario.Diario | None = None):
        super().__init__()  # sin padre: ver `_HILOS_VIVOS`
        self._proveedor = proveedor
        self._publicacion = publicacion
        self._opciones = opciones
        self._plataformas = plataformas
        self._nombre_proveedor = nombre_proveedor
        self.diario = diario_publicacion
        self._ruta_log = diario_publicacion.ruta if diario_publicacion else None

    def start(self, *args) -> None:
        _retener(self)
        super().start(*args)

    def run(self) -> None:
        vistos: dict[Plataforma, Resultado] = {}

        def avisar(plataforma: Plataforma, estado: Estado, resultado) -> None:
            if estado in (Estado.HECHO, Estado.ERROR) and resultado is not None:
                vistos[plataforma] = resultado
            self.progreso.emit(plataforma.value, estado.value, resultado)

        try:
            resultados = publicador.publicar(
                self._proveedor, self._publicacion, self._opciones, self._plataformas,
                progreso=avisar,
                nombre_proveedor=self._nombre_proveedor,
                cancelado=self.isInterruptionRequested,
            )
        except BaseException as e:  # publicador aísla los fallos; esto es el último seguro
            log.exception("Fallo inesperado en el hilo de publicación")
            resultados = dict(vistos)
            fichero = self._ruta_log.name if self._ruta_log else _("no disponible")
            for plataforma in self._plataformas:
                if plataforma not in resultados:
                    resultados[plataforma] = Resultado(plataforma, ok=False, error=_(
                        "Error inesperado ({tipo}). Detalles en el registro: {fichero}").format(
                        tipo=type(e).__name__, fichero=fichero))
        finally:
            self._proveedor = None  # suelta la clave que guarda el proveedor
        self.terminado.emit({p: resultados[p] for p in ORDEN if p in resultados})


class DialogoPublicar(QDialog):
    """Revisa textos, elige plataformas y modos, y publica tras confirmar."""

    publicacion_terminada = Signal(object)  # dict[Plataforma, Resultado]
    configurar_redes = Signal()

    def __init__(self, video: Path, caption: Caption, ajustes: Ajustes,
                 llavero=credenciales, fabrica: Fabrica | None = None,
                 medir: Callable[[Path], float] | None = None, parent=None):
        super().__init__(parent)
        self.video = Path(video)
        self.ajustes = ajustes
        self.llavero = llavero
        self.fabrica = fabrica or (lambda nombre, clave, datos: proveedores.crear(
            nombre, clave, datos))
        self._medir = medir or medir_duracion
        # Duración (None mientras ffprobe la mide; 0 si no se pudo leer) y tamaño.
        self.duracion: float | None = None
        try:
            self.tamano: int | None = self.video.stat().st_size
        except OSError:
            self.tamano = None
        # Cuentas conectadas: lo último guardado y, en cuanto llega, la
        # consulta en vivo. Una plataforma ausente es desconocida.
        self._cuentas: dict[Plataforma, Cuenta | None] = {}
        self._cuentas_en_vivo = False
        self._fecha_cuentas = ""
        self._error_cuentas = ""
        self._consulta_n = 0
        # Lo que el usuario quiere marcado; las casillas deshabilitadas
        # (cuenta no conectada, vídeo largo para X…) se desmarcan sin olvidarlo.
        self._deseadas: set[Plataforma] = set(ajustes.plataformas_redes)
        self._aplicando = False
        # Filas que muestran el progreso o el resultado de un intento: la
        # información de la cuenta no las pisa.
        self._con_resultado: set[Plataforma] = set()
        self._x_editado = False
        self._rellenando_x = False
        self._hilo: HiloPublicacion | None = None
        self._diario: diario.Diario | None = None
        self.ruta_log: Path | None = None
        self._en_curso: list[Plataforma] = []
        self._opciones_en_curso = Opciones()
        self._procesando: set[Plataforma] = set()
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
        self.campo_x = QPlainTextEdit()
        self.campo_x.setFixedHeight(64)
        self.campo_x.setToolTip(_(
            "El post de X. Sin Premium admite {maximo} caracteres: una URL cuenta 23 y un "
            "emoji, 2. Mientras no lo cambies, se rellena con el título y los "
            "hashtags.").format(maximo=MAX_TEXTO_X))
        self.contador_x = QLabel()
        fila_x = QHBoxLayout()
        fila_x.addWidget(self.campo_x, 1)
        fila_x.addWidget(self.contador_x, 0, Qt.AlignmentFlag.AlignTop)
        formulario.addRow(_("Texto para X:"), fila_x)
        raiz.addWidget(grupo_textos)

        grupo_plataformas = QGroupBox(_("Plataformas (en este orden)"))
        rejilla = QGridLayout(grupo_plataformas)
        rejilla.setColumnStretch(2, 1)
        self.casillas: dict[Plataforma, QCheckBox] = {}
        self.estados: dict[Plataforma, QLabel] = {}
        self.combo_tiktok = QComboBox()
        for modo in ModoTikTok:
            self.combo_tiktok.addItem(_(ETIQUETAS_TIKTOK[modo]), modo.value)
        self.combo_tiktok.setCurrentIndex(self.combo_tiktok.findData(ajustes.tiktok_modo.value))
        self.combo_instagram = QComboBox()
        for modo in ModoInstagram:
            self.combo_instagram.addItem(_(ETIQUETAS_INSTAGRAM[modo]), modo.value)
        self.combo_instagram.setCurrentIndex(
            self.combo_instagram.findData(ajustes.instagram_modo.value))
        self.combo_facebook = QComboBox()
        for modo in ModoFacebook:
            self.combo_facebook.addItem(_(ETIQUETAS_FACEBOOK[modo]), modo.value)
        self.combo_facebook.setCurrentIndex(
            self.combo_facebook.findData(ajustes.facebook_modo.value))
        modo_por_plataforma = {
            Plataforma.TIKTOK: self.combo_tiktok,
            Plataforma.YOUTUBE: QLabel(_("Short público")),
            Plataforma.INSTAGRAM: self.combo_instagram,
            Plataforma.X: QLabel(_("Post público")),
            Plataforma.FACEBOOK: self.combo_facebook,
        }
        for fila, plataforma in enumerate(ORDEN):
            casilla = QCheckBox(plataforma.nombre)
            casilla.setChecked(plataforma in self._deseadas)
            casilla.toggled.connect(
                lambda marcada, p=plataforma: self._al_marcar(p, marcada))
            estado = QLabel()
            estado.setOpenExternalLinks(True)
            estado.setWordWrap(True)
            self.casillas[plataforma] = casilla
            self.estados[plataforma] = estado
            rejilla.addWidget(casilla, fila, 0)
            rejilla.addWidget(modo_por_plataforma[plataforma], fila, 1)
            rejilla.addWidget(estado, fila, 2)
        raiz.addWidget(grupo_plataformas)

        # Indeterminada mientras se publica. Sin altura máxima: con el estilo de
        # macOS una barra de 6 px no se dibuja.
        self.barra = QProgressBar()
        self.barra.setRange(0, 0)
        self.barra.setTextVisible(False)
        self.barra.hide()
        raiz.addWidget(self.barra)

        fila_estado = QHBoxLayout()
        self.etiqueta_estado = QLabel()
        self.etiqueta_estado.setWordWrap(True)
        self.etiqueta_estado.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.etiqueta_estado.hide()
        self.boton_registro = QPushButton(_("Ver registro"))
        self.boton_registro.setToolTip(_("Muestra en el Finder el registro de esta publicación"))
        self.boton_registro.clicked.connect(self._ver_registro)
        self.boton_registro.hide()
        fila_estado.addWidget(self.etiqueta_estado, 1)
        fila_estado.addWidget(self.boton_registro)
        raiz.addLayout(fila_estado)

        self.resumen = QLabel()
        self.resumen.setWordWrap(True)
        self.resumen.setOpenExternalLinks(True)
        self.resumen.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.resumen.hide()
        raiz.addWidget(self.resumen)

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

        self.campo_titulo.textChanged.connect(self._al_cambiar_textos)
        self.campo_hashtags.textChanged.connect(self._al_cambiar_textos)
        self.campo_x.textChanged.connect(self._al_editar_x)
        self._rellenar_x()
        self.refrescar_servicio()
        self._refrescar_aviso()
        self._medir_video()

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
            x_premium=self.ajustes.x_premium,
            facebook_modo=ModoFacebook(self.combo_facebook.currentData()),
        )

    def publicacion(self) -> Publicacion:
        return Publicacion(
            video=self.video,
            titulo=self.campo_titulo.text().strip(),
            caption=self.campo_caption.toPlainText().strip(),
            hashtags=tuple(self.campo_hashtags.text().split()),
            palabras_clave=self._palabras_clave,
            texto_x=self.campo_x.toPlainText().strip(),
        )

    # --- texto de X ---

    def _rellenar_x(self) -> None:
        """Mientras el usuario no lo edite, el texto de X sigue al título y
        a los hashtags."""
        if self._x_editado:
            return
        self._rellenando_x = True
        try:
            self.campo_x.setPlainText(texto_x_por_defecto(replace(self.publicacion(), texto_x="")))
        finally:
            self._rellenando_x = False

    def _al_cambiar_textos(self, *args) -> None:
        self._rellenar_x()
        self._refrescar()

    def _al_editar_x(self) -> None:
        if self._rellenando_x:
            return
        # Vaciarlo devuelve el texto automático en el siguiente cambio.
        self._x_editado = bool(self.campo_x.toPlainText().strip())
        self._refrescar()

    # --- duración del vídeo y cuentas (en segundo plano) ---

    def _medir_video(self) -> None:
        medir, video = self._medir, self.video
        segundo_plano.en_segundo_plano(lambda: float(medir(video) or 0.0), self._al_medir,
                                       "tsots-ffprobe")

    def _al_medir(self, resultado) -> None:
        self.duracion = resultado if isinstance(resultado, float) else 0.0
        self._refrescar()

    def _consultar_cuentas(self) -> None:
        """Pide al servicio las cuentas conectadas (y, si hace falta elegir
        la página de Facebook, sus páginas). Sin clave o sin perfil, nada."""
        self._consulta_n += 1
        listo, _motivo = self._listo()
        if not listo:
            return
        numero = self._consulta_n
        llavero, fabrica = self.llavero, self.fabrica
        nombre = self.ajustes.proveedor_redes
        datos = self.ajustes.ajustes_proveedor()
        paginas = None if self.ajustes.pagina_facebook is None else False

        def trabajo():
            return numero, consulta_cuentas.consultar(llavero, fabrica, nombre, datos,
                                                      paginas=paginas)

        segundo_plano.en_segundo_plano(trabajo, self._al_consultar, "tsots-cuentas")

    def _al_consultar(self, resultado) -> None:
        if isinstance(resultado, BaseException):  # `consultar` no lanza; por si acaso
            resultado = (self._consulta_n,
                         consulta_cuentas.Consulta(error=type(resultado).__name__))
        numero, consulta = resultado
        if numero != self._consulta_n:
            return  # llegó tarde: ya hay otra consulta en marcha
        if consulta.cuentas is not None:
            self._cuentas = dict(consulta.cuentas)
            self._cuentas_en_vivo = True
            self._fecha_cuentas = datetime.now().strftime("%H:%M")
            self._error_cuentas = ""
            self.ajustes.guardar_cuentas(consulta.cuentas)
        else:
            self._error_cuentas = consulta.error
        # Una sola página de Facebook: no hay nada que elegir.
        if consulta.paginas is not None and len(consulta.paginas) == 1 \
                and self.ajustes.pagina_facebook is None:
            self.ajustes.pagina_facebook = consulta.paginas[0]
        self._refrescar_etiqueta_servicio()
        self._refrescar()

    # --- estado de cada plataforma ---

    def _al_marcar(self, plataforma: Plataforma, marcada: bool) -> None:
        if self._aplicando:
            return
        if marcada:
            self._deseadas.add(plataforma)
        else:
            self._deseadas.discard(plataforma)
        self._con_resultado.discard(plataforma)
        self._refrescar()

    def _estado_plataforma(self, plataforma: Plataforma) -> tuple[bool, str, str, str]:
        """(habilitada, motivo que impide publicar si está marcada, texto
        informativo, color del texto)."""
        servicio = proveedores.nombre_visible(self.ajustes.proveedor_redes)
        cuenta = self._cuentas.get(plataforma)
        if plataforma in self._cuentas and cuenta is None:
            texto, color = consulta_cuentas.describir(plataforma, None, servicio)
            return False, "", texto, color
        bloqueo = ""
        if plataforma == Plataforma.X and not self.ajustes.x_premium:
            if self.duracion is None:
                return False, "", _("Comprobando la duración del vídeo…"), COLOR_SECUNDARIO
            motivo = limites.motivo_no_admite_x(self.duracion, self.tamano, False)
            if motivo:
                return False, "", motivo, COLOR_AVISO
            if longitud_x(self.campo_x.toPlainText().strip()) > MAX_TEXTO_X:
                bloqueo = _("Texto para X de más de {maximo} caracteres: acórtalo (o marca "
                            "Premium en Redes…)").format(maximo=MAX_TEXTO_X)
        if plataforma == Plataforma.FACEBOOK and self.ajustes.pagina_facebook is None:
            bloqueo = _("Falta la página de Facebook: elígela en Redes…")
        texto, color = (consulta_cuentas.describir(plataforma, cuenta, servicio)
                        if cuenta is not None else ("", ""))
        return True, bloqueo, texto, color

    def _refrescar_plataformas(self) -> list[str]:
        """Aplica el estado de cada fila. Devuelve los motivos que impiden
        publicar lo marcado."""
        if self.publicando:
            return []
        bloqueos: list[str] = []
        self._aplicando = True
        try:
            for plataforma in ORDEN:
                casilla = self.casillas[plataforma]
                habilitada, bloqueo, texto, color = self._estado_plataforma(plataforma)
                casilla.setEnabled(habilitada)
                marcada = habilitada and plataforma in self._deseadas
                if casilla.isChecked() != marcada:
                    casilla.setChecked(marcada)
                if marcada and bloqueo:
                    bloqueos.append(bloqueo)
                    texto, color = bloqueo, COLOR_AVISO
                if plataforma in self._con_resultado:
                    continue
                etiqueta = self.estados[plataforma]
                etiqueta.setText(html.escape(texto))
                etiqueta.setToolTip(texto if len(texto) > 40 else "")
                etiqueta.setStyleSheet(f"color: {color};" if color else "")
        finally:
            self._aplicando = False
        return bloqueos

    def _listo(self) -> tuple[bool, str]:
        nombre = self.ajustes.proveedor_redes
        if not self._hay_clave:
            return False, _("Falta la API key del servicio: guárdala en Redes…")
        if proveedores.usa_perfil(nombre) and not self.ajustes.perfil_redes:
            return False, _("Falta el perfil del servicio: escríbelo en Redes…")
        return True, ""

    def refrescar_servicio(self) -> None:
        """Vuelve a leer ajustes y Llavero (tras cerrar el diálogo Redes…) y
        vuelve a consultar las cuentas conectadas."""
        nombre = self.ajustes.proveedor_redes
        self._hay_clave = self.llavero.hay_clave(nombre)
        guardadas = self.ajustes.cuentas_guardadas()
        self._cuentas = dict(guardadas.cuentas) if guardadas else {}
        self._cuentas_en_vivo = False
        self._fecha_cuentas = guardadas.fecha if guardadas else ""
        self._error_cuentas = ""
        self._refrescar_etiqueta_servicio()
        self._consultar_cuentas()
        self._refrescar()

    def _refrescar_etiqueta_servicio(self) -> None:
        nombre = self.ajustes.proveedor_redes
        listo, motivo = self._listo()
        if listo:
            perfil = self.ajustes.perfil_redes
            texto = _("Vía {servicio}").format(servicio=proveedores.nombre_visible(nombre))
            if perfil:
                texto += " · " + _("perfil «{perfil}»").format(perfil=perfil)
            if proveedores.usa_perfil(nombre) and proveedores.parece_email(perfil):
                texto += " · " + _("⚠ el perfil parece un email: revísalo en Redes…")
                self.etiqueta_servicio.setStyleSheet(f"color: {COLOR_AVISO};")
            else:
                self.etiqueta_servicio.setStyleSheet("")
            if self._error_cuentas:
                texto += " · " + (_("No se pudieron comprobar las cuentas; se usa lo último "
                                    "que se supo.") if self._cuentas
                                  else _("No se pudieron comprobar las cuentas."))
            self.etiqueta_servicio.setText(texto)
            self.etiqueta_servicio.setToolTip(self._error_cuentas)
        else:
            self.etiqueta_servicio.setText(motivo)
            self.etiqueta_servicio.setToolTip("")
            self.etiqueta_servicio.setStyleSheet(f"color: {COLOR_AVISO};")

    def _refrescar(self, *args) -> None:
        largo = len(self.campo_titulo.text().strip())
        self.contador_titulo.setText(f"{largo}/{MAX_TITULO_YOUTUBE}")
        self.contador_titulo.setStyleSheet(
            f"color: {COLOR_AVISO};" if largo > MAX_TITULO_YOUTUBE else "")
        largo_x = longitud_x(self.campo_x.toPlainText().strip())
        self.contador_x.setText(f"{largo_x}/{MAX_TEXTO_X}")
        self.contador_x.setStyleSheet(
            f"color: {COLOR_AVISO};" if largo_x > MAX_TEXTO_X and not self.ajustes.x_premium
            else "")
        bloqueos = self._refrescar_plataformas()
        listo, _motivo = self._listo()
        self.boton_publicar.setEnabled(
            listo and not self.publicando and bool(self.plataformas())
            and bool(self.campo_titulo.text().strip()) and not bloqueos)

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
            if entrada.sin_confirmar:
                nombre = _("{plataforma} (sin confirmar)").format(plataforma=nombre)
            elif ((plataforma == Plataforma.TIKTOK and entrada.modo == ModoTikTok.BORRADOR.value)
                  or (plataforma == Plataforma.FACEBOOK
                      and entrada.modo == ModoFacebook.BORRADOR.value)):
                nombre = _("{plataforma} (borrador)").format(plataforma=nombre)
            partes.append(f"{nombre} {fecha}")
        self.aviso_publicado.setText(
            _("⚠ Este vídeo ya se publicó: {lista}. Si vuelves a publicarlo, "
              "saldrá repetido.").format(lista=", ".join(partes)))
        self.aviso_publicado.show()

    # --- publicar ---

    def _resumen(self) -> str:
        opciones = self.opciones()
        return "\n".join(f"• {p.nombre}: {self._modo_visible(p, opciones)}"
                         for p in self.plataformas())

    def _confirmar(self) -> bool:
        elegidas = set(self.plataformas())
        ultimas = {p: e for p, e in registro.ultimas(self.video).items() if p in elegidas}
        confirmadas = [p.nombre for p in ORDEN if p in ultimas and not ultimas[p].sin_confirmar]
        dudosas = [p.nombre for p in ORDEN if p in ultimas and ultimas[p].sin_confirmar]
        texto = _("Se publicará «{titulo}» en:\n\n{resumen}").format(
            titulo=self.campo_titulo.text().strip(), resumen=self._resumen())
        if confirmadas:
            texto += "\n\n" + _("Ya publicado antes en: {lista}.").format(
                lista=", ".join(confirmadas))
        if dudosas:
            texto += "\n\n" + _(
                "⚠ Sin confirmar en: {lista}. El último intento pudo publicarse igualmente: "
                "compruébalo en la app antes de publicar otra vez.").format(
                lista=", ".join(dudosas))
        texto += "\n\n" + _("¿Publicar ahora?")
        respuesta = QMessageBox.question(
            self, _("Publicar en redes"), texto,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return respuesta == QMessageBox.StandardButton.Yes

    def publicar(self) -> None:
        if self.publicando:
            return
        if not self.boton_publicar.isEnabled():
            _listo, motivo = self._listo()
            self._poner_estado(motivo or _(
                "Marca al menos una plataforma y escribe un título."), COLOR_AVISO)
            return
        nombre = self.ajustes.proveedor_redes
        plataformas = self.plataformas()
        opciones = self.opciones()
        self._preparar(plataformas, opciones)
        self._registrar_inicio(nombre, plataformas, opciones)
        self._poner_estado(_("Esperando confirmación…"))
        if not self._confirmar():
            log.info("Cancelado por el usuario en la confirmación: no se envía nada.")
            self._terminar_sin_enviar(_("Publicación cancelada: no se ha enviado nada."),
                                      COLOR_AVISO, marcar=False)
            return
        log.info("Confirmado por el usuario.")
        self._poner_estado(_("Leyendo la API key del Llavero…"))
        self.etiqueta_estado.repaint()
        try:
            clave = self.llavero.leer(nombre)
        except credenciales.ErrorLlavero as e:
            self._terminar_sin_enviar(_("No se pudo leer la API key del Llavero: {motivo}").format(
                motivo=str(e)))
            return
        except Exception as e:
            log.exception("Llavero: excepción inesperada al leer la clave")
            self._terminar_sin_enviar(_("No se pudo leer la API key del Llavero ({tipo}).").format(
                tipo=type(e).__name__))
            return
        if not clave:
            log.warning("Llavero: la entrada existe pero la lectura no devolvió ninguna clave.")
            self.refrescar_servicio()
            self._terminar_sin_enviar(_(
                "No se encontró la API key en el Llavero. Vuelve a guardarla en Redes…"))
            return
        if self._diario is not None:
            self._diario.ocultar(clave)
        log.info("Llavero: clave leída.")
        try:
            proveedor = self.fabrica(nombre, clave, self.ajustes.ajustes_proveedor())
        except Exception as e:
            log.exception("No se pudo crear el proveedor")
            self._terminar_sin_enviar(_(
                "No se pudo preparar el servicio ({tipo}). Detalles en el registro.").format(
                tipo=type(e).__name__))
            return
        finally:
            del clave
        # Lo que el usuario quiere marcado, también lo que hoy no se puede
        # (p. ej. X con un vídeo largo): la próxima vez vuelve a estar.
        self.ajustes.plataformas_redes = [p for p in ORDEN if p in self._deseadas]
        self.ajustes.tiktok_modo = opciones.tiktok_modo
        self.ajustes.instagram_modo = opciones.instagram_modo
        self.ajustes.facebook_modo = opciones.facebook_modo
        self._hilo = HiloPublicacion(proveedor, self.publicacion(), opciones,
                                     plataformas, nombre, self._diario)
        self._hilo.progreso.connect(self._al_progresar)
        self._hilo.terminado.connect(self._al_terminar)
        self._bloquear(True)
        self._poner_estado(_("Publicando: {lista}…").format(
            lista=", ".join(p.nombre for p in plataformas)))
        log.info("Hilo de publicación en marcha.")
        self._hilo.start()

    # --- estado y registro ---

    def _preparar(self, plataformas: list[Plataforma], opciones: Opciones) -> None:
        """Deja el diálogo listo para un intento nuevo y abre su registro."""
        self._cerrar_diario()
        self._en_curso = list(plataformas)
        self._opciones_en_curso = opciones
        self._procesando = set()
        self.resumen.clear()
        self.resumen.hide()
        self._con_resultado = set(plataformas)
        for plataforma in plataformas:
            etiqueta = self.estados[plataforma]
            etiqueta.setText(_("En cola"))
            etiqueta.setToolTip("")
            etiqueta.setStyleSheet("")
        self._refrescar()  # las demás filas vuelven a mostrar su cuenta
        self._diario = diario.Diario(self.video)
        self.ruta_log = self._diario.ruta
        self.boton_registro.setVisible(self.ruta_log is not None)
        self.boton_registro.setEnabled(self.ruta_log is not None)

    def _registrar_inicio(self, nombre: str, plataformas: list[Plataforma],
                          opciones: Opciones) -> None:
        log.info("Inicio de la publicación · %s · Python %s",
                 plataforma_sistema.platform(), plataforma_sistema.python_version())
        try:
            tamano = f"{self.video.stat().st_size} bytes"
        except OSError as e:
            tamano = f"no se puede leer: {type(e).__name__}"
        log.info("Vídeo: %s (%s)", self.video, tamano)
        log.info("Proveedor: %s (%s) · API key en el Llavero: %s · perfil: %s",
                 proveedores.nombre_visible(nombre), nombre,
                 "sí" if self._hay_clave else "no",
                 "sí" if self.ajustes.perfil_redes else "no")
        log.info("Plataformas y modos: %s", ", ".join(
            f"{p.nombre} [{publicador.modo_de(p, opciones)}: {self._modo_visible(p, opciones)}]"
            for p in plataformas))
        publicacion = self.publicacion()
        log.info("Título: %r · caption: %d caracteres · hashtags: %s",
                 publicacion.titulo, len(publicacion.caption), " ".join(publicacion.hashtags))
        if Plataforma.X in plataformas:
            log.info("Texto de X: %d caracteres según X · Premium: %s · vídeo: %s, %s bytes",
                     longitud_x(publicacion.texto_x), "sí" if opciones.x_premium else "no",
                     limites.duracion_legible(self.duracion) if self.duracion else "duración ?",
                     self.tamano if self.tamano is not None else "?")
        if Plataforma.FACEBOOK in plataformas:
            log.info("Página de Facebook: %s", "sí" if self.ajustes.pagina_facebook else "no")
        if self._cuentas_en_vivo:
            log.info("Cuentas (comprobadas a las %s): %s", self._fecha_cuentas,
                     consulta_cuentas.resumen(self._cuentas))
        elif self._cuentas:
            log.info("Cuentas (guardadas del %s; consulta en vivo: %s): %s", self._fecha_cuentas,
                     self._error_cuentas or "sin respuesta aún",
                     consulta_cuentas.resumen(self._cuentas))
        else:
            log.info("Cuentas: sin comprobar (%s)", self._error_cuentas or "sin respuesta aún")

    def _poner_estado(self, texto: str, color: str = "") -> None:
        self.etiqueta_estado.setText(texto)
        self.etiqueta_estado.setStyleSheet(f"color: {color};" if color else "")
        self.etiqueta_estado.setVisible(bool(texto))

    def _terminar_sin_enviar(self, texto: str, color: str = COLOR_ERROR,
                             marcar: bool = True) -> None:
        """Final de un intento que no llegó a enviar nada: siempre se ve."""
        log.warning("Sin enviar: %s", texto)
        if not marcar:  # esas filas vuelven a mostrar su cuenta
            self._con_resultado -= set(self._en_curso)
        for plataforma in ORDEN:
            etiqueta = self.estados[plataforma]
            if marcar and plataforma in self._en_curso:
                etiqueta.setText(html.escape("✗ " + _("No enviado")))
                etiqueta.setToolTip(texto)
                etiqueta.setStyleSheet(f"color: {COLOR_ERROR};")
            else:
                etiqueta.setText("")
        self._poner_estado(texto, color)
        log.info("Fin: no se ha enviado nada.")
        self._cerrar_diario()
        self._refrescar()

    def _cerrar_diario(self) -> None:
        if self._diario is not None:
            self._diario.cerrar()
            self._diario = None

    def _ver_registro(self) -> None:
        if self.ruta_log is not None:
            revelar_en_finder(self.ruta_log)

    def _modo_visible(self, plataforma: Plataforma, opciones: Opciones) -> str:
        if plataforma == Plataforma.TIKTOK:
            return _(ETIQUETAS_TIKTOK[opciones.tiktok_modo])
        if plataforma == Plataforma.INSTAGRAM:
            return _(ETIQUETAS_INSTAGRAM[opciones.instagram_modo])
        if plataforma == Plataforma.FACEBOOK:
            return _(ETIQUETAS_FACEBOOK[opciones.facebook_modo])
        if plataforma == Plataforma.X:
            return _("Post público")
        return _("Short público")

    def _bloquear(self, bloqueado: bool) -> None:
        for widget in (self.campo_titulo, self.campo_caption, self.campo_hashtags,
                       self.campo_x, self.combo_tiktok, self.combo_instagram,
                       self.combo_facebook, self.boton_redes, self.boton_cerrar,
                       *self.casillas.values()):
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
            numero = self._en_curso.index(plataforma) + 1 if plataforma in self._en_curso else 0
            self._poner_estado(_("Subiendo a {plataforma} ({n} de {total})…").format(
                plataforma=plataforma.nombre, n=numero, total=len(self._en_curso)))
        elif estado == Estado.PROCESANDO:
            etiqueta.setText(_("Procesando en el servicio…"))
            etiqueta.setStyleSheet("")
            self._procesando.add(plataforma)
        else:
            self._procesando.discard(plataforma)
            self._mostrar_resultado(plataforma, resultado)
        # Todo enviado y alguna sigue en el servicio: se dice qué se espera.
        en_marcha = (_("En cola"), _("Subiendo…"))
        if self._procesando and not any(
                self.estados[p].text() in en_marcha for p in self._en_curso):
            self._poner_estado(_("Esperando a que el servicio termine: {lista}…").format(
                lista=", ".join(p.nombre for p in ORDEN if p in self._procesando)))

    def _texto_resultado(self, plataforma: Plataforma, resultado: Resultado) -> tuple[str, str]:
        """HTML (escapado) y color con que se muestra un resultado."""
        if resultado.ok:
            if resultado.url:
                texto = _('✓ Publicado · <a href="{url}">Abrir</a>').format(
                    url=html.escape(resultado.url, quote=True))
            elif (plataforma == Plataforma.TIKTOK
                  and self._opciones_en_curso.tiktok_modo == ModoTikTok.BORRADOR):
                texto = html.escape(_("✓ En borradores: termínalo en la app de TikTok"))
            elif (plataforma == Plataforma.FACEBOOK
                  and self._opciones_en_curso.facebook_modo == ModoFacebook.BORRADOR):
                texto = html.escape(_("✓ En borradores: termínalo en Facebook"))
            else:
                texto = html.escape(_("✓ Publicado"))
            return texto, COLOR_OK
        if resultado.pendiente:
            return html.escape("⏳ " + (resultado.error or _("Sigue procesándose"))), COLOR_AVISO
        return html.escape("✗ " + (resultado.error or _("Error"))), COLOR_ERROR

    def _mostrar_resultado(self, plataforma: Plataforma, resultado: Resultado,
                           corto: bool = False) -> None:
        """`corto`: al final, el motivo completo va en el resumen de abajo y
        aquí queda solo la marca (el motivo sigue en el tooltip)."""
        etiqueta = self.estados[plataforma]
        texto, color = self._texto_resultado(plataforma, resultado)
        if corto and not resultado.ok:
            texto = html.escape("⏳ " + _("Por confirmar") if resultado.pendiente
                                else "✗ " + _("Error: ver el resumen"))
        etiqueta.setText(texto)
        etiqueta.setToolTip(resultado.error)
        etiqueta.setStyleSheet(f"color: {color};")

    def _texto_final(self) -> tuple[str, str]:
        total = len(self.resultados)
        ok = sum(1 for r in self.resultados.values() if r.ok)
        pendientes = sum(1 for r in self.resultados.values() if not r.ok and r.pendiente)
        if ok == 0 and pendientes == 0:
            return _("Falló en todas"), COLOR_ERROR
        texto = _("Publicado en {ok} de {total}").format(ok=ok, total=total)
        if pendientes:
            texto += " · " + _("{n} por confirmar").format(n=pendientes)
        return texto, (COLOR_OK if ok == total else COLOR_AVISO)

    def _al_terminar(self, resultados: dict) -> None:
        self._hilo = None  # lo suelta `_soltar` cuando acaba del todo
        try:
            self.resultados = {
                p: resultados.get(p) or Resultado(p, ok=False, error=_("No se llegó a enviar."))
                for p in self._en_curso}
            lineas = []
            for plataforma, resultado in self.resultados.items():
                self._mostrar_resultado(plataforma, resultado, corto=True)
                texto, color = self._texto_resultado(plataforma, resultado)
                lineas.append(f'<b>{html.escape(plataforma.nombre)}</b>: '
                              f'<span style="color: {color};">{texto}</span>')
                # Lo que salió, o pudo salir, no se vuelve a marcar: evita duplicados.
                if resultado.ok or resultado.pendiente:
                    self._deseadas.discard(plataforma)
                    self._aplicando = True
                    try:
                        self.casillas[plataforma].setChecked(False)
                    finally:
                        self._aplicando = False
            self.resumen.setText("<br>".join(lineas))
            self.resumen.show()
            texto, color = self._texto_final()
            self._poner_estado(texto, color)
            log.info("Resumen: %s", texto)
            for plataforma, resultado in self.resultados.items():
                log.info("  %s: %s", plataforma.nombre, "OK " + (resultado.url or "")
                         if resultado.ok else ("pendiente: " if resultado.pendiente
                                               else "error: ") + resultado.error)
        except Exception as e:
            log.exception("Fallo al mostrar el resultado")
            self._poner_estado(_("Terminó, pero no se pudo mostrar el resultado ({tipo}). "
                                 "Mira el registro.").format(tipo=type(e).__name__), COLOR_ERROR)
        finally:
            log.info("Fin")
            self._cerrar_diario()
            self._bloquear(False)
            self._refrescar_aviso()
        self.publicacion_terminada.emit(self.resultados)

    # --- cierre ---

    def reject(self) -> None:
        if self.publicando:
            return  # la subida sigue: no se abandona a medias
        super().reject()

    def done(self, resultado: int) -> None:
        if self.publicando:
            return  # tampoco por accept() ni por otra vía
        super().done(resultado)

    def closeEvent(self, evento) -> None:
        if self.publicando:
            evento.ignore()
            return
        super().closeEvent(evento)
