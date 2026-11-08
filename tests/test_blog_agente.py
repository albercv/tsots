"""Agente del blog (`lanzador/blog/`): el script con un `claude` falso, nunca el real."""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
BLOG = RAIZ / "lanzador" / "blog"
SCRIPT = BLOG / "procesar_pendientes.sh"
INSTRUCCIONES = BLOG / "instrucciones.md"
GUARDA = BLOG / "guarda_borrador.sh"
PYTHON = str(RAIZ / ".venv-clearvoice" / "bin" / "python")
E2D = "mcp__claude_ai_E2D_-_Blog__"
HERRAMIENTAS = [f"{E2D}posts_create", f"{E2D}posts_request_upload", f"{E2D}posts_validate",
                f"{E2D}posts_set_cover", f"{E2D}posts_list_media", "Read", "Write",
                f"Bash({PYTHON} -m videopipeline.blog_subida:*)"]
PROHIBIDAS = [f"{E2D}posts_update_frontmatter", f"{E2D}posts_delete",
              f"{E2D}posts_update_body", f"{E2D}posts_rebuild"]
RESULTADO = json.dumps({"slug": "mi-post", "locale": "es",
                        "url": "https://evolve2digital.com/es/blog/mi-post"})


def _blog(tmp_path, *nombres):
    blog = tmp_path / "blog"
    for n in nombres:
        (blog / "pendientes" / n).mkdir(parents=True)
        (blog / "pendientes" / n / "meta.json").write_text("{}")
    return blog


def _ejecutar(tmp_path, blog, claude=None, **extra):
    """Lanza el script con HOME y PATH temporales. `claude`: cuerpo bash del claude falso."""
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    if claude is not None:
        falso = bin_ / "claude"
        falso.write_text("#!/bin/bash\nprintf '%s\\0' \"$@\" > args.bin\npwd > cwd.txt\n"
                         'echo x >> "$LLAMADAS"\n' + claude)
        falso.chmod(0o755)
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(tmp_path / "home"),
           "LLAMADAS": str(tmp_path / "llamadas"), **extra}
    return subprocess.run(["/bin/bash", str(SCRIPT), str(blog)], env=env,
                          capture_output=True, text=True, timeout=60)


def _llamadas(tmp_path):
    f = tmp_path / "llamadas"
    return len(f.read_text().splitlines()) if f.exists() else 0


def test_carpeta_con_resultado_pasa_a_hechos(tmp_path):
    blog = _blog(tmp_path, "2026-11-08-video")
    final = tmp_path / "x_limpio.mp4"  # el vídeo de la carpeta es un enlace duro al final
    final.write_bytes(b"video")
    os.link(final, blog / "pendientes" / "2026-11-08-video" / "video.mp4")
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
    assert args[:9] == ["-p", prompt, "--add-dir", carpeta, "--allowedTools", ",".join(HERRAMIENTAS),
                        "--disallowedTools", ",".join(PROHIBIDAS), "--settings"]
    assert len(args) == 10
    assert json.loads(args[9]) == {"hooks": {"PreToolUse": [{
        "matcher": f"{E2D}posts_create",
        "hooks": [{"type": "command", "command": f"/bin/bash '{GUARDA}'"}]}]}}
    # El borrador ya lleva el vídeo: la copia sobra, el final sigue.
    assert not (hecho / "video.mp4").exists() and final.read_bytes() == b"video"


def test_carpeta_sin_resultado_pasa_a_errores_con_motivo(tmp_path):
    blog = _blog(tmp_path, "2026-11-08-video")
    (blog / "pendientes" / "2026-11-08-video" / "video.mp4").write_bytes(b"video")
    # resultado.json sin "url" no cuenta como hecho
    r = _ejecutar(tmp_path, blog, "for i in $(seq 1 50); do echo \"linea $i\"; done\n"
                                  "echo '{\"slug\": \"x\"}' > resultado.json\nexit 1\n")
    assert r.returncode == 0, r.stderr
    error = blog / "errores" / "2026-11-08-video"
    assert (error / "motivo.txt").read_text().splitlines() == [f"linea {i}" for i in range(11, 51)]
    assert (error / "claude.log").exists()
    assert (error / "video.mp4").exists()  # para reintentar
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
    assert "bloqueo activo" in r.stdout


def test_bloqueo_de_mas_de_180_min_se_quita_y_se_procesa(tmp_path):
    blog = _blog(tmp_path, "2026-11-08-video")
    (blog / ".bloqueo").mkdir()
    viejo = time.time() - 181 * 60
    os.utime(blog / ".bloqueo", (viejo, viejo))
    r = _ejecutar(tmp_path, blog, f"echo '{RESULTADO}' > resultado.json\n")
    assert r.returncode == 0, r.stderr
    assert "bloqueo de hace más de 180 min" in r.stdout
    assert _llamadas(tmp_path) == 1
    assert (blog / "hechos" / "2026-11-08-video").is_dir()
    assert not (blog / ".bloqueo").exists()


def test_carpeta_que_no_se_puede_mover_se_aparta(tmp_path):
    blog = _blog(tmp_path, "2026-11-08-video")
    (blog / "hechos" / "2026-11-08-video").mkdir(parents=True)
    (blog / "hechos" / "2026-11-08-video" / "otro.txt").write_text("de antes")
    claude = f"echo '{RESULTADO}' > resultado.json\n"
    r = _ejecutar(tmp_path, blog, claude)
    assert r.returncode == 0, r.stderr
    apartada = blog / "pendientes" / ".2026-11-08-video.no-movida"
    assert (apartada / "resultado.json").exists()
    assert not (blog / "pendientes" / "2026-11-08-video").exists()
    assert ".2026-11-08-video.no-movida" in r.stdout
    assert (blog / "hechos" / "2026-11-08-video" / "otro.txt").read_text() == "de antes"
    _ejecutar(tmp_path, blog, claude)
    assert _llamadas(tmp_path) == 1  # no se vuelve a procesar (sería otro borrador)


def test_carpeta_que_llega_durante_la_ejecucion_entra_en_la_misma(tmp_path):
    """Otro vídeo termina mientras se procesa el primero: su arranque sale por el
    bloqueo, así que esta ejecución tiene que recoger su carpeta."""
    blog = _blog(tmp_path, "2026-11-08-uno")
    r = _ejecutar(tmp_path, blog, f"echo '{RESULTADO}' > resultado.json\n"
                                  '[ "$(wc -l < "$LLAMADAS")" -eq 1 ] && mkdir ../2026-11-08-dos\n')
    assert r.returncode == 0, r.stderr
    assert _llamadas(tmp_path) == 2
    assert (blog / "hechos" / "2026-11-08-uno").is_dir()
    assert (blog / "hechos" / "2026-11-08-dos").is_dir()
    assert not any((blog / "pendientes").iterdir())


def test_carpeta_que_sigue_en_pendientes_no_se_repite_en_la_misma_ejecucion(tmp_path):
    """Sin poder mover ni apartar la carpeta, se queda con su nombre: repasar
    pendientes/ no debe volver a procesarla (sería otro borrador)."""
    blog = _blog(tmp_path, "2026-11-08-video")
    pendientes = blog / "pendientes"
    pendientes.chmod(0o555)  # nada sale de pendientes/
    try:
        r = _ejecutar(tmp_path, blog, f"echo '{RESULTADO}' > resultado.json\n")
    finally:
        pendientes.chmod(0o755)
    assert r.returncode == 0, r.stderr
    assert _llamadas(tmp_path) == 1
    assert (pendientes / "2026-11-08-video").is_dir()
    assert "se volverá a procesar" in r.stdout


def test_claude_que_no_termina_va_a_errores(tmp_path):
    blog = _blog(tmp_path, "2026-11-08-video")
    inicio = time.monotonic()
    r = _ejecutar(tmp_path, blog, "exec sleep 30\n", TSOTS_BLOG_LIMITE="1")
    assert r.returncode == 0, r.stderr
    assert time.monotonic() - inicio < 15
    assert "Tiempo agotado" in (blog / "errores" / "2026-11-08-video" / "motivo.txt").read_text()


def test_motivo_menciona_el_borrador_ya_creado(tmp_path):
    blog = _blog(tmp_path, "2026-11-08-video")
    r = _ejecutar(tmp_path, blog, """echo '{"slug": "mi-post", "locale": "es"}' > borrador.json
echo 'ERROR: paso 5, la subida falló'
exit 1
""")
    assert r.returncode == 0, r.stderr
    motivo = (blog / "errores" / "2026-11-08-video" / "motivo.txt").read_text()
    assert "mi-post" in motivo and "ERROR: paso 5, la subida falló" in motivo


@pytest.mark.parametrize("entrada, codigo", [
    ({"published": False}, 0),
    ({}, 2),
    ({"published": True}, 2),
    ({"published": "false"}, 2),
    ({"published": 0}, 2),
    (None, 2),  # entrada que no es JSON
])
def test_guarda_solo_deja_crear_borradores(entrada, codigo):
    datos = "basura" if entrada is None else json.dumps({
        "tool_name": f"{E2D}posts_create",
        "tool_input": {"title": "Un título", **entrada}})
    r = subprocess.run(["/bin/bash", str(GUARDA)], input=datos, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin"}, timeout=30)
    assert r.returncode == codigo
    if codigo:
        assert "published: false" in r.stderr and len(r.stderr.strip().splitlines()) == 1


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
                  "[contact]", "resultado.json", "borrador.json", 'cover: "portada"',
                  "https://evolve2digital.com/<locale>/blog/<slug>"):
        assert marca in texto


def test_instrucciones_reintentan_la_misma_orden_una_vez():
    texto = " ".join(INSTRUCCIONES.read_text().split())
    assert "repite **la misma orden** una vez" in texto and "ya estaban subidos" in texto


def test_la_app_lanza_este_script(monkeypatch):
    from videopipeline import difusion, steps

    # Solo se restaura la ruta real; el resto de redes de seguridad siguen puestas.
    monkeypatch.setattr(difusion, "AGENTE",
                        steps.BASE_DIR / "lanzador" / "blog" / "procesar_pendientes.sh")

    assert difusion.AGENTE == SCRIPT
    assert not (BLOG / "com.tsots.blog.plist.plantilla").exists()  # ya no hay launchd
    assert os.access(SCRIPT, os.X_OK)  # la app lo ejecuta directamente
    assert os.access(GUARDA, os.X_OK)
