"""Agente de edición (`lanzador/edicion/`): el script con un `claude` falso, nunca el real."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from videopipeline import edicion

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "lanzador" / "edicion" / "procesar_pendientes.sh"
NOMBRE = "short 1"


def _trabajo(tmp_path, video, nombre=NOMBRE):
    """Carpeta pendiente con video.mp4 y trabajo.json; el origen vive en tmp_path/orig."""
    orig = tmp_path / "orig"
    orig.mkdir(exist_ok=True)
    origen = orig / f"{nombre}.mp4"
    shutil.copy(video, origen)
    st = origen.stat()
    edi = tmp_path / "edicion"
    carpeta = edi / "pendientes" / nombre
    carpeta.mkdir(parents=True)
    shutil.copy(video, carpeta / "video.mp4")
    (carpeta / "trabajo.json").write_text(json.dumps({
        "origen": str(origen), "origen_tam": st.st_size, "origen_mtime": st.st_mtime,
        "destino": str(orig / f"{nombre}.editado.mp4"), "estilo": "divertido"}))
    return edi, origen


def _ejecutar(tmp_path, edi, claude=None, **extra):
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    if claude is not None:
        falso = bin_ / "claude"
        falso.write_text("#!/bin/bash\nprintf '%s\\0' \"$@\" > args.bin\n" + claude)
        falso.chmod(0o755)
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(tmp_path / "home"),
           "TSOTS_EDICION_PYTHON": sys.executable, **extra}
    return subprocess.run(["/bin/bash", str(SCRIPT), str(edi)], env=env,
                          capture_output=True, text=True, timeout=60)


def test_exito(tmp_path, video_vertical):
    edi, origen = _trabajo(tmp_path, video_vertical)
    r = _ejecutar(tmp_path, edi, "cp video.mp4 salida.mp4\n")
    assert r.returncode == 0, r.stderr
    hecho = edi / "hechos" / NOMBRE
    assert (origen.parent / f"{NOMBRE}.editado.mp4").exists()
    assert (hecho / "resultado.json").exists() and not (hecho / "video.mp4").exists()
    args = (hecho / "args.bin").read_text().split("\0")[:-1]
    assert args[args.index("--model") + 1] == "claude-haiku-5-5"
    assert args[1].endswith(f"\n\nTrabajo: {edi / 'pendientes' / NOMBRE}")
    assert "@PYTHON@" not in args[1]
    assert not (edi / ".bloqueo").exists()


def test_salida_mala_va_a_errores(tmp_path, video_vertical):
    edi, origen = _trabajo(tmp_path, video_vertical)
    r = _ejecutar(tmp_path, edi, "echo nada\n")
    assert r.returncode == 0, r.stderr
    error = edi / "errores" / NOMBRE
    assert "No existe salida.mp4" in (error / "motivo.txt").read_text()
    assert (error / "video.mp4").exists()  # para reintentar
    assert not (origen.parent / f"{NOMBRE}.editado.mp4").exists()


def test_origen_cambiado(tmp_path, video_vertical):
    edi, origen = _trabajo(tmp_path, video_vertical)
    r = _ejecutar(tmp_path, edi, f"cp video.mp4 salida.mp4\ntouch -t 200101010101 '{origen}'\n")
    assert r.returncode == 0, r.stderr
    assert "origen cambiado" in (edi / "errores" / NOMBRE / "motivo.txt").read_text()
    assert not (origen.parent / f"{NOMBRE}.editado.mp4").exists()


def test_tiempo_agotado(tmp_path, video_vertical):
    edi, _ = _trabajo(tmp_path, video_vertical)
    inicio = time.monotonic()
    r = _ejecutar(tmp_path, edi, "exec sleep 30\n", TSOTS_EDICION_LIMITE="1")
    assert r.returncode == 0, r.stderr
    assert time.monotonic() - inicio < 15
    assert "Tiempo agotado" in (edi / "errores" / NOMBRE / "motivo.txt").read_text()


def test_sin_claude(tmp_path, video_vertical):
    edi, _ = _trabajo(tmp_path, video_vertical)
    r = _ejecutar(tmp_path, edi)
    assert r.returncode == 0, r.stderr
    assert "sin claude" in r.stdout
    assert "No se encuentra claude" in (edi / "errores" / NOMBRE / "motivo.txt").read_text()


def test_bloqueo(tmp_path, video_vertical):
    edi, _ = _trabajo(tmp_path, video_vertical)
    (edi / ".bloqueo").mkdir()
    r = _ejecutar(tmp_path, edi, "cp video.mp4 salida.mp4\n")
    assert r.returncode == 0 and "bloqueo activo" in r.stdout
    assert (edi / "pendientes" / NOMBRE).is_dir()
    assert not (edi / "pendientes" / NOMBRE / "claude.log").exists()


def test_nombre_con_interrogacion(tmp_path, video_vertical):
    nombre = "Episodio 20 - 01 - ¿Juniors o Seniors"
    edi, origen = _trabajo(tmp_path, video_vertical, nombre)
    r = _ejecutar(tmp_path, edi, "cp video.mp4 salida.mp4\n")
    assert r.returncode == 0, r.stderr
    assert (edi / "hechos" / nombre).is_dir()
    assert (origen.parent / f"{nombre}.editado.mp4").exists()


def test_no_define_credenciales():
    texto = SCRIPT.read_text()
    assert "ANTHROPIC_API_KEY" not in texto and "OAUTH_TOKEN" not in texto


def test_lanzar_agente(tmp_path, monkeypatch):
    monkeypatch.setattr(edicion, "AGENTE", SCRIPT)
    lanzados = []
    monkeypatch.setattr(edicion.subprocess, "Popen", lambda *a, **k: lanzados.append(a))
    assert edicion.lanzar_agente_edicion(tmp_path) is False  # ni existe pendientes/
    (tmp_path / "pendientes" / ".oculta").mkdir(parents=True)
    assert edicion.lanzar_agente_edicion(tmp_path) is False
    (tmp_path / "pendientes" / "uno").mkdir()
    assert edicion.lanzar_agente_edicion(tmp_path) is True
    assert lanzados[0][0] == [str(SCRIPT), str(tmp_path)]


def test_claude_disponible(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    if Path("/opt/homebrew/bin/claude").exists():
        pytest.skip("hay un claude real en /opt/homebrew")
    assert edicion.claude_disponible() is False


def test_la_app_lanza_este_script():
    assert os.access(SCRIPT, os.X_OK) and (SCRIPT.parent / "SKILL.md").is_file()
