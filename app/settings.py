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

    @property
    def contexto_marca(self) -> str:
        return str(self._q.value("caption/contexto_marca", "") or "")

    @contexto_marca.setter
    def contexto_marca(self, texto: str) -> None:
        self._q.setValue("caption/contexto_marca", texto)

    @property
    def modelo_caption(self) -> str:
        return str(self._q.value("caption/modelo", "qwen3.5:9b") or "qwen3.5:9b")

    @modelo_caption.setter
    def modelo_caption(self, modelo: str) -> None:
        self._q.setValue("caption/modelo", modelo)

    @property
    def idioma_ui(self) -> str:
        return str(self._q.value("ui/idioma", "sistema") or "sistema")

    @idioma_ui.setter
    def idioma_ui(self, idioma: str) -> None:
        self._q.setValue("ui/idioma", idioma)

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
