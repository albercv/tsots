from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from videopipeline.i18n import N_, _

if TYPE_CHECKING:
    from videopipeline.ficha import Ficha


class EstadoTrabajo(Enum):
    ESPERA = N_("en espera")
    PROCESANDO = N_("procesando")
    HECHO = N_("hecho")
    ERROR = N_("error")
    CANCELADO = N_("cancelado")


_TERMINADOS = (EstadoTrabajo.HECHO, EstadoTrabajo.ERROR, EstadoTrabajo.CANCELADO)
_ACTIVOS = (EstadoTrabajo.ESPERA, EstadoTrabajo.PROCESANDO)
_NOMBRE_PASO = {
    "audio": N_("audio"),
    "silencios": N_("silencios"),
    "subtitulos": N_("subtítulos"),
    "caption": N_("caption"),
    "vertical": N_("vertical"),
}


def resumen_de(ficha: Ficha) -> str:
    """Lo que el vídeo ya tiene: «✓ audio · silencios · subtítulos · caption»."""
    desactualizado = "vertical" in ficha.desactualizado
    partes = [
        _(_NOMBRE_PASO[paso]) for paso in ficha.pasos_hechos()
        if not (desactualizado and paso == "vertical")  # se avisa abajo, una vez
    ]
    if desactualizado:
        partes.append(_("vertical desactualizado"))
    return "✓ " + " · ".join(partes) if partes else ""


@dataclass
class Trabajo:
    ruta: Path
    estado: EstadoTrabajo = EstadoTrabajo.ESPERA
    percent: float | None = None
    etiqueta: str = ""
    error: str = ""
    aviso: str = ""
    salida: Path | None = None
    salida_vertical: Path | None = None
    diagnostico: dict | None = None  # titulo, causa, solucion, detalle, paso, log
    ficha_id: str | None = None
    resumen: str = ""
    ocupa: int = 0  # bytes de la ficha


class ModeloCola(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._trabajos: list[Trabajo] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._trabajos)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        trabajo = self._trabajos[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            partes = [trabajo.ruta.name, "—", _(trabajo.estado.value)]
            if trabajo.estado == EstadoTrabajo.PROCESANDO:
                if trabajo.etiqueta:
                    partes.append(f"· {trabajo.etiqueta}")
                if trabajo.percent is not None:
                    partes.append(f"({trabajo.percent:.0f}%)")
            if trabajo.estado == EstadoTrabajo.ERROR and trabajo.error:
                # Primera línea = título legible; el resto va al tooltip/diálogo.
                partes.append(f"· {trabajo.error.splitlines()[0]}")
            if trabajo.estado == EstadoTrabajo.HECHO and trabajo.salida_vertical:
                partes.append(_("+ vertical"))
            if trabajo.resumen:
                partes.append(trabajo.resumen)
            if trabajo.ocupa > 0:
                partes.append(f"· {round(trabajo.ocupa / 1_000_000)} MB")
            if trabajo.aviso:
                partes.append("⚠")
            return " ".join(partes)
        if role == Qt.ItemDataRole.ToolTipRole:
            piezas = [t for t in (trabajo.error, trabajo.aviso) if t]
            if trabajo.salida_vertical:
                piezas.append(_("Vertical: {ruta}").format(ruta=trabajo.salida_vertical))
            return "\n".join(piezas) if piezas else None
        if role == Qt.ItemDataRole.ForegroundRole:
            if trabajo.estado == EstadoTrabajo.ERROR:
                return QBrush(QColor("#c62828"))
            if trabajo.estado == EstadoTrabajo.CANCELADO:
                return QBrush(QColor("#888888"))
        return None

    def trabajo(self, fila: int) -> Trabajo:
        return self._trabajos[fila]

    def anadir(self, entradas: list[tuple[Path, str | None]]) -> list[int]:
        """Añade (ruta, ficha_id). Devuelve las filas nuevas o reactivadas."""
        filas = []
        for ruta, ficha_id in entradas:
            fila = None if ficha_id is None else self.fila_de_ficha(ficha_id)
            if fila is not None:
                # Ya está en la cola: si terminó se repite; si espera, no se toca.
                if self._trabajos[fila].estado in _TERMINADOS:
                    self.volver_a_espera([fila])
                    filas.append(fila)
                continue
            if ficha_id is None and any(
                t.ruta == ruta and t.estado in _ACTIVOS for t in self._trabajos
            ):
                continue
            fila = len(self._trabajos)
            self.beginInsertRows(QModelIndex(), fila, fila)
            self._trabajos.append(Trabajo(ruta=ruta, ficha_id=ficha_id))
            self.endInsertRows()
            filas.append(fila)
        return filas

    def fila_de_ficha(self, ficha_id: str) -> int | None:
        return next(
            (f for f, t in enumerate(self._trabajos) if t.ficha_id == ficha_id), None)

    def volver_a_espera(self, filas: list[int]) -> None:
        """Repite los trabajos terminados; los que esperan o procesan no se tocan."""
        for fila in filas:
            if self._trabajos[fila].estado in _TERMINADOS:
                self.actualizar(
                    fila, estado=EstadoTrabajo.ESPERA, error="", aviso="",
                    percent=None, diagnostico=None)

    def quitar(self, fila: int) -> None:
        if not 0 <= fila < len(self._trabajos):
            return
        self.beginRemoveRows(QModelIndex(), fila, fila)
        del self._trabajos[fila]
        self.endRemoveRows()

    def limpiar_hechos(self) -> None:
        for fila in range(len(self._trabajos) - 1, -1, -1):
            if self._trabajos[fila].estado == EstadoTrabajo.HECHO:
                self.quitar(fila)

    def pendientes(self) -> list[int]:
        return [
            fila
            for fila, t in enumerate(self._trabajos)
            if t.estado == EstadoTrabajo.ESPERA
        ]

    def actualizar(self, fila: int, **cambios) -> None:
        trabajo = self._trabajos[fila]
        for clave, valor in cambios.items():
            setattr(trabajo, clave, valor)
        indice = self.index(fila)
        self.dataChanged.emit(indice, indice)
