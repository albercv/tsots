from __future__ import annotations

import pytest

from videopipeline import caption as cap
from videopipeline.steps import PasoFallido
from videopipeline.subtitles import Palabra


def _respuesta_ok() -> dict:
    return {
        "titulo": "Chat GPT Ads: segundo día y validación",
        "caption": "Hoy toca ser honestos.\n\n¿Y tú?",
        "hashtags": ["#marketingdigital", "#chatgptads", "#ia", "#negocios",
                     "#seo", "#reels", "#emprender", "#ads"],
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
    with pytest.raises(PasoFallido, match="respuesta del modelo no válida") as info:
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
