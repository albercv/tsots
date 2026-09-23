from __future__ import annotations

from videopipeline import glosario as gl
from videopipeline.subtitles import Palabra


def _p(*textos: str) -> list[Palabra]:
    return [Palabra(texto=t, inicio=float(i), fin=i + 0.5) for i, t in enumerate(textos)]


def _textos(palabras: list[Palabra]) -> list[str]:
    return [p.texto for p in palabras]


# --- parseo ------------------------------------------------------------------

def test_parsear_linea_con_variantes():
    g = gl.parsear("Claude Code = Cloud Code, Claus Code")
    assert g.terminos == (gl.Termino("Claude Code", ("Cloud Code", "Claus Code")),)


def test_parsear_ignora_vacias_y_comentarios():
    g = gl.parsear("\n# comentario\n  \nAnthropic\n")
    assert [t.correcto for t in g.terminos] == ["Anthropic"]


def test_parsear_linea_sin_igual_solo_termino():
    g = gl.parsear("TSOTS")
    assert g.terminos == (gl.Termino("TSOTS", ()),)


def test_parsear_tolera_espacios_y_comas_sobrantes():
    g = gl.parsear("  X  =  a ,, b , ")
    assert g.terminos == (gl.Termino("X", ("a", "b")),)


def test_parsear_texto_vacio_devuelve_glosario_vacio():
    g = gl.parsear("")
    assert g.vacio and g.n_terminos == 0 and g.n_correcciones == 0


def test_parsear_descarta_lineas_sin_termino_y_variante_igual_al_termino():
    g = gl.parsear("= huérfana\nClaude Code = claude code, Cloud Code")
    assert g.terminos == (gl.Termino("Claude Code", ("Cloud Code",)),)


def test_contadores():
    g = gl.parsear("Claude Code = Cloud Code, Claus Code\nAnthropic")
    assert g.n_terminos == 2 and g.n_correcciones == 2


# --- prompts -----------------------------------------------------------------

def test_prompt_whisper_une_terminos():
    g = gl.parsear("Claude Code = Cloud Code\nAnthropic\nEvolve2Digital")
    assert gl.prompt_whisper(g) == "Claude Code, Anthropic, Evolve2Digital."


def test_prompt_whisper_vacio_es_none():
    assert gl.prompt_whisper(gl.parsear("")) is None


def test_prompt_whisper_no_repite_terminos():
    g = gl.parsear("Claude\nClaude = Cloud")
    assert gl.prompt_whisper(g) == "Claude."


def test_prompt_whisper_recorta_a_max_chars():
    texto = "\n".join(f"termino{i:03d}" for i in range(200))
    g = gl.parsear(texto)
    prompt = gl.prompt_whisper(g)
    assert len(prompt) <= gl.MAX_CHARS_PROMPT
    assert prompt.endswith(".")
    incluidos = prompt.rstrip(".").split(", ")
    assert gl.recortados(g) == 200 - len(incluidos) > 0


def test_recortados_cero_si_cabe():
    assert gl.recortados(gl.parsear("A\nB")) == 0


def test_terminos_caption_devuelve_formas_correctas():
    g = gl.parsear("Claude Code = Cloud Code\nAnthropic\nClaude Code")
    assert gl.terminos_caption(g) == ("Claude Code", "Anthropic")


# --- correcciones --------------------------------------------------------------

def test_corregir_una_palabra():
    g = gl.parsear("Anthropic = Antropic")
    palabras = _p("de", "Antropic")
    r = gl.corregir(palabras, g)
    assert _textos(r) == ["de", "Anthropic"]
    assert (r[1].inicio, r[1].fin) == (1.0, 1.5)


def test_corregir_varias_palabras_misma_longitud():
    g = gl.parsear("Claude Code = Cloud Code")
    r = gl.corregir(_p("en", "Cloud", "Code."), g)
    assert _textos(r) == ["en", "Claude", "Code."]
    assert [(p.inicio, p.fin) for p in r] == [(0.0, 0.5), (1.0, 1.5), (2.0, 2.5)]


def test_corregir_sin_distinguir_mayusculas_ni_tildes():
    g = gl.parsear("Claude Code = Cloud Code\nEvolve2Digital = evolve to digital")
    assert _textos(gl.corregir(_p("cloud", "CODE"), g)) == ["Claude", "Code"]
    assert _textos(gl.corregir(_p("evolve", "tó", "digital"), g)) == ["Evolve2Digital"]


def test_corregir_cambia_numero_de_palabras():
    g = gl.parsear("Evolve2Digital = evolve to digital")
    r = gl.corregir(_p("con", "evolve", "to", "digital", "hoy"), g)
    assert _textos(r) == ["con", "Evolve2Digital", "hoy"]
    assert (r[1].inicio, r[1].fin) == (1.0, 3.5)


def test_corregir_reparte_tiempos_si_hay_mas_palabras():
    g = gl.parsear("Claude Code = claudecode")
    r = gl.corregir(_p("claudecode"), g)
    assert _textos(r) == ["Claude", "Code"]
    assert (r[0].inicio, r[0].fin, r[1].inicio, r[1].fin) == (0.0, 0.25, 0.25, 0.5)


def test_corregir_conserva_puntuacion_final_y_signos_iniciales():
    g = gl.parsear("Claude Code = Cloud Code")
    assert _textos(gl.corregir(_p("¿Cloud", "Code?"), g)) == ["¿Claude", "Code?"]


def test_corregir_no_toca_coincidencias_parciales():
    g = gl.parsear("Claude = Cloud")
    assert _textos(gl.corregir(_p("Cloudflare", "cloud-native"), g)) == [
        "Cloudflare", "cloud-native"]


def test_corregir_prefiere_la_variante_mas_larga():
    g = gl.parsear("Claude = Cloud\nClaudeCode = Cloud Code")
    assert _textos(gl.corregir(_p("Cloud", "Code", "y", "Cloud"), g)) == [
        "ClaudeCode", "y", "Claude"]


def test_corregir_glosario_vacio_devuelve_misma_lista():
    palabras = _p("hola")
    assert gl.corregir(palabras, gl.parsear("")) is palabras


def test_corregir_no_modifica_la_lista_original():
    g = gl.parsear("Claude = Cloud")
    palabras = _p("Cloud")
    gl.corregir(palabras, g)
    assert _textos(palabras) == ["Cloud"]
