from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
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

from videopipeline.caption import Caption, leer_md
from videopipeline.config import PipelineConfig

from .queue_model import EstadoTrabajo, ModeloCola
from .settings import Ajustes
from .widgets.dialogo_marca import DialogoMarca
from .widgets.panel_caption import PanelCaption
from .widgets.panel_opciones import PanelOpciones
from .widgets.vista_previa import VistaPrevia
from .widgets.zona_drop import ZonaDrop
from .worker import EjecutorCola


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
        self.setWindowTitle("The Silence of the Shorts")
        self.ajustes = ajustes or Ajustes()
        self.modelo_cola = ModeloCola(self)
        self.ejecutor = EjecutorCola(self)
        self._procesando = False

        central = QWidget()
        raiz = QVBoxLayout(central)
        fila_superior = QHBoxLayout()

        columna_izquierda = QVBoxLayout()
        self.zona_drop = ZonaDrop()
        self.zona_drop.archivos_soltados.connect(self.anadir_videos)
        columna_izquierda.addWidget(self.zona_drop)

        self.vista_cola = QListView()
        self.vista_cola.setModel(self.modelo_cola)
        self.vista_cola.doubleClicked.connect(self._abrir_resultado)
        columna_izquierda.addWidget(QLabel("Cola"))
        columna_izquierda.addWidget(self.vista_cola, 1)

        fila_botones_cola = QHBoxLayout()
        self.boton_quitar = QPushButton("Quitar")
        self.boton_quitar.clicked.connect(self._quitar_seleccionado)
        self.boton_limpiar = QPushButton("Limpiar hechos")
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
        self.boton_carpeta = QPushButton("Cambiar…")
        self.boton_carpeta.clicked.connect(self._elegir_carpeta)
        self.boton_procesar = QPushButton("▶ Procesar")
        self.boton_procesar.clicked.connect(self._procesar_o_cancelar)
        fila_inferior.addWidget(QLabel("Salida:"))
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
                "Sin pista de audio",
                f"Estos vídeos no tienen audio y no se han añadido:\n{nombres}",
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
            lineas.append(f"Paso: {diag['paso']}")
        if diag.get("causa"):
            lineas.append(f"<br>Causa: {diag['causa']}")
        if diag.get("solucion"):
            lineas.append(f"<br>Qué hacer: {diag['solucion']}")
        if not diag:
            lineas.append(trabajo.error)
        dialogo = QMessageBox(self)
        dialogo.setIcon(QMessageBox.Icon.Critical)
        dialogo.setWindowTitle(f"Error: {titulo}")
        dialogo.setText("<br>".join(lineas))
        detalle = diag.get("detalle") or trabajo.error
        if detalle:
            dialogo.setDetailedText(detalle)
        dialogo.addButton(QMessageBox.StandardButton.Close)
        log = diag.get("log")
        if log and Path(log).is_file():
            boton_log = dialogo.addButton(
                "Abrir log", QMessageBox.ButtonRole.ActionRole
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
            self.panel_caption.mostrar(self._caption_de(trabajo))
        else:
            self.vista_previa.establecer_video(None)
            self.panel_caption.mostrar(None)

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
            str(carpeta) if carpeta else "Junto al original (_limpio.mp4)"
        )

    def _elegir_carpeta(self) -> None:
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de salida")
        if carpeta:
            self.ajustes.carpeta_salida = Path(carpeta)
            self._refrescar_etiqueta_salida()

    def _editar_marca(self) -> None:
        dialogo = DialogoMarca(self.ajustes.contexto_marca, self)
        if dialogo.exec():
            self.ajustes.contexto_marca = dialogo.texto()

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
                modelo_caption=self.ajustes.modelo_caption,
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
                self.panel_caption.mostrar(
                    self._caption_de(self.modelo_cola.trabajo(fila))
                )
        else:
            estado = (
                EstadoTrabajo.CANCELADO
                if error == "Cancelado"
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
            self.boton_procesar.setText("■ Cancelar")
            self.boton_procesar.setEnabled(True)
        else:
            self.boton_procesar.setText("▶ Procesar")
            self.boton_procesar.setEnabled(bool(self.modelo_cola.pendientes()))
        self.boton_quitar.setEnabled(not self._procesando)
        self.boton_limpiar.setEnabled(not self._procesando)

    # --- ciclo de vida ---

    def closeEvent(self, evento) -> None:
        if self._procesando:
            respuesta = QMessageBox.question(
                self,
                "Proceso en curso",
                "Hay un vídeo procesándose. ¿Cancelar y salir?",
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                evento.ignore()
                return
            self.ejecutor.cancelar()
        self.ajustes.guardar_geometria(bytes(self.saveGeometry()))
        evento.accept()


def main() -> int:
    app = QApplication(sys.argv)
    faltan = _dependencias_faltantes()
    if faltan:
        QMessageBox.critical(
            None,
            "Faltan dependencias",
            "No se encuentran en PATH: " + ", ".join(faltan)
            + "\nInstálalas y vuelve a abrir la aplicación.",
        )
        return 1
    ventana = VentanaPrincipal()
    ventana.resize(900, 560)
    ventana.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
