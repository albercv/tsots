from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QUrl
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
    QVBoxLayout,
    QWidget,
)

from videopipeline import i18n
from videopipeline.caption import Caption, leer_md
from videopipeline.config import PipelineConfig
from videopipeline.i18n import _
from videopipeline.ollama import listar_modelos, memoria_para_modelos

from .queue_model import EstadoTrabajo, ModeloCola
from .settings import Ajustes
from .widgets.cabecera import Cabecera
from .widgets.dialogo_glosario import DialogoGlosario
from .widgets.dialogo_marca import DialogoMarca
from .widgets.dialogo_publicar import DialogoPublicar
from .widgets.dialogo_redes import DialogoRedes
from .widgets.panel_caption import PanelCaption
from .widgets.panel_opciones import PanelOpciones
from .widgets.vista_previa import VistaPrevia
from .widgets.zona_drop import ZonaDrop
from .worker import EjecutorCola


# Icono de la ventana (el del Dock lo pone el bundle .app desde el mismo PNG).
RUTA_ICONO = Path(__file__).resolve().parent / "recursos" / "icon_512.png"
BASE_DIR = Path(__file__).resolve().parent.parent
# Lanzador nativo del bundle: relanzar por aquí conserva identidad y caffeinate.
RUTA_LANZADOR = (
    BASE_DIR / "TheSilenceOfTheShorts.app" / "Contents" / "MacOS" / "TheSilenceOfTheShorts"
)


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
        fila_botones_cola.addWidget(self.boton_quitar)
        fila_botones_cola.addWidget(self.boton_limpiar)
        columna_izquierda.addLayout(fila_botones_cola)

        fila_superior.addLayout(columna_izquierda, 2)

        # La columna derecha apilada (opciones + preview + caption) supera los
        # 1100 px; va dentro de un QScrollArea para que la ventana pueda
        # encoger en pantallas pequeñas y aparezca scroll en vez de bloquear.
        self.panel = PanelOpciones()
        self.panel.cargar(self.ajustes.cargar_panel())
        contenido_derecha = QWidget()
        columna_derecha = QVBoxLayout(contenido_derecha)
        columna_derecha.setContentsMargins(0, 0, 0, 0)
        columna_derecha.addWidget(self.panel)
        self.vista_previa = VistaPrevia()
        columna_derecha.addWidget(self.vista_previa)
        self.panel_caption = PanelCaption()
        self.panel_caption.publicar.connect(self._publicar)
        columna_derecha.addWidget(self.panel_caption)
        columna_derecha.addStretch(1)
        self.scroll_derecha = QScrollArea()
        self.scroll_derecha.setWidget(contenido_derecha)
        self.scroll_derecha.setWidgetResizable(True)
        self.scroll_derecha.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_derecha.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_derecha.setMinimumWidth(
            contenido_derecha.minimumSizeHint().width()
            + self.scroll_derecha.verticalScrollBar().sizeHint().width()
        )
        fila_superior.addWidget(self.scroll_derecha, 1)
        raiz.addLayout(fila_superior, 1)

        fila_inferior = QHBoxLayout()
        self.etiqueta_salida = QLabel()
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
        self.ejecutor.diagnostico.connect(self._al_diagnosticar)
        self.modelo_cola.rowsInserted.connect(self._refrescar_boton)
        self.modelo_cola.rowsRemoved.connect(self._refrescar_boton)
        self.modelo_cola.dataChanged.connect(self._refrescar_boton)
        self._refrescar_boton()

        self.panel.opciones_subs_cambiadas.connect(self._refrescar_preview)
        self.panel.editar_marca.connect(self._editar_marca)
        self.panel.editar_glosario.connect(self._editar_glosario)
        self.panel.modelo_caption_cambiado.connect(self._al_cambiar_modelo_caption)
        self.panel.refrescar_modelos.connect(self._cargar_modelos_ollama)
        self._cargar_modelos_ollama()
        self.vista_cola.selectionModel().currentChanged.connect(
            self._al_cambiar_seleccion
        )

        geometria = self.ajustes.cargar_geometria()
        if geometria:
            self.restoreGeometry(geometria)
        self._ajustar_a_pantalla()

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
        if con_audio:
            self.modelo_cola.anadir(con_audio)

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

    def _mostrar_caption(self, trabajo) -> None:
        caption = self._caption_de(trabajo)
        self.panel_caption.mostrar(caption, trabajo.salida if caption else None)

    def _caption_de(self, trabajo) -> Caption | None:
        if trabajo.estado != EstadoTrabajo.HECHO or not trabajo.salida:
            return None
        return leer_md(trabajo.salida.with_suffix(".md"))

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

    def _abrir_redes(self) -> None:
        """Botón de la barra inferior: sin `checked` ni callback."""
        self._configurar_redes()

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
        self.ajustes.guardar_panel(valores)
        carpeta = self.ajustes.carpeta_salida
        trabajos: list[tuple[int, str]] = []
        for fila in pendientes:
            trabajo = self.modelo_cola.trabajo(fila)
            config = PipelineConfig(
                video=trabajo.ruta, salida=carpeta,
                contexto_marca=self.ajustes.contexto_marca,
                glosario=self.ajustes.glosario,
                modelo_caption=self.ajustes.modelo_caption,
                idioma_ui=i18n.idioma_actual(),
                **valores,
            )
            trabajos.append((fila, config.to_json()))
        self._procesando = True
        self._refrescar_boton()
        self.ejecutor.iniciar(trabajos)

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

    def _al_avisar(self, fila: int, texto: str) -> None:
        self.modelo_cola.actualizar(fila, aviso=texto)

    def _al_terminar_trabajo(
        self, fila: int, ok: bool, salida: str, error: str
    ) -> None:
        if ok:
            self.modelo_cola.actualizar(
                fila, estado=EstadoTrabajo.HECHO, salida=Path(salida),
                percent=None, etiqueta="",
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
                self._limpiar_temporal(self.modelo_cola.trabajo(fila).ruta)

    def _limpiar_temporal(self, video: Path) -> None:
        """Borra los tmp ocultos que el runner dejó a medias al cancelar."""
        final = (
            PipelineConfig(video=video, salida=self.ajustes.carpeta_salida)
            .ruta_salida_final()
            .expanduser()
            .resolve()
        )
        final.with_name(f".{final.stem}_tmp{final.suffix}").unlink(
            missing_ok=True
        )
        final.with_name(f".{final.stem}_subs_tmp{final.suffix}").unlink(
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
            self.boton_procesar.setEnabled(bool(self.modelo_cola.pendientes()))
        self.boton_quitar.setEnabled(not self._procesando)
        self.boton_limpiar.setEnabled(not self._procesando)

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
    ventana = VentanaPrincipal(ajustes)
    ventana.resize(900, 560)
    ventana.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
