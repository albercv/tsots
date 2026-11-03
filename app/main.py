from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QProcess, Qt, QTimer, QTranslator, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from videopipeline import i18n
from videopipeline.caption import Caption, leer_md
from videopipeline.config import PipelineConfig, modo_equivalente
from videopipeline.ficha import (
    CAPTION, Ficha, cargar, limpiar_temporales, mover_salidas, ocupa, olvidar,
    reconocer,
)
from videopipeline.i18n import _
from videopipeline.ollama import listar_modelos, memoria_para_modelos
from videopipeline.reproceso_plan import Consulta, Decisiones, planificar, revisar

from .queue_model import EstadoTrabajo, ModeloCola, resumen_de
from .settings import Ajustes
from .widgets.cabecera import Cabecera
from .widgets.dialogo_glosario import DialogoGlosario
from .widgets.dialogo_marca import DialogoMarca
from .widgets import dialogo_publicar
from .widgets.dialogo_programadas import DialogoProgramadas
from .widgets.dialogo_publicar import DialogoPublicar
from .widgets.dialogo_redes import DialogoRedes
from .widgets.dialogo_reproceso import preguntar_reproceso
from .widgets.panel_caption import PanelCaption
from .widgets.panel_opciones import PanelOpciones
from .widgets.vista_previa import VistaPrevia
from .widgets.zona_drop import ZonaDrop
from .worker import EjecutorCola


# Icono de la aplicación y de la ventana (el bundle .app usa el mismo PNG).
RUTA_ICONO = Path(__file__).resolve().parent / "recursos" / "icon_512.png"
BASE_DIR = Path(__file__).resolve().parent.parent
# Lanzador nativo del bundle: relanzar por aquí conserva identidad y caffeinate.
# Alto mínimo de la zona de secciones: la cabecera abierta y un par de filas.
ALTO_MINIMO_SECCIONES = 90
# Tamaño inicial; se recorta al área útil de la pantalla.
TAMANO_INICIAL = (960, 720)
RUTA_LANZADOR = (
    BASE_DIR / "TheSilenceOfTheShorts.app" / "Contents" / "MacOS" / "TheSilenceOfTheShorts"
)


def preparar_aplicacion(app: QApplication) -> None:
    """El logo y los botones estándar de Qt en el idioma de la interfaz.

    En macOS el icono de la aplicación es el del Dock y el de los avisos
    nativos: sin él sale el de Python al arrancar sin el bundle .app. Los
    botones (Sí, Cancelar…) los traduce Qt, no gettext."""
    app.setWindowIcon(QIcon(str(RUTA_ICONO)))
    traductor = QTranslator(app)
    if traductor.load(f"qtbase_{i18n.idioma_actual()}",
                      QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(traductor)


def _dependencias_faltantes() -> list[str]:
    return [
        nombre
        for nombre in ("ffmpeg", "ffprobe", "auto-editor")
        if shutil.which(nombre) is None
    ]


def _tiene_pista_audio(ruta: Path) -> bool:
    resultado = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(ruta),
        ],
        capture_output=True,
        text=True,
    )
    return bool(resultado.stdout.strip())


class VentanaPrincipal(QMainWindow):
    def __init__(self, ajustes: Ajustes | None = None):
        super().__init__()
        self.ajustes = ajustes or Ajustes()
        i18n.instalar(
            i18n.detectar() if self.ajustes.idioma_ui == "sistema"
            else self.ajustes.idioma_ui
        )
        self.setWindowTitle("The Silence of the Shorts")
        self.setWindowIcon(QIcon(str(RUTA_ICONO)))
        self.modelo_cola = ModeloCola(self)
        self.ejecutor = EjecutorCola(self)
        self._procesando = False
        self._reiniciando = False

        central = QWidget()
        raiz = QVBoxLayout(central)
        # Cabecera con el logo a todo el ancho; zona de soltar, cola y
        # opciones debajo.
        self.cabecera = Cabecera(RUTA_ICONO)
        raiz.addWidget(self.cabecera)
        fila_superior = QHBoxLayout()

        columna_izquierda = QVBoxLayout()
        self.zona_drop = ZonaDrop()
        self.zona_drop.archivos_soltados.connect(self.anadir_videos)
        columna_izquierda.addWidget(self.zona_drop)

        self.vista_cola = QListView()
        self.vista_cola.setModel(self.modelo_cola)
        self.vista_cola.doubleClicked.connect(self._abrir_resultado)
        self.etiqueta_cola = QLabel(_("Cola"))
        columna_izquierda.addWidget(self.etiqueta_cola)
        columna_izquierda.addWidget(self.vista_cola, 1)

        fila_botones_cola = QHBoxLayout()
        self.boton_quitar = QPushButton(_("Quitar"))
        self.boton_quitar.clicked.connect(self._quitar_seleccionado)
        self.boton_limpiar = QPushButton(_("Limpiar hechos"))
        self.boton_limpiar.clicked.connect(self._limpiar_hechos)
        self.boton_reprocesar = QPushButton(_("Volver a procesar"))
        self.boton_reprocesar.clicked.connect(self._reprocesar_seleccionado)
        self.boton_olvidar = QPushButton(_("Olvidar este vídeo"))
        self.boton_olvidar.setToolTip(
            _("Borra los datos guardados para rehacer pasos; no toca los vídeos"))
        self.boton_olvidar.clicked.connect(self._olvidar_seleccionado)
        fila_botones_cola.addWidget(self.boton_quitar)
        fila_botones_cola.addWidget(self.boton_limpiar)
        columna_izquierda.addLayout(fila_botones_cola)
        # Uno por fila: juntos ensanchan la ventana más de lo que cabe.
        columna_izquierda.addWidget(self.boton_reprocesar)
        columna_izquierda.addWidget(self.boton_olvidar)

        fila_superior.addLayout(columna_izquierda, 2)

        # Columna derecha: arriba las secciones de opciones (plegables) en un
        # QScrollArea, que es lo único que se desplaza si no caben; abajo, fija
        # y siempre a la vista, la previsualización y el caption en pestañas.
        self.panel = PanelOpciones()
        self.panel.cargar(self.ajustes.cargar_panel())
        self.scroll_derecha = QScrollArea()
        self.scroll_derecha.setWidget(self.panel)
        self.scroll_derecha.setWidgetResizable(True)
        self.scroll_derecha.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_derecha.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_derecha.setMinimumWidth(
            self.panel.minimumSizeHint().width()
            + self.scroll_derecha.verticalScrollBar().sizeHint().width()
        )
        self.scroll_derecha.setMinimumHeight(ALTO_MINIMO_SECCIONES)

        self.vista_previa = VistaPrevia()
        self.panel_caption = PanelCaption()
        self.panel_caption.publicar.connect(self._publicar)
        self.pestanas = QTabWidget()
        self.pestanas.setDocumentMode(True)
        self.pestanas.addTab(self.vista_previa, _("Previsualización"))
        self.pestanas.addTab(self.panel_caption, _("Caption"))
        self._fijar_alto_pestanas()

        columna_derecha = QVBoxLayout()
        columna_derecha.setContentsMargins(0, 0, 0, 0)
        columna_derecha.addWidget(self.scroll_derecha, 1)
        columna_derecha.addWidget(self.pestanas)
        fila_superior.addLayout(columna_derecha, 1)
        raiz.addLayout(fila_superior, 1)

        fila_inferior = QHBoxLayout()
        self.etiqueta_salida = QLabel()
        # Que una ruta larga no imponga el ancho mínimo de la ventana: se
        # recorta y la ruta entera queda en el tooltip.
        self.etiqueta_salida.setMinimumWidth(60)
        self._refrescar_etiqueta_salida()
        self.boton_carpeta = QPushButton(_("Cambiar…"))
        self.boton_carpeta.clicked.connect(self._elegir_carpeta)
        self.boton_procesar = QPushButton()
        self.boton_procesar.clicked.connect(self._procesar_o_cancelar)
        fila_inferior.addWidget(QLabel("🌐"))
        self.combo_idioma_ui = QComboBox()
        self.combo_idioma_ui.addItem(_("Sistema"), "sistema")
        self.combo_idioma_ui.addItem("Español", "es")
        self.combo_idioma_ui.addItem("English", "en")
        self.combo_idioma_ui.setCurrentIndex(
            max(0, self.combo_idioma_ui.findData(self.ajustes.idioma_ui))
        )
        self.combo_idioma_ui.currentIndexChanged.connect(
            self._al_cambiar_idioma_ui
        )
        fila_inferior.addWidget(self.combo_idioma_ui)
        # Ajustes de la app (no de un vídeo): junto al idioma, siempre visibles.
        self.boton_redes = QPushButton(_("Redes…"))
        self.boton_redes.setToolTip(_("Servicio, perfil y API key para publicar"))
        # Método ligado, no lambda: una lambda con `self` mantiene viva la
        # ventana después de soltarla (el botón es su hijo y guarda la lambda).
        self.boton_redes.clicked.connect(self._abrir_redes)
        fila_inferior.addWidget(self.boton_redes)
        self.boton_programadas = QPushButton(_("Programadas…"))
        self.boton_programadas.setToolTip(_("Lo que tienes programado en el servicio"))
        self.boton_programadas.clicked.connect(self._abrir_programadas)
        fila_inferior.addWidget(self.boton_programadas)
        fila_inferior.addWidget(QLabel(_("Salida:")))
        fila_inferior.addWidget(self.etiqueta_salida, 1)
        fila_inferior.addWidget(self.boton_carpeta)
        fila_inferior.addWidget(self.boton_procesar)
        raiz.addLayout(fila_inferior)

        self.setCentralWidget(central)

        self.ejecutor.progreso.connect(self._al_progresar)
        self.ejecutor.trabajo_iniciado.connect(self._al_iniciar_trabajo)
        self.ejecutor.trabajo_terminado.connect(self._al_terminar_trabajo)
        self.ejecutor.cola_terminada.connect(self._al_terminar_cola)
        self.ejecutor.aviso.connect(self._al_avisar)
        self.ejecutor.salida_vertical.connect(self._al_salida_vertical)
        self.ejecutor.diagnostico.connect(self._al_diagnosticar)
        self.modelo_cola.rowsInserted.connect(self._refrescar_boton)
        self.modelo_cola.rowsRemoved.connect(self._refrescar_boton)
        self.modelo_cola.dataChanged.connect(self._refrescar_boton)
        self._refrescar_boton()

        self.panel.opciones_subs_cambiadas.connect(self._refrescar_preview)
        self.panel.opciones_subs_cambiadas.connect(self._mostrar_pestana_preview)
        self.panel.editar_marca.connect(self._editar_marca)
        self.panel.editar_glosario.connect(self._editar_glosario)
        self.panel.modelo_caption_cambiado.connect(self._al_cambiar_modelo_caption)
        self.panel.refrescar_modelos.connect(self._cargar_modelos_ollama)
        self.panel.seccion_abierta_cambiada.connect(self._al_abrir_seccion)
        self.panel.pasos_cambiados.connect(self._refrescar_boton)
        self._cargar_modelos_ollama()
        self.vista_cola.selectionModel().currentChanged.connect(
            self._al_cambiar_seleccion
        )

        geometria = self.ajustes.cargar_geometria()
        if geometria:
            self.restoreGeometry(geometria)
        self._ajustar_a_pantalla()

    def _fijar_alto_pestanas(self) -> None:
        """Alto fijo para la zona de pestañas: el de la previsualización a
        tamaño completo o el del caption, lo que sea mayor. Así no salta al
        cambiar de pestaña, al llegar el primer fotograma ni al aparecer un
        caption, y las secciones de encima se llevan el resto."""
        pila = self.pestanas.findChild(QStackedWidget)
        paginas = max(
            self.vista_previa.etiqueta.maximumHeight(),
            self.panel_caption.sizeHint().height(),
        )
        cromo = self.pestanas.sizeHint().height() - pila.sizeHint().height()
        self.pestanas.setFixedHeight(cromo + paginas)
        self.pestanas.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

    def _al_abrir_seccion(self, _clave: str) -> None:
        # El layout aún no ha recolocado las secciones: esperar a que lo haga.
        QTimer.singleShot(0, self._mostrar_seccion_abierta)

    def _mostrar_seccion_abierta(self) -> None:
        """Desplaza las opciones para que la sección recién abierta se vea
        entera o, si no cabe, desde su cabecera."""
        clave = self.panel.seccion_abierta()
        if not clave:
            return
        seccion = self.panel.secciones[clave]
        barra = self.scroll_derecha.verticalScrollBar()
        alto_visible = self.scroll_derecha.viewport().height()
        arriba, alto = seccion.y(), seccion.height()
        if alto > alto_visible or arriba < barra.value():
            barra.setValue(arriba)
        elif arriba + alto > barra.value() + alto_visible:
            barra.setValue(arriba + alto - alto_visible)

    def _ajustar_a_pantalla(self) -> None:
        """Evita ventanas más grandes que el área útil (geometría guardada en
        otro monitor, o mínimos antiguos)."""
        pantalla = self.screen() or QApplication.primaryScreen()
        if pantalla is None:
            return
        disponible = pantalla.availableGeometry()
        ancho = min(self.width(), disponible.width())
        alto = min(self.height(), disponible.height())
        if (ancho, alto) != (self.width(), self.height()):
            self.resize(ancho, alto)
        if not disponible.contains(self.frameGeometry()):
            self.move(
                max(disponible.left(), min(self.x(), disponible.right() - ancho)),
                max(disponible.top(), min(self.y(), disponible.bottom() - alto)),
            )

    # --- cola ---

    def anadir_videos(self, rutas: list[Path]) -> None:
        sin_audio = [r for r in rutas if not _tiene_pista_audio(r)]
        con_audio = [r for r in rutas if r not in sin_audio]
        if sin_audio:
            nombres = "\n".join(r.name for r in sin_audio)
            QMessageBox.warning(
                self,
                _("Sin pista de audio"),
                _(
                    "Estos vídeos no tienen audio y no se han añadido:\n{nombres}"
                ).format(nombres=nombres),
            )
        reconocidos: list[tuple[Path, Ficha]] = []
        avisos, errores = [], []
        for ruta in con_audio:
            try:
                ficha, aviso = reconocer(ruta, self.ajustes.carpeta_salida)
            except Exception as error:  # noqa: BLE001 — un archivo no frena a los demás
                errores.append(f"{ruta.name}: {error}")
                continue
            reconocidos.append((ruta, ficha))
            if aviso:
                avisos.append(aviso)
        self._anadir_reconocidos(reconocidos)
        if errores:
            QMessageBox.warning(
                self,
                _("No se puede añadir"),
                _("Estos vídeos no se han añadido:\n{errores}").format(
                    errores="\n".join(errores)),
            )
        if avisos:
            QMessageBox.information(self, _("Aviso"), "\n".join(avisos))

    def _anadir_reconocidos(self, reconocidos: list[tuple[Path, Ficha]]) -> None:
        por_ruta = dict(reconocidos)
        # Una fila con esa ruta y otra ficha (olvidada, o sustituida porque el
        # archivo se editó) es el mismo vídeo: pasa a la ficha nueva, sin
        # fila duplicada.
        for fila in range(self.modelo_cola.rowCount()):
            trabajo = self.modelo_cola.trabajo(fila)
            ficha = por_ruta.get(trabajo.ruta)
            if ficha is not None and trabajo.ficha_id != ficha.id:
                self.modelo_cola.actualizar(fila, ficha_id=ficha.id)
        self.modelo_cola.anadir([(ruta, ficha.id) for ruta, ficha in reconocidos])
        for ficha in por_ruta.values():
            fila = self.modelo_cola.fila_de_ficha(ficha.id)
            if fila is not None:
                self.modelo_cola.actualizar(
                    fila, resumen=resumen_de(ficha), ocupa=ocupa(ficha))

    def _quitar_seleccionado(self) -> None:
        if self._procesando:
            return
        indices = self.vista_cola.selectedIndexes()
        for indice in sorted(indices, key=lambda i: -i.row()):
            trabajo = self.modelo_cola.trabajo(indice.row())
            if trabajo.estado != EstadoTrabajo.PROCESANDO:
                self.modelo_cola.quitar(indice.row())

    def _limpiar_hechos(self) -> None:
        if self._procesando:
            return
        self.modelo_cola.limpiar_hechos()

    def _ficha_de(self, trabajo) -> Ficha | None:
        return cargar(trabajo.ficha_id) if trabajo.ficha_id else None

    def _reprocesar_seleccionado(self) -> None:
        if self._procesando:
            return
        self.modelo_cola.volver_a_espera(
            [indice.row() for indice in self.vista_cola.selectedIndexes()])

    def _olvidar_seleccionado(self) -> None:
        if self._procesando:
            return
        indices = self.vista_cola.selectedIndexes()
        if not indices:
            return
        fila = indices[0].row()
        trabajo = self.modelo_cola.trabajo(fila)
        ficha = self._ficha_de(trabajo)
        if ficha is not None:
            texto = _(
                'Se borrarán los datos guardados para rehacer pasos de '
                '"{nombre}" ({mb} MB). Los vídeos y su caption no se tocan.'
            ).format(nombre=trabajo.ruta.name, mb=round(ocupa(ficha) / 1_000_000))
            # La versión anterior de una salida antigua que se guardó en la
            # ficha antes de sobrescribirla se borra con ella, aunque después
            # se adoptara el original verdadero.
            for guardada in sorted(ficha.carpeta.glob("original.*")):
                texto += " " + _(
                    'La versión anterior del vídeo que se guardó ahí '
                    '("{archivo}") también se borra.'
                ).format(archivo=guardada.name)
            respuesta = QMessageBox.question(
                self,
                _("Olvidar este vídeo"),
                texto,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return
            olvidar(ficha)
        self.modelo_cola.actualizar(fila, ficha_id=None, resumen="", ocupa=0)

    def _abrir_resultado(self, indice) -> None:
        trabajo = self.modelo_cola.trabajo(indice.row())
        if trabajo.estado == EstadoTrabajo.HECHO and trabajo.salida:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(trabajo.salida)))
        elif trabajo.estado == EstadoTrabajo.ERROR:
            self._mostrar_error(trabajo)

    # --- errores ---

    def _dialogo_error(self, trabajo) -> QMessageBox:
        diag = trabajo.diagnostico or {}
        titulo = diag.get("titulo") or trabajo.error.splitlines()[0]
        # macOS ignora el windowTitle de QMessageBox: el título va en el cuerpo.
        lineas = [f"<b>{titulo}</b>", trabajo.ruta.name]
        if diag.get("paso"):
            lineas.append(_("Paso: {paso}").format(paso=diag["paso"]))
        if diag.get("causa"):
            lineas.append(_("<br>Causa: {causa}").format(causa=diag["causa"]))
        if diag.get("solucion"):
            lineas.append(
                _("<br>Qué hacer: {solucion}").format(solucion=diag["solucion"])
            )
        if not diag:
            lineas.append(trabajo.error)
        dialogo = QMessageBox(self)
        dialogo.setIcon(QMessageBox.Icon.Critical)
        dialogo.setWindowTitle(_("Error: {titulo}").format(titulo=titulo))
        dialogo.setText("<br>".join(lineas))
        detalle = diag.get("detalle") or trabajo.error
        if detalle:
            dialogo.setDetailedText(detalle)
        dialogo.addButton(QMessageBox.StandardButton.Close)
        log = diag.get("log")
        if log and Path(log).is_file():
            boton_log = dialogo.addButton(
                _("Abrir log"), QMessageBox.ButtonRole.ActionRole
            )
            boton_log.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(log))
            )
        return dialogo

    def _mostrar_error(self, trabajo) -> None:
        self._dialogo_error(trabajo).exec()

    def _al_diagnosticar(self, fila: int, diagnostico: dict) -> None:
        self.modelo_cola.actualizar(fila, diagnostico=diagnostico)

    # --- preview ---

    def _al_cambiar_seleccion(self, indice, _anterior) -> None:
        if indice.isValid():
            trabajo = self.modelo_cola.trabajo(indice.row())
            self.vista_previa.establecer_video(trabajo.ruta)
            self._refrescar_preview()
            self._mostrar_caption(trabajo)
        else:
            self.vista_previa.establecer_video(None)
            self.panel_caption.mostrar(None)
            self.pestanas.setCurrentWidget(self.vista_previa)

    def _mostrar_caption(self, trabajo) -> None:
        """Carga el caption del trabajo y elige pestaña: Caption si lo hay
        (lo siguiente es copiarlo o publicarlo), Previsualización si no."""
        caption = self._caption_de(trabajo)
        self.panel_caption.mostrar(caption, self._video_de(trabajo) if caption else None)
        self.pestanas.setCurrentWidget(
            self.panel_caption if caption else self.vista_previa
        )

    def _video_de(self, trabajo) -> Path | None:
        """El vídeo que se publica: el final de su ficha o, sin él, la salida."""
        ficha = self._ficha_de(trabajo)
        if ficha is not None and ficha.final is not None:
            return ficha.final.ruta
        return trabajo.salida

    def _caption_de(self, trabajo) -> Caption | None:
        if trabajo.estado == EstadoTrabajo.PROCESANDO:
            return None
        ficha = self._ficha_de(trabajo)
        if (ficha is not None and CAPTION in ficha.artefactos
                and ficha.final is not None and ficha.final.ruta.is_file()):
            caption = leer_md(ficha.ruta("caption.md"))
            if caption is not None:
                self._restaurar_md(ficha)
                return caption
        # Sin ficha (o sin caption en ella): el `.md` junto a la salida.
        if trabajo.estado != EstadoTrabajo.HECHO or not trabajo.salida:
            return None
        return leer_md(trabajo.salida.with_suffix(".md"))

    def _restaurar_md(self, ficha: Ficha) -> None:
        """La copia de la ficha es la fuente de verdad: si falta el `.md` junto
        al final (Publicar lo lee), se vuelve a escribir."""
        md = ficha.final.ruta.with_suffix(".md")
        if md.is_file():
            return
        temporal = md.with_name(f".{md.stem}_tmp{md.suffix}")
        try:
            shutil.copyfile(ficha.ruta("caption.md"), temporal)
            temporal.replace(md)
        except OSError:
            pass  # el caption se muestra igual; se reintenta al volver a elegirlo

    def _mostrar_pestana_preview(self) -> None:
        # Al tocar las opciones de subtítulos se quiere ver el efecto.
        # Método y no lambda: una lambda con self en una señal mantiene viva
        # la ventana tras cerrarla.
        self.pestanas.setCurrentWidget(self.vista_previa)

    def _refrescar_preview(self) -> None:
        valores = self.panel.valores()
        self.vista_previa.actualizar_opciones(
            valores["diseno"], valores["posicion_subs"],
            valores["tamano_subs"], valores["subtitulos"],
        )

    # --- salida ---

    def _refrescar_etiqueta_salida(self) -> None:
        carpeta = self.ajustes.carpeta_salida
        self.etiqueta_salida.setText(
            str(carpeta) if carpeta else _("Junto al original (_limpio.mp4)")
        )
        self.etiqueta_salida.setToolTip(self.etiqueta_salida.text())

    def _elegir_carpeta(self) -> None:
        carpeta = QFileDialog.getExistingDirectory(self, _("Carpeta de salida"))
        if carpeta:
            self.ajustes.carpeta_salida = Path(carpeta)
            self._refrescar_etiqueta_salida()

    def _cargar_modelos_ollama(self) -> None:
        """Rellena el selector con los modelos instalados en Ollama (reales)."""
        self.panel.poblar_modelos(
            listar_modelos(), memoria_para_modelos(), self.ajustes.modelo_caption
        )

    def _al_cambiar_modelo_caption(self, modelo: str) -> None:
        if modelo:
            self.ajustes.modelo_caption = modelo

    def _editar_marca(self) -> None:
        dialogo = DialogoMarca(self.ajustes.contexto_marca, self)
        if dialogo.exec():
            self.ajustes.contexto_marca = dialogo.texto()

    def _editar_glosario(self) -> None:
        dialogo = DialogoGlosario(self.ajustes.glosario, self)
        if dialogo.exec():
            self.ajustes.glosario = dialogo.texto()

    # --- redes ---

    def _publicar(self) -> None:
        caption, video = self.panel_caption.caption, self.panel_caption.video
        if caption is None or video is None:
            QMessageBox.warning(
                self, _("Publicar en redes"),
                _("Elige en la cola un vídeo terminado que tenga caption."))
            return
        if not video.is_file():
            QMessageBox.warning(
                self, _("Publicar en redes"),
                _("No se encuentra el vídeo terminado:\n{ruta}").format(ruta=video))
            return
        dialogo = DialogoPublicar(video, caption, self.ajustes, parent=self)
        dialogo.configurar_redes.connect(
            lambda: self._configurar_redes(dialogo.refrescar_servicio, dialogo))
        dialogo.exec()
        # El hilo de la subida no depende del diálogo (ver dialogo_publicar);
        # aun así, solo se libera cuando no publica.
        if not dialogo.publicando:
            dialogo.deleteLater()

    def _abrir_redes(self) -> None:
        """Botón de la barra inferior: sin `checked` ni callback."""
        self._configurar_redes()

    def _abrir_programadas(self) -> None:
        dialogo = DialogoProgramadas(self.ajustes, parent=self)
        dialogo.exec()  # no se cierra mientras cancela
        dialogo.deleteLater()

    def _configurar_redes(self, al_guardar=None, padre=None) -> None:
        dialogo = DialogoRedes(self.ajustes, parent=padre or self)
        if dialogo.exec() and al_guardar is not None:
            al_guardar()

    # --- procesado ---

    def procesar(self) -> None:
        pendientes = self.modelo_cola.pendientes()
        if not pendientes:
            return
        valores = self.panel.valores()
        # Las versiones anteriores comparten estos ajustes y solo leen `modo`.
        self.ajustes.guardar_panel({
            **valores,
            "modo": modo_equivalente(valores["paso_audio"], valores["paso_silencios"]),
        })
        carpeta = self.ajustes.carpeta_salida
        filas: list[tuple[int, PipelineConfig, Ficha | None]] = []
        avisos = []
        for fila in pendientes:
            trabajo = self.modelo_cola.trabajo(fila)
            if trabajo.ficha_id is None and not self._reconocer_fila(fila, avisos):
                continue
            config = PipelineConfig(
                video=trabajo.ruta, salida=carpeta,
                contexto_marca=self.ajustes.contexto_marca,
                glosario=self.ajustes.glosario,
                modelo_caption=self.ajustes.modelo_caption,
                idioma_ui=i18n.idioma_actual(),
                **valores,
            )
            ficha = self._ficha_de(trabajo)
            if ficha is not None and ficha.final is None and ficha.vertical is None:
                # Aún sin salidas: van a la carpeta de ahora. Las demás fichas
                # conservan la suya, que es donde están sus archivos.
                mover_salidas(ficha, carpeta)
            filas.append((fila, config, ficha))
        if avisos:
            QMessageBox.information(self, _("Aviso"), "\n".join(avisos))

        decisiones = self._preguntar_reproceso(filas)
        if decisiones is None:
            return
        trabajos: list[tuple[int, str]] = []
        sin_nada: list[str] = []
        for fila, config, ficha in filas:
            trabajo = self.modelo_cola.trabajo(fila)
            datos = json.loads(config.to_json())
            # Siempre por la ficha: una fila arrastrada desde una salida se
            # llama como ella, pero su original es el de la ficha.
            decision = decisiones.get(trabajo.ficha_id, Decisiones())
            if ficha is not None:
                plan = planificar(ficha, config, decision)
                if plan.error:
                    self.modelo_cola.actualizar(
                        fila, estado=EstadoTrabajo.ERROR, error=plan.error,
                        percent=None, etiqueta="")
                    continue
                if plan.vacio:
                    sin_nada.append(trabajo.ruta.name)
                    if ficha.final is not None:  # lo que ya hay es el resultado
                        self._al_terminar_trabajo(
                            fila, True, str(ficha.final.ruta), "")
                    continue
            datos["reproceso"] = {
                "ficha": trabajo.ficha_id,
                "rehacer": sorted(decision.rehacer),
                "regenerar_vertical": decision.regenerar_vertical,
            }
            trabajos.append((fila, json.dumps(datos, ensure_ascii=False)))
        if sin_nada:
            QMessageBox.information(
                self, _("Nada que hacer"),
                _("Nada que hacer en: {nombres}").format(nombres=", ".join(sin_nada)))
        if not trabajos:
            return
        self._procesando = True
        self._refrescar_boton()
        self.ejecutor.iniciar(trabajos)

    def _reconocer_fila(self, fila: int, avisos: list[str]) -> bool:
        """Una fila sin ficha (p. ej. tras «Olvidar este vídeo») se reconoce
        como al arrastrarla: nunca se procesa como un vídeo nuevo, que
        escribiría `x_limpio_limpio` o borraría el caption de una salida."""
        trabajo = self.modelo_cola.trabajo(fila)
        try:
            ficha, aviso = reconocer(trabajo.ruta, self.ajustes.carpeta_salida)
        except Exception as error:  # noqa: BLE001 — un archivo no frena a los demás
            self.modelo_cola.actualizar(
                fila, estado=EstadoTrabajo.ERROR, percent=None, etiqueta="",
                error=f"{trabajo.ruta.name}: {error}")
            return False
        if aviso:
            avisos.append(aviso)
        self.modelo_cola.actualizar(
            fila, ficha_id=ficha.id, resumen=resumen_de(ficha), ocupa=ocupa(ficha))
        return True

    def _preguntar_reproceso(
        self, filas: list[tuple[int, PipelineConfig, Ficha | None]]
    ) -> dict[str, Decisiones] | None:
        """Avisa de lo que los vídeos ya tienen. None si el usuario cancela;
        sin nada que avisar, ni se pregunta (todo se mantiene)."""
        consultas: dict[str, tuple[str, list[Consulta]]] = {}
        hay_vertical: set[str] = set()
        for fila, config, ficha in filas:
            if ficha is None:
                continue
            lista = revisar(ficha, config)
            # Si cambia el audio, los silencios o los subtítulos, el vertical que
            # ya hay puede quedar desactualizado: se ofrece regenerarlo (R7).
            if ficha.vertical is not None and (
                    config.paso_audio or config.paso_silencios or config.subtitulos):
                hay_vertical.add(ficha.id)
            if lista or ficha.id in hay_vertical:
                consultas[ficha.id] = (self.modelo_cola.trabajo(fila).ruta.name, lista)
        if not consultas:
            return {}
        return preguntar_reproceso(self, consultas, hay_vertical)

    def _procesar_o_cancelar(self) -> None:
        if self._procesando:
            self.ejecutor.cancelar()
        else:
            self.procesar()

    def _al_iniciar_trabajo(self, fila: int) -> None:
        self.modelo_cola.actualizar(
            fila, estado=EstadoTrabajo.PROCESANDO, percent=None, etiqueta=""
        )

    def _al_progresar(self, fila: int, evento: dict) -> None:
        self.modelo_cola.actualizar(
            fila,
            etiqueta=evento.get("label", ""),
            percent=evento.get("percent"),
        )

    def _al_salida_vertical(self, fila: int, ruta: str) -> None:
        self.modelo_cola.actualizar(fila, salida_vertical=Path(ruta))

    def _al_avisar(self, fila: int, texto: str) -> None:
        self.modelo_cola.actualizar(fila, aviso=texto)

    def _al_terminar_trabajo(
        self, fila: int, ok: bool, salida: str, error: str
    ) -> None:
        if ok:
            cambios = {"salida": Path(salida)}
            ficha = self._ficha_de(self.modelo_cola.trabajo(fila))
            if ficha is not None:  # la pasada la dejó al día
                if ficha.final is not None:
                    cambios["salida"] = ficha.final.ruta
                if ficha.vertical is not None:
                    cambios["salida_vertical"] = ficha.vertical.ruta
                cambios.update(resumen=resumen_de(ficha), ocupa=ocupa(ficha))
            self.modelo_cola.actualizar(
                fila, estado=EstadoTrabajo.HECHO, percent=None, etiqueta="",
                **cambios,
            )
            actual = self.vista_cola.currentIndex()
            if actual.isValid() and actual.row() == fila:
                self._mostrar_caption(self.modelo_cola.trabajo(fila))
        else:
            estado = (
                EstadoTrabajo.CANCELADO
                if error == _("Cancelado")
                else EstadoTrabajo.ERROR
            )
            self.modelo_cola.actualizar(
                fila, estado=estado, error=error, percent=None, etiqueta="",
            )
            if estado == EstadoTrabajo.CANCELADO:
                self._limpiar_temporal(self.modelo_cola.trabajo(fila))

    def _limpiar_temporal(self, trabajo) -> None:
        """Borra los tmp ocultos que el runner dejó a medias al cancelar."""
        ficha = self._ficha_de(trabajo)
        if ficha is not None:
            limpiar_temporales(ficha)
            return
        video, carpeta = trabajo.ruta, self.ajustes.carpeta_salida
        # Los pasos del trabajo cancelado no se conocen aquí: se prueban todos
        # los destinos posibles (horizontal, su vertical y vertical único).
        destinos = (
            PipelineConfig(video=video, salida=carpeta).ruta_salida_final(),
            PipelineConfig(video=video, salida=carpeta, paso_vertical=True)
            .ruta_salida_vertical(),
            PipelineConfig(video=video, salida=carpeta, paso_audio=False,
                           paso_silencios=False, paso_vertical=True)
            .ruta_salida_final(),
        )
        for destino in destinos:
            final = destino.expanduser().resolve()
            for sufijo in ("_tmp", "_subs_tmp"):
                final.with_name(f".{final.stem}{sufijo}{final.suffix}").unlink(
                    missing_ok=True
                )

    def _al_terminar_cola(self) -> None:
        self._procesando = False
        # Trabajos que quedaron en PROCESANDO tras cancelar vuelven a ESPERA.
        for fila in range(self.modelo_cola.rowCount()):
            if self.modelo_cola.trabajo(fila).estado == EstadoTrabajo.PROCESANDO:
                self.modelo_cola.actualizar(fila, estado=EstadoTrabajo.ESPERA)
        self._refrescar_boton()

    def _refrescar_boton(self, *args) -> None:
        if self._procesando:
            self.boton_procesar.setText(_("■ Cancelar"))
            self.boton_procesar.setEnabled(True)
        else:
            self.boton_procesar.setText(_("▶ Procesar"))
            hay_pasos = self.panel.hay_pasos()
            self.boton_procesar.setEnabled(
                bool(self.modelo_cola.pendientes()) and hay_pasos
            )
            self.boton_procesar.setToolTip(
                "" if hay_pasos else
                _("Marca al menos un paso.")
            )
        self.boton_quitar.setEnabled(not self._procesando)
        self.boton_limpiar.setEnabled(not self._procesando)
        self.boton_reprocesar.setEnabled(not self._procesando)
        self.boton_olvidar.setEnabled(not self._procesando)

    # --- idioma ---

    def _al_cambiar_idioma_ui(self, *args) -> None:
        codigo = self.combo_idioma_ui.currentData()
        if not codigo or codigo == self.ajustes.idioma_ui:
            return
        respuesta = QMessageBox.question(
            self,
            _("Idioma"),
            _("Para cambiar el idioma la app se reiniciará. Se cancelará "
              "cualquier proceso en marcha. ¿Reiniciar ahora?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            # Revertir el combo sin volver a preguntar.
            self.combo_idioma_ui.blockSignals(True)
            self.combo_idioma_ui.setCurrentIndex(
                max(0, self.combo_idioma_ui.findData(self.ajustes.idioma_ui))
            )
            self.combo_idioma_ui.blockSignals(False)
            return
        self.ajustes.idioma_ui = codigo
        self._reiniciar()

    def _reiniciar(self) -> None:
        """Cancela lo que haya en marcha, relanza la app y cierra esta."""
        self._reiniciando = True
        if self._procesando:
            self.ejecutor.cancelar()
        self.ajustes.guardar_geometria(bytes(self.saveGeometry()))
        self._relanzar()
        QApplication.quit()

    def _comando_relanzar(self) -> list[str]:
        """Lanzador del bundle si existe (identidad, caffeinate); si no, python -m app."""
        if RUTA_LANZADOR.is_file() and os.access(RUTA_LANZADOR, os.X_OK):
            return [str(RUTA_LANZADOR)]
        return [sys.executable, "-m", "app"]

    def _relanzar(self) -> None:
        programa, *args = self._comando_relanzar()
        QProcess.startDetached(programa, args, str(BASE_DIR))

    # --- ciclo de vida ---

    def closeEvent(self, evento) -> None:
        if dialogo_publicar.hilos_vivos():
            QMessageBox.information(
                self, _("Publicar en redes"),
                _("Se está publicando en redes. Espera a que termine para salir."))
            evento.ignore()
            return
        if self._procesando and not self._reiniciando:
            respuesta = QMessageBox.question(
                self,
                _("Proceso en curso"),
                _("Hay un vídeo procesándose. ¿Cancelar y salir?"),
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                evento.ignore()
                return
            self.ejecutor.cancelar()
        self.ajustes.guardar_geometria(bytes(self.saveGeometry()))
        evento.accept()


def main() -> int:
    ajustes = Ajustes()
    i18n.instalar(
        i18n.detectar() if ajustes.idioma_ui == "sistema" else ajustes.idioma_ui
    )
    app = QApplication(sys.argv)
    preparar_aplicacion(app)
    faltan = _dependencias_faltantes()
    if faltan:
        QMessageBox.critical(
            None,
            _("Faltan dependencias"),
            _("No se encuentran en PATH: {faltan}"
              "\nInstálalas y vuelve a abrir la aplicación.").format(
                faltan=", ".join(faltan)
            ),
        )
        return 1
    # Nunca destruir un hilo de publicación en marcha al salir (Qt abortaría).
    app.aboutToQuit.connect(dialogo_publicar.esperar_hilos)
    ventana = VentanaPrincipal(ajustes)
    ventana.resize(*TAMANO_INICIAL)
    ventana._ajustar_a_pantalla()
    ventana.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
