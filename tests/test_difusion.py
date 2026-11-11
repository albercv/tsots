import json
import logging
import subprocess
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from videopipeline import difusion
from videopipeline.difusion import lanzar_agente, preparar
from videopipeline.steps import PasoFallido
from videopipeline.subtitles import Palabra

HOY = date(2026, 11, 8)
CLIENTE = lambda m, msgs, esq: {"texto": "Gancho.\n\n" + "x" * 1400, "hashtags": ["#ia"]}


def _nitida(i=0):
    img = np.zeros((90, 160, 3), np.uint8)
    img[::2] = 255
    img[:, :, 0] = (i * 7) % 256  # imágenes distintas
    return img


def _sin_ffmpeg(origen, destino):
    raise PasoFallido("sin ffmpeg en los tests")


def _llamar(tmp_path, *, leer=None, nombre="x", hoy=HOY, cliente=CLIENTE,
            palabras=(Palabra("hola", 1.0, 1.5),), codificar=_sin_ffmpeg,
            detector=lambda f: np.zeros((0, 5))):
    final = tmp_path / "salida" / f"{nombre}_limpio.mp4"
    final.parent.mkdir(exist_ok=True)
    base = tmp_path / "base.mp4"
    base.write_bytes(b"video")
    return final, preparar(
        nombre=nombre, base=base, video_blog=base, final=final,
        palabras=list(palabras), titulo="Claude Code ahorra tokens",
        idioma="es", contexto_marca="", modelo="m", dir_blog=tmp_path / "blog",
        cliente=cliente, detector=detector,
        leer=leer or (lambda v, t: _nitida(int(t))), hoy=hoy, duracion=100.0, codificar=codificar,
    )


def test_preparar_escribe_linkedin_y_blog(tmp_path):
    final, res = _llamar(tmp_path)
    assert res.linkedin_md == final.with_suffix(".linkedin.md") and res.linkedin_md.exists()
    car = final.with_suffix(".linkedin")
    assert Image.open(car / "01_portada.png").size == (1080, 1350)
    assert len(list(car.glob("0[2-9]_*"))) == 2
    blog = tmp_path / "blog" / "pendientes" / "2026-11-08-x"
    assert res.carpeta_blog == blog
    for f in ("video.mp4", "transcripcion.txt", "portada.png", "meta.json"):
        assert (blog / f).exists()
    assert Image.open(blog / "portada.png").size == (1672, 941)
    meta = json.loads((blog / "meta.json").read_text())
    assert len(meta["candidatos"]) == 6
    assert all((blog / c["archivo"]).exists() and "segundo" in c for c in meta["candidatos"])
    assert meta["titulo_seo"] is None and meta["idioma"] == "es"
    assert not (tmp_path / "blog" / "pendientes" / ".x.tmp").exists()


def test_nombre_ocupado_en_hechos_lleva_sufijo(tmp_path):
    (tmp_path / "blog" / "hechos" / "2026-11-08-x").mkdir(parents=True)
    (tmp_path / "blog" / "pendientes" / "2026-11-08-x-2").mkdir(parents=True)
    _, res = _llamar(tmp_path)
    assert res.carpeta_blog.name == "2026-11-08-x-3"


def test_sin_candidatos_falla_sin_dejar_carpeta(tmp_path):
    with pytest.raises(PasoFallido):
        _llamar(tmp_path, leer=lambda v, t: None)
    pendientes = tmp_path / "blog" / "pendientes"
    assert not pendientes.exists() or not list(pendientes.glob("*"))


def test_carpeta_linkedin_previa_se_reemplaza(tmp_path):
    final = tmp_path / "salida" / "x_limpio.mp4"
    viejo = final.with_suffix(".linkedin") / "candidatos"
    viejo.mkdir(parents=True)
    (viejo / "candidato_09.jpg").write_bytes(b"viejo")
    _llamar(tmp_path)
    assert not (viejo / "candidato_09.jpg").exists()


def test_texto_de_linkedin_fallido_no_impide_el_blog(tmp_path):
    def cliente_roto(m, msgs, esq):
        raise PasoFallido("Ollama no responde")

    final, res = _llamar(tmp_path, cliente=cliente_roto)
    assert res.linkedin_md is None and str(res.fallo_linkedin) == "Ollama no responde"
    assert not final.with_suffix(".linkedin.md").exists()
    car = final.with_suffix(".linkedin")
    assert (car / "01_portada.png").exists() and len(list(car.glob("0[2-9]_*"))) == 2
    for f in ("video.mp4", "transcripcion.txt", "portada.png", "meta.json"):
        assert (res.carpeta_blog / f).exists()


CARA = np.array([[40, 20, 120, 80, 0.99]])  # cara entera en un fotograma de 160×90


def _fotos(final):
    return sorted(p.name for p in final.with_suffix(".linkedin").glob("*.*"))


def test_ideas_van_como_tarjetas_tras_la_portada(tmp_path):
    cliente = lambda m, msgs, esq: {**CLIENTE(m, msgs, esq),
                                    "ideas": ["Idea uno de prueba", "Idea dos de prueba"]}
    final, _ = _llamar(tmp_path, cliente=cliente, detector=lambda f: CARA)
    assert _fotos(final) == ["01_portada.png", "02_idea.png", "03_idea.png"]
    assert Image.open(final.with_suffix(".linkedin") / "02_idea.png").size == (1080, 1350)


def test_video_a_camara_no_lleva_capturas(tmp_path):
    final, _ = _llamar(tmp_path, detector=lambda f: CARA)
    assert _fotos(final) == ["01_portada.png"]


def test_capturas_solo_de_fotogramas_sin_cara(tmp_path):
    # primera mitad a cámara (marca 0), segunda sin cara (pantalla, demo...)
    final, _ = _llamar(tmp_path, leer=lambda v, t: _nitida(0 if t < 50 else 1),
                       detector=lambda f: CARA if f[1, 0, 2] == 0 else np.zeros((0, 5)))
    assert _fotos(final) == ["01_portada.png", "02_candidato_03.jpg", "03_candidato_05.jpg"]


def test_transcripcion_txt_en_lineas_cortas(tmp_path):
    palabras = [Palabra("transcripción", i * 0.5, i * 0.5 + 0.4) for i in range(200)]
    _, res = _llamar(tmp_path, palabras=palabras)
    lineas = (res.carpeta_blog / "transcripcion.txt").read_text(encoding="utf-8").splitlines()
    assert len(lineas) > 1 and max(map(len, lineas)) <= 300
    assert " ".join(lineas).split() == ["transcripción"] * 200


def test_video_del_blog_es_la_codificacion_web(tmp_path):
    def codificar(origen, destino):
        destino.write_bytes(b"web-720")
    _, res = _llamar(tmp_path, codificar=codificar)
    assert (res.carpeta_blog / "video.mp4").read_bytes() == b"web-720"


def test_si_falla_la_codificacion_se_enlaza_el_video_original(tmp_path):
    _, res = _llamar(tmp_path)  # _sin_ffmpeg lanza PasoFallido
    assert (res.carpeta_blog / "video.mp4").read_bytes() == b"video"


def test_comando_de_codificacion_web(tmp_path):
    from videopipeline.steps import cmd_codificar_web
    cmd = cmd_codificar_web("ffmpeg", tmp_path / "a.mp4", tmp_path / "b.mp4")
    assert "scale=720:-2" in cmd and "libx264" in cmd and "26" in cmd


# --- Lanzar el agente del blog -------------------------------------------------

@pytest.fixture()
def agente(tmp_path, monkeypatch):
    """Script del agente de mentira y `Popen` que solo apunta: nunca se lanza nada."""
    script = tmp_path / "procesar_pendientes.sh"
    script.write_text("#!/bin/bash\n")
    lanzados = []
    monkeypatch.setattr(difusion, "AGENTE", script)
    monkeypatch.setattr(difusion.subprocess, "Popen",
                        lambda *a, **k: lanzados.append((a, k)))
    return script, lanzados


def test_lanzar_agente_con_carpeta_pendiente_lo_suelta_sin_esperar(tmp_path, agente):
    script, lanzados = agente
    blog = tmp_path / "blog"
    (blog / "pendientes" / ".a-medias.tmp").mkdir(parents=True)
    (blog / "pendientes" / "2026-11-08-x").mkdir()
    (blog / "agente.log").write_text("anterior\n")

    assert lanzar_agente(blog) is True

    [(args, kwargs)] = lanzados
    assert args == ([str(script), str(blog)],)
    registro = kwargs.pop("stdout")
    assert kwargs.pop("stderr") is registro
    assert Path(registro.name) == blog / "agente.log" and "a" in registro.mode
    assert kwargs == {"stdin": subprocess.DEVNULL, "start_new_session": True,
                      "close_fds": True}
    assert (blog / "agente.log").read_text() == "anterior\n"  # se añade, no se pisa


@pytest.mark.parametrize("ocultas, ficheros", [
    (None, []),  # sin pendientes/
    ([], []),
    ([".x.tmp", ".y.no-movida"], []),  # a medio escribir o apartadas
    ([], ["suelto.txt"]),
])
def test_lanzar_agente_sin_carpetas_pendientes_no_lanza(tmp_path, agente, ocultas, ficheros):
    _, lanzados = agente
    blog = tmp_path / "blog"
    if ocultas is not None:
        (blog / "pendientes").mkdir(parents=True)
    for nombre in ocultas or []:
        (blog / "pendientes" / nombre).mkdir()
    for nombre in ficheros:
        (blog / "pendientes" / nombre).write_text("x")

    assert lanzar_agente(blog) is False
    assert lanzados == [] and not (blog / "agente.log").exists()


def test_lanzar_agente_sin_script_no_lanza(tmp_path, agente, monkeypatch):
    _, lanzados = agente
    monkeypatch.setattr(difusion, "AGENTE", tmp_path / "no-existe.sh")
    (tmp_path / "blog" / "pendientes" / "2026-11-08-x").mkdir(parents=True)

    assert lanzar_agente(tmp_path / "blog") is False
    assert lanzados == []


def test_lanzar_agente_que_no_arranca_avisa_en_el_log_sin_fallar(
        tmp_path, agente, monkeypatch, caplog):
    def no_arranca(*a, **k):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(difusion.subprocess, "Popen", no_arranca)
    (tmp_path / "blog" / "pendientes" / "2026-11-08-x").mkdir(parents=True)

    with caplog.at_level(logging.WARNING, logger="videopipeline.difusion"):
        assert lanzar_agente(tmp_path / "blog") is False
    assert "Operation not permitted" in caplog.text
