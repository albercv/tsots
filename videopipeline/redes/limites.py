"""Límites de vídeo de cada plataforma (no del proveedor).

Hoy solo X los tiene: sin Premium admite vídeos de hasta 140 s (2:20) y
512 MB. Con Premium, los límites son de horas y de GB: no se comprueban.
"""
from __future__ import annotations

import math

from ..i18n import _

MAX_DURACION_X = 140  # segundos
MAX_TAMANO_X = 512 * 1024 * 1024  # bytes
_MB = 1024 * 1024


def duracion_legible(segundos: float) -> str:
    """«2:48» o «1:02:05», redondeando hacia arriba al segundo."""
    total = max(0, math.ceil(segundos - 1e-9))
    horas, resto = divmod(total, 3600)
    minutos, segundos = divmod(resto, 60)
    if horas:
        return f"{horas}:{minutos:02d}:{segundos:02d}"
    return f"{minutos}:{segundos:02d}"


def motivo_no_admite_x(duracion: float | None, tamano: int | None, premium: bool) -> str:
    """Por qué X no admite el vídeo, o "" si lo admite. Una duración o un
    tamaño desconocidos (`None` o 0) no bloquean."""
    if premium:
        return ""
    if duracion and duracion > MAX_DURACION_X:
        return _("X sin Premium admite vídeos de hasta {maximo}; este dura {duracion}.").format(
            maximo=duracion_legible(MAX_DURACION_X), duracion=duracion_legible(duracion))
    if tamano and tamano > MAX_TAMANO_X:
        return _("X sin Premium admite vídeos de hasta {maximo} MB; este ocupa "
                 "{tamano} MB.").format(maximo=MAX_TAMANO_X // _MB,
                                        tamano=math.ceil(tamano / _MB))
    return ""
