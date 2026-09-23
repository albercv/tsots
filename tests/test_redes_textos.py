from __future__ import annotations

from pathlib import Path

import pytest

from videopipeline.redes.modelo import (
    ORDEN,
    ModoFacebook,
    ModoInstagram,
    ModoTikTok,
    Opciones,
    Plataforma,
    Publicacion,
)
from videopipeline.redes.textos import (
    MAX_ETIQUETAS_YOUTUBE,
    MAX_TEXTO_X,
    URL_X,
    etiquetas_youtube,
    hashtags_para,
    longitud_x,
    recortar_x,
    texto_para,
    texto_x_por_defecto,
    titulo_para,
)


def _pub(**kw) -> Publicacion:
    base = dict(video=Path("v.mp4"), titulo="Título", caption="Cuerpo",
                hashtags=("#a", "#b"), palabras_clave=("ia", "pymes"))
    base.update(kw)
    return Publicacion(**base)


def test_orden_fijo_tiktok_youtube_instagram_x_facebook():
    assert ORDEN == (Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM,
                     Plataforma.X, Plataforma.FACEBOOK)
    assert [p.nombre for p in ORDEN] == ["TikTok", "YouTube", "Instagram", "X", "Facebook"]


def test_opciones_por_defecto():
    o = Opciones()
    assert o.tiktok_modo == ModoTikTok.BORRADOR
    assert o.instagram_modo == ModoInstagram.PRUEBA
    assert o.youtube_categoria == "22"
    assert o.x_premium is False
    assert o.facebook_modo == ModoFacebook.REEL
    assert _pub().texto_x == ""


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


# --- X ---


@pytest.mark.parametrize("texto, esperado", [
    ("", 0),
    ("hola", 4),
    ("¿Qué tal, año?", 14),  # latín con tildes: 1 cada uno
    ("“comillas” — guion", 18),  # puntuación tipográfica habitual: 1
    ("mira https://example.com/una/ruta/muy/larga?x=1", 5 + URL_X),
    ("dos http://a.es y www.b.com/c", 4 + URL_X + 3 + URL_X),
    ("web evolve2digital.com.", 4 + URL_X + 1),  # dominio sin esquema; el punto final no
    ("日本語", 6),  # CJK: 2 cada uno
    ("ok 👍", 3 + 2),
    ("👍🏽", 2),  # tono de piel: un solo emoji
    ("👨‍👩‍👧", 2),  # secuencia ZWJ: un solo emoji
    ("❤️", 2),  # con selector de variación
    ("🇪🇸", 2),  # bandera: dos indicadores regionales
    ("1️⃣", 2),  # tecla
    ("e\u0301", 1),  # se normaliza (NFC) antes de contar
])
def test_longitud_x_cuenta_como_x(texto, esperado):
    assert longitud_x(texto) == esperado


def test_texto_x_por_defecto_titulo_mas_hashtags():
    assert texto_x_por_defecto(_pub()) == "Título\n\n#a #b"
    assert texto_x_por_defecto(_pub(hashtags=())) == "Título"
    assert texto_x_por_defecto(_pub(titulo="", hashtags=("a", "#A", "b"))) == "#a #b"


def test_texto_x_quita_hashtags_desde_el_final():
    titulo = "t" * 250
    hashtags = ("#uno", "#dos", "#tres", "#cuatro", "#cinco", "#seis", "#siete")
    texto = texto_x_por_defecto(_pub(titulo=titulo, hashtags=hashtags))
    assert longitud_x(texto) <= MAX_TEXTO_X
    assert texto.startswith(titulo + "\n\n#uno #dos")
    assert "#siete" not in texto
    # Se quita el mínimo: con uno más ya no cabría.
    quedan = texto.split("\n\n")[1].split()
    siguiente = hashtags[len(quedan)]
    assert longitud_x(texto + " " + siguiente) > MAX_TEXTO_X


def test_texto_x_acorta_el_titulo_si_ni_sin_hashtags_cabe():
    titulo = "palabra " * 60
    texto = texto_x_por_defecto(_pub(titulo=titulo, hashtags=("#a",)))
    assert longitud_x(texto) <= MAX_TEXTO_X
    assert texto.endswith("…") and "#a" not in texto
    assert texto.startswith("palabra palabra")


def test_texto_x_cuenta_emoji_y_urls_al_recortar():
    titulo = "🔥" * 200  # 400 según X aunque son 200 caracteres
    texto = texto_x_por_defecto(_pub(titulo=titulo, hashtags=()))
    assert longitud_x(texto) <= MAX_TEXTO_X
    assert len(texto) < 145


def test_recortar_x_no_deja_una_url_a_medias_por_encima_del_limite():
    texto = "a " * 130 + "https://example.com/" + "x" * 80
    recortado = recortar_x(texto, MAX_TEXTO_X)
    assert longitud_x(recortado) <= MAX_TEXTO_X


def test_texto_para_x_usa_el_texto_propio_o_el_de_por_defecto():
    assert texto_para(Plataforma.X, _pub()) == "Título\n\n#a #b"
    assert texto_para(Plataforma.X, _pub(texto_x="  Mi post  ")) == "Mi post"


def test_texto_propio_de_x_largo_se_recorta_sin_premium_y_no_con_premium():
    largo = "frase larga " * 40  # 480
    sin = texto_para(Plataforma.X, _pub(texto_x=largo))
    assert longitud_x(sin) <= MAX_TEXTO_X and sin.endswith("…")
    con = texto_para(Plataforma.X, _pub(texto_x=largo), x_premium=True)
    assert con == largo.strip()


# --- Facebook ---


def test_facebook_texto_es_caption_mas_hashtags_y_titulo_el_titulo():
    assert texto_para(Plataforma.FACEBOOK, _pub()) == "Cuerpo\n\n#a #b"
    assert titulo_para(Plataforma.FACEBOOK, _pub()) == "Título"
    assert len(titulo_para(Plataforma.FACEBOOK, _pub(titulo="x " * 300))) <= 255
