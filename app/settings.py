from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings

from videopipeline.redes.modelo import (
    ORDEN,
    YOUTUBE_CATEGORIA_POR_DEFECTO,
    Cuenta,
    ModoFacebook,
    ModoInstagram,
    ModoTikTok,
    Pagina,
    Plataforma,
)
from videopipeline.redes.proveedor import PROVEEDOR_POR_DEFECTO, PROVEEDORES

# Marcadas la primera vez. X y Facebook se activan a mano: pueden no estar en
# el plan del servicio y Facebook necesita una página.
PLATAFORMAS_POR_DEFECTO = (Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM)


@dataclass(frozen=True)
class CuentasGuardadas:
    """Última consulta de cuentas que salió bien. Una plataforma que no está
    en `cuentas` es desconocida; con valor `None`, no conectada."""

    cuentas: dict[Plataforma, Cuenta | None]
    fecha: str  # ISO 8601


def _a_bool(valor) -> bool:
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in ("true", "1", "yes")


def _cuenta_a_dict(cuenta: Cuenta | None) -> dict | None:
    if cuenta is None:
        return None
    return {"nombre": cuenta.nombre, "usuario": cuenta.usuario,
            "reconectar": cuenta.reconectar, "capacidades": list(cuenta.capacidades),
            "premium": cuenta.premium}


def _cuenta_de_dict(plataforma: Plataforma, datos) -> Cuenta | None:
    if not isinstance(datos, dict):
        return None
    premium = datos.get("premium")
    return Cuenta(plataforma, nombre=str(datos.get("nombre") or ""),
                  usuario=str(datos.get("usuario") or ""),
                  reconectar=bool(datos.get("reconectar")),
                  capacidades=tuple(str(c) for c in datos.get("capacidades") or ()),
                  premium=premium if isinstance(premium, bool) else None)


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
        pagina = self.pagina_facebook
        return {"perfil": self.perfil_redes, "pagina_facebook": pagina.id if pagina else ""}

    # Página de Facebook elegida (Meta solo deja publicar en páginas). Es un
    # dato no secreto que se guarda por proveedor, como el perfil.

    def pagina_facebook_de(self, proveedor: str) -> Pagina | None:
        ident = str(self._q.value(f"redes/facebook_pagina/{proveedor}", "") or "").strip()
        if not ident:
            return None
        nombre = str(self._q.value(f"redes/facebook_pagina_nombre/{proveedor}", "") or "")
        return Pagina(ident, nombre)

    def guardar_pagina_facebook(self, proveedor: str, pagina: Pagina | None) -> None:
        if pagina is None or not pagina.id.strip():
            self._q.remove(f"redes/facebook_pagina/{proveedor}")
            self._q.remove(f"redes/facebook_pagina_nombre/{proveedor}")
            return
        self._q.setValue(f"redes/facebook_pagina/{proveedor}", pagina.id.strip())
        self._q.setValue(f"redes/facebook_pagina_nombre/{proveedor}", pagina.nombre.strip())

    @property
    def pagina_facebook(self) -> Pagina | None:
        return self.pagina_facebook_de(self.proveedor_redes)

    @pagina_facebook.setter
    def pagina_facebook(self, pagina: Pagina | None) -> None:
        self.guardar_pagina_facebook(self.proveedor_redes, pagina)

    # Cuentas conectadas en el servicio: la última consulta que salió bien,
    # para seguir sin conexión. Solo nombres visibles, nada secreto.

    def cuentas_guardadas(self) -> CuentasGuardadas | None:
        """Las del perfil actual; `None` si no hay o son de otro perfil."""
        bruto = self._q.value(f"redes/cuentas/{self.proveedor_redes}")
        try:
            datos = json.loads(str(bruto)) if bruto else None
        except ValueError:
            return None
        if not isinstance(datos, dict) or datos.get("perfil") != self.perfil_redes:
            return None
        cuentas_json = datos.get("cuentas")
        if not isinstance(cuentas_json, dict):
            return None
        cuentas = {p: _cuenta_de_dict(p, cuentas_json[p.value])
                   for p in Plataforma if p.value in cuentas_json}
        return CuentasGuardadas(cuentas, str(datos.get("fecha") or ""))

    def guardar_cuentas(self, cuentas: dict[Plataforma, Cuenta | None],
                        fecha: datetime | None = None) -> None:
        datos = {
            "perfil": self.perfil_redes,
            "fecha": (fecha or datetime.now()).isoformat(timespec="seconds"),
            "cuentas": {Plataforma(p).value: _cuenta_a_dict(c) for p, c in cuentas.items()},
        }
        self._q.setValue(f"redes/cuentas/{self.proveedor_redes}",
                         json.dumps(datos, ensure_ascii=False))

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
    def x_premium(self) -> bool:
        """Lo declara el usuario: con Premium, X admite vídeos largos y
        textos de más de 280 caracteres."""
        return _a_bool(self._q.value("redes/x_premium", False))

    @x_premium.setter
    def x_premium(self, activo: bool) -> None:
        self._q.setValue("redes/x_premium", bool(activo))

    @property
    def facebook_modo(self) -> ModoFacebook:
        try:
            return ModoFacebook(self._q.value("redes/facebook_modo", ModoFacebook.REEL.value))
        except ValueError:
            return ModoFacebook.REEL

    @facebook_modo.setter
    def facebook_modo(self, modo: ModoFacebook) -> None:
        self._q.setValue("redes/facebook_modo", ModoFacebook(modo).value)

    @property
    def plataformas_redes(self) -> list[Plataforma]:
        """Plataformas marcadas la última vez. Si nunca se publicó, las de
        `PLATAFORMAS_POR_DEFECTO`. Una elección guardada antes de que
        existieran X y Facebook sigue valiendo: quedan desmarcadas."""
        valor = self._q.value("redes/plataformas")
        if valor is None:
            return list(PLATAFORMAS_POR_DEFECTO)
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
