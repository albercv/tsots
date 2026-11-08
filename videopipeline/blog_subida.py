"""Sube portada, fotogramas y vídeo al blog con el token de `posts_request_upload`.

Uso (lo invoca el agente de `claude -p`):
    python -m videopipeline.blog_subida <uploadUrl> --fichero ruta=slug_key
        [--fichero ...] [--portada slug_key] [--alt slug_key=texto ...]

Protocolo (leído de la página de subida del blog el 2026-11-08): por fichero,
`POST /api/admin/media/upload` con `Authorization: Bearer <token>`,
`Content-Type` y `X-Media-Name`, cuerpo en streaming; después
`POST /api/admin/media/upload/commit` con los nombres, alt y la portada.
El token (parámetro `token` de la URL) nunca se escribe en mensajes ni logs.
"""
from __future__ import annotations

import argparse
import logging
import mimetypes
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

log = logging.getLogger(__name__)

_SLUG = re.compile(r"^[a-z0-9_]+$")
VELOCIDAD_MINIMA = 250_000  # bytes/s que se dan por buenos en el peor caso


def tiempos(tamano: int) -> httpx.Timeout:
    """Límites de espera: la escritura crece con el tamaño."""
    return httpx.Timeout(connect=30.0, read=300.0, pool=30.0,
                         write=max(600.0, tamano / VELOCIDAD_MINIMA))


def _error(r: httpx.Response) -> RuntimeError:
    try:
        motivo = r.json()["error"]
    except (ValueError, KeyError, TypeError):
        motivo = f"HTTP {r.status_code}"
    return RuntimeError(f"El blog rechazó la subida: {motivo}")


def subir(upload_url: str, ficheros: list[tuple[Path, str]], *, portada: str | None = None,
          alts: dict[str, str] | None = None, http: httpx.Client | None = None) -> None:
    """Sube los ficheros y confirma. `RuntimeError` si el blog responde con error."""
    alts = alts or {}
    nombres = [n for _, n in ficheros]
    for n in nombres:
        if not _SLUG.match(n):
            raise ValueError(f"slug-key no válida: {n!r} (solo a-z, 0-9 y _)")
    if len(set(nombres)) != len(nombres):
        raise ValueError("slug-keys repetidas")
    partes = urlsplit(upload_url)
    token = (parse_qs(partes.query).get("token") or [""])[0]
    if not token or not partes.netloc:
        raise ValueError("uploadUrl sin origen o sin token")
    origen = f"{partes.scheme}://{partes.netloc}"
    auth = {"authorization": f"Bearer {token}"}
    cliente = http or httpx.Client()
    try:
        for ruta, nombre in ficheros:
            tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
            with ruta.open("rb") as f:
                r = cliente.post(f"{origen}/api/admin/media/upload", content=f,
                                 timeout=tiempos(ruta.stat().st_size),
                                 headers={**auth, "content-type": tipo, "x-media-name": nombre})
            log.info("subida %s: HTTP %s", nombre, r.status_code)
            if not r.is_success:
                raise _error(r)
        cuerpo: dict = {"files": [{"name": n, "alt": alts.get(n, ""), "caption": ""}
                                  for n in nombres]}
        if portada:
            cuerpo["cover"] = portada
        r = cliente.post(f"{origen}/api/admin/media/upload/commit", json=cuerpo, headers=auth,
                         timeout=tiempos(0))
        log.info("confirmación: HTTP %s", r.status_code)
        if not r.is_success:
            raise _error(r)
    finally:
        if http is None:
            cliente.close()


def _alt(texto: str) -> tuple[str, str]:
    clave, sep, alt = texto.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"se esperaba slug_key=texto, no {texto!r}")
    return clave, alt


def _fichero(texto: str) -> tuple[Path, str]:
    # La ruta puede contener "=": la slug-key va tras el último.
    ruta, sep, clave = texto.rpartition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"se esperaba ruta=slug_key, no {texto!r}")
    return Path(ruta), clave


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m videopipeline.blog_subida")
    p.add_argument("upload_url")
    p.add_argument("--fichero", action="append", type=_fichero, required=True,
                   help="ruta=slug_key")
    p.add_argument("--portada")
    p.add_argument("--alt", action="append", type=_alt, default=[], help="slug_key=texto")
    a = p.parse_args(argv)
    try:
        subir(a.upload_url, a.fichero, portada=a.portada, alts=dict(a.alt))
    except (RuntimeError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except httpx.HTTPError as e:  # su texto puede incluir la URL con el token
        print(f"Error de red: {type(e).__name__}", file=sys.stderr)
        return 1
    for _, n in a.fichero:
        print(f"subido {n}")
    print(f"listo: {len(a.fichero)} ficheros confirmados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
