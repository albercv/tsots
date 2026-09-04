from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

BASE_DIR = Path(__file__).resolve().parent.parent


class EjecutorCola(QObject):
    progreso = Signal(int, dict)
    trabajo_iniciado = Signal(int)  # fila
    trabajo_terminado = Signal(int, bool, str, str)  # fila, ok, salida, error
    aviso = Signal(int, str)  # fila, texto
    cola_terminada = Signal()

    PROGRAMA = [sys.executable, "-m", "videopipeline.runner"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pendientes: list[tuple[int, str]] = []
        self._proceso: QProcess | None = None
        self._fila_actual: int = -1
        self._cancelado = False
        self._error_actual = ""
        self._salida_actual = ""
        self._buffer = ""
        self._config_tmp: Path | None = None
        self._activo = False

    def iniciar(self, trabajos: list[tuple[int, str]]) -> None:
        if self._activo or self._proceso is not None:
            return
        self._activo = True
        self._pendientes = list(trabajos)
        self._cancelado = False
        self._siguiente()

    def cancelar(self) -> None:
        self._cancelado = True
        self._pendientes.clear()
        if self._proceso is not None:
            self._proceso.terminate()
            if not self._proceso.waitForFinished(3000):
                self._proceso.kill()

    def _siguiente(self) -> None:
        if not self._pendientes:
            self._activo = False
            self.cola_terminada.emit()
            return
        fila, config_json = self._pendientes.pop(0)
        self._fila_actual = fila
        self._error_actual = ""
        self._salida_actual = ""
        self._buffer = ""

        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        tmp.write(config_json)
        tmp.close()
        self._config_tmp = Path(tmp.name)

        proceso = QProcess(self)
        proceso.setWorkingDirectory(str(BASE_DIR))
        proceso.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels
        )
        proceso.readyReadStandardOutput.connect(self._leer)
        proceso.finished.connect(self._terminado)
        proceso.errorOccurred.connect(self._error_proceso)
        self._proceso = proceso
        programa, *args = self.PROGRAMA
        proceso.start(programa, [*args, "--config", str(self._config_tmp)])
        self.trabajo_iniciado.emit(fila)

    def _leer(self) -> None:
        if self._proceso is None:
            return
        self._buffer += bytes(
            self._proceso.readAllStandardOutput()
        ).decode("utf-8", errors="replace")
        self._buffer = self._buffer.replace("\r\n", "\n").replace("\r", "\n")
        while "\n" in self._buffer:
            linea, self._buffer = self._buffer.split("\n", 1)
            linea = linea.strip()
            if not linea:
                continue
            try:
                evento = json.loads(linea)
            except json.JSONDecodeError:
                continue  # ruido de librerías por stdout
            if not isinstance(evento, dict):
                continue  # ruido de librerías por stdout (JSON no-objeto)
            if "error" in evento:
                self._error_actual = evento["error"]
            elif evento.get("done"):
                self._salida_actual = evento.get("salida", "")
            elif "warning" in evento:
                self.aviso.emit(self._fila_actual, str(evento["warning"]))
            else:
                self.progreso.emit(self._fila_actual, evento)

    def _error_proceso(self, error) -> None:
        if error != QProcess.ProcessError.FailedToStart:
            return  # otros errores (p.ej. Crashed) los gestiona `finished`
        self._error_actual = "No se pudo lanzar el proceso"
        self._terminado(-1, None)

    def _terminado(self, codigo: int, _estado) -> None:
        if self._proceso is None:
            return  # ya gestionado (p.ej. por _error_proceso); evita doble emisión
        proceso_anterior = self._proceso
        self._leer()
        if self._config_tmp is not None:
            self._config_tmp.unlink(missing_ok=True)
            self._config_tmp = None
        ok = codigo == 0 and not self._cancelado and self._salida_actual != ""
        error = self._error_actual
        if self._cancelado:
            error = "Cancelado"
        elif not ok and not error:
            error = f"El proceso terminó con código {codigo}"
        self._proceso = None
        proceso_anterior.deleteLater()
        self.trabajo_terminado.emit(
            self._fila_actual, ok, self._salida_actual, "" if ok else error
        )
        if self._cancelado:
            self._activo = False
            self.cola_terminada.emit()
        else:
            self._siguiente()
