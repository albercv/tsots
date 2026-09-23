from __future__ import annotations

import json
from datetime import datetime

from videopipeline.redes import registro
from videopipeline.redes.modelo import Plataforma


def test_ruta_junto_al_video(tmp_path):
    assert registro.ruta(tmp_path / "clip_limpio.mp4") == tmp_path / "clip_limpio.publicado.json"


def test_escribir_y_leer_incluye_proveedor(tmp_path):
    video = tmp_path / "clip_limpio.mp4"
    registro.anotar(video, Plataforma.TIKTOK, "https://tt/1", "prov", "borrador",
                    fecha=datetime(2026, 9, 23, 12, 0, 0))
    datos = json.loads(registro.ruta(video).read_text(encoding="utf-8"))
    assert datos["version"] == 1
    assert datos["publicaciones"] == [{
        "plataforma": "tiktok", "fecha": "2026-09-23T12:00:00",
        "url": "https://tt/1", "proveedor": "prov", "modo": "borrador"}]
    [entrada] = registro.leer(video)
    assert entrada.plataforma == Plataforma.TIKTOK and entrada.proveedor == "prov"


def test_publicaciones_sucesivas_se_fusionan(tmp_path):
    video = tmp_path / "v.mp4"
    registro.anotar(video, Plataforma.TIKTOK, "a", "p")
    registro.anotar(video, Plataforma.YOUTUBE, "b", "p")
    registro.anotar(video, Plataforma.TIKTOK, "c", "p")
    assert [e.url for e in registro.leer(video)] == ["a", "b", "c"]
    assert registro.ultimas(video)[Plataforma.TIKTOK].url == "c"
    assert registro.ya_publicado(video) == {Plataforma.TIKTOK, Plataforma.YOUTUBE}
    assert not list(tmp_path.glob(".*.tmp"))


def test_registro_ausente_o_danado_es_vacio(tmp_path):
    video = tmp_path / "v.mp4"
    assert registro.ya_publicado(video) == set()
    registro.ruta(video).write_text("{no json", encoding="utf-8")
    assert registro.leer(video) == []
    registro.ruta(video).write_text(
        json.dumps({"publicaciones": [{"plataforma": "myspace"}, {"x": 1},
                                      {"plataforma": "youtube", "fecha": "f"}]}),
        encoding="utf-8")
    assert registro.ya_publicado(video) == {Plataforma.YOUTUBE}
