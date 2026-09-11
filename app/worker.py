from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from videopipeline.errores import Diagnostico, explicar, explicar_codigo_salida
from videopipeline.i18n import _

BASE_DIR = Path(__file__).resolve().parent.parent

# Líneas no-JSON que se conservan por si el runner muere sin emitir error.
MAX_RUIDO = 80


class EjecutorCola(QObject):
    progreso = Signal(int, dict)
    trabajo_iniciado = Signal(int)  # fila
    trabajo_terminado = Signal(int, bool, str, str)  # fila, ok, salida, error
    # fila, diagnóstico (titulo, causa, solucion, detalle, conocido, paso, log).
    # Se emite ANTES de trabajo_terminado cuando el trabajo falla.
    diagnostico = Signal(int, dict)
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
        self._error_evento: dict | None = None
        self._salida_actual = ""
        self._buffer = ""
        self._ruido: list[str] = []
        self._ultimo_paso = ""
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
        self._error_evento = None
        self._salida_actual = ""
        self._buffer = ""
        self._ruido = []
        self._ultimo_paso = ""

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
                self._recordar_ruido(linea)  # tracebacks, avisos de librerías
                continue
            if not isinstance(evento, dict):
                self._recordar_ruido(linea)
                continue
            if "error" in evento:
                self._error_actual = evento["error"]
                self._error_evento = evento
            elif evento.get("done"):
                self._salida_actual = evento.get("salida", "")
            elif "warning" in evento:
                self.aviso.emit(self._fila_actual, str(evento["warning"]))
            else:
                if evento.get("label"):
                    self._ultimo_paso = str(evento["label"])
                self.progreso.emit(self._fila_actual, evento)

    def _recordar_ruido(self, linea: str) -> None:
        self._ruido.append(linea)
        if len(self._ruido) > MAX_RUIDO:
            del self._ruido[: len(self._ruido) - MAX_RUIDO]

    def _error_proceso(self, error) -> None:
        if error != QProcess.ProcessError.FailedToStart:
            return  # otros errores (p.ej. Crashed) los gestiona `finished`
        self._error_actual = _("No se pudo lanzar el proceso")
        self._terminado(-1, None)

    def _diagnostico_estructurado(self) -> dict | None:
        """Diagnóstico que el runner emitió en su evento de error, si lo hay."""
        evento = self._error_evento or {}
        base = evento.get("diagnostico")
        if not isinstance(base, dict):
            return None
        return {
            **base,
            "paso": str(evento.get("paso") or self._ultimo_paso),
            "log": str(evento.get("log") or ""),
        }

    def _diagnostico_por_muerte(self, codigo: int, estado) -> dict:
        """El runner murió sin reportar: reconstruye qué se sabe.

        Qt en Unix entrega, para CrashExit, el NÚMERO DE SEÑAL en `codigo`.
        """
        if estado == QProcess.ExitStatus.CrashExit:
            mensaje = _("El proceso murió por una señal (código {codigo})").format(
                codigo=codigo
            )
            senal = explicar_codigo_salida(-codigo)
        else:
            mensaje = _(
                "El proceso terminó inesperadamente (código {codigo})"
            ).format(codigo=codigo)
            senal = explicar_codigo_salida(codigo)
        if self._ultimo_paso:
            mensaje += _(" en «{paso}»").format(paso=self._ultimo_paso)
        partes = []
        if senal:
            partes.append(senal)
        if self._error_actual:
            partes.append(self._error_actual)
        if self._ruido:
            partes.append(
                _("Salida del proceso (últimas líneas):") + "\n"
                + "\n".join(self._ruido)
            )
        diag = explicar(mensaje, "\n".join(partes))
        if not diag.conocido and senal:
            diag.causa = senal
        return {
            "titulo": diag.titulo, "causa": diag.causa,
            "solucion": diag.solucion, "detalle": diag.detalle,
            "conocido": diag.conocido,
            "paso": self._ultimo_paso, "log": "",
        }

    def _terminado(self, codigo: int, estado) -> None:
        if self._proceso is None:
            return  # ya gestionado (p.ej. por _error_proceso); evita doble emisión
        proceso_anterior = self._proceso
        self._leer()
        if self._config_tmp is not None:
            self._config_tmp.unlink(missing_ok=True)
            self._config_tmp = None
        crash = estado == QProcess.ExitStatus.CrashExit
        ok = (codigo == 0 and not crash and not self._cancelado
              and self._salida_actual != "")
        error = self._error_actual
        diagnostico: dict | None = None
        if self._cancelado:
            error = _("Cancelado")
        elif not ok:
            diagnostico = self._diagnostico_estructurado()
            if diagnostico is None:
                diagnostico = self._diagnostico_por_muerte(codigo, estado)
            error = Diagnostico(
                **{k: diagnostico[k]
                   for k in ("titulo", "causa", "solucion", "detalle", "conocido")}
            ).texto()
        self._proceso = None
        proceso_anterior.deleteLater()
        if diagnostico is not None:
            self.diagnostico.emit(self._fila_actual, diagnostico)
        self.trabajo_terminado.emit(
            self._fila_actual, ok, self._salida_actual, "" if ok else error
        )
        if self._cancelado:
            self._activo = False
            self.cola_terminada.emit()
        else:
            self._siguiente()
