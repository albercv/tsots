from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings

from .credenciales import huella_perfil
from videopipeline.redes.modelo import (
    ORDEN,
    UBICACION_POR_DEFECTO,
    YOUTUBE_CATEGORIA_POR_DEFECTO,
    Ciudad,
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


# Cada dato por perfil, con su clave de antes: la que leen las versiones
# anteriores y la que se usa sin perfil activo.
_GLOBALES = {
    "contexto_marca": "caption/contexto_marca",
    "ciudad": "redes/ciudad",
    "facebook_pagina": "redes/facebook_pagina/{proveedor}",
    "facebook_pagina_nombre": "redes/facebook_pagina_nombre/{proveedor}",
    "plataformas": "redes/plataformas",
    "tiktok_modo": "redes/tiktok_modo",
    "instagram_modo": "redes/instagram_modo",
    "facebook_modo": "redes/facebook_modo",
    "x_premium": "redes/x_premium",
    "youtube_categoria": "redes/youtube_categoria",
    "cuentas": "redes/cuentas/{proveedor}",
}


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
            "premium": cuenta.premium, "ubicacion": cuenta.ubicacion}


def _cuenta_de_dict(plataforma: Plataforma, datos) -> Cuenta | None:
    if not isinstance(datos, dict):
        return None
    premium = datos.get("premium")
    ubicacion = datos.get("ubicacion")
    return Cuenta(plataforma, nombre=str(datos.get("nombre") or ""),
                  usuario=str(datos.get("usuario") or ""),
                  reconectar=bool(datos.get("reconectar")),
                  capacidades=tuple(str(c) for c in datos.get("capacidades") or ()),
                  premium=premium if isinstance(premium, bool) else None,
                  ubicacion=ubicacion if isinstance(ubicacion, bool) else None)


class Ajustes:
    def __init__(self, qsettings: QSettings | None = None):
        self._q = qsettings or QSettings("albercv", "LimpiadorVideo")
        self._fijo: tuple[str, str] | None = None
        # Migración la primera vez; recoge también un activo que una versión
        # anterior puso y no está en la lista.
        for proveedor in PROVEEDORES:
            if activo := self.perfil_de(proveedor):
                self.anadir_perfil(proveedor, activo)

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
        return str(self._q.value(self._clave("contexto_marca"), "") or "")

    @contexto_marca.setter
    def contexto_marca(self, texto: str) -> None:
        self._q.setValue(self._clave("contexto_marca"), texto)

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
        self.anadir_perfil(proveedor, perfil)

    def _contexto(self) -> tuple[str, str]:
        """(proveedor, perfil) al que se refieren las propiedades por perfil."""
        return self._fijo or (self.proveedor_redes, self.perfil_redes)

    @staticmethod
    def _clave_de(proveedor: str, perfil: str, nombre: str) -> str:
        if perfil:
            return f"redes/perfil_datos/{proveedor}/{huella_perfil(perfil)}/{nombre}"
        return _GLOBALES[nombre].format(proveedor=proveedor)

    def _clave(self, nombre: str) -> str:
        return self._clave_de(*self._contexto(), nombre)

    def de_perfil(self, proveedor: str, perfil: str) -> Ajustes:
        """Vista con los mismos QSettings cuyas propiedades por perfil leen y
        escriben `perfil`, sin cambiar el activo."""
        copia = copy.copy(self)
        copia._fijo = (proveedor, perfil.strip())
        return copia

    def perfiles_de(self, proveedor: str) -> list[str]:
        try:
            lista = json.loads(str(self._q.value(f"redes/perfiles/{proveedor}", "") or "[]"))
        except ValueError:
            return []
        if not isinstance(lista, list):
            return []
        return [p.strip() for p in lista if isinstance(p, str) and p.strip()]

    def anadir_perfil(self, proveedor: str, perfil: str) -> None:
        perfil = perfil.strip()
        lista_clave = f"redes/perfiles/{proveedor}"
        if not perfil:
            return
        if not self._q.contains(lista_clave):
            # El primer perfil hereda lo de siempre; solo lo que aún no tiene.
            for nombre, plantilla in _GLOBALES.items():
                origen = plantilla.format(proveedor=proveedor)
                destino = self._clave_de(proveedor, perfil, nombre)
                if self._q.contains(origen) and not self._q.contains(destino):
                    self._q.setValue(destino, self._q.value(origen))
        perfiles = self.perfiles_de(proveedor)
        if perfil not in perfiles:
            self._q.setValue(lista_clave, json.dumps([*perfiles, perfil], ensure_ascii=False))

    def quitar_perfil(self, proveedor: str, perfil: str) -> None:
        perfil = perfil.strip()
        # La lista se queda aunque quede vacía: así no se vuelve a heredar.
        quedan = [p for p in self.perfiles_de(proveedor) if p != perfil]
        self._q.setValue(f"redes/perfiles/{proveedor}", json.dumps(quedan, ensure_ascii=False))
        self._q.remove(f"redes/perfil_datos/{proveedor}/{huella_perfil(perfil)}")
        if self.perfil_de(proveedor) == perfil:
            self._q.setValue(f"redes/perfil/{proveedor}", quedan[0] if quedan else "")

    @property
    def perfil_redes(self) -> str:
        return self.perfil_de(self.proveedor_redes)

    @perfil_redes.setter
    def perfil_redes(self, perfil: str) -> None:
        self.guardar_perfil(self.proveedor_redes, perfil)

    def ajustes_proveedor(self) -> dict[str, str]:
        """Datos no secretos que recibe `proveedor.crear`."""
        pagina = self.pagina_facebook
        return {"perfil": self._contexto()[1], "pagina_facebook": pagina.id if pagina else ""}

    # Página de Facebook elegida (Meta solo deja publicar en páginas). Dato no
    # secreto, por perfil.

    @property
    def pagina_facebook(self) -> Pagina | None:
        ident = str(self._q.value(self._clave("facebook_pagina"), "") or "").strip()
        if not ident:
            return None
        return Pagina(ident, str(self._q.value(self._clave("facebook_pagina_nombre"), "") or ""))

    @pagina_facebook.setter
    def pagina_facebook(self, pagina: Pagina | None) -> None:
        if pagina is None or not pagina.id.strip():
            self._q.remove(self._clave("facebook_pagina"))
            self._q.remove(self._clave("facebook_pagina_nombre"))
            return
        self._q.setValue(self._clave("facebook_pagina"), pagina.id.strip())
        self._q.setValue(self._clave("facebook_pagina_nombre"), pagina.nombre.strip())

    # Ubicación de las publicaciones: aquí solo la ciudad, que es pública. El
    # lugar de TikTok es de la cuenta y va al Llavero (`credenciales`).

    @property
    def ciudad(self) -> Ciudad | None:
        """Nunca guardada: la de por defecto (Madrid). «Sin ubicación» se
        guarda vacía. Una que ya no está en el catálogo: la de por defecto."""
        valor = self._q.value(self._clave("ciudad"))
        if valor is None:
            return UBICACION_POR_DEFECTO.ciudad
        if not str(valor):
            return None
        return Ciudad.de_clave(str(valor)) or UBICACION_POR_DEFECTO.ciudad

    @ciudad.setter
    def ciudad(self, ciudad: Ciudad | None) -> None:
        self._q.setValue(self._clave("ciudad"), ciudad.name if ciudad else "")

    # Cuentas conectadas en el servicio: la última consulta que salió bien,
    # para seguir sin conexión. Solo nombres visibles, nada secreto.

    def cuentas_guardadas(self) -> CuentasGuardadas | None:
        """Las del perfil actual; `None` si no hay o son de otro perfil."""
        bruto = self._q.value(self._clave("cuentas"))
        try:
            datos = json.loads(str(bruto)) if bruto else None
        except ValueError:
            return None
        if not isinstance(datos, dict) or datos.get("perfil") != self._contexto()[1]:
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
            "perfil": self._contexto()[1],
            "fecha": (fecha or datetime.now()).isoformat(timespec="seconds"),
            "cuentas": {Plataforma(p).value: _cuenta_a_dict(c) for p, c in cuentas.items()},
        }
        self._q.setValue(self._clave("cuentas"),
                         json.dumps(datos, ensure_ascii=False))

    # Programadas desde la app: referencia del servicio → vídeo y fecha, para
    # olvidar su entrada del registro si se cancela desde el calendario.

    def _programadas(self) -> dict[str, dict]:
        bruto = self._q.value("redes/programadas")
        try:
            datos = json.loads(str(bruto)) if bruto else {}
        except ValueError:
            return {}
        if not isinstance(datos, dict):
            return {}
        return {str(k): v for k, v in datos.items()
                if isinstance(v, dict) and isinstance(v.get("video"), str)}

    def programadas_locales(self) -> dict[str, str]:
        """Referencia → ruta del vídeo."""
        return {k: v["video"] for k, v in self._programadas().items()}

    def _guardar_programadas(self, datos: dict[str, dict]) -> None:
        self._q.setValue("redes/programadas", json.dumps(datos, ensure_ascii=False))

    def anotar_programada(self, referencia: str, video: Path, fecha: datetime) -> None:
        self._guardar_programadas({**self._programadas(), referencia: {
            "video": str(video), "fecha": fecha.isoformat(timespec="seconds")}})

    def olvidar_programada(self, referencia: str) -> str:
        """Quita la referencia; devuelve su vídeo, o "" si no estaba."""
        datos = self._programadas()
        entrada = datos.pop(referencia, None)
        if entrada is None:
            return ""
        self._guardar_programadas(datos)
        return entrada["video"]

    def podar_programadas(self, ahora: datetime) -> None:
        """Olvida las que ya salieron (o debían salir): ya no se pueden
        cancelar. Sin fecha legible, se quedan."""
        datos = self._programadas()

        def vigente(entrada: dict) -> bool:
            try:
                return datetime.fromisoformat(str(entrada.get("fecha"))) > ahora
            except (TypeError, ValueError):
                return True

        quedan = {k: v for k, v in datos.items() if vigente(v)}
        if quedan != datos:
            self._guardar_programadas(quedan)

    @property
    def youtube_categoria(self) -> str:
        return str(self._q.value(self._clave("youtube_categoria"), YOUTUBE_CATEGORIA_POR_DEFECTO)
                   or YOUTUBE_CATEGORIA_POR_DEFECTO)

    @youtube_categoria.setter
    def youtube_categoria(self, categoria: str) -> None:
        self._q.setValue(self._clave("youtube_categoria"), categoria)

    @property
    def tiktok_modo(self) -> ModoTikTok:
        try:
            return ModoTikTok(self._q.value(self._clave("tiktok_modo"), ModoTikTok.BORRADOR.value))
        except ValueError:
            return ModoTikTok.BORRADOR

    @tiktok_modo.setter
    def tiktok_modo(self, modo: ModoTikTok) -> None:
        self._q.setValue(self._clave("tiktok_modo"), ModoTikTok(modo).value)

    @property
    def instagram_modo(self) -> ModoInstagram:
        try:
            return ModoInstagram(self._q.value(self._clave("instagram_modo"),
                                               ModoInstagram.PRUEBA.value))
        except ValueError:
            return ModoInstagram.PRUEBA

    @instagram_modo.setter
    def instagram_modo(self, modo: ModoInstagram) -> None:
        self._q.setValue(self._clave("instagram_modo"), ModoInstagram(modo).value)

    @property
    def x_premium(self) -> bool:
        """Lo declara el usuario: con Premium, X admite vídeos largos y
        textos de más de 280 caracteres."""
        return _a_bool(self._q.value(self._clave("x_premium"), False))

    @x_premium.setter
    def x_premium(self, activo: bool) -> None:
        self._q.setValue(self._clave("x_premium"), bool(activo))

    @property
    def facebook_modo(self) -> ModoFacebook:
        try:
            return ModoFacebook(self._q.value(self._clave("facebook_modo"), ModoFacebook.REEL.value))
        except ValueError:
            return ModoFacebook.REEL

    @facebook_modo.setter
    def facebook_modo(self, modo: ModoFacebook) -> None:
        self._q.setValue(self._clave("facebook_modo"), ModoFacebook(modo).value)

    @property
    def plataformas_redes(self) -> list[Plataforma]:
        """Plataformas marcadas la última vez. Si nunca se publicó, las de
        `PLATAFORMAS_POR_DEFECTO`. Una elección guardada antes de que
        existieran X y Facebook sigue valiendo: quedan desmarcadas."""
        valor = self._q.value(self._clave("plataformas"))
        if valor is None:
            return list(PLATAFORMAS_POR_DEFECTO)
        nombres = str(valor).split(",") if not isinstance(valor, list) else valor
        return [p for p in ORDEN if p.value in {n.strip() for n in nombres}]

    @plataformas_redes.setter
    def plataformas_redes(self, plataformas) -> None:
        elegidas = {Plataforma(p) for p in plataformas}
        self._q.setValue(self._clave("plataformas"),
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
