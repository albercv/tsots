"""Agente del blog (`lanzador/blog/`): el script con un `claude` falso, nunca el real."""
import json
import os
import plistlib
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
BLOG = RAIZ / "lanzador" / "blog"
SCRIPT = BLOG / "procesar_pendientes.sh"
INSTRUCCIONES = BLOG / "instrucciones.md"
PYTHON = str(RAIZ / ".venv-clearvoice" / "bin" / "python")
E2D = "mcp__claude_ai_E2D_-_Blog__"
HERRAMIENTAS = [f"{E2D}posts_create", f"{E2D}posts_request_upload", f"{E2D}posts_validate",
                f"{E2D}posts_set_cover", f"{E2D}posts_list_media", "Read", "Write",
                f"Bash({PYTHON} -m videopipeline.blog_subida:*)"]
RESULTADO = json.dumps({"slug": "mi-post", "locale": "es",
                        "url": "https://evolve2digital.com/es/blog/mi-post"})


def _blog(tmp_path, *nombres):
    blog = tmp_path / "blog"
    for n in nombres:
        (blog / "pendientes" / n).mkdir(parents=True)
        (blog / "pendientes" / n / "meta.json").write_text("{}")
    return blog


def _ejecutar(tmp_path, blog, claude=None):
    """Lanza el script con HOME y PATH temporales. `claude`: cuerpo bash del claude falso."""
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    if claude is not None:
        falso = bin_ / "claude"
        falso.write_text("#!/bin/bash\nprintf '%s\\0' \"$@\" > args.bin\npwd > cwd.txt\n"
                         'echo x >> "$LLAMADAS"\n' + claude)
        falso.chmod(0o755)
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(tmp_path / "home"),
           "LLAMADAS": str(tmp_path / "llamadas")}
    return subprocess.run(["/bin/bash", str(SCRIPT), str(blog)], env=env,
                          capture_output=True, text=True, timeout=60)


def _llamadas(tmp_path):
    f = tmp_path / "llamadas"
    return len(f.read_text().splitlines()) if f.exists() else 0


def test_carpeta_con_resultado_pasa_a_hechos(tmp_path):
    blog = _blog(tmp_path, "2026-11-08-video")
    r = _ejecutar(tmp_path, blog, f"echo '{RESULTADO}' > resultado.json\n")
    assert r.returncode == 0, r.stderr
    hecho = blog / "hechos" / "2026-11-08-video"
    assert json.loads((hecho / "resultado.json").read_text())["slug"] == "mi-post"
    assert not (blog / "pendientes" / "2026-11-08-video").exists()
    assert not (blog / ".bloqueo").exists()  # el trap suelta el bloqueo
    assert (hecho / "claude.log").exists()
    carpeta = str(blog / "pendientes" / "2026-11-08-video")
    assert Path((hecho / "cwd.txt").read_text().strip()).resolve() == Path(carpeta).resolve()
    args = (hecho / "args.bin").read_text().split("\0")[:-1]
    prompt = INSTRUCCIONES.read_text().rstrip("\n").replace("@PYTHON@", PYTHON)
    assert args == ["-p", prompt, "--add-dir", carpeta, "--allowedTools", ",".join(HERRAMIENTAS)]


def test_carpeta_sin_resultado_pasa_a_errores_con_motivo(tmp_path):
    blog = _blog(tmp_path, "2026-11-08-video")
    # resultado.json sin "url" no cuenta como hecho
    r = _ejecutar(tmp_path, blog, "for i in $(seq 1 50); do echo \"linea $i\"; done\n"
                                  "echo '{\"slug\": \"x\"}' > resultado.json\nexit 1\n")
    assert r.returncode == 0, r.stderr
    error = blog / "errores" / "2026-11-08-video"
    assert (error / "motivo.txt").read_text().splitlines() == [f"linea {i}" for i in range(11, 51)]
    assert (error / "claude.log").exists()
    assert not (blog / "hechos" / "2026-11-08-video").exists()
    assert not (blog / "pendientes" / "2026-11-08-video").exists()


def test_carpetas_ocultas_se_ignoran(tmp_path):
    blog = _blog(tmp_path, ".video.tmp", "2026-11-08-otro")
    r = _ejecutar(tmp_path, blog, f"echo '{RESULTADO}' > resultado.json\n")
    assert r.returncode == 0, r.stderr
    oculta = blog / "pendientes" / ".video.tmp"
    assert oculta.is_dir() and not (oculta / "claude.log").exists()
    assert _llamadas(tmp_path) == 1
    assert (blog / "hechos" / "2026-11-08-otro").is_dir()


def test_segunda_ejecucion_con_bloqueo_no_hace_nada(tmp_path):
    blog = _blog(tmp_path, "2026-11-08-video")
    (blog / ".bloqueo").mkdir()
    r = _ejecutar(tmp_path, blog, f"echo '{RESULTADO}' > resultado.json\n")
    assert r.returncode == 0, r.stderr
    assert _llamadas(tmp_path) == 0
    assert (blog / "pendientes" / "2026-11-08-video").is_dir()
    assert (blog / ".bloqueo").is_dir()  # el bloqueo es de la otra ejecución


@pytest.mark.skipif(Path("/opt/homebrew/bin/claude").exists(),
                    reason="el script encontraría el claude real de Homebrew")
def test_sin_claude_todas_a_errores(tmp_path):
    blog = _blog(tmp_path, "2026-11-08-uno", "2026-11-08-dos")
    r = _ejecutar(tmp_path, blog)  # sin claude falso y con HOME temporal: no hay claude
    assert r.returncode == 0, r.stderr
    for n in ("2026-11-08-uno", "2026-11-08-dos"):
        assert "claude" in (blog / "errores" / n / "motivo.txt").read_text()
    assert not any((blog / "pendientes").iterdir())


def test_instrucciones_prohiben_publicar():
    texto = INSTRUCCIONES.read_text()
    assert "`published: false`" in texto
    assert texto.count("published: true") == 1 and "Nunca uses `published: true`" in texto
    assert "`posts_delete`" in texto and "`posts_update_frontmatter`" in texto


def test_instrucciones_nombran_herramientas_y_orden_de_subida():
    texto = INSTRUCCIONES.read_text()
    for h in HERRAMIENTAS[:5]:
        assert f"`{h}`" in texto
    assert "@PYTHON@ -m videopipeline.blog_subida '<uploadUrl>' --fichero portada.png=portada" in texto
    for marca in ("<Lead>", "<PullQuote", "<Callout", "[video:video]", "[image:fotograma_1]",
                  "[contact]", "resultado.json", 'cover: "portada"'):
        assert marca in texto


def test_plist_plantilla_es_valido():
    plist = plistlib.loads((BLOG / "com.tsots.blog.plist.plantilla").read_bytes())
    script, dir_blog = plist["ProgramArguments"]
    assert script.endswith("procesar_pendientes.sh")
    assert plist["Label"] == "com.tsots.blog"
    assert plist["WatchPaths"] == [f"{dir_blog}/pendientes"]
    assert plist["StartInterval"] == 3600
    assert plist["StandardOutPath"] == plist["StandardErrorPath"] == f"{dir_blog}/agente.log"
    assert os.access(SCRIPT, os.X_OK)  # launchd lo ejecuta directamente
