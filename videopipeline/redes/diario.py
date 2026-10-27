"""Registro de diagnóstico de cada publicación.

Un fichero por intento: `logs/publicacion_<vídeo>_<YYYYmmdd-HHMMSS>.log`, en
la misma carpeta `logs/` que usan el runner y el lanzador de la app (la raíz
del proyecto, también cuando se abre desde el `.app`).

Todo el paquete `videopipeline.redes` escribe con `logging` bajo el logger
`videopipeline.redes`; mientras hay un `Diario` abierto, esos mensajes van a
su fichero. Nada sale por la consola (`propagate = False`), y cada línea,
traceback incluido, pasa por `limpiar` antes de escribirse: la clave nunca
llega al disco aunque aparezca en el mensaje de una excepción.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from ..steps import BASE_DIR

DIR_LOGS_PROYECTO = BASE_DIR / "logs"
DIR_LOGS = DIR_LOGS_PROYECTO  # los tests lo cambian por una carpeta temporal
NOMBRE_LOGGER = "videopipeline.redes"
MAX_CUERPO = 2000
OCULTO = "***"

logger = logging.getLogger(NOMBRE_LOGGER)
logger.addHandler(logging.NullHandler())  # sin Diario abierto, silencio
logger.propagate = False  # nunca a la consola ni a logs/lanzador.log

_VALOR = r"[^\s\"',;}&]+"
_PATRONES: tuple[tuple[re.Pattern, str], ...] = (
    # Cabecera de autorización, con o sin esquema delante del valor.
    (re.compile(r"(?i)\b(authorization)([\"']?\s*[:=]\s*[\"']?)(?:[A-Za-z]+\s+)?" + _VALOR),
     r"\1\2" + OCULTO),
    (re.compile(r"(?i)\b(bearer|basic)(\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1\2" + OCULTO),
    # Nombre de campo secreto seguido de `:` o `=`.
    (re.compile(r"(?i)\b(api[-_ ]?key|access[-_]?token|refresh[-_]?token|token|secret|"
                r"password|passwd|clave)([\"']?\s*[:=]\s*[\"']?)" + _VALOR),
     r"\1\2" + OCULTO),
    # "api key <valor largo>" sin separador.
    (re.compile(r"(?i)\b(api[-_ ]?key)(\s+)[A-Za-z0-9._~+/=-]{16,}"), r"\1\2" + OCULTO),
    # JWT.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}(?:\.[A-Za-z0-9_-]*)?"), OCULTO),
    # Cadena opaca muy larga con letras y cifras (base64, hex largo…).
    # Sin "/" para no tocar rutas ni URLs.
    (re.compile(r"(?<![\w+=-])(?=[A-Za-z0-9+=]*\d)(?=[A-Za-z0-9+=]*[A-Za-z])"
                r"[A-Za-z0-9+=]{40,}(?![\w+=-])"), OCULTO),
)


def limpiar(texto: str, secretos: Iterable[str] = ()) -> str:
    """Quita los secretos conocidos (tal cual y codificados para URL) y lo
    que parezca un token o una clave."""
    texto = str(texto)
    for secreto in sorted({s for s in secretos if s}, key=len, reverse=True):
        for forma in {secreto, quote(secreto, safe=""), quote(secreto)}:
            texto = texto.replace(forma, OCULTO)
    for patron, sustituto in _PATRONES:
        texto = patron.sub(sustituto, texto)
    return texto


def truncar(texto: str, maximo: int = MAX_CUERPO) -> str:
    texto = str(texto)
    if len(texto) <= maximo:
        return texto
    return f"{texto[:maximo]}… [truncado: {len(texto)} caracteres]"


def cuerpo(texto: str, secretos: Iterable[str] = ()) -> str:
    """Cuerpo de una respuesta, listo para el log: limpio, en una línea y acotado."""
    return truncar(limpiar(" ".join(str(texto).split()), secretos))


class _Formato(logging.Formatter):
    def __init__(self, secretos: list[str]):
        super().__init__("%(asctime)s.%(msecs)03d %(levelname)-7s [%(threadName)s] "
                         "%(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
        self._secretos = secretos

    def format(self, record: logging.LogRecord) -> str:
        return limpiar(super().format(record), self._secretos)


class Diario:
    """Abre el fichero de log de una publicación y engancha a él el logger
    del paquete. Si no se puede escribir, `ruta` es None y todo sigue."""

    def __init__(self, video: Path, ahora: datetime | None = None):
        self._secretos: list[str] = []
        self.log = logging.getLogger(NOMBRE_LOGGER + ".publicacion")
        marca = (ahora or datetime.now()).strftime("%Y%m%d-%H%M%S")
        base = f"publicacion_{Path(video).stem}_{marca}"
        ruta: Path | None = DIR_LOGS / f"{base}.log"
        numero = 2
        while ruta.exists():  # dos intentos en el mismo segundo: ficheros distintos
            ruta = DIR_LOGS / f"{base}-{numero}.log"
            numero += 1
        self._manejador: logging.Handler | None = None
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            self._manejador = logging.FileHandler(ruta, encoding="utf-8")
        except OSError:
            ruta = None
        self.ruta = ruta
        if self._manejador is not None:
            self._manejador.setFormatter(_Formato(self._secretos))
            self._manejador.setLevel(logging.DEBUG)
            logger.addHandler(self._manejador)
            logger.setLevel(logging.DEBUG)

    @property
    def abierto(self) -> bool:
        return self._manejador is not None

    def ocultar(self, secreto: str) -> None:
        """A partir de ahora, `secreto` se sustituye por *** en cada línea."""
        if secreto and secreto not in self._secretos:
            self._secretos.append(secreto)

    def cerrar(self) -> None:
        if self._manejador is not None:
            logger.removeHandler(self._manejador)
            self._manejador.close()
            self._manejador = None
        self._secretos.clear()
