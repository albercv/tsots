"""Consulta de las cuentas conectadas en el servicio de publicación.

La usan los diálogos Redes… y Publicar, siempre en segundo plano
(`segundo_plano`). Solo habla con el protocolo neutro `Proveedor`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from videopipeline.i18n import _
from videopipeline.redes import proveedor as proveedores
from videopipeline.redes.modelo import Cuenta, Pagina, Plataforma

from . import credenciales

Fabrica = Callable[[str, str, dict], proveedores.Proveedor]

COLOR_OK = "#43a047"
COLOR_ERROR = "#e53935"
COLOR_AVISO = "#b8860b"
COLOR_SECUNDARIO = "#888888"


@dataclass(frozen=True)
class Consulta:
    """Resultado de `consultar`. `cuentas` y `paginas` son `None` si no se
    pudieron consultar (el motivo, en `error` y `error_paginas`) o no se
    pidieron."""

    cuentas: dict[Plataforma, Cuenta | None] | None = None
    paginas: list[Pagina] | None = None
    error: str = ""
    error_paginas: str = ""


def consultar(llavero, fabrica: Fabrica, nombre: str, datos: dict, *,
              clave: str | None = None, paginas: bool | None = None) -> Consulta:
    """Cuentas (y páginas de Facebook) del servicio `nombre`. Pensada para
    ejecutarse fuera del hilo de la interfaz: nunca lanza.

    `clave`: la API key recién escrita; si falta, se lee del Llavero.
    `paginas`: `True` las pide siempre, `False` nunca y `None` solo si
    Facebook está conectada."""
    try:
        if not clave:
            clave = llavero.leer(nombre)
        if not clave:
            return Consulta(error=_("Falta la API key del servicio: guárdala en Redes…"))
        servicio = fabrica(nombre, clave, datos)
    except credenciales.ErrorLlavero as e:  # su mensaje nunca lleva la clave
        return Consulta(error=str(e))
    except Exception as e:  # el mensaje de otra excepción podría llevarla: solo el tipo
        return Consulta(error=_("No se pudo preparar la consulta ({tipo}).").format(
            tipo=type(e).__name__))
    finally:
        clave = None
    try:
        cuentas = servicio.cuentas()
    except proveedores.ErrorConsulta as e:
        return Consulta(error=str(e))
    except Exception as e:
        return Consulta(error=_("Error inesperado al consultar las cuentas ({tipo}).").format(
            tipo=type(e).__name__))
    if paginas is False or (paginas is None and cuentas.get(Plataforma.FACEBOOK) is None):
        return Consulta(cuentas=cuentas)
    try:
        return Consulta(cuentas=cuentas, paginas=servicio.paginas_facebook())
    except proveedores.ErrorConsulta as e:
        return Consulta(cuentas=cuentas, error_paginas=str(e))
    except Exception as e:
        return Consulta(cuentas=cuentas, error_paginas=_(
            "Error inesperado al consultar las páginas ({tipo}).").format(tipo=type(e).__name__))


def describir(plataforma: Plataforma, cuenta: Cuenta | None, servicio: str) -> tuple[str, str]:
    """Texto y color con que se muestra el estado de una cuenta."""
    if cuenta is None:
        return _("No conectada en {servicio}").format(servicio=servicio), COLOR_ERROR
    if cuenta.reconectar:
        texto = _("⚠ Reconecta {plataforma} en {servicio}").format(
            plataforma=plataforma.nombre, servicio=servicio)
        if cuenta.visible:
            texto += f" ({cuenta.visible})"
        return texto, COLOR_AVISO
    return cuenta.visible or _("Conectada"), COLOR_SECUNDARIO


def resumen(cuentas: dict[Plataforma, Cuenta | None]) -> str:
    """Una línea para el registro de la publicación (sin datos secretos)."""
    partes = []
    for plataforma, cuenta in cuentas.items():
        if cuenta is None:
            partes.append(f"{plataforma.nombre} no conectada")
            continue
        texto = f"{plataforma.nombre} {cuenta.visible or 'conectada'}"
        if cuenta.reconectar:
            texto += " (reconectar)"
        if cuenta.premium:
            texto += " (Premium)"
        partes.append(texto)
    return ", ".join(partes) or "(ninguna)"
