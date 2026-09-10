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
