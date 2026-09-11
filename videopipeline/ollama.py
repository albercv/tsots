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

from .i18n import _
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
            self.proceso.wait()  # Reap el proceso tras kill
        self.proceso = None


def asegurar_servidor(url: str = URL, espera_max: float = 15.0) -> Servidor:
    """Devuelve un servidor operativo, arrancando `ollama serve` si hace falta."""
    if disponible(url):
        return Servidor()
    binario = shutil.which("ollama")
    if binario is None:
        raise PasoFallido(
            _("Ollama no está instalado (no se encuentra 'ollama' en PATH)")
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
    raise PasoFallido(
        _("Ollama no responde en {url} tras {segundos:.0f} s").format(
            url=url, segundos=espera_max)
    )


GB = 1024 ** 3
# macOS deja a Metal ~3/4 de la memoria unificada para la GPU.
FRACCION_GPU = 0.75
# Contexto de 16k tokens + KV cache + sobrecarga del runner.
MARGEN_CONTEXTO = int(1.5 * GB)


@dataclass(frozen=True)
class Modelo:
    nombre: str
    tamano: int  # bytes en disco (≈ memoria que ocupa cargado)

    @property
    def etiqueta(self) -> str:
        return f"{self.nombre} · {_gb(self.tamano)} GB"


def _gb(n: int) -> str:
    return f"{n / GB:.1f}".replace(".", ",")


def listar_modelos(url: str = URL, timeout: float = 2.0) -> list[Modelo]:
    """Modelos instalados según `GET /api/tags`. Sin servidor → lista vacía."""
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=timeout) as r:
            datos = json.load(r)
    except (urllib.error.URLError, OSError, ValueError):
        return []
    modelos = []
    for entrada in datos.get("models", []) if isinstance(datos, dict) else []:
        nombre = entrada.get("name")
        if nombre:
            modelos.append(Modelo(str(nombre), int(entrada.get("size", 0) or 0)))
    return sorted(modelos, key=lambda m: m.nombre.lower())


def memoria_para_modelos(ram_bytes: int | None = None) -> int:
    """Memoria que macOS deja a la GPU para modelos (≈ 75 % de la RAM)."""
    if ram_bytes is None:
        import os
        ram_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    return int(ram_bytes * FRACCION_GPU)


def cabe(modelo: Modelo, memoria: int) -> bool:
    return modelo.tamano + MARGEN_CONTEXTO <= memoria


def motivo_no_cabe(modelo: Modelo, memoria: int) -> str:
    return _(
        "Necesita ~{total} GB de memoria ({modelo} GB del modelo + contexto) "
        "y este Mac deja ~{memoria} GB para modelos."
    ).format(total=_gb(modelo.tamano + MARGEN_CONTEXTO), modelo=_gb(modelo.tamano),
             memoria=_gb(memoria))


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
            cuerpo_bruto = r.read()
        try:
            respuesta = json.loads(cuerpo_bruto)
        except (json.JSONDecodeError, ValueError):
            # El cuerpo no es JSON válido
            detalle = cuerpo_bruto.decode("utf-8", errors="replace")
            raise PasoFallido(
                _("Ollama devolvió una respuesta no válida"), detalle=detalle[:2000]
            ) from None
    except urllib.error.HTTPError as error:
        detalle = error.read().decode("utf-8", errors="replace")
        if error.code == 404 and "not found" in detalle:
            raise PasoFallido(
                _("Modelo no descargado: {modelo}").format(modelo=modelo),
                detalle=detalle,
            ) from None
        raise PasoFallido(
            _("Ollama devolvió HTTP {codigo}").format(codigo=error.code),
            detalle=detalle,
        ) from None
    except (urllib.error.URLError, OSError) as error:
        raise PasoFallido(
            _("Ollama no responde en {url}").format(url=url), detalle=str(error)
        ) from None
    try:
        contenido = respuesta.get("message", {}).get("content", "")
    except (AttributeError, TypeError):
        # respuesta no es un dict: e.g. JSON array o valor primitivo
        raise PasoFallido(
            _("Ollama devolvió una respuesta no válida"),
            detalle=json.dumps(respuesta)[:2000]
        ) from None
    try:
        return json.loads(contenido)
    except (json.JSONDecodeError, TypeError):
        raise PasoFallido(
            _("La respuesta del modelo no es JSON válido"),
            detalle=str(contenido)[:2000],
        ) from None
