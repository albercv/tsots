import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from videopipeline.difusion import preparar
from videopipeline.steps import PasoFallido
from videopipeline.subtitles import Palabra

HOY = date(2026, 11, 8)
CLIENTE = lambda m, msgs, esq: {"texto": "Gancho.\n\n" + "x" * 1400, "hashtags": ["#ia"]}


def _nitida(i=0):
    img = np.zeros((90, 160, 3), np.uint8)
    img[::2] = 255
    img[:, :, 0] = (i * 7) % 256  # imágenes distintas
    return img


def _llamar(tmp_path, *, leer=None, nombre="x", hoy=HOY, cliente=CLIENTE,
            palabras=(Palabra("hola", 1.0, 1.5),)):
    final = tmp_path / "salida" / f"{nombre}_limpio.mp4"
    final.parent.mkdir(exist_ok=True)
    base = tmp_path / "base.mp4"
    base.write_bytes(b"video")
    return final, preparar(
        nombre=nombre, base=base, video_blog=base, final=final,
        palabras=list(palabras), titulo="Claude Code ahorra tokens",
        idioma="es", contexto_marca="", modelo="m", dir_blog=tmp_path / "blog",
        cliente=cliente, detector=lambda f: np.zeros((0, 5)),
        leer=leer or (lambda v, t: _nitida(int(t))), hoy=hoy, duracion=100.0,
    )


def test_preparar_escribe_linkedin_y_blog(tmp_path):
    final, res = _llamar(tmp_path)
    assert res.linkedin_md == final.with_suffix(".linkedin.md") and res.linkedin_md.exists()
    car = final.with_suffix(".linkedin")
    assert Image.open(car / "01_portada.png").size == (1080, 1350)
    assert len(list(car.glob("0[234]_*"))) == 3
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
    assert (car / "01_portada.png").exists() and len(list(car.glob("0[234]_*"))) == 3
    for f in ("video.mp4", "transcripcion.txt", "portada.png", "meta.json"):
        assert (res.carpeta_blog / f).exists()


def test_transcripcion_txt_en_lineas_cortas(tmp_path):
    palabras = [Palabra("transcripción", i * 0.5, i * 0.5 + 0.4) for i in range(200)]
    _, res = _llamar(tmp_path, palabras=palabras)
    lineas = (res.carpeta_blog / "transcripcion.txt").read_text(encoding="utf-8").splitlines()
    assert len(lineas) > 1 and max(map(len, lineas)) <= 300
    assert " ".join(lineas).split() == ["transcripción"] * 200
