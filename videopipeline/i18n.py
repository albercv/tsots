"""Traducción de la interfaz y de los mensajes del pipeline (gettext).

El español es el idioma fuente: las cadenas del código son los `msgid`.
Los catálogos viven en `locale/<idioma>/LC_MESSAGES/tsots.po` (fuente) y
`tsots.mo` (compilado). Añadir un idioma = un `.po` nuevo, sin tocar código.

Uso:
    from videopipeline.i18n import _, N_
    label = _("Extrayendo audio")        # traducido en tiempo de ejecución
    ESTADOS = (N_("en espera"), ...)      # marca para extraer; traducir después

`_` consulta el traductor instalado en el momento de la llamada, así que
`instalar()` puede ejecutarse después de importar los módulos.
"""
from __future__ import annotations

import gettext
import os
from pathlib import Path

DOMINIO = "tsots"
IDIOMA_FUENTE = "es"
IDIOMAS = ("es", "en")
DIR_LOCALE = Path(__file__).resolve().parent.parent / "locale"
VARIABLE_ENTORNO = "TSOTS_LANG"  # "es", "en" o "sistema"

_traductor: gettext.NullTranslations = gettext.NullTranslations()
_idioma: str = IDIOMA_FUENTE


def normalizar(codigo: str | None) -> str:
    """'en_US.UTF-8' → 'en'; desconocido o vacío → idioma fuente."""
    base = (codigo or "").replace("-", "_").split(".")[0].split("_")[0].lower()
    return base if base in IDIOMAS else IDIOMA_FUENTE


def instalar(idioma: str | None, dir_locale: Path | None = None) -> str:
    """Activa el idioma. Devuelve el idioma efectivo ('es' si no hay catálogo)."""
    global _traductor, _idioma
    _idioma = normalizar(idioma)
    if _idioma == IDIOMA_FUENTE:
        _traductor = gettext.NullTranslations()
    else:
        _traductor = gettext.translation(
            DOMINIO, localedir=str(dir_locale or DIR_LOCALE),
            languages=[_idioma], fallback=True,
        )
    return _idioma


def idioma_actual() -> str:
    return _idioma


def detectar() -> str:
    """Idioma preferido: TSOTS_LANG si es 'es'/'en'; si no, el del entorno."""
    forzado = os.environ.get(VARIABLE_ENTORNO, "").strip().lower()
    if forzado in IDIOMAS:
        return forzado
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        valor = os.environ.get(variable)
        if valor:
            return normalizar(valor)
    return IDIOMA_FUENTE


def _(texto: str) -> str:
    return _traductor.gettext(texto)


def N_(texto: str) -> str:
    """Marca una cadena para extracción sin traducirla aquí (se traduce al usarla)."""
    return texto
