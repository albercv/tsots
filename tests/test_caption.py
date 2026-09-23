from __future__ import annotations

import pytest

from videopipeline import caption as cap
from videopipeline.steps import PasoFallido
from videopipeline.subtitles import Palabra


def _respuesta_ok() -> dict:
    return {
        "titulo": "Chat GPT Ads: segundo día y validación",
        "caption": "Hoy toca ser honestos.\n\n¿Y tú?",
        "hashtags": ["#chatgptads", "#marketingdigital", "#ia", "#negocios",
                     "#emprender"],
        "palabras_clave": ["chat gpt ads", "validación perfil"],
    }


def test_texto_plano_une_palabras():
    palabras = [Palabra("Hola", 0, 0.2), Palabra("mundo", 0.2, 0.4)]
    assert cap.texto_plano(palabras) == "Hola mundo"


def test_recortar_a_max_palabras():
    texto = " ".join(f"p{i}" for i in range(4000))
    recortado = cap.recortar(texto)
    assert len(recortado.split()) == cap.MAX_PALABRAS
    assert recortado.startswith("p0 p1")
    assert cap.recortar("corto") == "corto"


def test_construir_mensajes_sin_marca():
    m = cap.construir_mensajes("blabla", "")
    assert [x["role"] for x in m] == ["system", "user"]
    assert "Contexto de marca" not in m[0]["content"]
    assert "blabla" in m[1]["content"]


def test_construir_mensajes_con_marca():
    m = cap.construir_mensajes("blabla", "Soy Alberto, tono cercano")
    assert "Contexto de marca" in m[0]["content"]
    assert "Soy Alberto, tono cercano" in m[0]["content"]


def test_construir_mensajes_idioma_ingles():
    m = cap.construir_mensajes("x", "", idioma="en")
    assert "hashtags" in m[0]["content"]
    assert "Respond only with JSON" in m[0]["content"]
    assert "Transcript:\nx" == m[1]["content"]


def test_construir_mensajes_idioma_ingles_con_marca():
    m = cap.construir_mensajes("x", "Soy Alberto", idioma="en")
    assert "Brand context" in m[0]["content"]
    assert "Soy Alberto" in m[0]["content"]


def test_construir_mensajes_idioma_desconocido_usa_espanol():
    m = cap.construir_mensajes("x", "", idioma="fr")
    assert "Transcripción:\nx" == m[1]["content"]


def test_esquema_exige_los_cuatro_campos():
    assert set(cap.ESQUEMA["required"]) == {"titulo", "caption", "hashtags",
                                            "palabras_clave"}


def test_generar_usa_cliente_y_devuelve_caption():
    llamadas = []

    def cliente(modelo, mensajes, esquema):
        llamadas.append((modelo, mensajes, esquema))
        return _respuesta_ok()

    c = cap.generar("transcripción", "marca", "qwen3.5:9b", cliente=cliente)
    assert isinstance(c, cap.Caption)
    assert c.titulo.startswith("Chat GPT Ads")
    assert llamadas[0][0] == "qwen3.5:9b"
    assert llamadas[0][2] is cap.ESQUEMA


def test_generar_normaliza_hashtags_y_titulo():
    r = _respuesta_ok()
    r["hashtags"] = ["MarketingDigital", "#ia", "#IA", "con espacio", "#seo"] + ["#x"] * 3
    r["titulo"] = "T" * 80

    c = cap.generar("t", "", "m", cliente=lambda *a: r)
    assert c.hashtags == ["#marketingdigital", "#ia", "#conespacio", "#seo", "#x"]
    assert len(c.titulo) == cap.MAX_TITULO


def test_generar_falla_si_faltan_campos():
    with pytest.raises(PasoFallido, match="respuesta del modelo no es válida") as info:
        cap.generar("t", "", "m", cliente=lambda *a: {"titulo": "solo"})
    assert "solo" in info.value.detalle


def test_generar_falla_si_transcripcion_vacia():
    with pytest.raises(PasoFallido, match="transcripción"):
        cap.generar("   ", "", "m", cliente=lambda *a: pytest.fail("no llamar"))


def test_md_ida_y_vuelta(tmp_path):
    c = cap.Caption(**_respuesta_ok())
    ruta = tmp_path / "v_limpio.md"
    cap.escribir_md(c, ruta)
    texto = ruta.read_text(encoding="utf-8")
    assert texto.startswith("# Chat GPT Ads")
    assert "## Caption" in texto and "## Hashtags" in texto and "## Palabras clave" in texto
    assert cap.leer_md(ruta) == c


def test_leer_md_inexistente_o_corrupto(tmp_path):
    assert cap.leer_md(tmp_path / "no.md") is None
    (tmp_path / "raro.md").write_text("sin secciones", encoding="utf-8")
    assert cap.leer_md(tmp_path / "raro.md") is None


def test_texto_completo_y_hashtags_texto():
    c = cap.Caption(**_respuesta_ok())
    assert c.hashtags_texto == " ".join(_respuesta_ok()["hashtags"])
    completo = c.texto_completo()
    assert completo.splitlines()[0] == c.titulo
    assert completo.rstrip().endswith(c.hashtags_texto)


def test_md_ida_y_vuelta_con_encabezados_dentro_del_caption(tmp_path):
    c = cap.Caption(
        titulo="Título",
        caption="Primera línea\n## Nota\nUna línea que empieza como encabezado\n# Otra",
        hashtags=["#a", "#b"],
        palabras_clave=["k1", "k2"],
    )
    ruta = tmp_path / "v_limpio.md"
    cap.escribir_md(c, ruta)
    assert cap.leer_md(ruta) == c


def test_leer_md_sin_alguna_seccion_devuelve_none(tmp_path):
    ruta = tmp_path / "v.md"
    ruta.write_text("# T\n\n## Caption\nx\n\n## Hashtags\n#a\n", encoding="utf-8")
    assert cap.leer_md(ruta) is None  # falta "## Palabras clave"


def test_generar_normaliza_saltos_de_linea_en_titulo_y_palabras_clave(tmp_path):
    r = _respuesta_ok()
    r["titulo"] = "Chat GPT Ads\nsegundo día"
    r["palabras_clave"] = ["a\nb"]

    def cliente(modelo, mensajes, esquema):
        return r

    c = cap.generar("t", "", "m", cliente=cliente)
    assert c.titulo == "Chat GPT Ads segundo día"
    assert c.palabras_clave == ["a b"]

    ruta = tmp_path / "v_limpio.md"
    cap.escribir_md(c, ruta)
    assert cap.leer_md(ruta) == c


def test_md_ida_y_vuelta_con_cabeceras_reales_dentro_del_caption(tmp_path):
    c = cap.Caption(
        titulo="Título",
        caption="Hola\n## Hashtags\n## Palabras clave\n## Caption\nAdiós",
        hashtags=["#a", "#b"],
        palabras_clave=["k1"],
    )
    ruta = tmp_path / "v_limpio.md"
    cap.escribir_md(c, ruta)
    assert cap.leer_md(ruta) == c


# --- hashtags: 5, relevantes, derivados de la descripción -------------------

def test_esquema_pide_exactamente_cinco_hashtags():
    h = cap.ESQUEMA["properties"]["hashtags"]
    assert cap.NUM_HASHTAGS == 5
    assert h["minItems"] == h["maxItems"] == 5


def test_hashtags_se_generan_despues_de_caption_y_palabras_clave():
    # Ollama genera en el orden del esquema: los hashtags deben salir cuando el
    # modelo ya ha escrito el caption y las palabras clave, para basarse en ellos.
    orden = list(cap.ESQUEMA["properties"])
    assert orden.index("hashtags") > orden.index("caption")
    assert orden.index("hashtags") > orden.index("palabras_clave")


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_prompt_pide_cinco_hashtags_relevantes_sin_genericos(idioma):
    system = cap.construir_mensajes("t", "", idioma)[0]["content"]
    assert "5" in system
    assert "#viral" in system and "#fyp" in system
    clave = "palabras_clave"
    assert clave in system.split("hashtags", 1)[1]


def test_generar_recorta_a_cinco_manteniendo_orden():
    r = _respuesta_ok()
    r["hashtags"] = ["#a1", "#a2", "#a3", "#a4", "#a5", "#a6", "#a7"]
    c = cap.generar("t", "", "m", cliente=lambda *a: r)
    assert c.hashtags == ["#a1", "#a2", "#a3", "#a4", "#a5"]


def test_generar_descarta_hashtags_genericos():
    r = _respuesta_ok()
    r["hashtags"] = ["#viral", "#FYP", "#chatgptads", "#parati", "#reels",
                     "#ia", "#foryou", "#trending", "#explore", "#negocios",
                     "#seo", "#ads"]
    c = cap.generar("t", "", "m", cliente=lambda *a: r)
    assert c.hashtags == ["#chatgptads", "#ia", "#negocios", "#seo", "#ads"]


def test_generar_completa_con_palabras_clave_si_faltan():
    r = _respuesta_ok()
    r["hashtags"] = ["#viral", "#chatgptads", "#fyp"]
    r["palabras_clave"] = ["chat gpt ads", "validación de perfil", "anuncios IA",
                           "meta ads", "presupuesto"]
    c = cap.generar("t", "", "m", cliente=lambda *a: r)
    assert c.hashtags == ["#chatgptads", "#validaciondeperfil", "#anunciosia",
                          "#metaads", "#presupuesto"]


def test_normaliza_puntuacion_y_acentos_pero_conserva_la_enie():
    r = _respuesta_ok()
    r["hashtags"] = ["#IA-Generativa!", "#Educación", "#España", "#año_2026", "#ok"]
    c = cap.generar("t", "", "m", cliente=lambda *a: r)
    assert c.hashtags == ["#iagenerativa", "#educacion", "#españa", "#año_2026", "#ok"]
