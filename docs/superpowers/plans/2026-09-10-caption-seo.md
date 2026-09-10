# Caption SEO (LLM local vía Ollama) — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Al final del pipeline, generar título SEO, caption y hashtags desde la transcripción con `qwen3.5:9b` en Ollama, guardarlos en `nombre_limpio.md` junto al vídeo y mostrarlos en la app con botones de copiar.

**Architecture:** Nuevo paso opcional `_fase_caption` en `videopipeline/pipeline.py`, con degradación a warning (nunca falla el vídeo), como los subtítulos. Lógica en dos módulos nuevos: `videopipeline/ollama.py` (cliente HTTP mínimo con arranque de `ollama serve` bajo demanda) y `videopipeline/caption.py` (prompt, esquema JSON, validación, lectura/escritura del `.md`). GUI: casilla + botón "Marca…" en el panel, diálogo de marca, panel de caption con Copiar.

**Tech Stack:** Python 3.11, PySide6 6.11, `urllib` (sin dependencias nuevas), Ollama 0.33 (`POST /api/chat` con `format` = JSON Schema), pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-09-10-caption-seo-design.md`

## Global Constraints

- Sin dependencias nuevas en `requirements.txt`.
- El paso de caption **nunca** hace fallar el vídeo: cualquier excepción → evento `{"warning": "Caption SEO falló: … Vídeo guardado sin caption."}`.
- Modelo por defecto: `qwen3.5:9b`. URL de Ollama: `http://localhost:11434`.
- Transcripción recortada a las primeras 3500 palabras.
- Título ≤ 60 caracteres. 8-15 hashtags en minúsculas, con `#`, sin espacios ni duplicados.
- Tests: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m "not slow" -q` debe quedar en verde tras cada tarea. Los tests nunca hablan con Ollama real salvo el marcado `slow`.
- Texto de la GUI y comentarios en español, como el resto del proyecto. Nombres de código en español (`generar`, `escribir_md`…).
- Commits: un commit por tarea, mensaje en inglés (convención del repo), con `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Ejecutar todo desde la raíz del proyecto: `cd ~/Documents/personalProjects/limpiadorVideo`.

## Mapa de ficheros

| Fichero | Responsabilidad |
|---|---|
| `videopipeline/config.py` (modificar) | Tres campos nuevos + validación |
| `videopipeline/errores.py` (modificar) | Tres patrones nuevos de error conocido |
| `videopipeline/ollama.py` (crear) | `disponible`, `asegurar_servidor`, `chat_json`. Solo HTTP y proceso; sin lógica de negocio |
| `videopipeline/caption.py` (crear) | `Caption`, `texto_plano`, `recortar`, `construir_mensajes`, `ESQUEMA`, `generar`, `escribir_md`, `leer_md` |
| `videopipeline/pipeline.py` (modificar) | `_fase_subtitulos` devuelve palabras; `_fase_caption`; `pasos_extra` |
| `limpiarVideo.py` (modificar) | Flags `--caption`, `--marca` |
| `app/settings.py` (modificar) | `contexto_marca`, `modelo_caption` |
| `app/widgets/dialogo_marca.py` (crear) | Diálogo de texto libre |
| `app/widgets/panel_opciones.py` (modificar) | Grupo "Caption SEO", casilla, botón, señal |
| `app/widgets/panel_caption.py` (crear) | Muestra `Caption` y copia al portapapeles |
| `app/main.py` (modificar) | Cableado: config, diálogo, panel |
| `tests/test_config.py`, `tests/test_errores.py`, `tests/test_ollama.py` (crear), `tests/test_caption.py` (crear), `tests/test_pipeline.py`, `tests/test_cli_compat.py`, `tests/test_app_queue.py`, `tests/test_app_widgets.py`, `tests/test_app_main.py`, `tests/test_integracion_lenta.py` | Tests |
| `SETUP.md` (modificar) | Documentación de uso |

---

### Task 1: Campos de configuración

**Files:**
- Modify: `videopipeline/config.py` (dataclass `PipelineConfig`, líneas 35-52 y `validar` 54-91)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `PipelineConfig.caption_seo: bool = False`, `PipelineConfig.contexto_marca: str = ""`, `PipelineConfig.modelo_caption: str = "qwen3.5:9b"`; `validar()` lanza `ValueError` si `modelo_caption` está vacío.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `tests/test_config.py`:

```python
def test_caption_defectos():
    c = _config_minima()
    assert c.caption_seo is False
    assert c.contexto_marca == ""
    assert c.modelo_caption == "qwen3.5:9b"


def test_caption_json_ida_y_vuelta():
    c = _config_minima(caption_seo=True, contexto_marca="Soy Alberto, tono cercano",
                       modelo_caption="qwen3.5:9b-q8_0")
    c2 = PipelineConfig.from_json(c.to_json())
    assert c2 == c
    assert c2.caption_seo is True
    assert c2.contexto_marca == "Soy Alberto, tono cercano"


def test_caption_modelo_vacio_invalido():
    with pytest.raises(ValueError, match="modelo_caption"):
        _config_minima(caption_seo=True, modelo_caption="").validar()
```

- [ ] **Step 2: Comprobar que fallan**

Run: `.venv-clearvoice/bin/python -m pytest tests/test_config.py -q`
Expected: 3 failed (`TypeError: unexpected keyword argument 'caption_seo'` / `AttributeError`).

- [ ] **Step 3: Implementar**

En `videopipeline/config.py`, tras `tamano_subs: int = 100` dentro de `PipelineConfig`:

```python
    caption_seo: bool = False
    contexto_marca: str = ""
    modelo_caption: str = "qwen3.5:9b"
```

Al final de `validar()`, tras la comprobación de `tamano_subs`:

```python
        if not self.modelo_caption.strip():
            raise ValueError("modelo_caption no puede estar vacío")
```

- [ ] **Step 4: Comprobar que pasan**

Run: `.venv-clearvoice/bin/python -m pytest tests/test_config.py -q`
Expected: todos pasan.

- [ ] **Step 5: Commit**

```bash
git add videopipeline/config.py tests/test_config.py
git commit -m "feat(config): caption_seo, contexto_marca and modelo_caption fields

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Errores conocidos de Ollama

**Files:**
- Modify: `videopipeline/errores.py` (tupla `_CONOCIDOS`, líneas 54-125)
- Test: `tests/test_errores.py`

**Interfaces:**
- Produces: `explicar(...)` reconoce tres mensajes que lanzará `videopipeline/ollama.py` (Task 3): `"Ollama no está instalado"`, `"Modelo no descargado"`, `"Ollama no responde"`.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `tests/test_errores.py`:

```python
def test_explicar_ollama_no_instalado():
    d = explicar("Ollama no está instalado (no se encuentra 'ollama' en PATH)")
    assert d.conocido
    assert "brew install ollama" in d.solucion


def test_explicar_modelo_ollama_no_descargado():
    d = explicar("Modelo no descargado: qwen3.5:9b",
                 '{"error":"model \'qwen3.5:9b\' not found"}')
    assert d.conocido
    assert "ollama pull" in d.solucion


def test_explicar_ollama_no_responde():
    d = explicar("Ollama no responde en http://localhost:11434 tras 15 s")
    assert d.conocido
    assert "11434" in d.causa or "11434" in d.solucion
```

- [ ] **Step 2: Comprobar que fallan**

Run: `.venv-clearvoice/bin/python -m pytest tests/test_errores.py -q`
Expected: 3 failed con `assert False` en `d.conocido`.

- [ ] **Step 3: Implementar**

En `videopipeline/errores.py`, añadir estas tres tuplas al final de `_CONOCIDOS` (antes del paréntesis de cierre):

```python
    (
        re.compile(r"Ollama no está instalado", re.I),
        "Ollama no está instalado",
        "El caption SEO se genera con un modelo local servido por Ollama y "
        "no se encuentra el ejecutable `ollama` en PATH.",
        "brew install ollama   (y luego: ollama pull qwen3.5:9b)",
    ),
    (
        re.compile(r"Modelo no descargado", re.I),
        "Modelo de Ollama no descargado",
        "Ollama responde pero no tiene el modelo pedido en local.",
        "ollama pull <modelo>  (el nombre exacto está en el detalle técnico)",
    ),
    (
        re.compile(r"Ollama no responde", re.I),
        "Ollama no responde",
        "No hay servidor en http://localhost:11434 y no se pudo arrancar "
        "`ollama serve` a tiempo (puerto ocupado, app de Ollama colgada, "
        "o descarga del modelo en curso).",
        "Ejecuta `ollama serve` en una terminal para ver el error, o abre la "
        "app de Ollama. Si el puerto 11434 está ocupado, libéralo.",
    ),
```

- [ ] **Step 4: Comprobar que pasan**

Run: `.venv-clearvoice/bin/python -m pytest tests/test_errores.py -q`
Expected: todos pasan.

- [ ] **Step 5: Commit**

```bash
git add videopipeline/errores.py tests/test_errores.py
git commit -m "feat(errores): explain Ollama not installed, model missing, server down

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Cliente Ollama

**Files:**
- Create: `videopipeline/ollama.py`
- Test: `tests/test_ollama.py`

**Interfaces:**
- Consumes: `PasoFallido` de `videopipeline/steps.py` (constructor `PasoFallido(mensaje, detalle="")`).
- Produces:
  - `URL: str = "http://localhost:11434"`
  - `disponible(url=URL, timeout=1.0) -> bool`
  - `class Servidor` con `cerrar() -> None` y propiedad `arrancado_por_nosotros: bool`
  - `asegurar_servidor(url=URL, espera_max=15.0) -> Servidor`
  - `chat_json(modelo, mensajes, esquema, url=URL, timeout=300.0) -> dict`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_ollama.py`:

```python
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from videopipeline import ollama
from videopipeline.steps import PasoFallido


class _Falso(BaseHTTPRequestHandler):
    """Servidor Ollama falso. `respuestas` lo configura cada test."""

    respuestas: dict = {}
    peticiones: list = []

    def log_message(self, *args):  # silencio
        pass

    def do_GET(self):
        if self.path == "/api/version":
            self._responder(200, {"version": "0.33.2"})
        else:
            self._responder(404, {"error": "no"})

    def do_POST(self):
        cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Falso.peticiones.append((self.path, cuerpo))
        codigo, datos = _Falso.respuestas.get(self.path, (404, {"error": "no"}))
        self._responder(codigo, datos)

    def _responder(self, codigo, datos):
        cuerpo = json.dumps(datos).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)


@pytest.fixture()
def servidor_falso():
    _Falso.respuestas = {}
    _Falso.peticiones = []
    httpd = HTTPServer(("127.0.0.1", 0), _Falso)
    hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_disponible_true_con_servidor(servidor_falso):
    assert ollama.disponible(servidor_falso) is True


def test_disponible_false_sin_servidor():
    assert ollama.disponible("http://127.0.0.1:1", timeout=0.2) is False


def test_chat_json_envia_formato_y_parsea(servidor_falso):
    _Falso.respuestas["/api/chat"] = (
        200, {"message": {"role": "assistant", "content": '{"titulo": "Hola"}'}}
    )
    esquema = {"type": "object", "properties": {"titulo": {"type": "string"}}}
    datos = ollama.chat_json("m", [{"role": "user", "content": "x"}], esquema,
                             url=servidor_falso)
    assert datos == {"titulo": "Hola"}
    ruta, cuerpo = _Falso.peticiones[0]
    assert ruta == "/api/chat"
    assert cuerpo["model"] == "m"
    assert cuerpo["stream"] is False
    assert cuerpo["format"] == esquema
    assert cuerpo["think"] is False
    assert cuerpo["options"]["num_ctx"] == 16384


def test_chat_json_modelo_no_descargado(servidor_falso):
    _Falso.respuestas["/api/chat"] = (404, {"error": "model 'm' not found"})
    with pytest.raises(PasoFallido, match="Modelo no descargado: m") as info:
        ollama.chat_json("m", [], {}, url=servidor_falso)
    assert "not found" in info.value.detalle


def test_chat_json_contenido_no_json(servidor_falso):
    _Falso.respuestas["/api/chat"] = (
        200, {"message": {"role": "assistant", "content": "esto no es json"}}
    )
    with pytest.raises(PasoFallido, match="no es JSON") as info:
        ollama.chat_json("m", [], {}, url=servidor_falso)
    assert "esto no es json" in info.value.detalle


def test_asegurar_servidor_no_arranca_si_ya_responde(servidor_falso, monkeypatch):
    monkeypatch.setattr(ollama.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("no debe lanzar ollama serve"))
    s = ollama.asegurar_servidor(servidor_falso)
    assert s.arrancado_por_nosotros is False
    s.cerrar()  # no hace nada


def test_asegurar_servidor_arranca_y_cierra(monkeypatch):
    lanzado = {}

    class ProcesoFalso:
        def __init__(self):
            self.terminado = False

        def terminate(self):
            self.terminado = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.terminado = True

    proceso = ProcesoFalso()

    def falso_popen(cmd, **kwargs):
        lanzado["cmd"] = cmd
        return proceso

    monkeypatch.setattr(ollama.subprocess, "Popen", falso_popen)
    monkeypatch.setattr(ollama.shutil, "which", lambda n: "/opt/homebrew/bin/ollama")
    # Primera sonda: no responde; tras arrancar: responde.
    sondas = iter([False, False, True])
    monkeypatch.setattr(ollama, "disponible",
                        lambda url=ollama.URL, timeout=1.0: next(sondas))
    monkeypatch.setattr(ollama.time, "sleep", lambda s: None)
    s = ollama.asegurar_servidor("http://x")
    assert lanzado["cmd"] == ["/opt/homebrew/bin/ollama", "serve"]
    assert s.arrancado_por_nosotros is True
    s.cerrar()
    assert proceso.terminado is True


def test_asegurar_servidor_sin_binario(monkeypatch):
    monkeypatch.setattr(ollama, "disponible",
                        lambda url=ollama.URL, timeout=1.0: False)
    monkeypatch.setattr(ollama.shutil, "which", lambda n: None)
    with pytest.raises(PasoFallido, match="Ollama no está instalado"):
        ollama.asegurar_servidor("http://x")


def test_asegurar_servidor_no_responde_tras_arrancar(monkeypatch):
    class ProcesoFalso:
        def terminate(self): pass
        def wait(self, timeout=None): return 0
        def kill(self): pass

    monkeypatch.setattr(ollama.subprocess, "Popen", lambda *a, **k: ProcesoFalso())
    monkeypatch.setattr(ollama.shutil, "which", lambda n: "/x/ollama")
    monkeypatch.setattr(ollama, "disponible",
                        lambda url=ollama.URL, timeout=1.0: False)
    monkeypatch.setattr(ollama.time, "sleep", lambda s: None)
    tiempos = iter([0.0, 5.0, 10.0, 16.0, 17.0])
    monkeypatch.setattr(ollama.time, "monotonic", lambda: next(tiempos))
    with pytest.raises(PasoFallido, match="Ollama no responde"):
        ollama.asegurar_servidor("http://x", espera_max=15.0)
```

- [ ] **Step 2: Comprobar que fallan**

Run: `.venv-clearvoice/bin/python -m pytest tests/test_ollama.py -q`
Expected: error de colección `ModuleNotFoundError: No module named 'videopipeline.ollama'`.

- [ ] **Step 3: Implementar**

Crear `videopipeline/ollama.py`:

```python
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
```

- [ ] **Step 4: Comprobar que pasan**

Run: `.venv-clearvoice/bin/python -m pytest tests/test_ollama.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add videopipeline/ollama.py tests/test_ollama.py
git commit -m "feat(ollama): minimal HTTP client with on-demand server start

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Módulo caption (prompt, validación, .md)

**Files:**
- Create: `videopipeline/caption.py`
- Test: `tests/test_caption.py`

**Interfaces:**
- Consumes: `Palabra` de `videopipeline/subtitles.py` (`Palabra(texto, inicio, fin)`); `chat_json` de Task 3; `PasoFallido`.
- Produces:
  - `@dataclass Caption(titulo: str, caption: str, hashtags: list[str], palabras_clave: list[str])` con propiedad `hashtags_texto -> str` (unidos por espacio) y método `texto_completo() -> str` (título, línea en blanco, caption, línea en blanco, hashtags, salto final).
  - `MAX_PALABRAS = 3500`, `MAX_TITULO = 60`
  - `texto_plano(palabras: list[Palabra]) -> str`
  - `recortar(transcripcion: str, max_palabras=MAX_PALABRAS) -> str`
  - `construir_mensajes(transcripcion: str, contexto_marca: str) -> list[dict]`
  - `ESQUEMA: dict`
  - `generar(transcripcion, contexto_marca, modelo, cliente=chat_json) -> Caption`
  - `escribir_md(caption: Caption, ruta: Path) -> None`
  - `leer_md(ruta: Path) -> Caption | None`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_caption.py`:

```python
from __future__ import annotations

import pytest

from videopipeline import caption as cap
from videopipeline.steps import PasoFallido
from videopipeline.subtitles import Palabra


def _respuesta_ok() -> dict:
    return {
        "titulo": "Chat GPT Ads: segundo día y validación",
        "caption": "Hoy toca ser honestos.\n\n¿Y tú?",
        "hashtags": ["#marketingdigital", "#chatgptads", "#ia", "#negocios",
                     "#seo", "#reels", "#emprender", "#ads"],
        "palabras_clave": ["chat gpt ads", "validación perfil"],
    }


def test_texto_plano_une_palabras():
    palabras = [Palabra("Hola", 0, 0.2), Palabra("mundo", 0.2, 0.4)]
    assert cap.texto_plano(palabras) == "Hola mundo"


def test_recortar_a_max_palabras():
    texto = " ".join(f"p{i}" for i in range(4000))
    recortado = cap.recortar(texto)
    assert len(recortado.split()) == cap.MAX_PALABRAS
    assert recortado.startswith("p0 p1")
    assert cap.recortar("corto") == "corto"


def test_construir_mensajes_sin_marca():
    m = cap.construir_mensajes("blabla", "")
    assert [x["role"] for x in m] == ["system", "user"]
    assert "Contexto de marca" not in m[0]["content"]
    assert "blabla" in m[1]["content"]


def test_construir_mensajes_con_marca():
    m = cap.construir_mensajes("blabla", "Soy Alberto, tono cercano")
    assert "Contexto de marca" in m[0]["content"]
    assert "Soy Alberto, tono cercano" in m[0]["content"]


def test_esquema_exige_los_cuatro_campos():
    assert set(cap.ESQUEMA["required"]) == {"titulo", "caption", "hashtags",
                                            "palabras_clave"}


def test_generar_usa_cliente_y_devuelve_caption():
    llamadas = []

    def cliente(modelo, mensajes, esquema):
        llamadas.append((modelo, mensajes, esquema))
        return _respuesta_ok()

    c = cap.generar("transcripción", "marca", "qwen3.5:9b", cliente=cliente)
    assert isinstance(c, cap.Caption)
    assert c.titulo.startswith("Chat GPT Ads")
    assert llamadas[0][0] == "qwen3.5:9b"
    assert llamadas[0][2] is cap.ESQUEMA


def test_generar_normaliza_hashtags_y_titulo():
    r = _respuesta_ok()
    r["hashtags"] = ["MarketingDigital", "#ia", "#IA", "con espacio", "#seo"] + ["#x"] * 3
    r["titulo"] = "T" * 80

    c = cap.generar("t", "", "m", cliente=lambda *a: r)
    assert c.hashtags == ["#marketingdigital", "#ia", "#conespacio", "#seo", "#x"]
    assert len(c.titulo) == cap.MAX_TITULO


def test_generar_falla_si_faltan_campos():
    with pytest.raises(PasoFallido, match="respuesta del modelo no válida") as info:
        cap.generar("t", "", "m", cliente=lambda *a: {"titulo": "solo"})
    assert "solo" in info.value.detalle


def test_generar_falla_si_transcripcion_vacia():
    with pytest.raises(PasoFallido, match="transcripción"):
        cap.generar("   ", "", "m", cliente=lambda *a: pytest.fail("no llamar"))


def test_md_ida_y_vuelta(tmp_path):
    c = cap.Caption(**_respuesta_ok())
    ruta = tmp_path / "v_limpio.md"
    cap.escribir_md(c, ruta)
    texto = ruta.read_text(encoding="utf-8")
    assert texto.startswith("# Chat GPT Ads")
    assert "## Caption" in texto and "## Hashtags" in texto and "## Palabras clave" in texto
    assert cap.leer_md(ruta) == c


def test_leer_md_inexistente_o_corrupto(tmp_path):
    assert cap.leer_md(tmp_path / "no.md") is None
    (tmp_path / "raro.md").write_text("sin secciones", encoding="utf-8")
    assert cap.leer_md(tmp_path / "raro.md") is None


def test_texto_completo_y_hashtags_texto():
    c = cap.Caption(**_respuesta_ok())
    assert c.hashtags_texto == " ".join(_respuesta_ok()["hashtags"])
    completo = c.texto_completo()
    assert completo.splitlines()[0] == c.titulo
    assert completo.rstrip().endswith(c.hashtags_texto)
```

- [ ] **Step 2: Comprobar que fallan**

Run: `.venv-clearvoice/bin/python -m pytest tests/test_caption.py -q`
Expected: error de colección `ModuleNotFoundError: No module named 'videopipeline.caption'`.

- [ ] **Step 3: Implementar**

Crear `videopipeline/caption.py`:

```python
"""Título SEO, caption y hashtags a partir de la transcripción, vía LLM local.

Todo es puro salvo `generar`, que recibe el cliente inyectado (por defecto
`ollama.chat_json`) para poder testearse sin servidor.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ollama import chat_json
from .steps import PasoFallido
from .subtitles import Palabra

MAX_PALABRAS = 3500
MAX_TITULO = 60
MIN_HASHTAGS, MAX_HASHTAGS = 8, 15

_SYSTEM = (
    "Eres un experto en SEO y copywriting para vídeo corto (Instagram Reels, "
    "TikTok, YouTube Shorts) en español de España. A partir de la transcripción "
    "de un vídeo genera:\n"
    f"- titulo: máximo {MAX_TITULO} caracteres, con la palabra clave principal al "
    "inicio, concreto, sin clickbait vacío.\n"
    "- caption: 120-200 palabras. Primera línea = gancho. Desarrollo con las 2-3 "
    "ideas clave del vídeo. Cierra con una llamada a la acción. Tono cercano y "
    "profesional. Sin hashtags dentro del caption.\n"
    f"- hashtags: entre {MIN_HASHTAGS} y {MAX_HASHTAGS}, en minúsculas, sin "
    "espacios, empezando por #. Mezcla 3 genéricos de alto volumen, 5 o más de "
    "nicho y 2 del tema concreto.\n"
    "- palabras_clave: 5-8 términos de búsqueda en español.\n"
    "No inventes datos que no estén en la transcripción. Responde solo JSON."
)

ESQUEMA: dict = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"},
                     "minItems": MIN_HASHTAGS, "maxItems": MAX_HASHTAGS},
        "palabras_clave": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["titulo", "caption", "hashtags", "palabras_clave"],
}


@dataclass
class Caption:
    titulo: str
    caption: str
    hashtags: list[str]
    palabras_clave: list[str]

    @property
    def hashtags_texto(self) -> str:
        return " ".join(self.hashtags)

    def texto_completo(self) -> str:
        return f"{self.titulo}\n\n{self.caption}\n\n{self.hashtags_texto}\n"


def texto_plano(palabras: list[Palabra]) -> str:
    return " ".join(p.texto for p in palabras)


def recortar(transcripcion: str, max_palabras: int = MAX_PALABRAS) -> str:
    palabras = transcripcion.split()
    if len(palabras) <= max_palabras:
        return transcripcion
    return " ".join(palabras[:max_palabras])


def construir_mensajes(transcripcion: str, contexto_marca: str) -> list[dict]:
    system = _SYSTEM
    if contexto_marca.strip():
        system += (
            "\n\nContexto de marca (respétalo en tono, nombre y llamada a la "
            f"acción):\n{contexto_marca.strip()}"
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Transcripción:\n{recortar(transcripcion)}"},
    ]


def _normalizar_hashtag(texto: str) -> str:
    limpio = re.sub(r"\s+", "", texto.strip().lstrip("#")).lower()
    return f"#{limpio}" if limpio else ""


def _validar(datos: dict) -> Caption:
    faltan = [c for c in ESQUEMA["required"] if c not in datos]
    tipos_mal = (
        not isinstance(datos.get("titulo"), str)
        or not isinstance(datos.get("caption"), str)
        or not isinstance(datos.get("hashtags"), list)
        or not isinstance(datos.get("palabras_clave"), list)
    )
    if faltan or tipos_mal:
        raise PasoFallido(
            "La respuesta del modelo no válida: faltan campos o tipos incorrectos",
            detalle=json.dumps(datos, ensure_ascii=False)[:2000],
        )
    vistos: list[str] = []
    for h in datos["hashtags"]:
        n = _normalizar_hashtag(str(h))
        if n and n not in vistos:
            vistos.append(n)
    return Caption(
        titulo=datos["titulo"].strip()[:MAX_TITULO],
        caption=datos["caption"].strip(),
        hashtags=vistos,
        palabras_clave=[str(p).strip() for p in datos["palabras_clave"] if str(p).strip()],
    )


def generar(
    transcripcion: str,
    contexto_marca: str,
    modelo: str,
    cliente: Callable[[str, list[dict], dict], dict] = chat_json,
) -> Caption:
    if not transcripcion.strip():
        raise PasoFallido("La transcripción está vacía; no hay texto para el caption")
    datos = cliente(modelo, construir_mensajes(transcripcion, contexto_marca), ESQUEMA)
    return _validar(datos)


def escribir_md(caption: Caption, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    lineas = [
        f"# {caption.titulo}", "",
        "## Caption", caption.caption, "",
        "## Hashtags", caption.hashtags_texto, "",
        "## Palabras clave",
        *[f"- {p}" for p in caption.palabras_clave], "",
    ]
    ruta.write_text("\n".join(lineas), encoding="utf-8")


def leer_md(ruta: Path) -> Caption | None:
    """Inverso de `escribir_md`. `None` si no existe o no tiene el formato."""
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError:
        return None
    partes = re.split(r"^## ", texto, flags=re.M)
    if len(partes) < 4 or not partes[0].startswith("# "):
        return None
    titulo = partes[0][2:].strip()
    secciones = {}
    for parte in partes[1:]:
        nombre, _, cuerpo = parte.partition("\n")
        secciones[nombre.strip()] = cuerpo.strip()
    try:
        return Caption(
            titulo=titulo,
            caption=secciones["Caption"],
            hashtags=secciones["Hashtags"].split(),
            palabras_clave=[l[2:].strip() for l in secciones["Palabras clave"].splitlines()
                            if l.startswith("- ")],
        )
    except KeyError:
        return None
```

- [ ] **Step 4: Comprobar que pasan**

Run: `.venv-clearvoice/bin/python -m pytest tests/test_caption.py -q`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add videopipeline/caption.py tests/test_caption.py
git commit -m "feat(caption): prompt, JSON schema, validation and markdown I/O

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Paso de caption en el pipeline

**Files:**
- Modify: `videopipeline/pipeline.py` (`_fase_subtitulos` líneas 34-95, `run` líneas 98-end)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `caption.generar`, `caption.escribir_md`, `caption.texto_plano`, `ollama.asegurar_servidor` (Tasks 3-4); `transcribir` ya importado.
- Produces: `_fase_subtitulos(...) -> tuple[Path, list[Palabra] | None]`; `_fase_caption(config, video_publicable, final, palabras, on_progress, paso, total) -> None`; `pasos_extra(config) -> int`. En `pipeline` los nombres parcheables son `generar_caption` y `asegurar_servidor`.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `tests/test_pipeline.py`:

```python
@pytest.fixture()
def entorno_caption(entorno_subs, monkeypatch):
    """Extiende `entorno_subs` mockeando Ollama y el generador de caption."""
    llamadas, video, base = entorno_subs

    class ServidorFalso:
        def cerrar(self):
            llamadas.append("ollama:cerrar")

    def falso_asegurar(*args, **kwargs):
        llamadas.append("ollama:asegurar")
        return ServidorFalso()

    def falso_generar(transcripcion, contexto_marca, modelo, cliente=None):
        llamadas.append(f"generar:{modelo}:{contexto_marca}:{transcripcion}")
        from videopipeline.caption import Caption
        return Caption(titulo="T", caption="C", hashtags=["#a"], palabras_clave=["k"])

    monkeypatch.setattr(pipeline, "asegurar_servidor", falso_asegurar)
    monkeypatch.setattr(pipeline, "generar_caption", falso_generar)
    return llamadas, video, base


def test_caption_con_subtitulos_reutiliza_transcripcion(entorno_caption, tmp_path):
    llamadas, video, base = entorno_caption
    salida = tmp_path / "f.mp4"
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=salida, subtitulos=True,
                       caption_seo=True, contexto_marca="marca X"),
        eventos.append,
    )
    assert llamadas.count("transcribir:es:small") == 1
    assert "generar:qwen3.5:9b:marca X:hola" in llamadas
    assert llamadas.index("ollama:asegurar") < llamadas.index("ollama:cerrar")
    md = (tmp_path / "f.md").read_text(encoding="utf-8")
    assert md.startswith("# T")
    etiquetas = [e["label"] for e in eventos if "label" in e]
    assert "Generando caption SEO" in etiquetas
    assert etiquetas.count("Transcribiendo") == 1
    assert all(e["total"] == 7 for e in eventos if "total" in e)  # 4 + 2 subs + 1


def test_caption_sin_subtitulos_transcribe(entorno_caption, tmp_path):
    llamadas, video, base = entorno_caption
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", caption_seo=True),
        eventos.append,
    )
    assert llamadas.count("transcribir:es:small") == 1
    assert "srt" not in llamadas and "quemar" not in llamadas
    etiquetas = [e["label"] for e in eventos if "label" in e]
    assert etiquetas[-2:] == ["Transcribiendo", "Generando caption SEO"]
    assert all(e["total"] == 6 for e in eventos if "total" in e)  # 4 + 2


def test_caption_off_no_toca_nada(entorno_caption, tmp_path):
    llamadas, video, base = entorno_caption
    pipeline.run(PipelineConfig(video=video, salida=tmp_path / "f.mp4"), None)
    assert not any(l.startswith("generar:") or l.startswith("ollama:") for l in llamadas)
    assert not (tmp_path / "f.md").exists()


def test_caption_falla_degrada_con_warning(entorno_caption, tmp_path, monkeypatch):
    llamadas, video, base = entorno_caption

    def revienta(*a, **k):
        raise RuntimeError("modelo caído")

    monkeypatch.setattr(pipeline, "generar_caption", revienta)
    salida = tmp_path / "f.mp4"
    (tmp_path / "f.md").write_text("viejo", encoding="utf-8")
    eventos: list[dict] = []
    resultado = pipeline.run(
        PipelineConfig(video=video, salida=salida, caption_seo=True), eventos.append
    )
    assert resultado == salida and salida.is_file()
    avisos = [e["warning"] for e in eventos if "warning" in e]
    assert len(avisos) == 1
    assert avisos[0].startswith("Caption SEO falló: modelo caído")
    assert "sin caption" in avisos[0]
    assert not (tmp_path / "f.md").exists()  # el .md obsoleto se borra
    assert "ollama:cerrar" in llamadas  # el servidor se cierra aunque falle


def test_caption_con_subtitulos_fallidos_transcribe_de_nuevo(entorno_caption, tmp_path,
                                                             monkeypatch):
    """Si la transcripción de subtítulos falló, el caption lo reintenta él."""
    llamadas, video, base = entorno_caption
    intentos = {"n": 0}

    def transcribir_flaky(video_, idioma, modelo):
        intentos["n"] += 1
        if intentos["n"] == 1:
            raise RuntimeError("whisper caído")
        from videopipeline.subtitles import Palabra
        return [Palabra(texto="hola", inicio=0.0, fin=0.5)]

    monkeypatch.setattr(pipeline, "transcribir", transcribir_flaky)
    eventos: list[dict] = []
    pipeline.run(
        PipelineConfig(video=video, salida=tmp_path / "f.mp4", subtitulos=True,
                       caption_seo=True),
        eventos.append,
    )
    assert intentos["n"] == 2
    assert (tmp_path / "f.md").is_file()


def test_pasos_extra():
    base = PipelineConfig(video=Path("/v.mp4"))
    assert pipeline.pasos_extra(base) == 0
    assert pipeline.pasos_extra(PipelineConfig(video=Path("/v.mp4"), subtitulos=True)) == 2
    assert pipeline.pasos_extra(PipelineConfig(video=Path("/v.mp4"), caption_seo=True)) == 2
    assert pipeline.pasos_extra(
        PipelineConfig(video=Path("/v.mp4"), subtitulos=True, caption_seo=True)
    ) == 3
```

- [ ] **Step 2: Comprobar que fallan**

Run: `.venv-clearvoice/bin/python -m pytest tests/test_pipeline.py -q`
Expected: los 6 nuevos fallan (`AttributeError: module 'videopipeline.pipeline' has no attribute 'asegurar_servidor'` / `generar_caption` / `pasos_extra`).

- [ ] **Step 3: Implementar**

En `videopipeline/pipeline.py`:

(a) Imports, tras `from .subtitles import ...`:

```python
from .caption import escribir_md, texto_plano
from .caption import generar as generar_caption
from .ollama import asegurar_servidor
from .subtitles import Palabra
```

(b) `_fase_subtitulos` pasa a devolver la tupla. Cambiar la firma y los tres `return`:

```python
def _fase_subtitulos(config: PipelineConfig, tmp_final: Path, final: Path,
                     trabajo: Path, on_progress: Progreso | None,
                     paso: int, total: int) -> tuple[Path, list[Palabra] | None]:
    """Añade subtítulos a tmp_final. Devuelve (ruta a publicar, palabras).

    Si algo falla, emite {"warning": ...} y devuelve tmp_final sin tocar:
    el pipeline nunca falla por subtítulos. `palabras` es None si la
    transcripción no se consiguió (el caption la reintentará).
    """
```

- En el primer `except` (transcripción): `return tmp_final, None`.
- En el `return tmp_subs` del quemado: `return tmp_subs, palabras`.
- En el último `except` (quemado): `return tmp_final, palabras`.

(c) Nuevas funciones tras `_fase_subtitulos`:

```python
def _fase_caption(config: PipelineConfig, video_publicable: Path, final: Path,
                  palabras: list[Palabra] | None, on_progress: Progreso | None,
                  paso: int, total: int) -> None:
    """Genera final.with_suffix('.md'). Nunca hace fallar el vídeo."""
    ruta_md = final.with_suffix(".md")
    ruta_md.unlink(missing_ok=True)  # nunca dejar un caption obsoleto
    servidor = None
    try:
        if palabras is None:
            _emitir(on_progress, paso, total, "Transcribiendo")
            palabras = transcribir(video_publicable, config.idioma_subs,
                                   config.modelo_whisper)
            paso += 1
        _emitir(on_progress, paso, total, "Generando caption SEO")
        servidor = asegurar_servidor()
        caption = generar_caption(
            texto_plano(palabras), config.contexto_marca, config.modelo_caption
        )
        escribir_md(caption, ruta_md)
    except Exception as error:  # noqa: BLE001 — degradación deliberada
        ruta_md.unlink(missing_ok=True)
        _avisar(on_progress,
                f"Caption SEO falló: {error}. Vídeo guardado sin caption.")
    finally:
        if servidor is not None:
            servidor.cerrar()


def pasos_extra(config: PipelineConfig) -> int:
    """Pasos añadidos por subtítulos (2) y caption (1, o 2 si transcribe él)."""
    extra = 2 if config.subtitulos else 0
    if config.caption_seo:
        extra += 1 if config.subtitulos else 2
    return extra
```

(d) En `run`, sustituir `extra = 2 if config.subtitulos else 0` por `extra = pasos_extra(config)`.

(e) En la rama `solo_silencios` de `run`, sustituir el bloque desde `publicar = tmp_final` hasta `return final` por:

```python
        publicar, palabras = tmp_final, None
        if config.subtitulos:
            publicar, palabras = _fase_subtitulos(
                config, tmp_final, final, trabajo, on_progress, 2, total
            )
        if config.caption_seo:
            primer_paso_caption = 1 + (2 if config.subtitulos else 0) + 1
            _fase_caption(config, publicar, final, palabras, on_progress,
                          primer_paso_caption, total)
        publicar.replace(final)
        return final
```

(f) Al final de `run` (rama general), sustituir desde `publicar = tmp_final` hasta `return final` por:

```python
    publicar, palabras = tmp_final, None
    pasos_base = total - pasos_extra(config)
    if config.subtitulos:
        publicar, palabras = _fase_subtitulos(
            config, tmp_final, final, trabajo, on_progress, pasos_base + 1, total
        )
    if config.caption_seo:
        primer_paso_caption = pasos_base + (2 if config.subtitulos else 0) + 1
        _fase_caption(config, publicar, final, palabras, on_progress,
                      primer_paso_caption, total)
    publicar.replace(final)
    return final
```

- [ ] **Step 4: Comprobar que pasan (todos los de pipeline, incluidos los antiguos de subtítulos)**

Run: `.venv-clearvoice/bin/python -m pytest tests/test_pipeline.py -q`
Expected: todos pasan. Si `test_subs_on_modo_completo` u otros antiguos fallan por el tipo de retorno de `_fase_subtitulos`, revisar que los tres `return` devuelven tupla.

- [ ] **Step 5: Suite completa**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m "not slow" -q`
Expected: verde.

- [ ] **Step 6: Commit**

```bash
git add videopipeline/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): optional SEO caption step reusing the transcription

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Flags de CLI

**Files:**
- Modify: `limpiarVideo.py` (argumentos líneas 24-31, `PipelineConfig(...)` línea 54)
- Test: `tests/test_cli_compat.py`

**Interfaces:**
- Produces: `limpiarVideo.py VIDEO [SALIDA] --caption [--marca TEXTO]`.

- [ ] **Step 1: Ver cómo prueban el CLI los tests existentes**

Run: `sed -n 1,40p tests/test_cli_compat.py`
Anotar cómo falsean `run`, `comprobar_dependencias` y `tiene_pista_audio` (por ejemplo `monkeypatch.setattr(limpiarVideo, "run", ...)`). Usar el mismo patrón en el test siguiente.

- [ ] **Step 2: Escribir el test que falla**

Añadir al final de `tests/test_cli_compat.py` (adaptar los `monkeypatch.setattr` al patrón visto en el paso 1):

```python
def test_cli_caption_y_marca(tmp_path, monkeypatch, capsys):
    import limpiarVideo

    video = tmp_path / "v.mp4"
    video.write_bytes(b"VID")
    capturado = {}

    def falso_run(config, on_progress):
        capturado["config"] = config
        return config.ruta_salida_final()

    monkeypatch.setattr(limpiarVideo, "run", falso_run)
    monkeypatch.setattr(limpiarVideo, "comprobar_dependencias", lambda: [])
    monkeypatch.setattr(limpiarVideo, "tiene_pista_audio", lambda v: True)
    limpiarVideo.main([str(video), "--caption", "--marca", "Soy Alberto"])
    config = capturado["config"]
    assert config.caption_seo is True
    assert config.contexto_marca == "Soy Alberto"
```

- [ ] **Step 3: Comprobar que falla**

Run: `.venv-clearvoice/bin/python -m pytest tests/test_cli_compat.py -q`
Expected: 1 failed (`SystemExit: 2`, argparse no conoce `--caption`).

- [ ] **Step 4: Implementar**

En `limpiarVideo.py`, tras el `add_argument("salida", ...)`:

```python
    parser.add_argument(
        "--caption", action="store_true",
        help="Genera título SEO, caption y hashtags (nombre_limpio.md) con Ollama.",
    )
    parser.add_argument(
        "--marca", default="",
        help="Contexto de marca para el caption (quién eres, tono, CTA).",
    )
```

Y la construcción de la config:

```python
    config = PipelineConfig(
        video=video, salida=salida,
        caption_seo=args.caption, contexto_marca=args.marca,
    )
```

- [ ] **Step 5: Comprobar que pasa**

Run: `.venv-clearvoice/bin/python -m pytest tests/test_cli_compat.py -q`
Expected: todos pasan.

- [ ] **Step 6: Commit**

```bash
git add limpiarVideo.py tests/test_cli_compat.py
git commit -m "feat(cli): --caption and --marca flags

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Ajustes persistentes de caption

**Files:**
- Modify: `app/settings.py` (clase `Ajustes`)
- Test: `tests/test_app_queue.py` (ahí viven los tests de `Ajustes`)

**Interfaces:**
- Produces: `Ajustes.contexto_marca: str` (get/set, clave `caption/contexto_marca`), `Ajustes.modelo_caption: str` (get/set, clave `caption/modelo`, por defecto `"qwen3.5:9b"`).

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `tests/test_app_queue.py`:

```python
def test_ajustes_caption_persistidos(tmp_path):
    a = _ajustes(tmp_path)
    assert a.contexto_marca == ""
    assert a.modelo_caption == "qwen3.5:9b"
    a.contexto_marca = "Soy Alberto\ntono cercano"
    a.modelo_caption = "qwen3.5:9b-q8_0"
    b = _ajustes(tmp_path)  # misma ruta .ini → mismos datos
    assert b.contexto_marca == "Soy Alberto\ntono cercano"
    assert b.modelo_caption == "qwen3.5:9b-q8_0"
```

- [ ] **Step 2: Comprobar que falla**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest tests/test_app_queue.py -q -k caption`
Expected: FAIL `AttributeError: 'Ajustes' object has no attribute 'contexto_marca'`.

- [ ] **Step 3: Implementar**

En `app/settings.py`, dentro de `Ajustes`, tras el setter de `carpeta_salida`:

```python
    @property
    def contexto_marca(self) -> str:
        return str(self._q.value("caption/contexto_marca", "") or "")

    @contexto_marca.setter
    def contexto_marca(self, texto: str) -> None:
        self._q.setValue("caption/contexto_marca", texto)

    @property
    def modelo_caption(self) -> str:
        return str(self._q.value("caption/modelo", "qwen3.5:9b") or "qwen3.5:9b")

    @modelo_caption.setter
    def modelo_caption(self, modelo: str) -> None:
        self._q.setValue("caption/modelo", modelo)
```

- [ ] **Step 4: Comprobar que pasa**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest tests/test_app_queue.py -q`
Expected: todos pasan.

- [ ] **Step 5: Commit**

```bash
git add app/settings.py tests/test_app_queue.py
git commit -m "feat(settings): persist brand context and caption model

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Diálogo de marca

**Files:**
- Create: `app/widgets/dialogo_marca.py`
- Test: `tests/test_app_widgets.py`

**Interfaces:**
- Produces: `DialogoMarca(texto_inicial: str = "", parent=None)` (`QDialog`) con `texto() -> str`; atributo público `editor: QPlainTextEdit`.

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `tests/test_app_widgets.py`:

```python
def test_dialogo_marca_devuelve_texto(qtbot):
    from app.widgets.dialogo_marca import DialogoMarca

    d = DialogoMarca("inicial")
    qtbot.addWidget(d)
    assert d.texto() == "inicial"
    d.editor.setPlainText("  Soy Alberto  ")
    assert d.texto() == "Soy Alberto"
```

- [ ] **Step 2: Comprobar que falla**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest tests/test_app_widgets.py -q -k marca`
Expected: FAIL `ModuleNotFoundError: No module named 'app.widgets.dialogo_marca'`.

- [ ] **Step 3: Implementar**

Crear `app/widgets/dialogo_marca.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)


class DialogoMarca(QDialog):
    """Texto libre que se añade al prompt del caption SEO."""

    def __init__(self, texto_inicial: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contexto de marca")
        self.resize(520, 320)
        layout = QVBoxLayout(self)
        ayuda = QLabel(
            "Quién eres, a quién hablas, tono, llamada a la acción habitual, "
            "hashtags que quieres siempre. Se envía al modelo con cada vídeo."
        )
        ayuda.setWordWrap(True)
        layout.addWidget(ayuda)
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(texto_inicial)
        self.editor.setPlaceholderText(
            "Ej.: Soy Alberto, consultor de IA para pymes (Evolve2Digital). "
            "Tono directo y cercano. CTA: sígueme para más. Hashtags fijos: "
            "#evolve2digital #iaparapymes"
        )
        layout.addWidget(self.editor, 1)
        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

    def texto(self) -> str:
        return self.editor.toPlainText().strip()
```

- [ ] **Step 4: Comprobar que pasa**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest tests/test_app_widgets.py -q`
Expected: todos pasan.

- [ ] **Step 5: Commit**

```bash
git add app/widgets/dialogo_marca.py tests/test_app_widgets.py
git commit -m "feat(gui): brand context dialog

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Casilla "Caption SEO" y botón "Marca…" en el panel

**Files:**
- Modify: `app/widgets/panel_opciones.py` (constructor tras el grupo de subtítulos, `valores()`, `cargar()`)
- Test: `tests/test_app_widgets.py`

**Interfaces:**
- Produces: `PanelOpciones.check_caption: QCheckBox`, `PanelOpciones.boton_marca: QPushButton`, señal `PanelOpciones.editar_marca = Signal()`; `valores()["caption_seo"]: bool`; `cargar({"caption_seo": ...})` acepta bool o cadena `"true"/"1"` (QSettings devuelve cadenas).

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `tests/test_app_widgets.py`:

```python
def test_panel_caption_defecto_off_y_en_valores(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    assert panel.valores()["caption_seo"] is False
    panel.check_caption.setChecked(True)
    assert panel.valores()["caption_seo"] is True
    PipelineConfig(video=Path("/v.mp4"), **panel.valores()).validar()


def test_panel_caption_cargar_desde_qsettings(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    panel.cargar({"caption_seo": "true"})
    assert panel.check_caption.isChecked()
    panel.cargar({"caption_seo": False})
    assert not panel.check_caption.isChecked()
    panel.cargar({})  # clave ausente → sigue como estaba
    assert not panel.check_caption.isChecked()


def test_panel_boton_marca_emite_senal(qtbot):
    panel = PanelOpciones()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.editar_marca, timeout=1000):
        panel.boton_marca.click()
```

- [ ] **Step 2: Comprobar que fallan**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest tests/test_app_widgets.py -q -k caption`
Expected: 3 failed (`KeyError: 'caption_seo'`, `AttributeError: check_caption`).

- [ ] **Step 3: Implementar**

En `app/widgets/panel_opciones.py`:

(a) Importar `QPushButton` en la lista de `PySide6.QtWidgets`.

(b) Junto a `opciones_subs_cambiadas = Signal()`:

```python
    editar_marca = Signal()
```

(c) En el constructor, tras `self._actualizar_subtitulos()` (la primera llamada, justo antes de `layout.addStretch(1)`):

```python
        grupo_caption = QGroupBox("Caption SEO")
        fila_caption = QHBoxLayout(grupo_caption)
        self.check_caption = QCheckBox("Título, caption y hashtags")
        self.check_caption.setToolTip(
            "Genera nombre_limpio.md con un modelo local (Ollama) a partir "
            "de la transcripción."
        )
        self.boton_marca = QPushButton("Marca…")
        self.boton_marca.setToolTip("Contexto de marca que se añade al prompt.")
        self.boton_marca.clicked.connect(self.editar_marca)
        fila_caption.addWidget(self.check_caption, 1)
        fila_caption.addWidget(self.boton_marca)
        layout.addWidget(grupo_caption)
```

(d) En `valores()`, añadir la clave:

```python
            "caption_seo": self.check_caption.isChecked(),
```

(e) En `cargar()`, antes de `self._actualizar_habilitados()`:

```python
        if "caption_seo" in valores:
            valor = valores["caption_seo"]
            self.check_caption.setChecked(
                valor if isinstance(valor, bool)
                else str(valor).lower() in ("true", "1")
            )
```

- [ ] **Step 4: Comprobar que pasan (y que `test_procesar_construye_configs` de `test_app_main.py` sigue verde, porque `valores()` va directo a `PipelineConfig(**valores)`)**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest tests/test_app_widgets.py tests/test_app_main.py -q`
Expected: todos pasan.

- [ ] **Step 5: Commit**

```bash
git add app/widgets/panel_opciones.py tests/test_app_widgets.py
git commit -m "feat(gui): Caption SEO checkbox and brand button in options panel

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Panel de caption con Copiar

**Files:**
- Create: `app/widgets/panel_caption.py`
- Test: `tests/test_app_widgets.py`

**Interfaces:**
- Consumes: `Caption` de Task 4.
- Produces: `PanelCaption(parent=None)` (`QWidget`) con `mostrar(caption: Caption | None) -> None`; atributos públicos `etiqueta_titulo: QLabel`, `texto_caption: QTextEdit`, `etiqueta_hashtags: QLabel`, `boton_copiar_titulo`, `boton_copiar_caption`, `boton_copiar_hashtags`, `boton_copiar_todo` (`QPushButton`). Oculto (`isHidden()`) cuando no hay caption.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `tests/test_app_widgets.py`:

```python
def _caption_ejemplo():
    from videopipeline.caption import Caption
    return Caption(titulo="Título X", caption="Cuerpo\ndos líneas",
                   hashtags=["#a", "#b"], palabras_clave=["k"])


def test_panel_caption_oculto_sin_datos_y_muestra_con_datos(qtbot):
    from app.widgets.panel_caption import PanelCaption

    panel = PanelCaption()
    qtbot.addWidget(panel)
    panel.mostrar(None)
    assert panel.isHidden()
    panel.mostrar(_caption_ejemplo())
    assert not panel.isHidden()
    assert panel.etiqueta_titulo.text() == "Título X"
    assert panel.texto_caption.toPlainText() == "Cuerpo\ndos líneas"
    assert panel.etiqueta_hashtags.text() == "#a #b"


def test_panel_caption_copia_al_portapapeles(qtbot):
    from PySide6.QtWidgets import QApplication
    from app.widgets.panel_caption import PanelCaption

    panel = PanelCaption()
    qtbot.addWidget(panel)
    panel.mostrar(_caption_ejemplo())
    portapapeles = QApplication.clipboard()
    panel.boton_copiar_titulo.click()
    assert portapapeles.text() == "Título X"
    panel.boton_copiar_caption.click()
    assert portapapeles.text() == "Cuerpo\ndos líneas"
    panel.boton_copiar_hashtags.click()
    assert portapapeles.text() == "#a #b"
    panel.boton_copiar_todo.click()
    assert portapapeles.text() == "Título X\n\nCuerpo\ndos líneas\n\n#a #b\n"
```

- [ ] **Step 2: Comprobar que fallan**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest tests/test_app_widgets.py -q -k panel_caption`
Expected: 2 failed (`ModuleNotFoundError: app.widgets.panel_caption`).

- [ ] **Step 3: Implementar**

Crear `app/widgets/panel_caption.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from videopipeline.caption import Caption


class PanelCaption(QWidget):
    """Muestra el caption SEO del trabajo seleccionado y lo copia por bloques."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._caption: Caption | None = None
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        grupo = QGroupBox("Caption SEO")
        layout = QVBoxLayout(grupo)
        self.etiqueta_titulo = QLabel()
        self.etiqueta_titulo.setStyleSheet("font-weight: bold;")
        self.etiqueta_titulo.setWordWrap(True)
        self.texto_caption = QTextEdit()
        self.texto_caption.setReadOnly(True)
        self.texto_caption.setFixedHeight(110)
        self.etiqueta_hashtags = QLabel()
        self.etiqueta_hashtags.setWordWrap(True)
        self.etiqueta_hashtags.setStyleSheet("color: #1e88e5;")
        layout.addWidget(self.etiqueta_titulo)
        layout.addWidget(self.texto_caption)
        layout.addWidget(self.etiqueta_hashtags)
        botones = QHBoxLayout()
        self.boton_copiar_titulo = QPushButton("Copiar título")
        self.boton_copiar_caption = QPushButton("Copiar caption")
        self.boton_copiar_hashtags = QPushButton("Copiar hashtags")
        self.boton_copiar_todo = QPushButton("Copiar todo")
        self.boton_copiar_titulo.clicked.connect(
            lambda: self._copiar(self._caption.titulo))
        self.boton_copiar_caption.clicked.connect(
            lambda: self._copiar(self._caption.caption))
        self.boton_copiar_hashtags.clicked.connect(
            lambda: self._copiar(self._caption.hashtags_texto))
        self.boton_copiar_todo.clicked.connect(
            lambda: self._copiar(self._caption.texto_completo()))
        for boton in (self.boton_copiar_titulo, self.boton_copiar_caption,
                      self.boton_copiar_hashtags, self.boton_copiar_todo):
            botones.addWidget(boton)
        layout.addLayout(botones)
        raiz.addWidget(grupo)
        self.hide()

    def mostrar(self, caption: Caption | None) -> None:
        self._caption = caption
        if caption is None:
            self.hide()
            return
        self.etiqueta_titulo.setText(caption.titulo)
        self.texto_caption.setPlainText(caption.caption)
        self.etiqueta_hashtags.setText(caption.hashtags_texto)
        self.show()

    def _copiar(self, texto: str) -> None:
        if self._caption is not None:
            QApplication.clipboard().setText(texto)
```

Nota: los `lambda` de los botones solo se ejecutan tras un clic, y los botones no son alcanzables mientras el panel está oculto, por lo que `self._caption` no es `None` al copiar; `_copiar` lo comprueba igualmente.

- [ ] **Step 4: Comprobar que pasan**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest tests/test_app_widgets.py -q`
Expected: todos pasan. Con `offscreen`, `QApplication.clipboard()` funciona en memoria.

- [ ] **Step 5: Commit**

```bash
git add app/widgets/panel_caption.py tests/test_app_widgets.py
git commit -m "feat(gui): caption panel with copy buttons

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Cableado en la ventana principal

**Files:**
- Modify: `app/main.py` (imports; constructor: columna derecha y conexiones; `_al_cambiar_seleccion`; `procesar`; `_al_terminar_trabajo`; nuevo slot `_editar_marca`)
- Test: `tests/test_app_main.py`

**Interfaces:**
- Consumes: `PanelCaption.mostrar`, `DialogoMarca`, `Ajustes.contexto_marca/modelo_caption`, `PanelOpciones.editar_marca`, `caption.leer_md`.
- Produces: `VentanaPrincipal.panel_caption: PanelCaption`; `VentanaPrincipal._editar_marca()`; `VentanaPrincipal._caption_de(trabajo) -> Caption | None`.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `tests/test_app_main.py`:

```python
def _md_ejemplo(ruta: Path) -> None:
    from videopipeline.caption import Caption, escribir_md
    escribir_md(Caption(titulo="Título X", caption="Cuerpo", hashtags=["#a"],
                        palabras_clave=["k"]), ruta)


def test_seleccion_de_hecho_muestra_caption(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4", tmp_path / "b.mp4"])
    salida_a = tmp_path / "a_limpio.mp4"
    salida_a.write_bytes(b"MP4")
    _md_ejemplo(tmp_path / "a_limpio.md")
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(salida_a), "")
    ventana.ejecutor.trabajo_terminado.emit(1, True, str(tmp_path / "b_limpio.mp4"), "")
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    assert not ventana.panel_caption.isHidden()
    assert ventana.panel_caption.etiqueta_titulo.text() == "Título X"
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(1))  # sin .md
    assert ventana.panel_caption.isHidden()


def test_terminar_trabajo_seleccionado_refresca_caption(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.vista_cola.setCurrentIndex(ventana.modelo_cola.index(0))
    assert ventana.panel_caption.isHidden()
    _md_ejemplo(tmp_path / "a_limpio.md")
    ventana.ejecutor.trabajo_terminado.emit(0, True, str(tmp_path / "a_limpio.mp4"), "")
    assert not ventana.panel_caption.isHidden()


def test_editar_marca_persiste_en_ajustes(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.contexto_marca = "antes"
    visto = {}

    class DialogoFalso:
        def __init__(self, texto_inicial="", parent=None):
            visto["inicial"] = texto_inicial

        def exec(self):
            return 1  # QDialog.DialogCode.Accepted

        def texto(self):
            return "después"

    monkeypatch.setattr("app.main.DialogoMarca", DialogoFalso)
    ventana.panel.editar_marca.emit()
    assert visto["inicial"] == "antes"
    assert ventana.ajustes.contexto_marca == "después"


def test_procesar_incluye_marca_y_modelo_caption(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.contexto_marca = "Soy Alberto"
    ventana.ajustes.modelo_caption = "qwen3.5:9b-q8_0"
    ventana.panel.check_caption.setChecked(True)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    capturado = {}
    monkeypatch.setattr(ventana.ejecutor, "iniciar",
                        lambda trabajos: capturado.setdefault("t", trabajos))
    ventana.procesar()
    config = json.loads(capturado["t"][0][1])
    assert config["caption_seo"] is True
    assert config["contexto_marca"] == "Soy Alberto"
    assert config["modelo_caption"] == "qwen3.5:9b-q8_0"
```

- [ ] **Step 2: Comprobar que fallan**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest tests/test_app_main.py -q -k "caption or marca"`
Expected: 4 failed (`AttributeError: panel_caption`, `AttributeError: app.main has no attribute DialogoMarca`…).

- [ ] **Step 3: Implementar**

En `app/main.py`:

(a) Imports, junto a los demás:

```python
from videopipeline.caption import Caption, leer_md

from .widgets.dialogo_marca import DialogoMarca
from .widgets.panel_caption import PanelCaption
```

(b) En el constructor, tras `columna_derecha.addWidget(self.vista_previa)`:

```python
        self.panel_caption = PanelCaption()
        columna_derecha.addWidget(self.panel_caption)
```

Y tras `self.panel.opciones_subs_cambiadas.connect(self._refrescar_preview)`:

```python
        self.panel.editar_marca.connect(self._editar_marca)
```

(c) `_al_cambiar_seleccion` pasa a:

```python
    def _al_cambiar_seleccion(self, indice, _anterior) -> None:
        if indice.isValid():
            trabajo = self.modelo_cola.trabajo(indice.row())
            self.vista_previa.establecer_video(trabajo.ruta)
            self._refrescar_preview()
            self.panel_caption.mostrar(self._caption_de(trabajo))
        else:
            self.vista_previa.establecer_video(None)
            self.panel_caption.mostrar(None)

    def _caption_de(self, trabajo) -> Caption | None:
        if trabajo.estado != EstadoTrabajo.HECHO or not trabajo.salida:
            return None
        return leer_md(trabajo.salida.with_suffix(".md"))
```

(d) Nuevo slot, junto a `_elegir_carpeta`:

```python
    def _editar_marca(self) -> None:
        dialogo = DialogoMarca(self.ajustes.contexto_marca, self)
        if dialogo.exec():
            self.ajustes.contexto_marca = dialogo.texto()
```

(e) En `procesar()`, la construcción de la config pasa a:

```python
            config = PipelineConfig(
                video=trabajo.ruta, salida=carpeta,
                contexto_marca=self.ajustes.contexto_marca,
                modelo_caption=self.ajustes.modelo_caption,
                **valores,
            )
```

(f) En `_al_terminar_trabajo`, dentro de la rama `if ok:` tras `self.modelo_cola.actualizar(...)`:

```python
            actual = self.vista_cola.currentIndex()
            if actual.isValid() and actual.row() == fila:
                self.panel_caption.mostrar(
                    self._caption_de(self.modelo_cola.trabajo(fila))
                )
```

- [ ] **Step 4: Comprobar que pasan**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest tests/test_app_main.py -q`
Expected: todos pasan.

- [ ] **Step 5: Suite completa y arranque manual**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m "not slow" -q`
Expected: verde.

Run: `open TheSilenceOfTheShorts.app` y comprobar a ojo: grupo "Caption SEO" con casilla y botón "Marca…"; el botón abre el diálogo; el panel de caption no aparece hasta seleccionar un trabajo hecho con `.md`. Cerrar la app.

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_app_main.py
git commit -m "feat(gui): wire caption panel, brand dialog and config into main window

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: Integración lenta y documentación

**Files:**
- Modify: `tests/test_integracion_lenta.py`
- Modify: `SETUP.md`

- [ ] **Step 1: Añadir el test lento (se salta si Ollama no responde)**

Al final de `tests/test_integracion_lenta.py`:

```python
@pytest.mark.slow
def test_pipeline_con_caption_real(video_con_voz, tmp_path, monkeypatch):
    from videopipeline import ollama
    from videopipeline.caption import leer_md

    if comprobar_dependencias():
        pytest.skip("faltan ffmpeg/auto-editor")
    if not (BASE_DIR / "checkpoints" / "MossFormer2_SE_48K").is_dir():
        pytest.skip("checkpoint MossFormer2_SE_48K no descargado")
    if not ollama.disponible():
        pytest.skip("Ollama no responde en localhost:11434")
    monkeypatch.chdir(BASE_DIR)
    salida = tmp_path / "final.mp4"
    eventos: list[dict] = []
    run(
        PipelineConfig(video=video_con_voz, salida=salida, umbral="1%",
                       caption_seo=True, contexto_marca="Prueba automática"),
        eventos.append,
    )
    avisos = [e for e in eventos if "warning" in e]
    assert avisos == [], avisos
    caption = leer_md(tmp_path / "final.md")
    assert caption is not None
    assert 0 < len(caption.titulo) <= 60
    assert 8 <= len(caption.hashtags) <= 15
    assert all(h.startswith("#") for h in caption.hashtags)
```

- [ ] **Step 2: Ejecutarlo**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m slow -q -k caption`
Expected: 1 passed (≈ 60-90 s: ClearVoice + Whisper + Ollama). Si se salta por Ollama, abrir la app de Ollama y repetir.

- [ ] **Step 3: Documentar**

En `SETUP.md`, antes de la sección `## Errores y logs`, insertar:

```markdown
## Caption SEO (título, caption, hashtags)

Casilla "Caption SEO" en el panel. Al terminar el vídeo se escribe
`nombre_limpio.md` junto a él con título (≤ 60 caracteres), caption
(120-200 palabras) y 8-15 hashtags, generados desde la transcripción por un
modelo local en Ollama. Al seleccionar el vídeo hecho en la cola aparece el
panel con botones de copiar.

- Requisitos: `brew install ollama` y `ollama pull qwen3.5:9b`. La app
  arranca `ollama serve` sola si no está corriendo y lo cierra al acabar.
- "Marca…": texto libre (quién eres, tono, CTA, hashtags fijos) que se
  añade al prompt. Se guarda en los ajustes.
- Modelo: `qwen3.5:9b` por defecto. Para cambiarlo, editar la clave
  `caption/modelo` de los ajustes (`defaults write com.albercv.LimpiadorVideo caption.modelo <modelo>`).
- Nunca hace fallar el vídeo: si Ollama no responde o el modelo no está
  descargado, la fila queda con ⚠ y el log dice qué instalar.
- CLI: `python limpiarVideo.py video.mp4 --caption --marca "Soy …"`.
```

- [ ] **Step 4: Suite completa**

Run: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m "not slow" -q`
Expected: verde.

- [ ] **Step 5: Commit**

```bash
git add tests/test_integracion_lenta.py SETUP.md
git commit -m "test+docs: real Ollama caption integration test and SETUP notes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Auto-revisión del plan

- **Cobertura de la spec:** config (T1), errores (T2), `ollama.py` (T3), `caption.py` con formato `.md` y `leer_md` (T4), `_fase_subtitulos` con tupla y `_fase_caption` con borrado de `.md` obsoleto, conteo de pasos y cierre del servidor en `finally` (T5), CLI (T6), `Ajustes` (T7), diálogo (T8), panel de opciones (T9), panel de caption (T10), cableado en `main.py` incluidos `procesar` y refresco al terminar (T11), test lento y docs (T12). Sin huecos.
- **Consistencia de nombres:** `generar` se importa en pipeline como `generar_caption` y los tests lo parchean con ese nombre; `asegurar_servidor` se parchea en `pipeline`, no en `ollama`; `Caption.hashtags_texto` y `texto_completo()` se usan igual en T4, T10 y T11; `pasos_extra` definido en T5 y usado solo ahí.
- **Sin placeholders.**
