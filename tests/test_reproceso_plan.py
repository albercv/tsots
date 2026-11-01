from __future__ import annotations

from pathlib import Path

import pytest

from videopipeline import ficha as modulo_ficha
from videopipeline.config import PipelineConfig
from videopipeline.ficha import (
    AUDIO, BASE, CAPTION, HORIZONTAL, SEGUIMIENTO, TRANSCRIPCION, VERTICAL,
    Artefacto, Ficha, Huella,
)
from videopipeline.reproceso_plan import (
    Accion, Consulta, Decisiones, ajustes_audio, ajustes_caption,
    ajustes_silencios, ajustes_subtitulos, ajustes_transcripcion,
    ajustes_vertical, clave, planificar, revisar,
)

A = Accion


@pytest.fixture(autouse=True)
def dir_fichas(tmp_path, monkeypatch):
    """Los archivos de las fichas de los tests nunca van al proyecto."""
    monkeypatch.setattr(modulo_ficha, "DIR_FICHAS", tmp_path / "fichas")


def _panel(**valores) -> PipelineConfig:
    """Lo que pide el panel: ningún paso marcado salvo los que se pasan."""
    marcas = dict(paso_audio=False, paso_silencios=False, subtitulos=False,
                  caption_seo=False, paso_vertical=False)
    marcas.update(valores)
    return PipelineConfig(video=Path("/no/importa.mov"), **marcas)


# Los ajustes del panel por defecto: los que tiene una ficha hecha con él.
AUD = ajustes_audio(_panel())
SIL = ajustes_silencios(_panel())
SUBS = ajustes_subtitulos(_panel())
TRANS = ajustes_transcripcion(_panel())
L_S = clave(None, SIL)  # recortado sin audio limpio
L_AS = clave(AUD, SIL)  # recortado sobre el audio limpio


def _archivo(ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"x")
    return ruta


def _base(audio=False, silencios=False, linea=None, aparte=True) -> Artefacto:
    ajustes = {}
    if audio:
        ajustes["audio"] = AUD
    if silencios:
        ajustes["silencios"] = SIL
    if linea is None:
        linea = clave(AUD if audio else None, SIL) if silencios else "original"
    return Artefacto(clave(ajustes, linea), "base.mp4" if aparte else None,
                     ajustes, linea)


def _audio(linea="original") -> Artefacto:
    return Artefacto(clave(AUD), "audio_limpio.flac", AUD, linea)


def _transcripcion(linea) -> Artefacto:
    return Artefacto(clave(TRANS), "transcripcion.json", TRANS, linea)


def _horizontal(subs=True) -> Artefacto:
    return Artefacto("h", None, {"subtitulos": SUBS} if subs else {})


def _vertical(encuadre="central", subs=False) -> Artefacto:
    ajustes = {"vertical": {"encuadre": encuadre}}
    if subs:
        ajustes["subtitulos"] = SUBS
    return Artefacto("v", None, ajustes)


def _caption() -> Artefacto:
    return Artefacto("c", "caption.md", {"caption": ajustes_caption(_panel())})


def _ficha(tmp_path, artefactos, *, final="horizontal", con_vertical=False,
           original=True, **campos) -> Ficha:
    """Ficha en memoria cuyos archivos existen: original, salidas y artefactos."""
    salida = tmp_path / "salida"
    ficha = Ficha(id="f", nombre="x", carpeta_salida=salida,
                  artefactos=artefactos, **campos)
    if original:
        ficha.original = Huella.de(_archivo(tmp_path / "x.mov"))
    if final == "horizontal":
        ficha.final = Huella.de(_archivo(salida / "x_limpio.mp4"))
    elif final == "vertical":
        ficha.final = Huella.de(_archivo(salida / "x_vertical.mp4"))
    if con_vertical:
        ficha.vertical = Huella.de(_archivo(salida / "x_limpio_vertical.mp4"))
    for artefacto in artefactos.values():
        if artefacto.archivo is not None:
            _archivo(ficha.ruta(artefacto.archivo))
    return ficha


def _completa(tmp_path, **extra) -> Ficha:
    """Audio, silencios, subtítulos y caption hechos con el panel por defecto."""
    return _ficha(tmp_path, {
        AUDIO: _audio(), BASE: _base(audio=True, silencios=True),
        TRANSCRIPCION: _transcripcion(L_AS), HORIZONTAL: _horizontal(),
        CAPTION: _caption(), **extra,
    }, con_vertical=VERTICAL in extra)


TODO = dict(paso_audio=True, paso_silencios=True, subtitulos=True,
            caption_seo=True)

CASOS = [
    ("caption_con_transcripcion_de_otra_linea",
     lambda t: _ficha(t, {BASE: _base(silencios=True, aparte=False),
                          HORIZONTAL: _horizontal(subs=False),
                          TRANSCRIPCION: _transcripcion("original")}),
     dict(caption_seo=True), Decisiones(), [A.CAPTION]),
    ("caption_sin_transcripcion",
     lambda t: _ficha(t, {BASE: _base(silencios=True, aparte=False),
                          HORIZONTAL: _horizontal(subs=False)}),
     dict(caption_seo=True), Decisiones(), [A.TRANSCRIBIR, A.CAPTION]),
    ("rehacer_caption", _completa, dict(caption_seo=True),
     Decisiones(rehacer=frozenset({"caption"})), [A.CAPTION]),
    ("anadir_subtitulos",
     lambda t: _ficha(t, {AUDIO: _audio(),
                          BASE: _base(audio=True, silencios=True, aparte=False),
                          HORIZONTAL: _horizontal(subs=False),
                          CAPTION: _caption()}),
     TODO, Decisiones(), [A.TRANSCRIBIR, A.QUEMAR]),
    ("cambiar_estilo", _completa, dict(subtitulos=True, diseno="caja"),
     Decisiones(rehacer=frozenset({"subtitulos"})), [A.QUEMAR]),
    ("rehacer_subtitulos", _completa, dict(subtitulos=True),
     Decisiones(rehacer=frozenset({"subtitulos"})), [A.TRANSCRIBIR, A.QUEMAR]),
    ("anadir_silencios_a_audio_y_subtitulos",
     lambda t: _ficha(t, {AUDIO: _audio(), BASE: _base(audio=True),
                          TRANSCRIPCION: _transcripcion("original"),
                          HORIZONTAL: _horizontal(), CAPTION: _caption()}),
     TODO, Decisiones(), [A.CORTAR, A.TRANSCRIBIR, A.QUEMAR]),
    ("rehacer_silencios_con_audio_limpiado_sobre_la_base",
     lambda t: _ficha(t, {AUDIO: _audio(L_S),
                          BASE: _base(audio=True, silencios=True, linea=L_S),
                          TRANSCRIPCION: _transcripcion(L_S),
                          HORIZONTAL: _horizontal(), CAPTION: _caption()}),
     dict(TODO, margen="0.4s"), Decisiones(rehacer=frozenset({"silencios"})),
     [A.LIMPIAR_AUDIO_ORIGINAL, A.CORTAR, A.TRANSCRIBIR, A.QUEMAR]),
    ("anadir_audio_a_un_video_recortado_con_subtitulos",
     lambda t: _ficha(t, {BASE: _base(silencios=True),
                          TRANSCRIPCION: _transcripcion(L_S),
                          HORIZONTAL: _horizontal(), CAPTION: _caption()}),
     TODO, Decisiones(),
     [A.LIMPIAR_AUDIO_BASE, A.PONER_AUDIO, A.QUEMAR]),
    ("rehacer_audio_con_recorte", _completa,
     dict(TODO, modelo="FRCRN_SE_16K"), Decisiones(rehacer=frozenset({"audio"})),
     [A.LIMPIAR_AUDIO_ORIGINAL, A.CORTAR, A.TRANSCRIBIR, A.QUEMAR]),
    ("anadir_vertical_central", _completa,
     dict(TODO, paso_vertical=True), Decisiones(), [A.VERTICAL]),
    ("cambiar_encuadre_a_cara",
     lambda t: _completa(t, **{VERTICAL: _vertical(subs=True)}),
     dict(paso_vertical=True, encuadre="cara"),
     Decisiones(rehacer=frozenset({"vertical"})), [A.SEGUIMIENTO, A.VERTICAL]),
    ("pasos_ya_hechos_mismos_ajustes",
     lambda t: _completa(t, **{VERTICAL: _vertical(subs=True)}),
     dict(TODO, paso_vertical=True), Decisiones(), []),
]


@pytest.mark.parametrize("ficha, panel, decisiones, esperado",
                         [caso[1:] for caso in CASOS],
                         ids=[caso[0] for caso in CASOS])
def test_casos_de_la_spec(tmp_path, ficha, panel, decisiones, esperado):
    plan = planificar(ficha(tmp_path), _panel(**panel), decisiones)

    assert plan.error == ""
    assert plan.acciones == esperado
    assert plan.vacio == (esperado == [])


def test_cambiar_estilo_no_retranscribe(tmp_path):
    plan = planificar(_completa(tmp_path), _panel(subtitulos=True, diseno="caja"),
                      Decisiones(rehacer=frozenset({"subtitulos"})))

    assert A.TRANSCRIBIR not in plan.acciones
    assert plan.acciones == [A.QUEMAR]
    assert plan.config.diseno == "caja"


def test_cambiar_glosario_y_rehacer_vuelve_a_transcribir(tmp_path):
    plan = planificar(_completa(tmp_path),
                      _panel(subtitulos=True, glosario="Claude Code"),
                      Decisiones(rehacer=frozenset({"subtitulos"})))

    assert plan.acciones == [A.TRANSCRIBIR, A.QUEMAR]


def test_glosario_nuevo_no_invalida_la_transcripcion_por_si_solo(tmp_path):
    plan = planificar(_completa(tmp_path),
                      _panel(**TODO, paso_vertical=True, glosario="Claude Code"),
                      Decisiones())

    assert plan.acciones == [A.VERTICAL]


def test_caption_se_mantiene_al_recortar(tmp_path):
    ficha = _ficha(tmp_path, {AUDIO: _audio(), BASE: _base(audio=True),
                              TRANSCRIPCION: _transcripcion("original"),
                              HORIZONTAL: _horizontal(), CAPTION: _caption()})

    plan = planificar(ficha, _panel(**TODO), Decisiones())

    assert A.CORTAR in plan.acciones
    assert A.CAPTION not in plan.acciones


def _con_vertical_sin_subs(tmp_path) -> Ficha:
    return _ficha(tmp_path, {AUDIO: _audio(),
                             BASE: _base(audio=True, aparte=False),
                             HORIZONTAL: _horizontal(subs=False),
                             VERTICAL: _vertical()}, con_vertical=True)


def test_vertical_desactualizado_sin_regenerar_se_marca(tmp_path):
    plan = planificar(_con_vertical_sin_subs(tmp_path),
                      _panel(paso_audio=True, paso_silencios=True), Decisiones())

    assert plan.acciones == [A.CORTAR, A.ESCRIBIR_FINAL]
    assert plan.marcar_desactualizado


def test_vertical_desactualizado_se_regenera_si_se_pide(tmp_path):
    plan = planificar(_con_vertical_sin_subs(tmp_path),
                      _panel(paso_audio=True, paso_silencios=True),
                      Decisiones(regenerar_vertical=True))

    assert plan.acciones == [A.CORTAR, A.ESCRIBIR_FINAL, A.VERTICAL]
    assert not plan.marcar_desactualizado


def test_vertical_regenerado_sin_pedirlo_usa_el_encuadre_de_la_ficha(tmp_path):
    ficha = _ficha(tmp_path, {HORIZONTAL: _horizontal(subs=False),
                              VERTICAL: _vertical("cara")}, con_vertical=True)

    plan = planificar(ficha, _panel(paso_silencios=True, encuadre="barras"),
                      Decisiones(regenerar_vertical=True))

    assert plan.acciones == [A.CORTAR, A.ESCRIBIR_FINAL, A.SEGUIMIENTO,
                             A.VERTICAL]
    assert plan.config.encuadre == "cara"


def test_seguimiento_valido_no_se_repite(tmp_path):
    ficha = _completa(tmp_path, **{
        VERTICAL: _vertical("cara", subs=True),
        SEGUIMIENTO: Artefacto(L_AS, "cara.cmd", {"x_inicial": 10})})

    plan = planificar(ficha, _panel(paso_vertical=True, encuadre="cara"),
                      Decisiones(rehacer=frozenset({"vertical"})))

    assert plan.acciones == [A.VERTICAL]


def _solo_vertical(tmp_path, subs) -> Ficha:
    artefactos = {VERTICAL: _vertical(subs=subs)}
    if subs:
        artefactos[TRANSCRIPCION] = _transcripcion("original")
    return _ficha(tmp_path, artefactos, final="vertical")


def test_vertical_unico_gana_horizontal_se_renombra(tmp_path):
    plan = planificar(_solo_vertical(tmp_path, subs=True),
                      _panel(subtitulos=True), Decisiones())

    assert plan.acciones == [A.QUEMAR, A.RENOMBRAR_VERTICAL]
    assert not plan.marcar_desactualizado


def test_vertical_unico_desactualizado_se_regenera_y_retira(tmp_path):
    plan = planificar(_solo_vertical(tmp_path, subs=False),
                      _panel(paso_silencios=True), Decisiones())

    assert plan.acciones == [A.CORTAR, A.ESCRIBIR_FINAL, A.VERTICAL,
                             A.RETIRAR_VERTICAL_UNICO]
    assert not plan.marcar_desactualizado


def test_vertical_unico_con_subtitulos_nuevos_regenera_el_vertical(tmp_path):
    plan = planificar(_solo_vertical(tmp_path, subs=False),
                      _panel(subtitulos=True, paso_vertical=True), Decisiones())

    assert plan.acciones == [A.TRANSCRIBIR, A.VERTICAL]


def test_ficha_nueva_planifica_la_pasada_completa(tmp_path):
    ficha = _ficha(tmp_path, {}, final=None)

    plan = planificar(ficha, _panel(**TODO, paso_vertical=True), Decisiones())

    assert plan.acciones == [A.LIMPIAR_AUDIO_ORIGINAL, A.CORTAR, A.TRANSCRIBIR,
                             A.QUEMAR, A.CAPTION, A.VERTICAL]


def test_falta_original_da_error(tmp_path):
    ficha = _ficha(tmp_path, {HORIZONTAL: _horizontal(subs=False)})
    ficha.original.ruta.unlink()

    plan = planificar(ficha, _panel(paso_silencios=True), Decisiones())

    assert str(ficha.original.ruta) in plan.error
    assert plan.acciones == []
    assert not plan.vacio


def test_falta_la_base_se_rehace_desde_el_original(tmp_path):
    ficha = _completa(tmp_path)
    ficha.ruta("base.mp4").unlink()

    plan = planificar(ficha, _panel(subtitulos=True, diseno="caja"),
                      Decisiones(rehacer=frozenset({"subtitulos"})))

    assert plan.acciones == [A.CORTAR, A.QUEMAR]


def test_caption_sin_final_da_error(tmp_path):
    plan = planificar(_ficha(tmp_path, {}, final=None), _panel(caption_seo=True),
                      Decisiones())

    assert "aún no tiene vídeo procesado" in plan.error
    assert plan.acciones == []


def _legado(tmp_path, **campos) -> Ficha:
    """Salida antigua con su .md y su .srt importados."""
    return _ficha(tmp_path, {
        CAPTION: Artefacto("importado", "caption.md"),
        TRANSCRIPCION: Artefacto("importado", "transcripcion.json",
                                 linea_tiempo="legado"),
    }, subs_quemados_sin_base=True, **campos)


def test_legado_con_subs_bloquea_subtitulos(tmp_path):
    ficha = _legado(tmp_path, original=False, legado=True)
    panel = _panel(subtitulos=True, paso_vertical=True)

    consultas = revisar(ficha, panel)
    plan = planificar(ficha, panel, Decisiones(rehacer=frozenset({"subtitulos"})))

    assert [(c.paso, c.tipo) for c in consultas] == [
        ("subtitulos", "bloqueado"), ("vertical", "bloqueado")]
    assert A.QUEMAR not in plan.acciones
    assert A.VERTICAL not in plan.acciones
    assert len(plan.avisos) == 2
    assert all("original" in aviso for aviso in plan.avisos)


def test_legado_permite_recortar(tmp_path):
    ficha = _legado(tmp_path, original=False, legado=True)

    plan = planificar(ficha, _panel(paso_silencios=True), Decisiones())

    assert plan.error == ""
    assert plan.acciones == [A.CORTAR, A.ESCRIBIR_FINAL]


def test_legado_vertical_sin_original_no_puede_cambiar_la_base(tmp_path):
    ficha = _ficha(tmp_path, {}, final="vertical", original=False, legado=True)

    plan = planificar(ficha, _panel(paso_silencios=True), Decisiones())

    assert "No encuentro el original" in plan.error


def test_legado_adoptado_con_subs_quema_sobre_el_original(tmp_path):
    ficha = _legado(tmp_path)  # original adoptado: legado=False
    panel = _panel(subtitulos=True)

    assert revisar(ficha, panel) == []
    plan = planificar(ficha, panel, Decisiones())

    assert plan.error == ""
    assert plan.avisos == []
    assert plan.acciones == [A.TRANSCRIBIR, A.QUEMAR]


def test_revisar_hecho_y_otros_ajustes(tmp_path):
    ficha = _completa(tmp_path)

    consultas = revisar(ficha, _panel(paso_audio=True, subtitulos=True,
                                      caption_seo=True, diseno="caja"))

    por_paso = {c.paso: c for c in consultas}
    assert set(por_paso) == {"audio", "subtitulos", "caption"}
    assert por_paso["audio"].tipo == "hecho"
    assert "volverá a transcribir y quemar los subtítulos" in por_paso["audio"].texto
    assert por_paso["caption"].tipo == "hecho"
    assert por_paso["caption"].texto.startswith('"x" ya tiene caption.')
    assert por_paso["subtitulos"].tipo == "otros_ajustes"
    assert "diseno: reels_bold → caja" in por_paso["subtitulos"].cambios


def test_revisar_glosario_nuevo_es_otros_ajustes(tmp_path):
    consultas = revisar(_completa(tmp_path),
                        _panel(subtitulos=True, glosario="Claude Code"))

    assert consultas == [Consulta("subtitulos", "otros_ajustes",
                                  consultas[0].texto, ("glosario",))]


def test_revisar_paso_de_base_nuevo_avisa_de_lo_que_se_rehace(tmp_path):
    ficha = _ficha(tmp_path, {HORIZONTAL: _horizontal(),
                              TRANSCRIPCION: _transcripcion("original")})

    consultas = revisar(ficha, _panel(paso_silencios=True))

    assert [(c.paso, c.tipo) for c in consultas] == [("silencios", "cambia_base")]
    assert "se volverán a transcribir y quemar" in consultas[0].texto


def test_revisar_vertical_unico_avisa_sin_desactualizarlo(tmp_path):
    consultas = revisar(_solo_vertical(tmp_path, subs=False),
                        _panel(paso_silencios=True))

    assert [(c.paso, c.tipo) for c in consultas] == [("silencios", "cambia_base")]
    assert "desactualizado" not in consultas[0].texto


def test_revisar_sin_nada_hecho_no_pregunta(tmp_path):
    assert revisar(_ficha(tmp_path, {}, final=None), _panel(**TODO)) == []


def test_implicito_usa_ajustes_de_la_ficha(tmp_path):
    caja = ajustes_subtitulos(_panel(diseno="caja"))
    ficha = _ficha(tmp_path, {AUDIO: _audio(), BASE: _base(audio=True),
                              TRANSCRIPCION: _transcripcion("original"),
                              HORIZONTAL: Artefacto("h", None,
                                                    {"subtitulos": caja})})
    panel = _panel(paso_audio=True, paso_silencios=True, subtitulos=True,
                   glosario="Anthropic")

    plan = planificar(ficha, panel, Decisiones())

    assert plan.acciones == [A.CORTAR, A.TRANSCRIBIR, A.QUEMAR]
    assert plan.config.diseno == "caja"
    assert plan.config.glosario == "Anthropic"


def test_artefacto_sin_archivo_se_rehace(tmp_path):
    ficha = _ficha(tmp_path, {AUDIO: _audio(), BASE: _base(audio=True),
                              HORIZONTAL: _horizontal(subs=False)})
    ficha.ruta("audio_limpio.flac").unlink()

    plan = planificar(ficha, _panel(paso_audio=True, paso_silencios=True),
                      Decisiones())

    assert plan.acciones == [A.LIMPIAR_AUDIO_ORIGINAL, A.CORTAR,
                             A.ESCRIBIR_FINAL]


def test_ajustes_y_clave():
    c = _panel(diseno="caja", glosario="Anthropic")
    assert ajustes_audio(c) == {"tarea": c.tarea, "modelo": c.modelo}
    assert ajustes_silencios(c) == {"margen": "0.2s", "umbral": "4%",
                                    "silencios": "cortar", "velocidad": 4}
    assert ajustes_subtitulos(c) == {"diseno": "caja", "posicion": 75,
                                     "tamano": 100, "idioma": "es",
                                     "modelo_whisper": "turbo"}
    assert ajustes_transcripcion(c) == {"idioma": "es", "modelo_whisper": "turbo",
                                        "glosario": clave("Anthropic")}
    assert ajustes_vertical(c) == {"encuadre": "central"}
    assert ajustes_caption(c) == {"modelo_caption": c.modelo_caption}
    assert clave({"a": 1, "b": 2}) == clave({"b": 2, "a": 1})
    assert len(clave("x")) == 16 and clave("x") != clave("y")
