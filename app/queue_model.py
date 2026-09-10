from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor


class EstadoTrabajo(Enum):
    ESPERA = "en espera"
    PROCESANDO = "procesando"
    HECHO = "hecho"
    ERROR = "error"
    CANCELADO = "cancelado"


@dataclass
class Trabajo:
    ruta: Path
    estado: EstadoTrabajo = EstadoTrabajo.ESPERA
    percent: float | None = None
    etiqueta: str = ""
    error: str = ""
    aviso: str = ""
    salida: Path | None = None
    diagnostico: dict | None = None  # titulo, causa, solucion, detalle, paso, log


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
            partes = [trabajo.ruta.name, "—", trabajo.estado.value]
            if trabajo.estado == EstadoTrabajo.PROCESANDO:
                if trabajo.etiqueta:
                    partes.append(f"· {trabajo.etiqueta}")
                if trabajo.percent is not None:
                    partes.append(f"({trabajo.percent:.0f}%)")
            if trabajo.estado == EstadoTrabajo.ERROR and trabajo.error:
                # Primera línea = título legible; el resto va al tooltip/diálogo.
                partes.append(f"· {trabajo.error.splitlines()[0]}")
            if trabajo.aviso:
                partes.append("⚠")
            return " ".join(partes)
        if role == Qt.ItemDataRole.ToolTipRole:
            piezas = [t for t in (trabajo.error, trabajo.aviso) if t]
            return "\n".join(piezas) if piezas else None
        if role == Qt.ItemDataRole.ForegroundRole:
            if trabajo.estado == EstadoTrabajo.ERROR:
                return QBrush(QColor("#c62828"))
            if trabajo.estado == EstadoTrabajo.CANCELADO:
                return QBrush(QColor("#888888"))
        return None

    def trabajo(self, fila: int) -> Trabajo:
        return self._trabajos[fila]

    def anadir(self, rutas: list[Path]) -> list[Path]:
        existentes = {
            t.ruta for t in self._trabajos
            if t.estado in (EstadoTrabajo.ESPERA, EstadoTrabajo.PROCESANDO)
        }
        nuevas = []
        for r in rutas:
            if r not in existentes:
                nuevas.append(r)
                existentes.add(r)  # Track within this call to dedupe
        if not nuevas:
            return []
        inicio = len(self._trabajos)
        self.beginInsertRows(QModelIndex(), inicio, inicio + len(nuevas) - 1)
        self._trabajos.extend(Trabajo(ruta=r) for r in nuevas)
        self.endInsertRows()
        return nuevas

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
