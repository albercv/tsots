"""Cliente mínimo de Ollama (HTTP local), sin dependencias externas.

Solo transporte y ciclo de vida del servidor. La lógica del caption vive
en `caption.py`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .steps import PasoFallido

URL = "http://localhost:11434"


def disponible(url: str = URL, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/version", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


@dataclass
class Servidor:
    """Handle del servidor. Solo termina el proceso si lo arrancamos nosotros."""

    proceso: subprocess.Popen | None = None

    @property
    def arrancado_por_nosotros(self) -> bool:
        return self.proceso is not None

    def cerrar(self) -> None:
        if self.proceso is None:
            return
        self.proceso.terminate()
        try:
            self.proceso.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proceso.kill()
        self.proceso = None


def asegurar_servidor(url: str = URL, espera_max: float = 15.0) -> Servidor:
    """Devuelve un servidor operativo, arrancando `ollama serve` si hace falta."""
    if disponible(url):
        return Servidor()
    binario = shutil.which("ollama")
    if binario is None:
        raise PasoFallido(
            "Ollama no está instalado (no se encuentra 'ollama' en PATH)"
        )
    proceso = subprocess.Popen(
        [binario, "serve"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    inicio = time.monotonic()
    while time.monotonic() - inicio < espera_max:
        if disponible(url):
            return Servidor(proceso=proceso)
        time.sleep(0.5)
    Servidor(proceso=proceso).cerrar()
    raise PasoFallido(f"Ollama no responde en {url} tras {espera_max:.0f} s")


def chat_json(
    modelo: str,
    mensajes: list[dict],
    esquema: dict,
    url: str = URL,
    timeout: float = 300.0,
) -> dict:
    """POST /api/chat con salida forzada a `esquema`. Devuelve el JSON parseado."""
    cuerpo = json.dumps({
        "model": modelo,
        "messages": mensajes,
        "stream": False,
        "format": esquema,
        "think": False,
        "options": {"temperature": 0.7, "num_ctx": 16384},
    }).encode("utf-8")
    peticion = urllib.request.Request(
        f"{url}/api/chat", data=cuerpo,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:
            respuesta = json.load(r)
    except urllib.error.HTTPError as error:
        detalle = error.read().decode("utf-8", errors="replace")
        if error.code == 404 and "not found" in detalle:
            raise PasoFallido(f"Modelo no descargado: {modelo}", detalle=detalle) from None
        raise PasoFallido(f"Ollama devolvió HTTP {error.code}", detalle=detalle) from None
    except (urllib.error.URLError, OSError) as error:
        raise PasoFallido(f"Ollama no responde en {url}", detalle=str(error)) from None
    contenido = respuesta.get("message", {}).get("content", "")
    try:
        return json.loads(contenido)
    except (json.JSONDecodeError, TypeError):
        raise PasoFallido(
            "La respuesta del modelo no es JSON válido", detalle=str(contenido)[:2000]
        ) from None
