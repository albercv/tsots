"""Interfaz neutra de un proveedor de publicación y registro de proveedores.

Un proveedor es un módulo de este paquete que expone:

- `NOMBRE: str`: nombre visible (p. ej. en el diálogo Redes…).
- `USA_PERFIL: bool`: si necesita un perfil o cuenta dentro del servicio.
- `AYUDA_PERFIL: str` (opcional, marcado con `N_`): qué escribir como perfil.
- `crear(clave, ajustes, http=None) -> Proveedor`: `clave` es la API key
  (sale del Llavero), `ajustes` los datos no secretos (hoy, `perfil`) y
  `http` un `httpx.Client` opcional que los tests sustituyen por uno falso.

Añadir un proveedor = un módulo nuevo + una línea en `PROVEEDORES`.
"""
from __future__ import annotations

import importlib
import re
from types import ModuleType
from typing import Any, Mapping, Protocol, runtime_checkable

from ..i18n import _
from .modelo import Opciones, Plataforma, Publicacion, Resultado


@runtime_checkable
class Proveedor(Protocol):
    nombre: str

    def publicar(self, plataforma: Plataforma, publicacion: Publicacion,
                 opciones: Opciones) -> Resultado:
        """Sube el vídeo a una plataforma. Nunca lanza por errores de red o
        del servicio: devuelve un `Resultado` con `ok=False` y `error`, o con
        `pendiente=True` y una `referencia` para `estado`. El texto de error
        nunca contiene la clave."""
        ...

    def estado(self, plataforma: Plataforma, referencia: str) -> Resultado:
        """Consulta una publicación pendiente. Misma regla: no lanza."""
        ...


# Identificador (se guarda en ajustes y en el registro) → módulo del proveedor.
PROVEEDORES: dict[str, str] = {"upload_post": "videopipeline.redes.upload_post"}
PROVEEDOR_POR_DEFECTO = "upload_post"


def modulo(nombre: str) -> ModuleType:
    try:
        ruta = PROVEEDORES[nombre]
    except KeyError:
        raise ValueError(f"Proveedor desconocido: {nombre!r}") from None
    return importlib.import_module(ruta)


def nombre_visible(nombre: str) -> str:
    return str(modulo(nombre).NOMBRE)


def usa_perfil(nombre: str) -> bool:
    return bool(getattr(modulo(nombre), "USA_PERFIL", False))


def ayuda_perfil(nombre: str) -> str:
    """Explicación (traducida) de qué es el perfil en ese servicio, o ""."""
    texto = getattr(modulo(nombre), "AYUDA_PERFIL", "")
    return _(texto) if texto else ""


_RE_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def parece_email(texto: str) -> bool:
    """Un perfil nunca es un email: se usa para avisar al escribirlo."""
    return bool(_RE_EMAIL.fullmatch((texto or "").strip()))


def crear(nombre: str, clave: str, ajustes: Mapping[str, str] | None = None,
          http: Any = None) -> Proveedor:
    return modulo(nombre).crear(clave, dict(ajustes or {}), http=http)
