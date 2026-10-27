"""Credenciales inventadas para los tests.

Se generan al ejecutar en lugar de escribirse como texto: así los escáneres de
secretos (GitGuardian y similares) no las confunden con credenciales reales.
Ninguna vale para nada: la firma es texto fijo, no una firma real.
"""
from __future__ import annotations

import base64
import json


def _b64(datos: dict | bytes) -> str:
    crudo = datos if isinstance(datos, bytes) else json.dumps(
        datos, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(crudo).rstrip(b"=").decode()


def jwt_falso(**carga) -> str:
    """Un JWT con forma válida, carga `carga` y firma inventada."""
    return ".".join((_b64({"alg": "HS256"}), _b64(carga or {"sub": "test"}),
                     _b64(b"firma-inventada-para-tests")))
