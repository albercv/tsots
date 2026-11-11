import pytest

from videopipeline.linkedin import (
    EJEMPLO_ES, ESQUEMA, MAX_CARACTERES, construir_mensajes, escribir, generar, leer, rutas,
)
from videopipeline.steps import PasoFallido


def test_generar_une_texto_y_hashtags():
    cliente = lambda m, msgs, esq: {"texto": "Gancho.\n\n" + "x" * 1400, "hashtags": ["#IA", "#viral", "pymes"]}
    texto, _ideas = generar("transcripción", "", "m", cliente=cliente)
    assert texto.endswith("\n\n#ia #pymes")


def test_hashtags_como_mucho_cinco():
    hs = [f"#t{i}" for i in range(8)]
    texto, _ideas = generar("t", "", "m", cliente=lambda *a: {"texto": "x" * 1400, "hashtags": hs})
    assert texto.rsplit("\n\n", 1)[1].split() == hs[:5]


def test_texto_corto_falla():
    with pytest.raises(PasoFallido):
        generar("t", "", "m", cliente=lambda *a: {"texto": "corto", "hashtags": []})


def test_texto_largo_se_corta_por_parrafo():
    largo = ("p" * 1200 + "\n\n") * 3
    texto, _ideas = generar("t", "", "m", cliente=lambda *a: {"texto": largo, "hashtags": []})
    assert len(texto) <= MAX_CARACTERES and texto.endswith("p")


def test_respuesta_invalida_falla():
    with pytest.raises(PasoFallido):
        generar("t", "", "m", cliente=lambda *a: {"texto": 3, "hashtags": []})


def test_prompt_es_incluye_ejemplo_y_no_copiar():
    system = construir_mensajes("hola", "", "es")[0]["content"]
    assert EJEMPLO_ES in system
    assert "no copies su contenido" in system
    assert "Qué significa en la práctica" in system


def test_prompt_en_aclara_ejemplo_en_espanol():
    system = construir_mensajes("hola", "marca X", "en")[0]["content"]
    assert "Spanish" in system and "marca X" in system


def test_rutas_junto_al_final(tmp_path):
    assert rutas(tmp_path / "x_limpio.mp4") == (tmp_path / "x_limpio.linkedin.md", tmp_path / "x_limpio.linkedin")


def test_escribir_y_leer_imagenes_ordenadas_sin_candidatos(tmp_path):
    final = tmp_path / "x_limpio.mp4"
    escribir("hola\n\n#a", final)
    md, carpeta = rutas(final)
    (carpeta / "candidatos").mkdir()
    (carpeta / "candidatos" / "c.png").write_bytes(b"")
    for n in ("b.jpg", "a.png", "notas.txt"):
        (carpeta / n).write_bytes(b"")
    texto, imgs = leer(final)
    assert texto == "hola\n\n#a"
    assert imgs == [carpeta / "a.png", carpeta / "b.jpg"]


def test_leer_sin_md_es_none(tmp_path):
    assert leer(tmp_path / "x_limpio.mp4") is None


def test_leer_md_que_no_es_utf8_es_none(tmp_path):
    final = tmp_path / "x_limpio.mp4"
    md, _carpeta = rutas(final)
    md.write_bytes(b"\xff\xfe no es UTF-8 \x80")
    assert leer(final) is None


def test_hashtags_del_modelo_no_se_duplican():
    cuerpo = "Gancho.\n\n" + "x" * 1400
    for final in ("\n\n#IA #Pymes", " #IA #Pymes", "\n#IA"):
        texto, _ideas = generar("t", "", "m", cliente=lambda *a: {"texto": cuerpo + final, "hashtags": ["#ia", "#pymes"]})
        assert texto.endswith("x\n\n#ia #pymes") and texto.count("#") == 2


def test_hashtag_en_mitad_de_frase_se_conserva():
    cuerpo = "Usa #Claude a diario.\n\n" + "x" * 1400
    texto, _ideas = generar("t", "", "m", cliente=lambda *a: {"texto": cuerpo, "hashtags": ["#ia"]})
    assert "Usa #Claude a diario." in texto


def test_prompt_prohibe_cta_de_red_social_e_inventos():
    es = construir_mensajes("hola", "", "es")[0]["content"]
    en = construir_mensajes("hola", "", "en")[0]["content"]
    assert "enlace en bio" in es and "si la transcripción no lo nombra, no lo nombres" in es
    assert "link in bio" in en and "if the transcript doesn't name it, don't name it" in en


def test_frase_con_enlace_en_bio_se_elimina():
    cuerpo = "Gancho.\n\n" + "x" * 1400
    for frase in ("Escríbeme (enlace en bio).", "Reach out, link in BIO!"):
        texto, _ideas = generar("t", "", "m", cliente=lambda *a: {"texto": f"{cuerpo}\n\nSígueme para más. {frase}\n\n¿Y tú?", "hashtags": []})
        assert "bio" not in texto.lower() and "¿Y tú?" in texto


def _ideas(ideas):
    return generar("t", "", "m", cliente=lambda *a: {"texto": "x" * 1400, "hashtags": [], "ideas": ideas})[1]


def test_ideas_se_limpian_y_descartan_las_que_no_caben_en_una_tarjeta():
    ideas = ["  «Los agentes cuestan lo que leen»  ", "Corta", "los agentes cuestan lo que leen",
             7, "Una idea con demasiadas palabras para caber en una tarjeta de LinkedIn sin verse diminuta",
             "Revisa quién supervisa a tus agentes de IA"]
    assert _ideas(ideas) == ["Los agentes cuestan lo que leen", "Revisa quién supervisa a tus agentes de IA"]


def test_ideas_como_mucho_tres():
    assert len(_ideas([f"Idea número {i} del vídeo" for i in range(5)])) == 3


def test_sin_ideas_el_post_sale_igual():
    texto, ideas = generar("t", "", "m", cliente=lambda *a: {"texto": "x" * 1400, "hashtags": []})
    assert ideas == [] and texto
    assert _ideas("no es una lista") == []


def test_prompt_y_esquema_piden_ideas():
    assert "ideas" in ESQUEMA["properties"] and "ideas" in ESQUEMA["required"]
    for idioma in ("es", "en"):
        assert '"ideas": [str]' in construir_mensajes("hola", "", idioma)[0]["content"]
