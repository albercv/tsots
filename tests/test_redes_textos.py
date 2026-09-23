from __future__ import annotations

from pathlib import Path

from videopipeline.redes.modelo import (
    ORDEN,
    ModoInstagram,
    ModoTikTok,
    Opciones,
    Plataforma,
    Publicacion,
)
from videopipeline.redes.textos import (
    MAX_ETIQUETAS_YOUTUBE,
    etiquetas_youtube,
    hashtags_para,
    texto_para,
    titulo_para,
)


def _pub(**kw) -> Publicacion:
    base = dict(video=Path("v.mp4"), titulo="Título", caption="Cuerpo",
                hashtags=("#a", "#b"), palabras_clave=("ia", "pymes"))
    base.update(kw)
    return Publicacion(**base)


def test_orden_fijo_tiktok_youtube_instagram():
    assert ORDEN == (Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM)
    assert [p.nombre for p in ORDEN] == ["TikTok", "YouTube", "Instagram"]


def test_opciones_por_defecto():
    o = Opciones()
    assert o.tiktok_modo == ModoTikTok.BORRADOR
    assert o.instagram_modo == ModoInstagram.PRUEBA
    assert o.youtube_categoria == "22"


def test_titulo_youtube_recortado_a_100():
    titulo = "palabra " * 30
    recortado = titulo_para(Plataforma.YOUTUBE, _pub(titulo=titulo))
    assert len(recortado) <= 100
    assert recortado.endswith("…")
    corto = titulo_para(Plataforma.YOUTUBE, _pub(titulo="Corto"))
    assert corto == "Corto"


def test_titulo_youtube_sin_angulos():
    assert titulo_para(Plataforma.YOUTUBE, _pub(titulo="a <b> c")) == "a b c"


def test_texto_es_caption_mas_hashtags():
    assert texto_para(Plataforma.TIKTOK, _pub()) == "Cuerpo\n\n#a #b"


def test_texto_largo_recorta_caption_y_nunca_hashtags():
    hashtags = tuple(f"#etiqueta{i}" for i in range(10))
    pub = _pub(caption="bla " * 1000, hashtags=hashtags)
    for plataforma in (Plataforma.TIKTOK, Plataforma.INSTAGRAM):
        texto = texto_para(plataforma, pub)
        assert len(texto) <= 2200
        assert texto.endswith(" ".join(hashtags))
        assert "…" in texto


def test_youtube_admite_descripcion_mas_larga():
    pub = _pub(caption="x" * 3000)
    assert len(texto_para(Plataforma.YOUTUBE, pub)) > 2200
    assert len(texto_para(Plataforma.YOUTUBE, _pub(caption="x" * 9000))) <= 5000


def test_instagram_maximo_30_hashtags():
    hashtags = tuple(f"#h{i}" for i in range(40))
    pub = _pub(hashtags=hashtags)
    assert len(hashtags_para(Plataforma.INSTAGRAM, pub)) == 30
    texto = texto_para(Plataforma.INSTAGRAM, pub)
    assert texto.count("#") == 30
    assert "#h29" in texto and "#h30" not in texto
    assert len(hashtags_para(Plataforma.TIKTOK, pub)) == 40


def test_hashtags_normalizados_y_sin_duplicados():
    pub = _pub(hashtags=("a", "#A", " #b ", ""))
    assert hashtags_para(Plataforma.TIKTOK, pub) == ["#a", "#b"]


def test_sin_hashtags_o_sin_caption():
    assert texto_para(Plataforma.TIKTOK, _pub(hashtags=())) == "Cuerpo"
    assert texto_para(Plataforma.TIKTOK, _pub(caption="")) == "#a #b"


def test_etiquetas_youtube_limitadas_a_500():
    pub = _pub(palabras_clave=tuple(f"palabra clave {i}" for i in range(100)))
    etiquetas = etiquetas_youtube(pub)
    coste = sum(len(e) + 2 for e in etiquetas) + len(etiquetas) - 1
    assert 0 < len(etiquetas) < 100
    assert coste <= MAX_ETIQUETAS_YOUTUBE
    assert etiquetas_youtube(_pub(palabras_clave=("#ia", "ia", ""))) == ["ia"]
