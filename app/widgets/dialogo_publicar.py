from __future__ import annotations

import html
import logging
import platform as plataforma_sistema
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from PySide6.QtCore import QDateTime, QProcess, Qt, QThread, QTimeZone, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
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
    QRadioButton,
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from videopipeline import linkedin
from videopipeline.caption import Caption
from videopipeline.i18n import _
from videopipeline.redes import proveedor as proveedores
from videopipeline.redes import diario, limites, portada_video, publicador, registro
from videopipeline.redes.modelo import (
    ETIQUETAS_FACEBOOK,
    ETIQUETAS_INSTAGRAM,
    ETIQUETAS_TIKTOK,
    ORDEN,
    PRIVACIDADES_TIKTOK,
    AjustesTikTok,
    Cuenta,
    ModoFacebook,
    ModoInstagram,
    ModoTikTok,
    Opciones,
    Plataforma,
    Publicacion,
    Resultado,
    Ubicacion,
)
from videopipeline.redes.publicador import Estado
from videopipeline.redes.textos import (
    MAX_TEXTO,
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
from .selector_perfil import SelectorPerfil
from .selector_ubicacion import DialogoUbicacion, describir_ubicacion, ubicacion_guardada
from .tira_imagenes import TiraImagenes

# Duración del vídeo (ffprobe). Se llama fuera del hilo de la interfaz; los
# tests la sustituyen.
medir_duracion = duracion_video

# Lo antes y lo más tarde que se puede programar: subir a cada red lleva su
# tiempo, y el servicio rechaza una fecha pasada o a más de un año.
MARGEN_MINIMO = timedelta(minutes=15)
MAXIMO = timedelta(days=365)

# Lo que se acepta al publicar en TikTok en directo.
URL_MUSICA_TIKTOK = "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en"
URL_MARCA_TIKTOK = "https://www.tiktok.com/legal/page/global/bc-policy/en"


def zona_local() -> tzinfo:
    """Zona horaria del Mac, con su nombre IANA si se puede (el servicio lo
    necesita para interpretar la hora); si no, su desfase actual."""
    try:
        return ZoneInfo(bytes(QTimeZone.systemTimeZoneId()).decode())
    except Exception:
        return datetime.now().astimezone().tzinfo


def fecha_local(texto_o_fecha, zona: tzinfo, formato: str) -> str:
    """Fecha (ISO o datetime) en la hora del Mac; el texto tal cual si no se entiende."""
    try:
        fecha = (texto_o_fecha if isinstance(texto_o_fecha, datetime)
                 else datetime.fromisoformat(texto_o_fecha))
    except (TypeError, ValueError):
        return str(texto_o_fecha)
    if fecha.tzinfo is not None:
        fecha = fecha.astimezone(zona)
    return fecha.strftime(formato)


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
                 diario_publicacion: diario.Diario | None = None,
                 ahora: Callable[[], datetime] | None = None):
        super().__init__()  # sin padre: ver `_HILOS_VIVOS`
        self._ahora = ahora
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
            with tempfile.TemporaryDirectory() as tmp:  # el envío lee la miniatura
                if set(self._plataformas) & {Plataforma.TIKTOK, Plataforma.INSTAGRAM,
                                             Plataforma.YOUTUBE}:
                    self._publicacion = portada_video.con_portada(self._publicacion, Path(tmp))
                resultados = publicador.publicar(
                    self._proveedor, self._publicacion, self._opciones, self._plataformas,
                    progreso=avisar,
                    nombre_proveedor=self._nombre_proveedor,
                    cancelado=self.isInterruptionRequested,
                    **({"ahora": self._ahora} if self._ahora else {}),
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
                 medir: Callable[[Path], float] | None = None,
                 ahora: Callable[[], datetime] | None = None, zona: tzinfo | None = None, perfil: str = "",
                 idioma: str = "", parent=None):
        super().__init__(parent)
        self.video = Path(video)
        self._zona = zona or zona_local()
        self._ahora = ahora or (lambda: datetime.now(self._zona))
        self.ajustes = ajustes
        # El perfil con el que se procesó el vídeo, si aún existe; si no, el activo.
        if perfil != ajustes.perfil_redes and perfil in ajustes.perfiles_de(
                ajustes.proveedor_redes):
            ajustes.perfil_redes = perfil
        self._perfil_leido = ajustes.perfil_redes  # del que se leyeron plataformas y modos
        self.perfil_usado = ""  # el de la publicación enviada
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
        # Lo que la cuenta de TikTok permite en directo (`None` mientras se
        # consulta), el motivo si no se pudo saber y de qué (servicio, perfil)
        # se pidió (`None`: hay que pedirlo).
        self._ajustes_tiktok: AjustesTikTok | None = None
        self._error_ajustes_tiktok = ""
        self._ajustes_tiktok_de: tuple[str, str] | None = None
        self._ajustes_tiktok_n = 0
        # Vídeo de la vista previa de la portada.
        self._portada_de: Path | None = None
        self._portada_n = 0
        self._idioma = idioma
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
        # La de Redes… (aquí solo la ciudad: el lugar de TikTok, del Llavero,
        # se lee al pulsar Cambiar… o Publicar) y la cambiada solo para este
        # vídeo (`None`: la de Redes…).
        self._ubicacion_global = Ubicacion()
        self._ubicacion_propia: Ubicacion | None = None
        self._procesando: set[Plataforma] = set()
        self.resultados: dict[Plataforma, Resultado] = {}
        self.setWindowTitle(_("Publicar en redes"))
        self.setMinimumWidth(640)

        exterior = QVBoxLayout(self)
        # Todo menos los botones va en una zona con scroll: en un portátil el
        # formulario entero no cabe en el alto útil de la pantalla.
        self.contenido = QWidget()
        raiz = QVBoxLayout(self.contenido)
        raiz.setContentsMargins(0, 0, 0, 0)
        nombre = self.video.name
        if nombre.endswith(".editado.mp4"):
            nombre = f"{nombre} {_('(editado)')}"
        cabecera = QLabel(nombre)
        cabecera.setStyleSheet("font-weight: bold;")
        raiz.addWidget(cabecera)
        self.cabecera = cabecera
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
        self._post_x = caption.post_x
        self.campo_x = QPlainTextEdit()
        self.campo_x.setFixedHeight(96)
        self.campo_x.setToolTip(_(
            "El post de X. Sin Premium admite {maximo} caracteres: una URL cuenta 23 y un "
            "emoji, 2. Mientras no lo cambies, se rellena con el post que propuso el "
            "modelo (o el título) y los hashtags que caben.").format(maximo=MAX_TEXTO_X))
        self.contador_x = QLabel()
        fila_x = QHBoxLayout()
        fila_x.addWidget(self.campo_x, 1)
        fila_x.addWidget(self.contador_x, 0, Qt.AlignmentFlag.AlignTop)
        formulario.addRow(_("Texto para X:"), fila_x)
        # LinkedIn: el post y sus fotos, junto al vídeo. Lo editado se publica,
        # pero no se guarda en el .md.
        self._linkedin = linkedin.leer(self.video)
        texto_linkedin, fotos_linkedin = self._linkedin or ("", [])
        self.campo_linkedin = QPlainTextEdit(texto_linkedin.strip())
        self.campo_linkedin.setFixedHeight(120)
        self.contador_linkedin = QLabel()
        fila_linkedin = QHBoxLayout()
        fila_linkedin.addWidget(self.campo_linkedin, 1)
        fila_linkedin.addWidget(self.contador_linkedin, 0, Qt.AlignmentFlag.AlignTop)
        formulario.addRow(_("Texto para LinkedIn:"), fila_linkedin)
        self.tira_linkedin = TiraImagenes(fotos_linkedin,
                                          linkedin.rutas(self.video)[1] / "candidatos")
        formulario.addRow(_("Fotos para LinkedIn:"), self.tira_linkedin)
        if self._linkedin is None:
            formulario.setRowVisible(fila_linkedin, False)
            formulario.setRowVisible(self.tira_linkedin, False)
        # X: un vídeo que X no admite va como post con fotos, empezando por
        # las primeras de LinkedIn. La fila solo se ve entonces (`_refrescar`).
        self.tira_x = TiraImagenes(fotos_linkedin[:limites.MAX_FOTOS_X],
                                   linkedin.rutas(self.video)[1] / "candidatos")
        formulario.addRow(_("Fotos para X:"), self.tira_x)
        formulario.setRowVisible(self.tira_x, False)
        self._formulario = formulario
        raiz.addWidget(grupo_textos)
        self.grupo_textos = grupo_textos

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
        self.modos = {
            Plataforma.TIKTOK: self.combo_tiktok,
            Plataforma.YOUTUBE: QLabel(_("Short público")),
            Plataforma.INSTAGRAM: self.combo_instagram,
            Plataforma.X: QLabel(_("Post público")),
            Plataforma.FACEBOOK: self.combo_facebook,
            Plataforma.LINKEDIN: QLabel(_("Post con fotos")),
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
            rejilla.addWidget(self.modos[plataforma], fila, 1)
            rejilla.addWidget(estado, fila, 2)
        raiz.addWidget(grupo_plataformas)

        # TikTok en directo: lo que TikTok exige mostrar antes de publicar.
        # Nada de esto se recuerda entre publicaciones.
        self.grupo_tiktok = QGroupBox(Plataforma.TIKTOK.nombre)
        caja_tiktok = QVBoxLayout(self.grupo_tiktok)
        self.etiqueta_cuenta_tiktok = QLabel()
        self.etiqueta_cuenta_tiktok.setTextFormat(Qt.TextFormat.PlainText)
        caja_tiktok.addWidget(self.etiqueta_cuenta_tiktok)
        self.combo_privacidad_tiktok = QComboBox()
        self._poner_privacidades(())
        caja_tiktok.addWidget(self.combo_privacidad_tiktok, 0, Qt.AlignmentFlag.AlignLeft)
        fila_interacciones = QHBoxLayout()
        self.casilla_comentarios_tiktok = QCheckBox(_("Permitir comentarios"))
        self.casilla_duos_tiktok = QCheckBox(_("Permitir dúos"))
        self.casilla_stitch_tiktok = QCheckBox(_("Permitir stitch"))
        for casilla in (self.casilla_comentarios_tiktok, self.casilla_duos_tiktok,
                        self.casilla_stitch_tiktok):
            fila_interacciones.addWidget(casilla)
        fila_interacciones.addStretch(1)
        caja_tiktok.addLayout(fila_interacciones)
        self.etiqueta_consentimiento_tiktok = QLabel()
        self.etiqueta_consentimiento_tiktok.setWordWrap(True)
        self.etiqueta_consentimiento_tiktok.setOpenExternalLinks(True)
        caja_tiktok.addWidget(self.etiqueta_consentimiento_tiktok)
        self.grupo_tiktok.hide()

        # Contenido comercial, para todas las redes.
        self.bloque_comercial = QWidget()
        caja_comercial = QVBoxLayout(self.bloque_comercial)
        caja_comercial.setContentsMargins(0, 0, 0, 0)
        self.casilla_comercial = QCheckBox(_("Contenido comercial"))
        self.casilla_tu_marca = QCheckBox(_("Tu marca: promocionas algo tuyo"))
        self.casilla_de_marca = QCheckBox(_("Contenido de marca: una marca te paga o te da algo"))
        fila_comercial = QHBoxLayout()
        fila_comercial.addSpacing(20)
        for casilla in (self.casilla_tu_marca, self.casilla_de_marca):
            casilla.setEnabled(False)
            fila_comercial.addWidget(casilla)
        fila_comercial.addStretch(1)
        self.etiqueta_comercial = QLabel()
        self.etiqueta_comercial.setWordWrap(True)
        self.etiqueta_comercial.hide()
        caja_comercial.addWidget(self.casilla_comercial)
        caja_comercial.addLayout(fila_comercial)
        caja_comercial.addWidget(self.etiqueta_comercial)

        self.vista_portada = QLabel()
        self.vista_portada.setFixedSize(90, 160)
        self.vista_portada.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vista_portada.setToolTip(_("Portada del vídeo"))
        self.vista_portada.hide()
        fila_cumplimiento = QHBoxLayout()
        columna = QVBoxLayout()
        columna.addWidget(self.grupo_tiktok)
        columna.addWidget(self.bloque_comercial)
        columna.addStretch(1)
        fila_cumplimiento.addLayout(columna, 1)
        fila_cumplimiento.addWidget(self.vista_portada, 0, Qt.AlignmentFlag.AlignTop)
        raiz.addLayout(fila_cumplimiento)

        fila_ubicacion = QHBoxLayout()
        fila_ubicacion.addWidget(QLabel(_("Ubicación:")))
        self.etiqueta_ubicacion = QLabel()
        self.etiqueta_ubicacion.setWordWrap(True)
        fila_ubicacion.addWidget(self.etiqueta_ubicacion, 1)
        self.boton_ubicacion = QPushButton(_("Cambiar…"))
        self.boton_ubicacion.setToolTip(_("Cambia la ubicación solo para este vídeo"))
        self.boton_ubicacion.clicked.connect(self._cambiar_ubicacion)
        fila_ubicacion.addWidget(self.boton_ubicacion)
        raiz.addLayout(fila_ubicacion)

        fila_cuando = QHBoxLayout()
        self.etiqueta_cuando = QLabel(_("Cuándo:"))
        fila_cuando.addWidget(self.etiqueta_cuando)
        self.radio_ahora = QRadioButton(_("Ahora"))
        self.radio_programar = QRadioButton(_("Programar"))
        self.radio_programar.setToolTip(_(
            "El servicio guarda el vídeo y lo publica a esa hora: puedes cerrar la app."))
        grupo_cuando = QButtonGroup(self)
        grupo_cuando.addButton(self.radio_ahora)
        grupo_cuando.addButton(self.radio_programar)
        self.radio_ahora.setChecked(True)
        # La siguiente hora en punto a más de una hora vista.
        self._fecha_inicial = (self._ahora() + timedelta(hours=2)).replace(
            minute=0, second=0, microsecond=0)
        self.campo_fecha = self._nuevo_campo_fecha(self._fecha_inicial)
        self.campo_fecha.setEnabled(False)
        self.aviso_fecha = QLabel()
        self.aviso_fecha.setStyleSheet(f"color: {COLOR_AVISO};")
        self.aviso_fecha.hide()
        for widget in (self.radio_ahora, self.radio_programar, self.campo_fecha):
            fila_cuando.addWidget(widget)
        fila_cuando.addWidget(self.aviso_fecha)
        fila_cuando.addStretch(1)
        raiz.addLayout(fila_cuando)

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
        self.selector_perfil = SelectorPerfil()
        self.selector_perfil.perfil_elegido.connect(self._al_elegir_perfil)
        fila_servicio.addWidget(self.etiqueta_servicio, 1)
        fila_servicio.addWidget(QLabel(_("Perfil:")))
        fila_servicio.addWidget(self.selector_perfil)
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
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QScrollArea.Shape.NoFrame)
        desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        desplazable.setWidget(self.contenido)
        exterior.addWidget(desplazable, 1)
        exterior.addLayout(botones)
        self._botones = botones

        self.campo_titulo.textChanged.connect(self._al_cambiar_textos)
        self.campo_hashtags.textChanged.connect(self._al_cambiar_textos)
        self.campo_x.textChanged.connect(self._al_editar_x)
        self.campo_linkedin.textChanged.connect(self._refrescar)
        self.tira_linkedin.cambiada.connect(self._refrescar)
        self.tira_x.cambiada.connect(self._refrescar)
        self.radio_programar.toggled.connect(self._refrescar)
        self.campo_fecha.dateTimeChanged.connect(self._refrescar)
        self.combo_tiktok.currentIndexChanged.connect(self._refrescar)
        self.combo_privacidad_tiktok.currentIndexChanged.connect(self._refrescar)
        self.casilla_comercial.toggled.connect(self._al_cambiar_comercial)
        self.casilla_de_marca.toggled.connect(self._al_cambiar_comercial)
        self.casilla_tu_marca.toggled.connect(self._refrescar)
        self._rellenar_x()
        self.refrescar_servicio()
        self._refrescar_aviso()
        self._medir_video()
        self._calcular_portada(self.video)
        self.ajustar_a_la_pantalla()

    def ajustar_a_la_pantalla(self) -> None:
        """Todo el contenido si cabe; si no, el alto de la pantalla (y scroll),
        como en Redes…."""
        margenes = self.layout().contentsMargins()
        barra = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        ideal = self.contenido.sizeHint()
        alto = (ideal.height() + self._botones.sizeHint().height() + self.layout().spacing()
                + margenes.top() + margenes.bottom())
        # Margen para la barra de título, que no cuenta en el alto del diálogo.
        alto_maximo = self.screen().availableGeometry().height() - 60
        self.resize(max(self.minimumWidth(), ideal.width() + barra + margenes.left()
                        + margenes.right()), min(alto, alto_maximo))

    # --- estado ---

    @property
    def publicando(self) -> bool:
        return self._hilo is not None

    def plataformas(self) -> list[Plataforma]:
        return [p for p in ORDEN if self.casillas[p].isChecked()]

    def opciones(self) -> Opciones:
        comercial = self.casilla_comercial.isChecked()
        return Opciones(
            tiktok_modo=ModoTikTok(self.combo_tiktok.currentData()),
            instagram_modo=ModoInstagram(self.combo_instagram.currentData()),
            youtube_categoria=self.ajustes.youtube_categoria,
            x_premium=self.ajustes.x_premium,
            facebook_modo=ModoFacebook(self.combo_facebook.currentData()),
            ubicacion=self.ubicacion(),
            programada=self.programada(),
            tiktok_privacidad=self.combo_privacidad_tiktok.currentData() or "",
            tiktok_comentarios=self.casilla_comentarios_tiktok.isChecked(),
            tiktok_duos=self.casilla_duos_tiktok.isChecked(),
            tiktok_stitch=self.casilla_stitch_tiktok.isChecked(),
            tu_marca=comercial and self.casilla_tu_marca.isChecked(),
            contenido_de_marca=comercial and self.casilla_de_marca.isChecked(),
            idioma=self._idioma,
        )

    def _tiktok_directo(self) -> bool:
        return self.combo_tiktok.currentData() == ModoTikTok.PUBLICO.value

    @staticmethod
    def _nuevo_campo_fecha(inicio: datetime) -> QDateTimeEdit:
        campo = QDateTimeEdit()
        campo.setCalendarPopup(True)
        campo.setDisplayFormat("dd/MM/yyyy HH:mm")
        campo.setDateTime(QDateTime(inicio.date(), inicio.time()))
        return campo

    def programada(self) -> datetime | None:
        """Fecha elegida, en la hora del Mac; `None` con «Ahora»."""
        if not self.radio_programar.isChecked():
            return None
        return self._fecha_de(self.campo_fecha)

    def _fecha_de(self, campo: QDateTimeEdit) -> datetime:
        """La fecha de un campo de fecha, en la hora del Mac."""
        elegida = campo.dateTime().toPython().replace(second=0, microsecond=0)
        if isinstance(self._zona, ZoneInfo):
            return elegida.replace(tzinfo=self._zona)
        # Zona sin nombre (desfase fijo): el desfase de esa fecha, no el de hoy.
        return elegida.astimezone()

    def _motivo_fecha(self) -> str:
        """Por qué no vale la fecha elegida, o "" si vale (o si es «Ahora»)."""
        return self._motivo_de(self.programada())

    def _motivo_de(self, programada: datetime | None) -> str:
        """Por qué no vale esa fecha, o "" si vale (o si es `None`, «Ahora»)."""
        if programada is None:
            return ""
        ahora = self._ahora()
        if programada < ahora + MARGEN_MINIMO:
            return _("Elige una hora al menos 15 minutos después de ahora.")
        if programada > ahora + MAXIMO:
            return _("Se puede programar como mucho a un año vista.")
        return ""

    def ubicacion(self) -> Ubicacion:
        if self._ubicacion_propia is not None:
            return self._ubicacion_propia
        return self._ubicacion_global

    def publicacion(self) -> Publicacion:
        return Publicacion(
            video=self.video,
            titulo=self.campo_titulo.text().strip(),
            caption=self.campo_caption.toPlainText().strip(),
            hashtags=tuple(self.campo_hashtags.text().split()),
            palabras_clave=self._palabras_clave,
            texto_x=self.campo_x.toPlainText().strip(),
            post_x=self._post_x,
            fotos=self.tira_linkedin.fotos(),
            texto_linkedin=self.campo_linkedin.toPlainText().strip(),
            fotos_x=self.tira_x.fotos() if self._x_con_fotos() else (),
        )

    # --- ubicación ---

    def _refrescar_ubicacion(self) -> None:
        texto = describir_ubicacion(self.ubicacion())
        if self._ubicacion_propia is not None:
            texto += " · " + _("solo este vídeo")
        self.etiqueta_ubicacion.setText(texto)

    def _preparar_busqueda(self, texto: str):
        nombre, datos = self.ajustes.proveedor_redes, self.ajustes.ajustes_proveedor()
        llavero, fabrica = self.llavero, self.fabrica
        return lambda: consulta_cuentas.buscar_lugares(llavero, fabrica, nombre, datos, texto)

    def _guardada(self) -> Ubicacion:
        return ubicacion_guardada(self.ajustes, self.llavero, self.ajustes.proveedor_redes,
                                  self.ajustes.perfil_redes)

    def _cambiar_ubicacion(self) -> None:
        guardada = self._guardada()
        dialogo = DialogoUbicacion(
            self._ubicacion_propia or guardada, self._preparar_busqueda,
            _("Ubicación de este vídeo"),
            _("Solo para este vídeo. La de siempre se cambia en Redes…."), self)
        dialogo.selector.poner_cuenta_tiktok(
            self._cuentas.get(Plataforma.TIKTOK),
            proveedores.nombre_visible(self.ajustes.proveedor_redes))
        if dialogo.exec():
            nueva = dialogo.ubicacion()
            self._ubicacion_propia = None if nueva == guardada else nueva
            self._refrescar_ubicacion()

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

    def _consultar_ajustes_tiktok(self) -> None:
        """Pide lo que la cuenta de TikTok permite en directo cuando TikTok
        queda marcado en modo directo, una vez por cuenta; tras un error, otra
        vez al volver a elegirlo."""
        if Plataforma.TIKTOK not in self._deseadas or not self._tiktok_directo():
            if self._error_ajustes_tiktok:
                self._ajustes_tiktok_de = None
            return
        cuenta = (self.ajustes.proveedor_redes, self.ajustes.perfil_redes)
        if cuenta == self._ajustes_tiktok_de or not self._listo()[0]:
            return
        self._ajustes_tiktok_de = cuenta
        self._ajustes_tiktok_n += 1
        self._ajustes_tiktok, self._error_ajustes_tiktok = None, ""
        self._poner_privacidades(())
        numero, llavero, fabrica = self._ajustes_tiktok_n, self.llavero, self.fabrica
        datos = self.ajustes.ajustes_proveedor()
        segundo_plano.en_segundo_plano(
            lambda: (numero, *consulta_cuentas.ajustes_tiktok(llavero, fabrica, cuenta[0], datos)),
            self._al_consultar_ajustes_tiktok, "tsots-tiktok")

    def _al_consultar_ajustes_tiktok(self, resultado) -> None:
        if isinstance(resultado, BaseException):  # `ajustes_tiktok` no lanza; por si acaso
            resultado = (self._ajustes_tiktok_n, None, type(resultado).__name__)
        numero, permisos, error = resultado
        if numero != self._ajustes_tiktok_n:
            return  # llegó tarde: ya hay otra consulta en marcha
        self._ajustes_tiktok, self._error_ajustes_tiktok = permisos, error
        if permisos is not None:
            self._poner_privacidades(permisos.privacidades)
            for casilla, apagada in ((self.casilla_comentarios_tiktok, permisos.comentarios_off),
                                     (self.casilla_duos_tiktok, permisos.duos_off),
                                     (self.casilla_stitch_tiktok, permisos.stitch_off)):
                if apagada:
                    casilla.setChecked(False)
                casilla.setEnabled(not apagada)
                casilla.setToolTip(_("Desactivado en tu cuenta de TikTok") if apagada else "")
        self._refrescar()

    def _poner_privacidades(self, privacidades: tuple[str, ...]) -> None:
        """Las privacidades de la cuenta, tras «Elige…»: no hay ninguna por defecto."""
        combo = self.combo_privacidad_tiktok
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_("Elige quién puede verlo…"), "")
        for valor in privacidades:
            combo.addItem(_(PRIVACIDADES_TIKTOK[valor]), valor)
        combo.blockSignals(False)
        self._limitar_privacidad()

    def _limitar_privacidad(self) -> None:
        """El contenido de marca no puede ser privado: sin «Solo yo»."""
        combo = self.combo_privacidad_tiktok
        indice = combo.findData("SELF_ONLY")
        if indice < 0:
            return
        de_marca = self.casilla_comercial.isChecked() and self.casilla_de_marca.isChecked()
        combo.model().item(indice).setEnabled(not de_marca)
        combo.setItemData(indice, _("El contenido de marca no puede ser privado")
                          if de_marca else "", Qt.ItemDataRole.ToolTipRole)
        if de_marca and combo.currentIndex() == indice:
            combo.setCurrentIndex(0)

    def _al_cambiar_comercial(self, *args) -> None:
        comercial = self.casilla_comercial.isChecked()
        self.casilla_tu_marca.setEnabled(comercial)
        self.casilla_de_marca.setEnabled(comercial)
        self._limitar_privacidad()
        self._refrescar()

    def _calcular_portada(self, video: Path) -> None:
        """Vista previa del fotograma de portada, elegido en segundo plano."""
        self._portada_de = video
        self._portada_n += 1
        numero = self._portada_n
        segundo_plano.en_segundo_plano(lambda: (numero, portada_video.elegir(video)),
                                       self._al_calcular_portada, "tsots-portada")

    def _al_calcular_portada(self, resultado) -> None:
        numero, elegido = resultado  # `elegir` no lanza
        if numero != self._portada_n:
            return
        if elegido is None:
            self.vista_portada.hide()
            return
        fotograma = elegido[1]
        alto, ancho = fotograma.shape[:2]
        imagen = QImage(fotograma.data, ancho, alto, fotograma.strides[0],
                        QImage.Format.Format_BGR888)  # OpenCV da BGR
        self.vista_portada.setPixmap(QPixmap.fromImage(imagen).scaled(
            self.vista_portada.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        self.vista_portada.show()

    # --- estado de cada plataforma ---

    def _x_con_fotos(self) -> bool:
        """X no admite el vídeo (sin Premium: más de 2:20 o de 512 MB) y hay
        post de LinkedIn: X publica un post con fotos."""
        return (self._linkedin is not None and not self.ajustes.x_premium
                and bool(limites.motivo_no_admite_x(self.duracion, self.tamano, False)))

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
        bloqueo = aviso_x = ""
        if plataforma == Plataforma.TIKTOK and self._tiktok_directo():
            permisos = self._ajustes_tiktok
            if self._error_ajustes_tiktok:
                bloqueo = self._error_ajustes_tiktok
            elif permisos is None:
                bloqueo = _("Cargando los permisos de TikTok…")
            elif permisos.max_segundos and self.duracion is None:
                bloqueo = _("Comprobando la duración del vídeo…")
            elif motivo_tiktok := self._motivo_duracion_tiktok(self.duracion):
                return False, "", motivo_tiktok, COLOR_AVISO
            elif not self.combo_privacidad_tiktok.currentData():
                bloqueo = _("Elige quién puede verlo en TikTok")
        if plataforma == Plataforma.X and not self.ajustes.x_premium:
            if self.duracion is None:
                return False, "", _("Comprobando la duración del vídeo…"), COLOR_SECUNDARIO
            motivo = limites.motivo_no_admite_x(self.duracion, self.tamano, False)
            if motivo and self._linkedin is None:
                return False, "", " ".join([motivo, _(
                    "Para publicar fotos en su lugar, activa «LinkedIn» y procésalo.")]), \
                    COLOR_AVISO
            if motivo:
                fotos_x = len(self.tira_x.fotos())
                if not fotos_x:
                    return False, "", _("Sin fotos para X: añade al menos una."), COLOR_AVISO
                if fotos_x > limites.MAX_FOTOS_X:
                    bloqueo = _("X admite {maximo} fotos por post: quita {sobran}.").format(
                        maximo=limites.MAX_FOTOS_X, sobran=fotos_x - limites.MAX_FOTOS_X)
                aviso_x = " ".join([motivo, _("Se publica un post con fotos.")])
            if not bloqueo and longitud_x(self.campo_x.toPlainText().strip()) > MAX_TEXTO_X:
                bloqueo = _("Texto para X de más de {maximo} caracteres: acórtalo (o marca "
                            "Premium en Redes…)").format(maximo=MAX_TEXTO_X)
        if plataforma == Plataforma.LINKEDIN:
            if self._linkedin is None:
                return False, "", _("Este vídeo no tiene post de LinkedIn: activa "
                                    "«LinkedIn» y procésalo."), COLOR_SECUNDARIO
            if not self.tira_linkedin.fotos():
                return False, "", _("Sin fotos: añade al menos una."), COLOR_AVISO
            texto_linkedin = self.campo_linkedin.toPlainText().strip()
            if not texto_linkedin:
                return False, "", _("Texto para LinkedIn vacío: escríbelo."), COLOR_AVISO
            if len(texto_linkedin) > MAX_TEXTO[plataforma]:
                bloqueo = _("Texto para LinkedIn de más de {maximo} caracteres: "
                            "acórtalo").format(maximo=MAX_TEXTO[plataforma])
        if plataforma == Plataforma.FACEBOOK and self.ajustes.pagina_facebook is None:
            bloqueo = _("Falta la página de Facebook: elígela en Redes…")
        texto, color = (consulta_cuentas.describir(plataforma, cuenta, servicio)
                        if cuenta is not None else ("", ""))
        if aviso_x:
            texto, color = " · ".join(filter(None, (aviso_x, texto))), color or COLOR_SECUNDARIO
        return True, bloqueo, texto, color

    def _motivo_duracion_tiktok(self, duracion: float | None) -> str:
        """Por qué TikTok en directo no admite un vídeo tan largo en esta
        cuenta, o "" si lo admite (o aún no se sabe)."""
        permisos = self._ajustes_tiktok
        if not (self._tiktok_directo() and permisos is not None and permisos.max_segundos
                and duracion and duracion > permisos.max_segundos):
            return ""
        return _("Este vídeo dura más de lo que tu cuenta de TikTok permite publicar "
                 "({limite})").format(limite=limites.duracion_legible(permisos.max_segundos))

    def _refrescar_plataformas(self) -> list[str]:
        """Aplica el estado de cada fila, del bloque de TikTok y del contenido
        comercial. Devuelve los motivos que impiden publicar lo marcado."""
        if self.publicando:
            return []
        self._consultar_ajustes_tiktok()  # antes: deja el estado en «Cargando…»
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
        motivo_comercial = self._refrescar_cumplimiento()
        return bloqueos + ([motivo_comercial] if motivo_comercial else [])

    def _refrescar_cumplimiento(self) -> str:
        """El bloque de TikTok (solo en directo) y los textos del contenido
        comercial. Devuelve por qué lo comercial impide publicar, o ""."""
        marcadas = set(self.plataformas())
        tiktok = Plataforma.TIKTOK in marcadas
        directo = tiktok and self._tiktok_directo()
        comercial = self.casilla_comercial.isChecked()
        tu_marca = comercial and self.casilla_tu_marca.isChecked()
        de_marca = comercial and self.casilla_de_marca.isChecked()
        self.grupo_tiktok.setVisible(directo)
        cuenta = self._cuentas.get(Plataforma.TIKTOK)
        self.etiqueta_cuenta_tiktok.setText(_("Se publicará en: {cuenta}").format(
            cuenta=cuenta.visible if cuenta is not None and cuenta.visible else "…"))
        enlace = '<a href="{url}">{texto}</a>'
        musica = enlace.format(url=URL_MUSICA_TIKTOK, texto=_("Confirmación de uso de música"))
        if de_marca:
            consentimiento = _("Al publicar, aceptas la {marca} y la {musica} de TikTok").format(
                marca=enlace.format(url=URL_MARCA_TIKTOK,
                                    texto=_("Política de contenido de marca")),
                musica=musica)
        else:
            consentimiento = _("Al publicar, aceptas la {musica} de TikTok").format(musica=musica)
        self.etiqueta_consentimiento_tiktok.setText(consentimiento)

        motivo = (_("Indica si promocionas algo tuyo, de un tercero o ambos")
                  if comercial and not (tu_marca or de_marca) else "")
        avisos = [motivo] if motivo else []
        if comercial and tiktok and not directo:
            avisos.append(_("Márcalo en la app de TikTok"))
        if de_marca and marcadas & {Plataforma.INSTAGRAM, Plataforma.FACEBOOK}:
            avisos.append(_("Añade la etiqueta de colaboración pagada desde la app de "
                            "Instagram o Facebook"))
        lineas = list(avisos)
        if directo and de_marca:
            lineas.insert(0, _('Se etiquetará como "Colaboración pagada"'))
        elif directo and tu_marca:
            lineas.insert(0, _('Se etiquetará como "Contenido promocional"'))
        self.etiqueta_comercial.setText("\n".join(lineas))
        self.etiqueta_comercial.setStyleSheet(
            f"color: {COLOR_AVISO if avisos else COLOR_SECUNDARIO};")
        self.etiqueta_comercial.setVisible(bool(lineas))
        return motivo

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
        self.selector_perfil.recargar(self.ajustes)
        if self.ajustes.perfil_redes != self._perfil_leido:
            self._leer_datos_del_perfil()
        nombre = self.ajustes.proveedor_redes
        self._hay_clave = self.llavero.hay_clave(nombre)
        guardadas = self.ajustes.cuentas_guardadas()
        self._cuentas = dict(guardadas.cuentas) if guardadas else {}
        self._cuentas_en_vivo = False
        self._fecha_cuentas = guardadas.fecha if guardadas else ""
        self._error_cuentas = ""
        self._refrescar_etiqueta_servicio()
        self._ubicacion_global = Ubicacion(self.ajustes.ciudad)
        self._refrescar_ubicacion()
        self._consultar_cuentas()
        # La cuenta de TikTok pudo reconectarse o cambiar: se vuelven a pedir sus permisos.
        self._ajustes_tiktok_de = None
        self._refrescar()

    def _al_elegir_perfil(self, perfil: str) -> None:
        self.ajustes.perfil_redes = perfil
        self.refrescar_servicio()

    def _leer_datos_del_perfil(self) -> None:
        """Plataformas deseadas y modos del perfil activo. La ubicación «solo
        este vídeo» se quita: su lugar de TikTok era de otra cuenta."""
        self._perfil_leido = self.ajustes.perfil_redes
        self._ubicacion_propia = None
        self._deseadas = set(self.ajustes.plataformas_redes)
        for plataforma, casilla in self.casillas.items():
            casilla.setChecked(plataforma in self._deseadas)
        for combo, modo in ((self.combo_tiktok, self.ajustes.tiktok_modo),
                            (self.combo_instagram, self.ajustes.instagram_modo),
                            (self.combo_facebook, self.ajustes.facebook_modo)):
            combo.setCurrentIndex(combo.findData(modo.value))

    def _refrescar_etiqueta_servicio(self) -> None:
        nombre = self.ajustes.proveedor_redes
        listo, motivo = self._listo()
        if listo:
            texto = _("Vía {servicio}").format(servicio=proveedores.nombre_visible(nombre))
            if proveedores.usa_perfil(nombre) and proveedores.parece_email(
                    self.ajustes.perfil_redes):
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
        largo_linkedin = len(self.campo_linkedin.toPlainText().strip())
        maximo_linkedin = MAX_TEXTO[Plataforma.LINKEDIN]
        self.contador_linkedin.setText(f"{largo_linkedin}/{maximo_linkedin}")
        self.contador_linkedin.setStyleSheet(
            f"color: {COLOR_AVISO};" if largo_linkedin > maximo_linkedin else "")
        x_con_fotos = self._x_con_fotos()
        self._formulario.setRowVisible(self.tira_x, x_con_fotos)
        self.modos[Plataforma.X].setText(_("Post con fotos") if x_con_fotos
                                         else _("Post público"))
        bloqueos = self._refrescar_plataformas()
        listo, _motivo = self._listo()
        programar = self.radio_programar.isChecked()
        self.campo_fecha.setEnabled(programar and not self.publicando)
        self.boton_publicar.setText(_("Programar") if programar else _("Publicar"))
        motivo_fecha = self._motivo_fecha()
        self.aviso_fecha.setText(motivo_fecha)
        self.aviso_fecha.setVisible(bool(motivo_fecha))
        self.boton_publicar.setEnabled(
            listo and not self.publicando and bool(self.plataformas())
            and bool(self.campo_titulo.text().strip()) and not bloqueos and not motivo_fecha)

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
            if entrada.programada:
                partes.append(_("{plataforma} (programado para el {fecha})").format(
                    plataforma=plataforma.nombre,
                    fecha=fecha_local(entrada.programada, self._zona, _("%d/%m/%Y %H:%M"))))
                continue
            fecha = fecha_local(entrada.fecha, self._zona, _("%d/%m/%Y %H:%M"))
            nombre = plataforma.nombre
            if entrada.sin_confirmar:
                nombre = _("{plataforma} (sin confirmar)").format(plataforma=nombre)
            elif ((plataforma == Plataforma.TIKTOK and entrada.modo == ModoTikTok.BORRADOR.value)
                  or (plataforma == Plataforma.FACEBOOK
                      and entrada.modo == ModoFacebook.BORRADOR.value)):
                nombre = _("{plataforma} (borrador)").format(plataforma=nombre)
            partes.append(f"{nombre} {fecha}")
        if any(e.programada for e in ultimas.values()):
            texto = _("⚠ Este vídeo ya está publicado o programado: {lista}. Si vuelves a "
                      "publicarlo, saldrá repetido.")
        else:
            texto = _("⚠ Este vídeo ya se publicó: {lista}. Si vuelves a publicarlo, "
                      "saldrá repetido.")
        self.aviso_publicado.setText(texto.format(lista=", ".join(partes)))
        self.aviso_publicado.show()

    # --- publicar ---

    def _resumen(self) -> str:
        opciones = self.opciones()
        return "\n".join(f"• {p.nombre}: {self._modo_visible(p, opciones)}"
                         for p in self.plataformas())

    def _confirmar(self) -> bool:
        elegidas = set(self.plataformas())
        ultimas = {p: e for p, e in registro.ultimas(self.video).items() if p in elegidas}
        formato = _("%d/%m/%Y %H:%M")
        programadas = [f"{p.nombre} ({fecha_local(ultimas[p].programada, self._zona, formato)})"
                       for p in ORDEN if p in ultimas and ultimas[p].programada]
        confirmadas = [p.nombre for p in ORDEN if p in ultimas and not ultimas[p].sin_confirmar
                       and not ultimas[p].programada]
        dudosas = [p.nombre for p in ORDEN if p in ultimas and ultimas[p].sin_confirmar]
        programada = self.programada()
        texto = (_("Se programará «{titulo}» en:\n\n{resumen}") if programada
                 else _("Se publicará «{titulo}» en:\n\n{resumen}")).format(
            titulo=self.campo_titulo.text().strip(), resumen=self._resumen())
        if set(self.ubicacion().plataformas()) & elegidas:
            texto += "\n\n" + _("Ubicación: {ubicacion}").format(
                ubicacion=describir_ubicacion(self.ubicacion(), elegidas))
        if confirmadas:
            texto += "\n\n" + _("Ya publicado antes en: {lista}.").format(
                lista=", ".join(confirmadas))
        if programadas:
            texto += "\n\n" + _("Ya programado en: {lista}.").format(
                lista=", ".join(programadas))
        if dudosas:
            texto += "\n\n" + _(
                "⚠ Sin confirmar en: {lista}. El último intento pudo publicarse igualmente: "
                "compruébalo en la app antes de publicar otra vez.").format(
                lista=", ".join(dudosas))
        if programada:
            texto += "\n\n" + _("¿Programar para el {fecha}?").format(
                fecha=fecha_local(programada, self._zona, _("%d/%m/%Y a las %H:%M")))
        else:
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
        self._refrescar()  # la hora elegida pudo quedarse corta mientras tanto
        if not self.boton_publicar.isEnabled():
            _listo, motivo = self._listo()
            self._poner_estado(motivo or self._motivo_fecha() or _(
                "Marca al menos una plataforma y escribe un título."), COLOR_AVISO)
            return
        nombre = self.ajustes.proveedor_redes
        plataformas = self.plataformas()
        # Con el lugar de TikTok guardado (Llavero), si no se cambió para este vídeo.
        opciones = replace(self.opciones(), ubicacion=self._ubicacion_propia or self._guardada())
        self._preparar(plataformas, opciones)
        self._registrar_inicio(nombre, plataformas, opciones)
        self._poner_estado(_("Esperando confirmación…"))
        if not self._confirmar():
            log.info("Cancelado por el usuario en la confirmación: no se envía nada.")
            self._terminar_sin_enviar(_("Publicación cancelada: no se ha enviado nada."),
                                      COLOR_AVISO, marcar=False)
            return
        log.info("Confirmado por el usuario.")
        motivo_fecha = self._motivo_fecha()  # la confirmación pudo quedarse abierta un rato
        if motivo_fecha:
            self._terminar_sin_enviar(motivo_fecha, COLOR_AVISO, marcar=False)
            return
        proveedor = self._abrir_servicio(nombre)
        if proveedor is None:
            return
        self._recordar_eleccion(opciones)
        self._hilo = HiloPublicacion(proveedor, self.publicacion(), opciones,
                                     plataformas, nombre, self._diario, self._ahora)
        self._hilo.progreso.connect(self._al_progresar)
        self._hilo.terminado.connect(self._al_terminar)
        self._bloquear(True)
        self._poner_estado((_("Programando: {lista}…") if opciones.programada
                            else _("Publicando: {lista}…")).format(
            lista=", ".join(p.nombre for p in plataformas)))
        log.info("Hilo de publicación en marcha.")
        self._hilo.start()

    def _abrir_servicio(self, nombre: str):
        """Lee la clave del Llavero y crea el proveedor. Si falla, lo dice
        (`_terminar_sin_enviar`) y devuelve `None`."""
        self._poner_estado(_("Leyendo la API key del Llavero…"))
        self.etiqueta_estado.repaint()
        try:
            clave = self.llavero.leer(nombre)
        except credenciales.ErrorLlavero as e:
            self._terminar_sin_enviar(_("No se pudo leer la API key del Llavero: {motivo}").format(
                motivo=str(e)))
            return None
        except Exception as e:
            log.exception("Llavero: excepción inesperada al leer la clave")
            self._terminar_sin_enviar(_("No se pudo leer la API key del Llavero ({tipo}).").format(
                tipo=type(e).__name__))
            return None
        if not clave:
            log.warning("Llavero: la entrada existe pero la lectura no devolvió ninguna clave.")
            self.refrescar_servicio()
            self._terminar_sin_enviar(_(
                "No se encontró la API key en el Llavero. Vuelve a guardarla en Redes…"))
            return None
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
            return None
        finally:
            del clave
        return proveedor

    def _recordar_eleccion(self, opciones: Opciones) -> None:
        # Lo que el usuario quiere marcado, también lo que hoy no se puede
        # (p. ej. X con un vídeo largo): la próxima vez vuelve a estar.
        self.perfil_usado = self.ajustes.perfil_redes
        self.ajustes.plataformas_redes = [p for p in ORDEN if p in self._deseadas]
        self.ajustes.tiktok_modo = opciones.tiktok_modo
        self.ajustes.instagram_modo = opciones.instagram_modo
        self.ajustes.facebook_modo = opciones.facebook_modo

    # --- estado y registro ---

    def _preparar(self, plataformas: list[Plataforma], opciones: Opciones) -> None:
        """Deja el diálogo listo para un intento nuevo y abre su registro."""
        self._cerrar_diario()
        self._reiniciar(plataformas, opciones)
        self._abrir_diario(self.video, opciones)

    def _reiniciar(self, plataformas: list[Plataforma], opciones: Opciones) -> None:
        """Las filas de las plataformas, listas para mostrar un envío nuevo."""
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

    def _abrir_diario(self, ruta: Path, opciones: Opciones) -> None:
        """Abre el registro del intento, con el nombre de `ruta`."""
        self._diario = diario.Diario(ruta)
        if opciones.ubicacion.tiktok is not None:  # el id es de la cuenta
            self._diario.ocultar(opciones.ubicacion.tiktok.id)
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
            if publicacion.fotos_x:
                log.info("X: post con fotos en lugar del vídeo: %s",
                         ", ".join(map(str, publicacion.fotos_x)))
        if Plataforma.FACEBOOK in plataformas:
            log.info("Página de Facebook: %s", "sí" if self.ajustes.pagina_facebook else "no")
        if Plataforma.LINKEDIN in plataformas:
            log.info("LinkedIn: texto de %d caracteres · fotos: %s",
                     len(publicacion.texto_linkedin), ", ".join(map(str, publicacion.fotos)))
        ubicacion = opciones.ubicacion
        log.info("Ubicación%s: %s · TikTok: %s · Instagram: %s · X: %s",
                 " (solo este vídeo)" if self._ubicacion_propia is not None else "",
                 ubicacion.nombre or "ninguna",
                 ubicacion.tiktok.visible if ubicacion.tiktok  # el id de TikTok, nunca
                 else ("se busca al publicar" if ubicacion.ciudad else "no"),
                 "sí" if Plataforma.INSTAGRAM in ubicacion.plataformas() else "no",
                 "sí" if Plataforma.X in ubicacion.plataformas() else "no")
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
            if opciones.tiktok_modo == ModoTikTok.PUBLICO and opciones.tiktok_privacidad:
                texto = _(PRIVACIDADES_TIKTOK[opciones.tiktok_privacidad])
                if opciones.contenido_de_marca:
                    return texto + " · " + _('Se etiquetará como "Colaboración pagada"')
                if opciones.tu_marca:
                    return texto + " · " + _('Se etiquetará como "Contenido promocional"')
                return texto
            return _(ETIQUETAS_TIKTOK[opciones.tiktok_modo])
        if plataforma == Plataforma.INSTAGRAM:
            return _(ETIQUETAS_INSTAGRAM[opciones.instagram_modo])
        if plataforma == Plataforma.FACEBOOK:
            return _(ETIQUETAS_FACEBOOK[opciones.facebook_modo])
        if plataforma == Plataforma.X:
            return _("Post con fotos") if self._x_con_fotos() else _("Post público")
        if plataforma == Plataforma.LINKEDIN:
            return _("Post con fotos")
        return _("Short público")

    def _bloquear(self, bloqueado: bool) -> None:
        for widget in (self.campo_titulo, self.campo_caption, self.campo_hashtags,
                       self.campo_x, self.campo_linkedin, self.tira_linkedin, self.tira_x,
                       self.combo_tiktok, self.combo_instagram,
                       self.combo_facebook, self.boton_redes, self.selector_perfil,
                       self.boton_cerrar,
                       self.boton_ubicacion, self.radio_ahora, self.radio_programar,
                       self.grupo_tiktok, self.bloque_comercial,
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
            # En cuanto se sabe, por si la app se cierra antes de terminar.
            if resultado is not None and resultado.programada is not None \
                    and resultado.referencia:
                self.ajustes.anotar_programada(resultado.referencia, self.video,
                                               resultado.programada)
        # Todo enviado y alguna sigue en el servicio: se dice qué se espera.
        en_marcha = (_("En cola"), _("Subiendo…"))
        if self._procesando and not any(
                self.estados[p].text() in en_marcha for p in self._en_curso):
            self._poner_estado(_("Esperando a que el servicio termine: {lista}…").format(
                lista=", ".join(p.nombre for p in ORDEN if p in self._procesando)))

    def _texto_resultado(self, plataforma: Plataforma, resultado: Resultado) -> tuple[str, str]:
        """HTML (escapado) y color con que se muestra un resultado."""
        if resultado.ok and resultado.programada is not None:
            return html.escape(_("📅 Programado para el {fecha}").format(
                fecha=fecha_local(resultado.programada, self._zona, _("%d/%m %H:%M")))), COLOR_OK
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
            if (plataforma == Plataforma.TIKTOK
                    and self._opciones_en_curso.tiktok_modo == ModoTikTok.PUBLICO):
                texto += " · " + html.escape(_("TikTok puede tardar unos minutos en mostrarlo"))
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
        texto = (_("Programado en {ok} de {total}") if self._opciones_en_curso.programada
                 else _("Publicado en {ok} de {total}")).format(ok=ok, total=total)
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
