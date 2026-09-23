from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from videopipeline.redes.modelo import (
    ORDEN,
    YOUTUBE_CATEGORIA_POR_DEFECTO,
    ModoInstagram,
    ModoTikTok,
    Plataforma,
)
from videopipeline.redes.proveedor import PROVEEDOR_POR_DEFECTO, PROVEEDORES


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
    def glosario(self) -> str:
        return str(self._q.value("transcripcion/glosario", "") or "")

    @glosario.setter
    def glosario(self, texto: str) -> None:
        self._q.setValue("transcripcion/glosario", texto)

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

    # --- redes (nada secreto: la API key va al Llavero) ---

    @property
    def proveedor_redes(self) -> str:
        valor = str(self._q.value("redes/proveedor", PROVEEDOR_POR_DEFECTO) or "")
        return valor if valor in PROVEEDORES else PROVEEDOR_POR_DEFECTO

    @proveedor_redes.setter
    def proveedor_redes(self, nombre: str) -> None:
        self._q.setValue("redes/proveedor", nombre)

    def perfil_de(self, proveedor: str) -> str:
        return str(self._q.value(f"redes/perfil/{proveedor}", "") or "")

    def guardar_perfil(self, proveedor: str, perfil: str) -> None:
        self._q.setValue(f"redes/perfil/{proveedor}", perfil.strip())

    @property
    def perfil_redes(self) -> str:
        return self.perfil_de(self.proveedor_redes)

    @perfil_redes.setter
    def perfil_redes(self, perfil: str) -> None:
        self.guardar_perfil(self.proveedor_redes, perfil)

    def ajustes_proveedor(self) -> dict[str, str]:
        """Datos no secretos que recibe `proveedor.crear`."""
        return {"perfil": self.perfil_redes}

    @property
    def youtube_categoria(self) -> str:
        return str(self._q.value("redes/youtube_categoria", YOUTUBE_CATEGORIA_POR_DEFECTO)
                   or YOUTUBE_CATEGORIA_POR_DEFECTO)

    @youtube_categoria.setter
    def youtube_categoria(self, categoria: str) -> None:
        self._q.setValue("redes/youtube_categoria", categoria)

    @property
    def tiktok_modo(self) -> ModoTikTok:
        try:
            return ModoTikTok(self._q.value("redes/tiktok_modo", ModoTikTok.BORRADOR.value))
        except ValueError:
            return ModoTikTok.BORRADOR

    @tiktok_modo.setter
    def tiktok_modo(self, modo: ModoTikTok) -> None:
        self._q.setValue("redes/tiktok_modo", ModoTikTok(modo).value)

    @property
    def instagram_modo(self) -> ModoInstagram:
        try:
            return ModoInstagram(self._q.value("redes/instagram_modo",
                                               ModoInstagram.PRUEBA.value))
        except ValueError:
            return ModoInstagram.PRUEBA

    @instagram_modo.setter
    def instagram_modo(self, modo: ModoInstagram) -> None:
        self._q.setValue("redes/instagram_modo", ModoInstagram(modo).value)

    @property
    def plataformas_redes(self) -> list[Plataforma]:
        """Plataformas marcadas la última vez (todas si nunca se publicó)."""
        valor = self._q.value("redes/plataformas")
        if valor is None:
            return list(ORDEN)
        nombres = str(valor).split(",") if not isinstance(valor, list) else valor
        return [p for p in ORDEN if p.value in {n.strip() for n in nombres}]

    @plataformas_redes.setter
    def plataformas_redes(self, plataformas) -> None:
        elegidas = {Plataforma(p) for p in plataformas}
        self._q.setValue("redes/plataformas",
                         ",".join(p.value for p in ORDEN if p in elegidas))

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
