from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from videopipeline.preview import extraer_frame, renderizar_preview

DEBOUNCE_MS = 300


class _Emisor(QObject):
    terminado = Signal(int, str, str)  # generación, ruta_png, error


class _TareaRender(QRunnable):
    def __init__(self, emisor: _Emisor, generacion: int, video: Path,
                 frame: Path, destino: Path, opciones: tuple, activo: bool):
        super().__init__()
        self._emisor = emisor
        self._generacion = generacion
        self._video = video
        self._frame = frame
        self._destino = destino
        self._opciones = opciones
        self._activo = activo

    def run(self) -> None:
        try:
            if not self._frame.is_file():
                # Módulo, no import directo: monkeypatcheable en tests.
                from app.widgets import vista_previa as _m

                _m.extraer_frame(self._video, self._frame)
            if not self._activo:
                self._emisor.terminado.emit(
                    self._generacion, str(self._frame), ""
                )
                return
            from app.widgets import vista_previa as _m

            diseno, posicion, tamano = self._opciones
            _m.renderizar_preview(
                self._frame, diseno, posicion, tamano, self._destino
            )
            self._emisor.terminado.emit(
                self._generacion, str(self._destino), ""
            )
        except Exception as error:  # noqa: BLE001 — placeholder, nunca romper
            self._emisor.terminado.emit(self._generacion, "", str(error))


class VistaPrevia(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.etiqueta = QLabel("Selecciona un vídeo de la cola")
        self.etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.etiqueta.setMinimumHeight(180)
        self.etiqueta.setMaximumHeight(260)
        self.etiqueta.setStyleSheet("color: #888;")
        layout.addWidget(self.etiqueta)

        self._video: Path | None = None
        self._opciones: tuple = ("reels_bold", 75, 100)
        self._activo = False
        self._generacion = 0
        self._pixmap_actual: QPixmap | None = None
        self._tmp_dir = tempfile.TemporaryDirectory(prefix="vista_previa_")
        self._tmp = Path(self._tmp_dir.name)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._emisor = _Emisor()
        self._emisor.terminado.connect(self._al_terminar)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._lanzar_render)

    def establecer_video(self, ruta: Path | None) -> None:
        self._video = ruta
        if ruta is None:
            self._generacion += 1
            self.etiqueta.setPixmap(QPixmap())
            self.etiqueta.setText("Selecciona un vídeo de la cola")
            return
        self._timer.start()

    def actualizar_opciones(self, diseno: str, posicion: int, tamano: int,
                            activo: bool) -> None:
        self._opciones = (diseno, posicion, tamano)
        self._activo = activo
        if self._video is not None:
            self._timer.start()

    def _lanzar_render(self) -> None:
        if self._video is None:
            return
        self._generacion += 1
        frame = self._tmp / f"{abs(hash(str(self._video)))}_frame.png"
        destino = self._tmp / f"render_{self._generacion}.png"
        tarea = _TareaRender(
            self._emisor, self._generacion, self._video, frame, destino,
            self._opciones, self._activo,
        )
        self._pool.start(tarea)

    def _al_terminar(self, generacion: int, ruta: str, error: str) -> None:
        if generacion != self._generacion:
            return
        if error:
            self._pixmap_actual = None
            self.etiqueta.setPixmap(QPixmap())
            self.etiqueta.setText(f"Preview no disponible: {error}")
            return
        pixmap = QPixmap(ruta)
        if pixmap.isNull():
            self._pixmap_actual = None
            self.etiqueta.setText("Preview no disponible")
            return
        self.etiqueta.setText("")
        self._pixmap_actual = pixmap
        self._repintar()

    def _repintar(self) -> None:
        if self._pixmap_actual is None:
            return
        self.etiqueta.setPixmap(
            self._pixmap_actual.scaled(
                self.etiqueta.width(), self.etiqueta.maximumHeight(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, evento) -> None:
        if self._pixmap_actual is not None:
            self._repintar()
        super().resizeEvent(evento)
