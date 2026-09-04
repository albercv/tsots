from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings


class Ajustes:
    def __init__(self, qsettings: QSettings | None = None):
        self._q = qsettings or QSettings("albercv", "LimpiadorVideo")

    @property
    def carpeta_salida(self) -> Path | None:
        valor = self._q.value("salida/carpeta", "")
        return Path(valor) if valor else None

    @carpeta_salida.setter
    def carpeta_salida(self, valor: Path | None) -> None:
        if valor is None:
            self._q.remove("salida/carpeta")
        else:
            self._q.setValue("salida/carpeta", str(valor))

    def guardar_panel(self, valores: dict) -> None:
        for clave, valor in valores.items():
            self._q.setValue(f"panel/{clave}", valor)

    def cargar_panel(self) -> dict:
        self._q.beginGroup("panel")
        valores = {clave: self._q.value(clave) for clave in self._q.childKeys()}
        self._q.endGroup()
        return valores

    def guardar_geometria(self, geometria: bytes) -> None:
        self._q.setValue("ventana/geometria", geometria)

    def cargar_geometria(self) -> bytes | None:
        valor = self._q.value("ventana/geometria")
        return valor if valor else None
