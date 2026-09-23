"""API keys de los proveedores de publicación en el Llavero de macOS.

Usa el comando `security` (sin dependencias nuevas). Servicio
`tsots-<proveedor>`, cuenta `api-key`. La clave nunca se escribe en
QSettings, ficheros, logs ni mensajes de error.

Para guardarla, la orden va por la entrada estándar de `security -i` y no
como argumento: así no aparece en la lista de procesos (`ps`).
"""
from __future__ import annotations

import re
import subprocess

from videopipeline.i18n import _

SECURITY = "/usr/bin/security"
CUENTA = "api-key"
NO_ENCONTRADO = 44  # código de salida de `security` cuando no existe el elemento
# Base64, JWT, hex, UUID… Sin espacios ni comillas: la orden va sin entrecomillar.
_CLAVE_VALIDA = re.compile(r"^[A-Za-z0-9._~+/=:-]+$")


class ErrorLlavero(Exception):
    """Fallo del Llavero. El mensaje nunca incluye la clave."""


def servicio(proveedor: str) -> str:
    return f"tsots-{proveedor}"


def _ejecutar(args: list[str], entrada: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([SECURITY, *args], input=entrada, capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise ErrorLlavero(_("No se pudo usar el Llavero ({tipo}).").format(
            tipo=type(e).__name__)) from None


def clave_valida(clave: str) -> bool:
    return bool(_CLAVE_VALIDA.match(clave.strip()))


def guardar(proveedor: str, clave: str) -> None:
    clave = clave.strip()
    if not clave_valida(clave):
        raise ErrorLlavero(_("La clave tiene espacios, comillas u otros caracteres no válidos."))
    orden = (f"add-generic-password -U -s {servicio(proveedor)} -a {CUENTA} "
             f"-w {clave}\n")
    resultado = _ejecutar(["-i"], entrada=orden)
    # `security -i` no siempre refleja en el código de salida el fallo de la
    # orden: se comprueba leyendo la clave de vuelta.
    if resultado.returncode != 0 or leer(proveedor) != clave:
        raise ErrorLlavero(_("No se pudo guardar la clave en el Llavero."))


def leer(proveedor: str) -> str | None:
    resultado = _ejecutar(
        ["find-generic-password", "-s", servicio(proveedor), "-a", CUENTA, "-w"])
    if resultado.returncode == NO_ENCONTRADO:
        return None
    if resultado.returncode != 0:
        raise ErrorLlavero(_("No se pudo leer la clave del Llavero (código {codigo}).").format(
            codigo=resultado.returncode))
    return resultado.stdout.strip() or None


def hay_clave(proveedor: str) -> bool:
    """Sin `-w`: comprueba que existe sin sacar el secreto."""
    try:
        resultado = _ejecutar(
            ["find-generic-password", "-s", servicio(proveedor), "-a", CUENTA])
    except ErrorLlavero:
        return False
    return resultado.returncode == 0


def borrar(proveedor: str) -> bool:
    resultado = _ejecutar(
        ["delete-generic-password", "-s", servicio(proveedor), "-a", CUENTA])
    if resultado.returncode == NO_ENCONTRADO:
        return False
    if resultado.returncode != 0:
        raise ErrorLlavero(_("No se pudo borrar la clave del Llavero (código {codigo}).").format(
            codigo=resultado.returncode))
    return True
