from __future__ import annotations

import json
import os
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from videopipeline import ficha as modulo_ficha
from videopipeline import pipeline, reproceso, shorts
from videopipeline.caption import Caption
from videopipeline.config import PipelineConfig
from videopipeline.ficha import (
    BASE, HORIZONTAL, SEGUIMIENTO, TRANSCRIPCION, VERTICAL, Artefacto, Ficha,
    Huella,
    _escribir_json, cargar, guardar,
)
from videopipeline.reproceso_plan import clave_seguimiento
from videopipeline.steps import PasoFallido
from videopipeline.subtitles import Palabra
from videopipeline.titulo import lineas_titulo
from tests.falsos_pipeline import banner_sintetico
from videopipeline.vertical import banner_vertical


def _frases_de(n: int, segundos: float) -> list[shorts.Frase]:
    """`n` frases seguidas de 10 palabras que duran `segundos` cada una."""
    paso = segundos / 10
    frases = []
    for f in range(n):
        palabras = [
            Palabra("palabra" + ("." if i == 9 else ""),
                    (f * 10 + i) * paso, (f * 10 + i + 1) * paso)
            for i in range(10)
        ]
        frases.append(shorts.Frase(palabras))
    return frases


def _cand(ini: int, fin: int, **campos) -> dict:
    return {"frase_inicio": ini, "frase_fin": fin, "titulo": "t", "motivo": "m",
            **campos}


def test_trocear_frases_por_puntuacion():
    palabras = [Palabra("Hola", 0.0, 0.4), Palabra("mundo.", 0.4, 0.9),
                Palabra("Adiós.", 1.0, 1.5)]
    frases = shorts.trocear_frases(palabras)
    assert [f.texto for f in frases] == ["Hola mundo.", "Adiós."]
    assert [(f.inicio, f.fin) for f in frases] == [(0.0, 0.9), (1.0, 1.5)]


def test_trocear_frases_sin_puntuacion_corta_por_pausa_y_tope():
    palabras = []
    t = 0.0
    for i in range(130):
        palabras.append(Palabra("palabra", t, t + 0.3))
        t += 0.3
        if i == 9:
            t += 1.5  # pausa mayor que PAUSA_FRASE
    frases = shorts.trocear_frases(palabras)
    assert [len(f.palabras) for f in frases] == [10, 60, 60]


def test_trocear_frases_puntuacion_antes_de_comillas():
    textos = ['Dijo', '"basta."', 'Luego', '«¿vale?»', 'Sí', '(claro.)', 'Y',
              "¡ya!'", 'Fin', 'dijo.”', 'Resto']
    palabras = [Palabra(t, i * 0.5, i * 0.5 + 0.4) for i, t in enumerate(textos)]
    frases = shorts.trocear_frases(palabras)
    assert [f.texto for f in frases] == [
        'Dijo "basta."', 'Luego «¿vale?»', 'Sí (claro.)', "Y ¡ya!'",
        'Fin dijo.”', 'Resto',
    ]


def test_trocear_frases_vacio():
    assert shorts.trocear_frases([]) == []


def test_maximo_shorts():
    # Hasta 3 por cada tramo de 10 minutos, contando el último aunque esté incompleto.
    assert [shorts.maximo_shorts(d) for d in (179, 180, 300, 600, 1199, 1800, 7860)] == [
        0, 3, 3, 3, 6, 9, 42]


def test_validar_descarta_rango_duracion_y_repetidos():
    frases = _frases_de(10, 10)
    datos = {"candidatos": [
        _cand(0, 3), _cand(5, 2), _cand(1, 3), _cand(1, 8), _cand(1, 8),
        _cand("2", "9"),
    ]}
    resultado = shorts.validar(datos, frases, duracion=100.0)
    assert [c.descarte for c in resultado] == [
        "fuera_de_rango", "fuera_de_rango", "duracion", "", "repetido", "",
    ]
    assert all(c.descarte in ("", *shorts.DESCARTES) for c in resultado)
    assert (resultado[5].frase_inicio, resultado[5].frase_fin) == (2, 9)


def test_validar_limites_de_duracion_son_validos():
    def una_frase(segundos: float) -> list[shorts.Frase]:
        return [shorts.Frase([Palabra("a", 0.0, segundos)])]

    for segundos, esperado in ((59.9, "duracion"), (60.0, ""), (179.0, ""),
                               (179.1, "duracion")):
        c = shorts.validar({"candidatos": [_cand(1, 1)]}, una_frase(segundos),
                           duracion=segundos)[0]
        assert c.descarte == esperado, segundos


def test_validar_ignora_entradas_que_no_son_dicts_con_enteros():
    frases = _frases_de(10, 10)
    datos = {"candidatos": [
        "basura", None, 7, {"titulo": "sin números"},
        _cand("uno", 8), _cand(1.5, 8), _cand(True, 8), _cand(None, 8),
        _cand(" 1 ", "8"),
    ]}
    resultado = shorts.validar(datos, frases, duracion=100.0)
    assert [(c.frase_inicio, c.frase_fin, c.descarte) for c in resultado] == [
        (1, 8, ""),
    ]


def test_validar_limpia_titulo_y_motivo():
    frases = _frases_de(10, 10)
    datos = {"candidatos": [_cand(1, 8, titulo="  Un   título\n largo ",
                                  motivo="  porque sí \n")]}
    c = shorts.validar(datos, frases, duracion=100.0)[0]
    assert (c.titulo, c.motivo) == ("Un título largo", "porque sí")


def test_validar_corte_con_margen_sin_pisar_vecinas():
    # Cada frase dura 10 s; entre ellas hay 0,1 s de hueco, menos que el margen.
    frases = []
    for f in range(10):
        t0 = f * 10.1
        frases.append(shorts.Frase([Palabra("a", t0, t0 + 10.0)]))
    datos = {"candidatos": [_cand(3, 9), _cand(1, 7), _cand(4, 10)]}
    intermedio, primera, ultima = shorts.validar(datos, frases, duracion=101.0)
    # Hueco de 0,1 s: el margen se recorta al fin de la frase anterior.
    assert intermedio.inicio == pytest.approx(frases[1].fin)
    assert intermedio.fin == pytest.approx(frases[9].inicio)
    # La primera frase no baja de 0 y el fin no entra en la octava.
    assert primera.inicio == 0.0
    assert primera.fin == pytest.approx(frases[7].inicio)
    # La última no pasa de la duración.
    assert ultima.fin == 101.0
    # Con hueco grande se aplica el margen entero.
    sueltas = [shorts.Frase([Palabra("a", 5.0 + f * 20.0, 15.0 + f * 20.0)])
               for f in range(10)]
    c = shorts.validar({"candidatos": [_cand(3, 9)]}, sueltas, duracion=300.0)[0]
    assert c.inicio == pytest.approx(sueltas[2].inicio - shorts.MARGEN_CORTE)
    assert c.fin == pytest.approx(sueltas[8].fin + shorts.MARGEN_CORTE)


def test_validar_nunca_corta_dentro_de_las_frases_del_short():
    # Whisper solapa vecinas: la anterior acaba en 10,3 s y el short empieza en
    # 10,1; el short acaba en 74,8 y la siguiente empieza en 74,5.
    def frase(inicio: float, fin: float, n: int) -> shorts.Frase:
        paso = (fin - inicio) / n
        return shorts.Frase([Palabra(f"p{inicio}-{i}", inicio + i * paso,
                                     inicio + (i + 1) * paso) for i in range(n)])

    frases = [frase(0.0, 10.3, 4), frase(10.1, 42.0, 16), frase(42.0, 74.8, 16),
              frase(74.5, 90.0, 4)]
    palabras = [p for f in frases[1:3] for p in f.palabras]
    c = shorts.validar({"candidatos": [_cand(2, 3)]}, frases, duracion=90.0)[0]
    assert c.descarte == ""
    assert c.inicio <= frases[1].inicio and c.fin >= frases[2].fin
    assert len(shorts.tramo_palabras(palabras, c.inicio, c.fin)) == len(palabras) == 32


def test_validar_sin_lista_falla():
    frases = _frases_de(10, 10)
    for datos in ({}, {"candidatos": "no"}, {"candidatos": None}):
        with pytest.raises(PasoFallido):
            shorts.validar(datos, frases, duracion=100.0)


def _nota(ini: float, fin: float, interes: float, indep: float,
          frases: tuple[int, int] | None = None) -> shorts.Candidato:
    # Por defecto cada nota tiene sus propias frases (según su inicio): solo se
    # pisan las que comparten alguna.
    f_ini, f_fin = frases or (int(ini) + 1, int(ini) + 2)
    return shorts.Candidato(f_ini, f_fin, "t", "m", inicio=ini, fin=fin,
                            interes=interes, independiente=indep)


def test_elegir_umbrales_orden_solapes_y_maximo():
    flojo = _nota(0, 70, 1.9, 0.9)
    no_solo = _nota(100, 170, 3.0, 0.29)
    mejor = _nota(200, 270, 3.5, 0.9)
    solapa = _nota(250, 320, 3.0, 0.8, frases=(202, 203))  # comparte la 202
    segundo = _nota(400, 470, 2.5, 0.8)
    de_mas = _nota(500, 570, 2.0, 0.7)
    todos = [flojo, no_solo, solapa, de_mas, segundo, mejor]
    elegidos = shorts.elegir(todos, maximo=2, duracion=3000)
    assert elegidos == [mejor, segundo]
    assert [c.descarte for c in (flojo, no_solo, mejor, solapa, segundo, de_mas)] == [
        "flojo", "no_se_entiende_solo", "", "solapa", "", "sobra",
    ]


def test_elegir_acepta_se_entiende_solo_desde_0_3():
    # `tev1` 4B puntúa más bajo que 0.8B en esta pregunta: con 0,5 caían trozos buenos.
    justo = _nota(0, 70, 3.0, 0.3)
    assert shorts.elegir([justo], maximo=1, duracion=600) == [justo]


def test_elegir_desempata_por_independiente_y_luego_inicio():
    a = _nota(0, 70, 3.0, 0.6)
    b = _nota(100, 170, 3.0, 0.9)
    c = _nota(200, 270, 3.0, 0.9)
    assert shorts.elegir([a, c, b], maximo=3, duracion=3000) == [b, c, a]


def test_elegir_deja_tocarse_los_extremos_y_ignora_los_ya_descartados():
    a = _nota(0, 70, 3.0, 0.9)
    b = _nota(70, 140, 2.5, 0.9)  # empieza donde acaba `a`: no se pisan
    ya = _nota(0, 70, 4.0, 1.0)
    ya.descarte = "duracion"
    assert shorts.elegir([ya, a, b], maximo=5, duracion=3000) == [a, b]
    assert ya.descarte == "duracion"


def test_elegir_frases_contiguas_no_se_solapan():
    # Dos shorts seguidos, con 0,2 s entre la frase 8 y la 9: los cortes con
    # margen se pisan, pero no comparten ninguna frase.
    frases, t = [], 0.0
    for f in range(16):
        if f == 8:
            t += 0.2
        frases.append(shorts.Frase([Palabra("a", t, t + 10.0)]))
        t += 10.0
    a, b = shorts.validar({"candidatos": [_cand(1, 8), _cand(9, 16)]}, frases,
                          duracion=t)
    assert a.fin > b.inicio
    a.interes, a.independiente = 3.0, 0.9
    b.interes, b.independiente = 2.5, 0.9
    assert shorts.elegir([a, b], maximo=2, duracion=3000) == [a, b]
    assert (a.descarte, b.descarte) == ("", "")


def test_elegir_sin_notas_no_pasa():
    sin_notas = shorts.Candidato(1, 2, "t", "m", inicio=0.0, fin=70.0)
    assert shorts.elegir([sin_notas], maximo=3, duracion=3000) == []
    assert sin_notas.descarte == "flojo"


def test_elegir_reparte_por_tramos():
    buenos = [_nota(120 + 100 * k, 190 + 100 * k, 3.5 - 0.1 * k, 0.9)
              for k in range(4)]
    lejano = _nota(2100, 2170, 2.0, 0.9)
    elegidos = shorts.elegir(buenos + [lejano], maximo=2, duracion=3000)
    assert elegidos == [buenos[0], lejano]
    assert [c.descarte for c in buenos[1:]] == ["sobra"] * 3


def test_elegir_primera_vuelta_recorta_a_maximo():
    a = _nota(100, 170, 3.5, 0.9)
    b = _nota(700, 770, 3.0, 0.9)
    c = _nota(1300, 1370, 2.5, 0.9)
    assert shorts.elegir([c, b, a], maximo=2, duracion=3000) == [a, b]
    assert c.descarte == "sobra"


def test_elegir_empate_gana_el_mas_largo():
    a = _nota(100, 170, 3.0, 0.9, frases=(10, 12))
    b = _nota(100, 270, 2.8, 0.9, frases=(11, 13))
    assert shorts.elegir([a, b], maximo=2, duracion=3000) == [b]
    assert a.descarte == "solapa"
    a = _nota(100, 170, 3.0, 0.9, frases=(10, 12))
    b = _nota(100, 270, 2.6, 0.9, frases=(11, 13))
    assert shorts.elegir([a, b], maximo=2, duracion=3000) == [a]
    assert b.descarte == "solapa"


def test_elegir_primera_vuelta_el_mas_largo_gana_en_su_tramo():
    a = _nota(100, 170, 3.0, 0.9, frases=(10, 12))
    b = _nota(100, 270, 2.8, 0.9, frases=(11, 13))
    assert shorts.elegir([a, b], maximo=1, duracion=3000) == [b]
    assert (a.descarte, b.descarte) == ("solapa", "")


def test_elegir_cadena_de_reemplazos_no_se_aleja_del_mejor():
    a = _nota(100, 170, 3.0, 0.9, frases=(10, 12))
    b = _nota(100, 220, 2.8, 0.9, frases=(11, 13))
    c = _nota(100, 270, 2.6, 0.9, frases=(12, 14))
    assert shorts.elegir([a, b, c], maximo=1, duracion=3000) == [b]
    assert (a.descarte, c.descarte) == ("solapa", "solapa")


def test_elegir_reemplazo_entre_tramos_libera_el_tramo_del_sustituido():
    a = _nota(100, 170, 3.0, 0.9, frases=(10, 12))  # tramo 0
    b = _nota(700, 870, 2.8, 0.9, frases=(11, 13))  # tramo 1, más largo: sustituye a `a`
    c = _nota(200, 270, 2.5, 0.9, frases=(50, 51))  # tramo 0, debe entrar en la 1.ª vuelta
    d = _nota(1300, 1370, 2.2, 0.9, frases=(90, 91))  # tramo 2
    assert shorts.elegir([a, b, c, d], maximo=2, duracion=3000) == [b, c]
    assert (a.descarte, d.descarte) == ("solapa", "sobra")


def test_elegir_segunda_vuelta_rellena():
    a = _nota(100, 170, 3.5, 0.9)
    b = _nota(200, 270, 3.0, 0.9)
    c = _nota(700, 770, 2.5, 0.9)
    assert shorts.elegir([a, b, c], maximo=3, duracion=3000) == [a, b, c]


def test_elegir_hasta_tres_por_tramo():
    buenos = [_nota(100 * k, 100 * k + 70, 3.5 - 0.1 * k, 0.9) for k in range(4)]
    elegidos = shorts.elegir(buenos, maximo=shorts.maximo_shorts(1800), duracion=1800)
    assert elegidos == buenos[:3]
    assert buenos[3].descarte == "sobra"


def test_elegir_cada_tramo_aporta_lo_que_pasa_la_nota():
    solo = _nota(100, 170, 3.0, 0.9)
    flojo = _nota(300, 370, 1.5, 0.9)
    otros = [_nota(700 + 100 * k, 770 + 100 * k, 3.4 - 0.1 * k, 0.9) for k in range(3)]
    elegidos = shorts.elegir([solo, flojo] + otros, maximo=9, duracion=1800)
    assert elegidos == otros + [solo]
    assert flojo.descarte == "flojo"


def test_elegir_segunda_vuelta_no_llena_de_mas_el_tramo_del_largo():
    # El tramo 0 ya tiene 3; `c` (tramo 0, más largo) no puede sustituir a `e`
    # (tramo 1): el tramo 0 pasaría a tener 4.
    llenos = [_nota(100 * k, 100 * k + 70, 3.5 - 0.1 * k, 0.9, frases=(10 * k + 1, 10 * k + 2))
              for k in range(3)]
    e = _nota(605, 675, 3.0, 0.9, frases=(60, 61))
    c = _nota(590, 760, 2.9, 0.9, frases=(59, 61))
    elegidos = shorts.elegir(llenos + [e, c], maximo=9, duracion=1800)
    assert elegidos == llenos + [e]
    assert c.descarte == "solapa"


def test_elegir_segunda_vuelta_cambia_entre_tramos_si_el_del_sustituido_tiene_otro():
    a = _nota(100, 170, 3.5, 0.9, frases=(1, 2))
    e1 = _nota(700, 770, 3.2, 0.9, frases=(70, 71))  # tramo 1
    e = _nota(605, 675, 3.0, 0.9, frases=(60, 61))  # tramo 1, el segundo
    c = _nota(590, 760, 2.9, 0.9, frases=(59, 61))  # tramo 0, más largo, pisa a `e`
    elegidos = shorts.elegir([a, e1, e, c], maximo=6, duracion=1200)
    assert elegidos == [a, e1, c]
    assert e.descarte == "solapa"


def test_elegir_segunda_vuelta_no_deja_sin_short_el_tramo_del_sustituido():
    a = _nota(100, 170, 3.5, 0.9, frases=(1, 2))
    e = _nota(605, 675, 3.0, 0.9, frases=(60, 61))  # único del tramo 1
    c = _nota(590, 760, 2.9, 0.9, frases=(59, 61))  # tramo 0, más largo, pisa a `e`
    elegidos = shorts.elegir([a, e, c], maximo=6, duracion=1200)
    assert elegidos == [a, e]
    assert c.descarte == "solapa"


def test_nombre_archivo_limpia_el_titulo():
    assert shorts.nombre_archivo(3, 'IA: ¿qué/cómo? "ya" ') == "03 - IA ¿qué cómo ya"
    assert shorts.nombre_archivo(1, " ... ") == "01 - Short"
    assert shorts.nombre_archivo(2, "a\tb\x00c\\d|e") == "02 - a b c d e"
    # Cortado a 60 caracteres justo en un espacio: no queda colgando.
    assert shorts.nombre_archivo(12, "x" * 59 + " yy") == "12 - " + "x" * 59
    assert len(shorts.nombre_archivo(12, "x" * 200)) == len("12 - ") + 60


def test_tramo_palabras_desplaza():
    palabras = [Palabra("a", 1.0, 2.0), Palabra("b", 10.0, 11.0),
                Palabra("c", 12.0, 13.0), Palabra("d", 14.5, 16.0)]
    tramo = shorts.tramo_palabras(palabras, 10.0, 15.0)
    assert tramo == [Palabra("b", 0.0, 1.0), Palabra("c", 2.0, 3.0)]
    assert palabras[1].inicio == 10.0  # no toca las originales


def _chat_falso(monkeypatch, respuestas):
    """Sustituye `chat_json`; `respuestas` es un dict fijo o una lista (una por llamada)."""
    llamadas = []

    def falso(modelo, mensajes, esquema, **kw):
        llamadas.append({"modelo": modelo, "mensajes": mensajes,
                         "esquema": esquema, **kw})
        if isinstance(respuestas, list):
            return respuestas[len(llamadas) - 1]
        return respuestas

    monkeypatch.setattr(shorts, "chat_json", falso)
    return llamadas


def _tev1(si: float, score: float) -> dict:
    """Respuesta de `tev1` con las tres partes del interés a la misma nota."""
    return {
        "independiente": {"type": "choice", "choice": "si",
                          "probabilities": {"si": si, "no": 1 - si}},
        **{parte: {"type": "score", "score": score,
                   "probabilities": {"0": 0.1, "1": 0.2}}
           for parte in shorts.PARTES_INTERES},
    }


def test_esquema_candidatos_exige_todos_los_campos():
    item = shorts.ESQUEMA_CANDIDATOS["properties"]["candidatos"]["items"]
    assert shorts.ESQUEMA_CANDIDATOS["required"] == ["candidatos"]
    assert sorted(item["required"]) == ["frase_fin", "frase_inicio", "motivo", "titulo"]
    assert item["properties"]["frase_inicio"]["type"] == "integer"
    assert item["properties"]["titulo"]["type"] == "string"


def test_nota_juez_interes_es_la_media_de_las_partes(monkeypatch):
    respuesta = {
        "independiente": {"type": "choice", "choice": "si", "probabilities": {
            "si": 0.6563623509207749, "no": 0.34363764907922517}},
        "gancho": {"type": "score", "score": 3.5},
        "valor": {"type": "score", "score": 1.0},
        "publico": {"type": "score", "score": 3.0},
    }
    pedidos = []

    def falso(modelo, estado, preguntas, **kw):
        pedidos.append((modelo, estado, preguntas))
        return respuesta

    monkeypatch.setattr(shorts, "systemone", falso)
    assert shorts.nota_juez("un fragmento", "Hablo a pymes") == (
        pytest.approx(0.6563623509207749), pytest.approx(2.5))
    assert pedidos == [("tev1:4b-nvfp4", "un fragmento",
                        shorts.preguntas_juez("Hablo a pymes"))]


def test_preguntas_juez_llevan_la_marca_solo_en_publico():
    con = shorts.preguntas_juez("  Hablo a dueños de pymes.  ")
    sin = shorts.preguntas_juez("   ")
    assert list(con) == ["independiente", *shorts.PARTES_INTERES]
    assert "Hablo a dueños de pymes." in con["publico"]["instructions"]
    assert "marca" not in sin["publico"]["instructions"]
    assert {k: v for k, v in con.items() if k != "publico"} == {
        k: v for k, v in sin.items() if k != "publico"}


def test_preguntas_juez_recortan_una_marca_enorme():
    # `tev1` responde 400 si el trozo y la pregunta pasan de su num_ctx (2048).
    publico = shorts.preguntas_juez("x" * 10_000)["publico"]["instructions"]
    assert publico.count("x") <= shorts.MAX_MARCA + 5


@pytest.mark.parametrize("respuesta", [
    {"gancho": {}},
    {},
    {"independiente": {"probabilities": {"si": "mucho"}},
     "gancho": {"score": 3.0}, "valor": {"score": 3.0}, "publico": {"score": 3.0}},
])
def test_nota_juez_forma_inesperada_falla(monkeypatch, respuesta):
    monkeypatch.setattr(shorts, "systemone", lambda *a, **kw: respuesta)
    with pytest.raises(PasoFallido, match="tev1:4b-nvfp4"):
        shorts.nota_juez("texto")


def _para_puntuar():
    frases = _frases_de(20, 10)
    a = shorts.Candidato(1, 8, "a", "m")
    b = shorts.Candidato(9, 16, "b", "m")
    descartado = shorts.Candidato(1, 2, "c", "m", descarte="duracion")
    texto = lambda c: " ".join(f.texto for f in frases[c.frase_inicio - 1:c.frase_fin])
    return frases, a, b, descartado, texto


def test_puntuar_con_tev1(monkeypatch):
    frases, a, b, descartado, texto = _para_puntuar()
    estados = []

    def falso(modelo, estado, preguntas, **kw):
        estados.append(estado)
        return _tev1(0.9, 3.5) if len(estados) == 1 else _tev1(0.4, 1.5)

    monkeypatch.setattr(shorts, "systemone", falso)
    llamadas = _chat_falso(monkeypatch, {})
    avisos, porcentajes = [], []
    juez = shorts.puntuar([a, b, descartado], frases, avisos.append, porcentajes.append)
    assert juez == "tev1:4b-nvfp4"
    assert (a.independiente, a.interes) == (pytest.approx(0.9), pytest.approx(3.5))
    assert (b.independiente, b.interes) == (pytest.approx(0.4), pytest.approx(1.5))
    assert (descartado.independiente, descartado.interes) == (None, None)
    assert estados == [texto(a), texto(b)]
    assert llamadas == [] and avisos == []
    assert porcentajes == [50.0, 100.0]


def test_jueces_son_modelos_de_decision_en_orden():
    assert shorts.JUECES == (
        "tev1:4b-nvfp4", "pplx-decider-flash:4b-nvfp4", "nimble-v3:9b-nvfp4")
    assert shorts.JUEZ == shorts.JUECES[0]


@pytest.mark.parametrize("caidos", [1, 2])
def test_puntuar_baja_a_la_reserva_y_repuntua_todo(monkeypatch, caidos):
    frases, a, b, descartado, texto = _para_puntuar()
    pedidos = []
    reserva = shorts.JUECES[caidos]

    def falso(modelo, estado, preguntas, **kw):
        pedidos.append((modelo, estado))
        # Los anteriores fallan en el segundo trozo, con el primero ya puntuado.
        if modelo != reserva:
            if [m for m, _ in pedidos].count(modelo) == 2:
                raise PasoFallido(f"Modelo no descargado: {modelo}")
            return _tev1(0.1, 0.5)
        return _tev1(0.7, 2.5)

    monkeypatch.setattr(shorts, "systemone", falso)
    llamadas = _chat_falso(monkeypatch, {})
    avisos = []
    assert shorts.puntuar([a, b, descartado], frases, avisos.append) == reserva
    # Todos con el mismo juez, también el primero: sin mezclar escalas.
    assert (a.independiente, a.interes) == (pytest.approx(0.7), pytest.approx(2.5))
    assert (b.independiente, b.interes) == (pytest.approx(0.7), pytest.approx(2.5))
    assert pedidos == [(m, texto(c)) for m in shorts.JUECES[:caidos + 1] for c in (a, b)]
    assert len(avisos) == caidos
    assert shorts.JUECES[caidos - 1] in avisos[-1] and reserva in avisos[-1]
    assert llamadas == []


def test_puntuar_sin_juez_falla_claro_y_no_recurre_a_un_llm(monkeypatch):
    frases, a, b, descartado, texto = _para_puntuar()

    def sin_modelo(modelo, estado, preguntas, **kw):
        raise PasoFallido(f"Modelo no descargado: {modelo}")

    monkeypatch.setattr(shorts, "systemone", sin_modelo)
    llamadas = _chat_falso(monkeypatch, {})
    with pytest.raises(PasoFallido) as e:
        shorts.puntuar([a, b], frases, lambda aviso: None)
    for juez in shorts.JUECES:
        assert f"ollama pull {juez}" in str(e.value)
    assert llamadas == []


def test_puntuar_sin_candidatos_vivos_no_llama_a_nadie(monkeypatch):
    frases, a, b, descartado, texto = _para_puntuar()

    def prohibido(*args, **kw):
        raise AssertionError("no debe llamar a Ollama")

    monkeypatch.setattr(shorts, "systemone", prohibido)
    monkeypatch.setattr(shorts, "chat_json", prohibido)
    assert shorts.puntuar([descartado], frases, lambda aviso: None) == shorts.JUEZ


# --- crear --------------------------------------------------------------------

LINEA = "base-recortada"
# Lo que propone el modelo, desordenado: el mejor (11-18), el segundo (25-32),
# uno que solapa al mejor (15-22) y uno de 20 s.
PROPUESTOS = [
    _cand(25, 32, titulo="El segundo"), _cand(15, 22, titulo="Solapado"),
    _cand(11, 18, titulo="El mejor trozo"), _cand(35, 36, titulo="Corto"),
]
MEJOR, SEGUNDO = "01 - El mejor trozo", "02 - El segundo"


def _palabras_charla() -> list[Palabra]:
    """40 frases de 10 s: la frase k son diez palabras «fk» de 1 s, con punto."""
    return [Palabra(f"f{k}" + ("." if i == 9 else ""), (k - 1) * 10.0 + i,
                    (k - 1) * 10.0 + i + 1)
            for k in range(1, 41) for i in range(10)]


def _comandos_cara() -> str:
    """Una orden cada 10 s con la x igual al segundo."""
    return "".join(f"{t:.3f} crop@v x {t};\n" for t in range(0, 400, 10))


@pytest.fixture()
def ficha_con_base(tmp_path, monkeypatch):
    """Ficha recortada (base aparte), con su transcripción y todo lo caro falso."""
    monkeypatch.setattr(modulo_ficha, "DIR_FICHAS", tmp_path / "fichas")
    original = tmp_path / "charla.mov"
    original.write_bytes(b"VID")
    salida = tmp_path / "salida"
    salida.mkdir()
    final = salida / "charla_limpio.mp4"
    final.write_bytes(b"FINAL")
    ficha = Ficha(
        id="f1", nombre="charla", carpeta_salida=salida,
        original=Huella.de(original), final=Huella.de(final),
        artefactos={
            BASE: Artefacto("b", "base.mp4", {"silencios": {}}, LINEA),
            HORIZONTAL: Artefacto("h"),
            TRANSCRIPCION: Artefacto("t", "transcripcion.json", {}, LINEA),
        })
    ficha.carpeta.mkdir(parents=True)
    ficha.ruta("base.mp4").write_bytes(b"BASE")
    _escribir_json(ficha.ruta("transcripcion.json"),
                   [asdict(p) for p in _palabras_charla()])
    guardar(ficha)

    e = SimpleNamespace(
        ficha=ficha, config=PipelineConfig(video=original, caption_seo=True),
        carpeta=salida / "charla", cortes=[], captions=[], caras=[],
        falla_corte=None,  # número de la llamada a convertir_vertical que falla
        preguntas=[],  # las que ha recibido el juez
        titulos=[],  # (texto, idioma, modelo, ¿Ollama arrancado?) de cada generar_titulo
        titulo_modelo="Título del tramo",  # lo que devuelve generar_titulo; None si falla
        servidor_abierto=False,
        notas={"f11": (0.9, 3.5), "f25": (0.8, 2.5), "f15": (0.9, 3.0)},
    )

    class ServidorFalso:
        def __init__(self):
            e.servidor_abierto = True

        def cerrar(self):
            e.servidor_abierto = False

    def falso_convertir(video, salida_, filtro, cwd, usa_ass, desde_original=False,
                        on_percent=None, tramo=None, banner=None):
        comandos, ass = cwd / "cara.cmd", cwd / "subs_vertical.ass"
        e.cortes.append({"video": video, "tramo": tramo, "filtro": filtro,
                         "banner": banner and Image.open(banner).size,
                         "usa_ass": usa_ass, "desde_original": desde_original,
                         "cara": comandos.read_text() if comandos.is_file() else None,
                         "ass": ass.read_text(encoding="utf-8") if ass.is_file() else None})
        if e.falla_corte == len(e.cortes):
            raise PasoFallido("ffmpeg explotó")
        salida_.write_bytes(b"SHORT")

    def falso_seguimiento(video, ancho, alto, ruta_cmd, on_percent=None,
                          detector=None):
        e.caras.append(video)
        ruta_cmd.write_text(_comandos_cara())
        return 0

    def falso_caption(transcripcion, contexto_marca, modelo, cliente=None,
                      idioma="es", terminos=()):
        e.captions.append(transcripcion)
        return Caption(titulo="T", caption="C", hashtags=["#a"],
                       palabras_clave=["k"])

    def falso_titulo(transcripcion, idioma, modelo, cliente=None):
        e.titulos.append((transcripcion, idioma, modelo, e.servidor_abierto))
        return e.titulo_modelo

    def falso_tev1(modelo, texto, preguntas, **kw):
        e.preguntas.append(preguntas)
        si, score = e.notas.get(texto.split()[0], (0.9, 1.0))
        return _tev1(si, score)

    monkeypatch.setattr(shorts, "duracion_video", lambda video: 1200.0)
    monkeypatch.setattr(shorts, "asegurar_servidor", ServidorFalso)
    def falso_chat(modelo, mensajes, esquema, **kw):
        if esquema is shorts.ESQUEMA_TEMAS:  # un solo tema, de 400 s
            return {"temas": [{"frase_inicio": 1, "titulo": "Charla",
                               "sigue_al_anterior": False}]}
        if len(mensajes) > 2:  # la corrección de una duración mala: sin cambios
            return {"candidatos": []}
        return {"candidatos": PROPUESTOS}

    monkeypatch.setattr(shorts, "chat_json", falso_chat)
    monkeypatch.setattr(shorts, "descargar", lambda modelo: None)
    monkeypatch.setattr(shorts, "systemone", falso_tev1)
    monkeypatch.setattr(shorts, "generar_titulo", falso_titulo)
    monkeypatch.setattr(pipeline, "convertir_vertical", falso_convertir)
    monkeypatch.setattr(pipeline, "asegurar_servidor", ServidorFalso)
    monkeypatch.setattr(pipeline, "generar_caption", falso_caption)
    for modulo in (pipeline, reproceso, shorts):
        monkeypatch.setattr(modulo, "resolucion_video", lambda video: (1920, 1080))
    monkeypatch.setattr(reproceso, "preparar_seguimiento", falso_seguimiento)
    return e


def _crear(e, opciones=None, eventos=None):
    recibidos = [] if eventos is None else eventos
    return shorts.crear(e.ficha, e.config, opciones or shorts.OpcionesShorts(),
                        recibidos.append)


def test_crear_pregunta_al_juez_con_el_contexto_de_marca(ficha_con_base):
    e = ficha_con_base
    e.config = PipelineConfig(video=e.config.video, contexto_marca="Hablo a pymes")
    _crear(e)
    assert e.preguntas and all(
        p == shorts.preguntas_juez("Hablo a pymes") for p in e.preguntas)


def _leer_json(ruta):
    return json.loads(ruta.read_text(encoding="utf-8"))


def test_opciones_shorts_de_datos():
    assert shorts.OpcionesShorts.de_datos({}) == shorts.OpcionesShorts(True, "cara")
    assert shorts.OpcionesShorts.de_datos(
        {"subtitulos": False, "encuadre": "barras"}) == shorts.OpcionesShorts(
        False, "barras")
    assert shorts.OpcionesShorts.de_datos({"banner": "/b/banner.png"}).banner == Path(
        "/b/banner.png")
    assert shorts.OpcionesShorts.de_datos({"banner": None}).banner is None
    with pytest.raises(ValueError, match="encuadre"):
        shorts.OpcionesShorts.de_datos({"encuadre": "zoom"})


def test_crear_escribe_la_carpeta_ordenada_y_el_json(ficha_con_base):
    e = ficha_con_base
    eventos = []
    resultado = _crear(e, eventos=eventos)

    assert resultado == shorts.Resultado(e.carpeta, 2)
    archivos = [f"{stem}{sufijo}" for stem in (MEJOR, SEGUNDO)
                for sufijo in (".mp4", ".srt", ".md")]
    assert sorted(p.name for p in e.carpeta.iterdir()) == sorted(
        archivos + ["shorts.json"])
    datos = _leer_json(e.carpeta / "shorts.json")
    assert (datos["version"], datos["ficha"], datos["video"], datos["juez"],
            datos["maximo"]) == (2, "f1", "charla", "tev1:4b-nvfp4", 6)
    assert [t["titulo"] for t in datos["temas"]] == ["Charla"]
    assert {c["origen"] for c in datos["candidatos"]} == {"fragmento"}
    assert datos["archivos"] == archivos
    assert [(c["titulo"], c["descarte"], c["archivo"]) for c in datos["candidatos"]] == [
        ("El mejor trozo", "", MEJOR + ".mp4"), ("El segundo", "", SEGUNDO + ".mp4"),
        ("Solapado", "solapa", ""), ("Corto", "duracion", ""),
    ]
    assert datos["candidatos"][0]["interes"] == pytest.approx(3.5)
    assert not (e.carpeta / shorts.TMP).exists()
    # La cara se detectó una vez sobre la base y queda en la ficha.
    assert e.caras == [e.ficha.ruta("base.mp4")]
    assert (cargar("f1").artefactos[SEGUIMIENTO].clave
            == clave_seguimiento(LINEA))
    etiquetas = [ev["label"] for ev in eventos if "step" in ev]
    propias = etiquetas[etiquetas.index("Buscando temas"):]
    assert list(dict.fromkeys(propias)) == [
        "Buscando temas", "Buscando los mejores momentos", "Puntuando los trozos",
        "Generando título", "Creando short 1 de 2", "Creando short 2 de 2"]
    assert [ev["warning"] for ev in eventos if "warning" in ev] == []


def test_crear_corta_cada_tramo_con_subtitulos_desde_cero(ficha_con_base):
    e = ficha_con_base
    _crear(e)

    assert [c["tramo"] for c in e.cortes] == [(100.0, 180.0), (240.0, 320.0)]
    assert all(c["video"] == e.ficha.ruta("base.mp4") and c["usa_ass"]
               and not c["desde_original"] for c in e.cortes)
    srt = (e.carpeta / f"{MEJOR}.srt").read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:00,000 --> ")
    # El caption de cada short es el de su trozo.
    assert e.captions[0].split()[0] == "f11" and "f10" not in e.captions[0]
    assert e.captions[1].split()[0] == "f25"


def _eventos_del_titulo(texto):
    return lineas_titulo(texto, (1080, 1920))[1]


def test_crear_quema_el_titulo_del_short(ficha_con_base):
    e = ficha_con_base
    _crear(e)

    # El texto es el del tramo de cada short, y Ollama sigue arrancado.
    assert [(t.split()[0], i, m, abierto) for t, i, m, abierto in e.titulos] == [
        ("f11", "es", e.config.modelo_caption, True),
        ("f25", "es", e.config.modelo_caption, True)]
    assert "f10" not in e.titulos[0][0]
    assert e.servidor_abierto is False
    # Los eventos de `lineas_titulo` están en el `.ass` de cada corte, de 0 a 5 s.
    eventos = _eventos_del_titulo("Título del tramo")
    assert len(eventos) == 2 and all("0:00:00.00,0:00:05.00" in ev for ev in eventos)
    assert all(c["usa_ass"] and all(ev in c["ass"] for ev in eventos)
               for c in e.cortes)
    # El nombre de archivo sigue siendo el del candidato; el JSON guarda lo quemado.
    assert (e.carpeta / f"{MEJOR}.mp4").is_file()
    candidatos = _leer_json(e.carpeta / "shorts.json")["candidatos"]
    assert [(c["archivo"], c["titulo_video"]) for c in candidatos] == [
        (MEJOR + ".mp4", "Título del tramo"), (SEGUNDO + ".mp4", "Título del tramo"),
        ("", ""), ("", "")]


def test_crear_sin_titulo_del_modelo_usa_el_del_candidato(ficha_con_base):
    e = ficha_con_base
    e.titulo_modelo = None

    _crear(e)

    for corte, titulo in zip(e.cortes, ("El mejor trozo", "El segundo")):
        assert all(ev in corte["ass"] for ev in _eventos_del_titulo(titulo))
    candidatos = _leer_json(e.carpeta / "shorts.json")["candidatos"]
    assert [c["titulo_video"] for c in candidatos[:2]] == ["El mejor trozo",
                                                           "El segundo"]


def test_crear_quema_el_titulo_sin_subtitulos(ficha_con_base):
    e = ficha_con_base

    _crear(e, shorts.OpcionesShorts(subtitulos=False))

    eventos = _eventos_del_titulo("Título del tramo")
    for corte in e.cortes:
        assert corte["usa_ass"] and "ass=subs_vertical.ass" in corte["filtro"]
        # Solo el título: sus dos eventos y ninguno de subtítulos.
        assert [linea for linea in corte["ass"].splitlines()
                if linea.startswith("Dialogue:")] == eventos
    assert not list(e.carpeta.glob("*.srt"))


def test_crear_sustituye_solo_lo_que_lista_el_json_anterior(ficha_con_base):
    e = ficha_con_base
    e.carpeta.mkdir()
    (e.carpeta / "01 - Viejo.mp4").write_bytes(b"VIEJO")
    (e.carpeta / "notas.txt").write_text("del usuario")
    (e.carpeta.parent / "fuera.txt").write_text("del usuario")
    (e.carpeta / "shorts.json").write_text(json.dumps(
        {"ficha": "f1",
         "archivos": ["01 - Viejo.mp4", "../fuera.txt", "..", ".", "", 7]}))

    assert _crear(e).n == 2

    assert not (e.carpeta / "01 - Viejo.mp4").exists()
    assert (e.carpeta / "notas.txt").read_text() == "del usuario"
    assert (e.carpeta.parent / "fuera.txt").read_text() == "del usuario"
    assert (e.carpeta / f"{MEJOR}.mp4").is_file()


def test_crear_borra_el_registro_de_publicacion_de_los_shorts_viejos(ficha_con_base):
    e = ficha_con_base
    e.carpeta.mkdir()
    # Un viejo con otro nombre y otro con el nombre de uno nuevo: ninguno
    # debe dejar un «ya publicado» al que herede el short nuevo.
    for nombre in ("01 - Viejo", MEJOR):
        (e.carpeta / f"{nombre}.mp4").write_bytes(b"VIEJO")
        (e.carpeta / f"{nombre}.publicado.json").write_text("{}")
    (e.carpeta / "ajeno.publicado.json").write_text("{}")
    (e.carpeta / "shorts.json").write_text(json.dumps(
        {"ficha": "f1", "archivos": ["01 - Viejo.mp4", f"{MEJOR}.mp4"]}))

    _crear(e)

    assert not (e.carpeta / "01 - Viejo.publicado.json").exists()
    assert not (e.carpeta / f"{MEJOR}.publicado.json").exists()
    assert (e.carpeta / "ajeno.publicado.json").exists()  # no lo listaba el json


_DE_OTRA_FICHA = [
    {"ficha": "otra", "archivos": ["01 - Viejo.mp4", f"{MEJOR}.mp4"]},
    {"archivos": ["01 - Viejo.mp4", f"{MEJOR}.mp4"]},
]


@pytest.mark.parametrize("viejo", _DE_OTRA_FICHA, ids=["otra_ficha", "sin_ficha"])
def test_crear_no_se_fia_del_json_de_otra_ficha(ficha_con_base, viejo):
    e = ficha_con_base
    e.carpeta.mkdir()
    (e.carpeta / "01 - Viejo.mp4").write_bytes(b"VIEJO")
    (e.carpeta / f"{MEJOR}.mp4").write_bytes(b"MIO")
    (e.carpeta / "shorts.json").write_text(json.dumps(viejo))

    # Lo que lista ese json no se da por de la app: un nombre repetido frena.
    with pytest.raises(PasoFallido, match="no lo creó la app"):
        _crear(e)

    assert (e.carpeta / "01 - Viejo.mp4").read_bytes() == b"VIEJO"
    assert (e.carpeta / f"{MEJOR}.mp4").read_bytes() == b"MIO"
    assert e.cortes == []


@pytest.mark.parametrize("viejo", _DE_OTRA_FICHA, ids=["otra_ficha", "sin_ficha"])
def test_crear_con_el_json_de_otra_ficha_no_borra_nada(ficha_con_base, viejo):
    e = ficha_con_base
    e.carpeta.mkdir()
    (e.carpeta / "01 - Viejo.mp4").write_bytes(b"VIEJO")
    (e.carpeta / "shorts.json").write_text(json.dumps(viejo))

    assert _crear(e).n == 2

    assert (e.carpeta / "01 - Viejo.mp4").read_bytes() == b"VIEJO"
    datos = _leer_json(e.carpeta / "shorts.json")
    assert datos["ficha"] == "f1"
    assert "01 - Viejo.mp4" not in datos["archivos"]


def test_crear_un_fallo_conserva_los_anteriores(ficha_con_base):
    e = ficha_con_base
    e.carpeta.mkdir()
    viejo = json.dumps({"ficha": "f1", "archivos": ["01 - Viejo.mp4"]})
    (e.carpeta / "01 - Viejo.mp4").write_bytes(b"VIEJO")
    (e.carpeta / "shorts.json").write_text(viejo)
    e.falla_corte = 2

    with pytest.raises(PasoFallido, match="ffmpeg explotó"):
        _crear(e)

    assert sorted(p.name for p in e.carpeta.iterdir()) == ["01 - Viejo.mp4",
                                                           "shorts.json"]
    assert (e.carpeta / "shorts.json").read_text() == viejo
    assert (e.carpeta / "01 - Viejo.mp4").read_bytes() == b"VIEJO"


def test_crear_un_fallo_la_primera_vez_no_deja_carpeta(ficha_con_base):
    e = ficha_con_base
    e.falla_corte = 1
    with pytest.raises(PasoFallido):
        _crear(e)
    assert not e.carpeta.exists()

    e.carpeta.mkdir()
    (e.carpeta / "notas.txt").write_text("del usuario")
    e.cortes.clear()
    with pytest.raises(PasoFallido):
        _crear(e)
    assert [p.name for p in e.carpeta.iterdir()] == ["notas.txt"]


def test_crear_un_corte_al_publicar_deja_el_json_con_todo(ficha_con_base,
                                                          monkeypatch):
    e = ficha_con_base
    e.carpeta.mkdir()
    (e.carpeta / "01 - Viejo.mp4").write_bytes(b"VIEJO")
    (e.carpeta / "notas.txt").write_text("del usuario")
    (e.carpeta / "shorts.json").write_text(
        json.dumps({"ficha": "f1", "archivos": ["01 - Viejo.mp4"]}))
    reemplazar = os.replace

    def corte(origen, destino):
        if Path(origen).name == f"{MEJOR}.srt":  # el segundo archivo nuevo
            raise OSError("se fue la luz")
        reemplazar(origen, destino)

    monkeypatch.setattr(os, "replace", corte)
    with pytest.raises(OSError, match="se fue la luz"):
        _crear(e)

    archivos = _leer_json(e.carpeta / "shorts.json")["archivos"]
    assert archivos == ["01 - Viejo.mp4"] + [
        f"{stem}{sufijo}" for stem in (MEJOR, SEGUNDO)
        for sufijo in (".mp4", ".srt", ".md")]
    en_disco = {p.name for p in e.carpeta.iterdir()} - {"shorts.json", "notas.txt"}
    assert en_disco == {f"{MEJOR}.mp4"} and en_disco <= set(archivos)
    assert (e.carpeta / "notas.txt").read_text() == "del usuario"


def test_crear_no_pisa_archivos_ajenos(ficha_con_base):
    e = ficha_con_base
    e.carpeta.mkdir()
    ajeno = e.carpeta / f"{MEJOR}.mp4"
    ajeno.write_bytes(b"MIO")

    with pytest.raises(PasoFallido, match="no lo creó la app"):
        _crear(e)

    assert e.cortes == []
    assert ajeno.read_bytes() == b"MIO"
    assert not (e.carpeta / shorts.TMP).exists()


def test_crear_sin_final_o_sin_base_falla_claro(ficha_con_base):
    e = ficha_con_base
    e.ficha.ruta("base.mp4").unlink()
    with pytest.raises(PasoFallido, match="ya no está"):
        _crear(e)
    e.ficha.final = None
    with pytest.raises(PasoFallido, match="aún no tiene vídeo procesado"):
        _crear(e)
    assert e.cortes == []


def test_crear_subs_quemados_sin_base_falla_claro(ficha_con_base):
    e = ficha_con_base
    del e.ficha.artefactos[BASE]
    e.ficha.original, e.ficha.legado = None, True
    e.ficha.subs_quemados_sin_base = True

    with pytest.raises(PasoFallido, match="lleva los subtítulos quemados"):
        _crear(e)
    assert e.cortes == []


def test_crear_final_cambiado_fuera_falla_claro(ficha_con_base):
    e = ficha_con_base
    e.ficha.artefactos[BASE].archivo = None  # la base es el final
    e.ficha.final.ruta.write_bytes(b"EDITADO FUERA")

    with pytest.raises(PasoFallido, match="ha cambiado fuera de la app"):
        _crear(e)
    assert e.cortes == []


def test_crear_video_corto_falla_claro(ficha_con_base, monkeypatch):
    e = ficha_con_base
    del e.ficha.artefactos[TRANSCRIPCION]
    transcritos = []
    monkeypatch.setattr(reproceso, "_transcribir_subs",
                        lambda *a, **kw: transcritos.append(a))
    monkeypatch.setattr(shorts, "duracion_video", lambda video: 170.0)

    with pytest.raises(PasoFallido, match="dura menos de 3 minutos"):
        _crear(e)
    # Falla antes de lo caro: ni transcribe ni sigue la cara.
    assert transcritos == [] and e.caras == []
    assert e.cortes == [] and not e.carpeta.exists()


def test_crear_transcribe_si_no_hay_transcripcion_de_la_base(ficha_con_base,
                                                            monkeypatch):
    e = ficha_con_base
    del e.ficha.artefactos[TRANSCRIPCION]
    e.ficha.ruta("transcripcion.json").unlink()
    transcritos = []

    def falso_transcribir(config, fuente, final, on_progress, paso, total,
                          degradar, wav_continuo=None):
        transcritos.append(fuente)
        return _palabras_charla(), None

    monkeypatch.setattr(reproceso, "_transcribir_subs", falso_transcribir)
    assert _crear(e).n == 2
    assert transcritos == [e.ficha.ruta("base.mp4")]
    assert cargar("f1").artefactos[TRANSCRIPCION].linea_tiempo == LINEA

    def falla(*args, **kwargs):
        raise PasoFallido("whisper explotó", detalle="falta el modelo")

    del e.ficha.artefactos[TRANSCRIPCION]
    monkeypatch.setattr(reproceso, "_transcribir_subs", falla)
    with pytest.raises(PasoFallido, match="No se pudo transcribir") as error:
        _crear(e)
    # La causa no se pierde.
    assert "whisper explotó" in error.value.detalle
    assert "falta el modelo" in error.value.detalle


def test_crear_cara_recorta_los_comandos_del_tramo(ficha_con_base):
    e = ficha_con_base
    e.ficha.artefactos[SEGUIMIENTO] = Artefacto(
        clave_seguimiento(LINEA), "cara.cmd", {"x_inicial": 0})
    e.ficha.ruta("cara.cmd").write_text(_comandos_cara())

    _crear(e)

    assert e.caras == []  # no se vuelve a detectar
    primero, segundo = e.cortes
    assert primero["cara"].startswith("0.000 crop@v x 100;\n10.000 crop@v x 110;\n")
    assert segundo["cara"].startswith("0.000 crop@v x 240;\n")
    assert all("sendcmd" in c["filtro"] for c in e.cortes)


def test_crear_sin_subtitulos_ni_caption(ficha_con_base):
    e = ficha_con_base
    e.config = replace(e.config, caption_seo=False)

    _crear(e, shorts.OpcionesShorts(subtitulos=False, encuadre="central"))

    assert sorted(p.name for p in e.carpeta.iterdir()) == [
        f"{MEJOR}.mp4", f"{SEGUNDO}.mp4", "shorts.json"]
    assert e.captions == [] and e.caras == []


def test_crear_sin_ninguno_bueno_no_toca_la_carpeta(ficha_con_base):
    e = ficha_con_base
    e.notas = {}  # todos con interés 1
    eventos = []

    assert _crear(e, eventos=eventos) == shorts.Resultado(e.carpeta, 0)

    assert [ev["warning"] for ev in eventos if "warning" in ev] == [
        'Ningún trozo de "charla" es lo bastante bueno para un short: no se ha '
        'creado ninguno.']
    assert not e.carpeta.exists() and e.cortes == []


def test_limpiar_temporal_borra_la_subcarpeta(ficha_con_base):
    e = ficha_con_base
    tmp = e.carpeta / shorts.TMP
    tmp.mkdir(parents=True)
    (tmp / "a medias.mp4").write_bytes(b"x")
    (e.carpeta / "notas.txt").write_text("del usuario")

    shorts.limpiar_temporal(e.ficha)
    shorts.limpiar_temporal(e.ficha)  # sin nada que borrar, tampoco falla

    assert not tmp.exists() and (e.carpeta / "notas.txt").is_file()
    assert shorts.carpeta_shorts(e.ficha) == e.carpeta


def test_limpiar_temporal_quita_la_carpeta_vacia(ficha_con_base):
    """Cancelar mata al runner antes de su limpieza: una primera pasada
    cancelada no debe dejar la carpeta vacía, pero nunca se quita con algo."""
    e = ficha_con_base
    tmp = e.carpeta / shorts.TMP
    tmp.mkdir(parents=True)
    (tmp / "a medias.mp4").write_bytes(b"x")

    shorts.limpiar_temporal(e.ficha)

    assert not e.carpeta.exists()
    shorts.limpiar_temporal(e.ficha)  # ni carpeta ni nada: tampoco falla

    tmp.mkdir(parents=True)
    (e.carpeta / "notas.txt").write_text("del usuario")
    shorts.limpiar_temporal(e.ficha)

    assert not tmp.exists()
    assert (e.carpeta / "notas.txt").read_text() == "del usuario"


def test_hay_shorts(ficha_con_base):
    e = ficha_con_base
    assert not shorts.hay_shorts(e.ficha)
    e.carpeta.mkdir()
    (e.carpeta / "shorts.json").write_text("{}")
    assert shorts.hay_shorts(e.ficha)


# --- Edición: opciones y encolado --------------------------------------------

def test_opciones_editar_y_estilo():
    o = shorts.OpcionesShorts.de_datos({"editar": True, "estilo": "formal"})
    assert o.editar is True and o.estilo == "formal"
    assert shorts.OpcionesShorts.de_datos({}).editar is False
    with pytest.raises(ValueError, match="estilo"):
        shorts.OpcionesShorts.de_datos({"estilo": "neon"})


@pytest.fixture()
def dir_edicion(tmp_path, monkeypatch):
    from videopipeline import edicion
    ruta = tmp_path / "edicion"
    monkeypatch.setattr(edicion, "DIR_EDICION", ruta)
    return ruta


def test_crear_sin_banner_no_lo_quema(ficha_con_base):
    e = ficha_con_base
    _crear(e)
    assert e.cortes and all(c["banner"] is None for c in e.cortes)
    assert all("[1:v]" not in c["filtro"] for c in e.cortes)


def test_crear_con_banner_lo_quema_bajo_los_subtitulos(ficha_con_base, dir_edicion, tmp_path):
    e = ficha_con_base
    banner = banner_sintetico(tmp_path)
    _crear(e, shorts.OpcionesShorts(banner=banner, editar=True))
    imagen, y = banner_vertical(banner, e.config.posicion_subs)
    assert e.cortes and all(c["banner"] == (1080, imagen.height) for c in e.cortes)
    assert all(f"[1:v]overlay=0:{y}," in c["filtro"] for c in e.cortes)
    # La edición con Claude sabe que está ahí: ni zoom ni gráficos lo pisan.
    for t in (dir_edicion / "pendientes").iterdir():
        zonas = _leer_json(t / "trabajo.json")["zonas"]
        assert zonas["graficos_hasta"] <= y and zonas["franja_zoom"][1] <= y


def test_crear_con_un_banner_que_no_esta_falla_antes_de_empezar(ficha_con_base, tmp_path):
    e = ficha_con_base
    with pytest.raises(PasoFallido, match="No se encuentra la imagen del banner"):
        _crear(e, shorts.OpcionesShorts(banner=tmp_path / "borrado.png"))
    assert not e.cortes


def test_crear_sin_editar_no_encola(ficha_con_base, dir_edicion):
    _crear(ficha_con_base)
    assert not (dir_edicion / "pendientes").exists()


def test_crear_con_editar_encola_un_trabajo_por_short(ficha_con_base, dir_edicion):
    e = ficha_con_base
    _crear(e, shorts.OpcionesShorts(editar=True, estilo="formal"))
    trabajos = sorted((dir_edicion / "pendientes").iterdir())
    assert len(trabajos) == 2
    for t in trabajos:
        datos = _leer_json(t / "trabajo.json")
        origen = Path(datos["origen"])
        assert origen.parent == e.carpeta and origen.is_file()
        assert datos["destino"] == str(origen.with_suffix(".editado.mp4"))
        assert datos["origen_tam"] == origen.stat().st_size
        assert datos["origen_mtime"] == origen.stat().st_mtime
        assert datos["estilo"] == "formal" and datos["encuadre"] == "cara"
        assert isinstance(datos["zonas"], dict) and datos["zonas"]
        # con encuadre cara y subtítulos quemados, el zoom no pisa los subtítulos
        zonas = datos["zonas"]
        assert zonas["subtitulos"] is not None
        assert zonas["franja_zoom"][1] <= zonas["subtitulos"][0]
        assert (t / "video.mp4").is_file()
        palabras = _leer_json(t / "palabras.json")
        assert palabras and palabras[0]["inicio"] < 5  # tiempos relativos al short


def test_editar_existentes_encola_los_shorts_ya_creados(ficha_con_base, dir_edicion):
    e = ficha_con_base
    _crear(e)  # sin «Editar con Claude»: nada en cola
    assert not (dir_edicion / "pendientes").exists()
    n = shorts.editar_existentes(
        e.ficha, e.config, shorts.OpcionesShorts(editar=True, estilo="academico"))
    trabajos = sorted((dir_edicion / "pendientes").iterdir())
    assert n == len(trabajos) == 2
    creados = {c["archivo"]: c for c in _leer_json(e.carpeta / "shorts.json")["candidatos"]
               if c["archivo"]}
    palabras = reproceso._Pasada(e.ficha, reproceso.Plan([], e.config, []), None)._palabras()
    for t in trabajos:
        datos = _leer_json(t / "trabajo.json")
        origen = Path(datos["origen"])
        assert origen.parent == e.carpeta and origen.is_file()
        assert datos["estilo"] == "academico" and datos["encuadre"] == "cara"
        assert datos["zonas"]["franja_zoom"][1] <= datos["zonas"]["subtitulos"][0]
        c = creados[origen.name]
        # las mismas palabras que se quemaron como subtítulos de ese short
        esperadas = [asdict(p) for p in shorts.tramo_palabras(palabras, c["inicio"], c["fin"])]
        assert _leer_json(t / "palabras.json") == esperadas


def test_editar_existentes_no_repite_los_que_ya_esperan(ficha_con_base, dir_edicion):
    e = ficha_con_base
    _crear(e)
    opciones = shorts.OpcionesShorts(editar=True)
    assert shorts.editar_existentes(e.ficha, e.config, opciones) == 2
    assert shorts.editar_existentes(e.ficha, e.config, opciones) == 0  # doble clic
    assert len(list((dir_edicion / "pendientes").iterdir())) == 2


def test_editar_existentes_sin_shorts(ficha_con_base, dir_edicion):
    e = ficha_con_base
    with pytest.raises(PasoFallido):
        shorts.editar_existentes(e.ficha, e.config, shorts.OpcionesShorts(editar=True))
    assert not (dir_edicion / "pendientes").exists()


def test_regenerar_borra_editado_viejo(ficha_con_base):
    e = ficha_con_base
    _crear(e)
    mp4 = sorted(e.carpeta.glob("*.mp4"))[0]
    editado = mp4.with_suffix(".editado.mp4")
    tmp = editado.with_name(editado.name + ".tmp")
    editado.write_bytes(b"E")
    tmp.write_bytes(b"T")
    _crear(e)
    assert not editado.exists() and not tmp.exists()


def test_encolar_que_falla_no_rompe_crear(ficha_con_base, dir_edicion, monkeypatch):
    from videopipeline import edicion

    def explota(*a, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(edicion, "encolar", explota)
    resultado = _crear(ficha_con_base, shorts.OpcionesShorts(editar=True))
    assert resultado.n == 2 and len(list(resultado.carpeta.glob("*.mp4"))) == 2


def test_encolar_que_falla_avisa(ficha_con_base, dir_edicion, monkeypatch):
    from videopipeline import edicion
    monkeypatch.setattr(edicion, "encolar",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    eventos = []
    _crear(ficha_con_base, shorts.OpcionesShorts(editar=True), eventos)
    assert any("boom" in str(e) for e in eventos)


def _carpeta_con_corto(tmp_path) -> Path:
    from videopipeline.caption import escribir_md
    escribir_md(Caption("SEO", "Cuerpo", ["#t"], ["k"]), tmp_path / "X.md")
    (tmp_path / "X.mp4").write_bytes(b"MP4")
    (tmp_path / "shorts.json").write_text(json.dumps({"candidatos": [
        {"archivo": "X.mp4", "titulo": "T", "inicio": 0.0, "fin": 30.0}]}))
    return tmp_path


def test_listar_prefiere_editado(tmp_path):
    carpeta = _carpeta_con_corto(tmp_path)
    (carpeta / "X.editado.mp4").write_bytes(b"MP4")
    (corto,) = shorts.listar(carpeta)
    assert corto.mp4.name == "X.editado.mp4" and corto.editado is True
    assert corto.caption.titulo == "SEO"


def test_listar_ignora_editado_mas_viejo_que_el_original(tmp_path):
    carpeta = _carpeta_con_corto(tmp_path)
    editado = carpeta / "X.editado.mp4"
    editado.write_bytes(b"MP4")
    os.utime(editado, (1, 1))
    (corto,) = shorts.listar(carpeta)
    assert corto.mp4.name == "X.mp4" and corto.editado is False


def test_listar_ignora_tmp(tmp_path):
    carpeta = _carpeta_con_corto(tmp_path)
    (carpeta / "X.editado.mp4.tmp").write_bytes(b"MP4")
    (corto,) = shorts.listar(carpeta)
    assert corto.mp4.name == "X.mp4" and corto.editado is False


# --- editar_video: un final que ya es un vertical 1080×1920 ---

def _vertical(monkeypatch, base=(1920, 1080)):
    """El final mide 1080×1920; la base, `base`; ffprobe no se usa."""
    monkeypatch.setattr(
        shorts, "resolucion_video",
        lambda ruta: (1080, 1920) if ruta.name.endswith(("_limpio.mp4", "_vertical.mp4"))
        else base)


def _trabajo_unico(dir_edicion):
    (trabajo,) = (dir_edicion / "pendientes").iterdir()
    return trabajo, _leer_json(trabajo / "trabajo.json")


def test_editar_video_encola_el_final_con_todas_las_palabras(
        ficha_con_base, dir_edicion, monkeypatch):
    e = ficha_con_base
    _vertical(monkeypatch)
    final = e.ficha.final.ruta
    assert shorts.editar_video(e.ficha, e.config,
                               shorts.OpcionesShorts(editar=True, estilo="formal")) == 1
    trabajo, datos = _trabajo_unico(dir_edicion)
    assert datos["origen"] == datos["grupo"] == str(final)
    assert datos["destino"] == str(final.with_suffix(".editado.mp4"))
    assert datos["estilo"] == "formal"
    todas = reproceso._Pasada(e.ficha, reproceso.Plan([], e.config, []), None)._palabras()
    assert _leer_json(trabajo / "palabras.json") == [asdict(p) for p in todas]


def test_zonas_con_los_ajustes_guardados_del_final_horizontal(
        ficha_con_base, dir_edicion, monkeypatch):
    e = ficha_con_base
    _vertical(monkeypatch)
    e.ficha.artefactos[HORIZONTAL].ajustes = {
        "subtitulos": {"diseno": "reels_karaoke", "posicion": 75, "tamano": 150},
        "titulo": "X"}
    e.config = replace(e.config, diseno="reels_bold", posicion_subs=50, tamano_subs=100,
                       subtitulos=False)
    shorts.editar_video(e.ficha, e.config, shorts.OpcionesShorts(editar=True))
    esperadas = shorts.zonas_edicion.calcular(
        replace(e.config, subtitulos=True, diseno="reels_karaoke", posicion_subs=75,
                tamano_subs=150), "central", (1080, 1920), con_titulo=True)
    _, datos = _trabajo_unico(dir_edicion)
    assert datos["zonas"] == esperadas and datos["zonas"]["franja_zoom"] is None


def test_sin_subtitulos_ni_titulo_guardados(ficha_con_base, dir_edicion, monkeypatch):
    e = ficha_con_base
    _vertical(monkeypatch)
    e.ficha.artefactos[HORIZONTAL].ajustes = {}
    e.config = replace(e.config, subtitulos=True)
    shorts.editar_video(e.ficha, e.config, shorts.OpcionesShorts(editar=True))
    zonas = _trabajo_unico(dir_edicion)[1]["zonas"]
    assert zonas["subtitulos"] is None and zonas["titulo"] is None


def test_vertical_unico_usa_los_ajustes_del_vertical(ficha_con_base, dir_edicion,
                                                     monkeypatch):
    e = ficha_con_base
    _vertical(monkeypatch)
    final = e.ficha.carpeta_salida / "charla_vertical.mp4"
    final.write_bytes(b"V")
    e.ficha.final = Huella.de(final)
    assert e.ficha.final.ruta == e.ficha.ruta_final(False)
    subs = {"diseno": "reels_karaoke", "posicion": 70, "tamano": 120}
    e.ficha.artefactos[VERTICAL] = Artefacto(
        "v", None, {"vertical": {"encuadre": "difuminado"}, "subtitulos": subs})
    shorts.editar_video(e.ficha, e.config, shorts.OpcionesShorts(editar=True))
    esperadas = shorts.zonas_edicion.calcular(
        replace(e.config, subtitulos=True, diseno="reels_karaoke", posicion_subs=70,
                tamano_subs=120), "difuminado", (1920, 1080), con_titulo=False)
    _, datos = _trabajo_unico(dir_edicion)
    assert datos["zonas"] == esperadas and datos["encuadre"] == "difuminado"
    assert datos["zonas"]["franja_zoom"] is not None


def test_editado_al_dia(tmp_path):
    final = tmp_path / "v.mp4"
    final.write_bytes(b"F")
    assert shorts.editado_al_dia(final) is None
    editado = tmp_path / "v.editado.mp4"
    editado.write_bytes(b"E")
    os.utime(final, (100, 100))
    os.utime(editado, (100, 100))
    assert shorts.editado_al_dia(final) == editado
    os.utime(editado, (50, 50))
    assert shorts.editado_al_dia(final) is None


@pytest.mark.parametrize("medida", [(1920, 1080), (720, 1280)])
def test_editar_video_rechaza_lo_que_no_es_1080x1920(
        ficha_con_base, dir_edicion, monkeypatch, medida):
    e = ficha_con_base
    monkeypatch.setattr(shorts, "resolucion_video", lambda ruta: medida)
    assert shorts.es_final_vertical(e.ficha) is False
    with pytest.raises(PasoFallido, match="1080×1920"):
        shorts.editar_video(e.ficha, e.config, shorts.OpcionesShorts(editar=True))
    assert not (dir_edicion / "pendientes").exists()


def test_es_final_vertical_nunca_lanza(ficha_con_base, monkeypatch):
    def roto(ruta):
        raise PasoFallido("ffprobe")
    monkeypatch.setattr(shorts, "resolucion_video", roto)
    assert shorts.es_final_vertical(ficha_con_base.ficha) is False
    ficha_con_base.ficha.final = None
    assert shorts.es_final_vertical(ficha_con_base.ficha) is False


def test_editar_video_sin_transcripcion(ficha_con_base, dir_edicion, monkeypatch):
    e = ficha_con_base
    _vertical(monkeypatch)
    del e.ficha.artefactos[TRANSCRIPCION]
    with pytest.raises(PasoFallido, match="transcripción"):
        shorts.editar_video(e.ficha, e.config, shorts.OpcionesShorts(editar=True))


def test_editar_video_dos_veces(ficha_con_base, dir_edicion, monkeypatch):
    e = ficha_con_base
    _vertical(monkeypatch)
    opciones = shorts.OpcionesShorts(editar=True)
    assert shorts.editar_video(e.ficha, e.config, opciones) == 1
    assert shorts.editar_video(e.ficha, e.config, opciones) == 0
    assert len(list((dir_edicion / "pendientes").iterdir())) == 1


def _a_hechos(dir_edicion):
    """Simula que el agente terminó: todos los trabajos pasan a hechos/."""
    (dir_edicion / "hechos").mkdir(exist_ok=True)
    for t in (dir_edicion / "pendientes").iterdir():
        t.rename(dir_edicion / "hechos" / t.name)


def test_editar_video_un_pendiente_con_sufijo_bloquea_otro_clic(
        ficha_con_base, dir_edicion, monkeypatch):
    e = ficha_con_base
    _vertical(monkeypatch)
    opciones = shorts.OpcionesShorts(editar=True)
    assert shorts.editar_video(e.ficha, e.config, opciones) == 1
    _a_hechos(dir_edicion)
    assert shorts.editar_video(e.ficha, e.config, opciones) == 1  # reedición: «-2»
    assert shorts.editar_video(e.ficha, e.config, opciones) == 0
    assert len(list((dir_edicion / "pendientes").iterdir())) == 1


def test_editar_video_un_pendiente_con_el_origen_cambiado_no_bloquea(
        ficha_con_base, dir_edicion, monkeypatch):
    e = ficha_con_base
    _vertical(monkeypatch)
    opciones = shorts.OpcionesShorts(editar=True)
    assert shorts.editar_video(e.ficha, e.config, opciones) == 1
    with e.ficha.final.ruta.open("ab") as f:  # el final se rehízo
        f.write(b"mas")
    assert shorts.editar_video(e.ficha, e.config, opciones) == 1
    assert len(list((dir_edicion / "pendientes").iterdir())) == 2


def test_editar_existentes_un_pendiente_con_sufijo_bloquea_otro_clic(
        ficha_con_base, dir_edicion):
    e = ficha_con_base
    _crear(e)
    opciones = shorts.OpcionesShorts(editar=True)
    assert shorts.editar_existentes(e.ficha, e.config, opciones) == 2
    _a_hechos(dir_edicion)
    assert shorts.editar_existentes(e.ficha, e.config, opciones) == 2
    assert shorts.editar_existentes(e.ficha, e.config, opciones) == 0
    assert len(list((dir_edicion / "pendientes").iterdir())) == 2


def test_editar_existentes_un_pendiente_con_el_origen_cambiado_no_bloquea(
        ficha_con_base, dir_edicion):
    e = ficha_con_base
    _crear(e)
    opciones = shorts.OpcionesShorts(editar=True)
    assert shorts.editar_existentes(e.ficha, e.config, opciones) == 2
    corto = next(e.carpeta.glob("*.mp4"))
    with corto.open("ab") as f:  # ese short se rehízo
        f.write(b"mas")
    assert shorts.editar_existentes(e.ficha, e.config, opciones) == 1


# --- Segmentación en temas ---------------------------------------------------

def _temas(*inicios):
    return {"temas": [{"frase_inicio": i, "titulo": f"tema {i}",
                       "sigue_al_anterior": False} for i in inicios]}


def test_ventana_diez_minutos():
    frases = _frases_de(120, 10)  # 20 minutos
    assert shorts.ventana(frases, 0) == 60
    assert shorts.ventana(frases, 119) == 120


def test_validar_temas_filtra_y_ordena():
    datos = {"temas": [
        {"frase_inicio": 20, "titulo": "  b  c ", "sigue_al_anterior": True},
        {"frase_inicio": 5, "titulo": "a", "sigue_al_anterior": "sí"},
        {"frase_inicio": "7", "titulo": "d", "sigue_al_anterior": False},
        {"frase_inicio": 20, "titulo": "repetido", "sigue_al_anterior": False},
        {"frase_inicio": 1, "titulo": "fuera", "sigue_al_anterior": False},
        {"frase_inicio": 31, "titulo": "fuera", "sigue_al_anterior": False},
        {"frase_inicio": None, "titulo": "x"},
        "basura",
    ]}
    assert shorts.validar_temas(datos, 1, 30) == [
        (5, "a", False), (7, "d", False), (20, "b c", True)]


def test_validar_temas_sin_lista_falla():
    with pytest.raises(PasoFallido):
        shorts.validar_temas({"temas": "no"}, 0, 10)
    with pytest.raises(PasoFallido):
        shorts.validar_temas([], 0, 10)


def test_segmentar_una_ventana(monkeypatch):
    frases = _frases_de(30, 10)
    datos = _temas(1, 10, 20)
    datos["temas"][1]["sigue_al_anterior"] = True
    datos["temas"][0]["sigue_al_anterior"] = True
    _chat_falso(monkeypatch, datos)
    temas = shorts.segmentar(frases, "m")
    assert [(t.frase_inicio, t.frase_fin) for t in temas] == [(1, 9), (10, 19), (20, 30)]
    assert [(t.inicio, t.fin) for t in temas] == [(0, 90), (90, 190), (190, 300)]
    assert [t.sigue_al_anterior for t in temas] == [False, True, False]


def test_segmentar_encadena_desde_el_ultimo_tema(monkeypatch):
    llamadas = _chat_falso(monkeypatch, [_temas(1, 30, 50), _temas(50, 80), _temas(80)])
    porcentajes = []
    temas = shorts.segmentar(_frases_de(120, 10), "m", porcentajes.append)
    assert llamadas[1]["mensajes"][1]["content"].split("\n")[1].startswith("[50]")
    assert llamadas[1]["mensajes"][0] == llamadas[0]["mensajes"][0]
    assert [t.frase_inicio for t in temas] == [1, 30, 50, 80]
    assert len(llamadas) == 3  # la 2.ª ventana llega a la frase 109
    assert porcentajes[-1] == 100.0


def test_segmentar_tema_mas_largo_que_la_ventana_no_se_atasca(monkeypatch):
    llamadas = _chat_falso(monkeypatch, [_temas(1), {"temas": []}])
    temas = shorts.segmentar(_frases_de(120, 10), "m")
    assert len(llamadas) == 2
    assert [(t.frase_inicio, t.frase_fin) for t in temas] == [(1, 120)]


def test_segmentar_reintenta_una_vez(monkeypatch):
    llamadas = _chat_falso(monkeypatch, [{"basura": 1}, _temas(1, 5)])
    assert len(shorts.segmentar(_frases_de(10, 10), "m")) == 2
    assert len(llamadas) == 2
    _chat_falso(monkeypatch, [{"basura": 1}, {"basura": 2}])
    with pytest.raises(PasoFallido):
        shorts.segmentar(_frases_de(10, 10), "m")


def test_segmentar_sin_frases_no_llama_al_modelo(monkeypatch):
    llamadas = _chat_falso(monkeypatch, _temas(1))
    assert shorts.segmentar([], "m") == []
    assert llamadas == []


def test_segmentar_temperatura_y_keep_alive(monkeypatch):
    llamadas = _chat_falso(monkeypatch, [_temas(1, 30, 50), _temas(50), _temas(80)])
    shorts.segmentar(_frases_de(120, 10), "m")
    assert len(llamadas) == 3
    for llamada in llamadas:
        assert llamada["temperatura"] == shorts.TEMPERATURA_TEMAS
        assert llamada["keep_alive"] == shorts.KEEP_ALIVE_SHORTS


def _temas_de(n: int, sigue: bool, ini: int = 1) -> list[shorts.Tema]:
    """`n` temas de una frase cada uno; `sigue` marca los que siguen al anterior."""
    return [shorts.Tema(ini + k, ini + k, f"t{k + 1}", sigue and k > 0)
            for k in range(n)]


def _rangos(cs) -> list[tuple[int, int]]:
    return [(c.frase_inicio, c.frase_fin) for c in cs]


def test_bloques_agrupa_por_sigue():
    t = [shorts.Tema(1, 1, "a", False), shorts.Tema(2, 2, "b", True),
         shorts.Tema(3, 3, "c", False), shorts.Tema(4, 4, "d", True),
         shorts.Tema(5, 5, "e", True)]
    assert [[x.titulo for x in b] for b in shorts.bloques(t)] == [["a", "b"], ["c", "d", "e"]]


def test_candidatos_tema_entero_en_rango():
    frases = _frases_de(3, 120.0)
    cs, largos = shorts.candidatos_de_temas(_temas_de(1, False), frases, 360.0)
    assert largos == []
    (c,) = cs
    esperado = shorts.validar({"candidatos": [_cand(1, 1)]}, frases, 360.0)[0]
    assert (c.origen, c.titulo, c.motivo, c.descarte) == ("tema", "t1", "", "")
    assert (c.inicio, c.fin) == (esperado.inicio, esperado.fin)


def test_candidatos_tramo_mas_largo_que_cabe():
    frases = _frases_de(5, 40.0)
    cs, largos = shorts.candidatos_de_temas(_temas_de(5, True), frases, 200.0)
    assert largos == []
    assert _rangos(cs) == [(1, 4), (2, 5), (3, 5), (4, 5)]
    assert {c.origen for c in cs} == {"tramo"}
    assert all(c.descarte == "" for c in cs)


def test_candidatos_tramo_no_cruza_bloques():
    frases = _frases_de(3, 40.0)
    cs, _ = shorts.candidatos_de_temas(_temas_de(3, False), frases, 120.0)
    assert _rangos(cs) == [(1, 1), (2, 2), (3, 3)]
    assert {c.descarte for c in cs} == {"tema_corto"}
    assert all((c.inicio, c.fin) == (0.0, 0.0) for c in cs)


def test_candidatos_tema_largo_va_a_fragmentos():
    frases = _frases_de(1, 400.0)
    cs, largos = shorts.candidatos_de_temas(_temas_de(1, False), frases, 400.0)
    assert cs == []
    assert [t.titulo for t in largos] == ["t1"]


def test_candidatos_limite_179_y_60_valen():
    for seg in (60.0, 179.0):
        cs, _ = shorts.candidatos_de_temas(_temas_de(1, False), _frases_de(1, seg), 300.0)
        assert [(c.origen, c.descarte) for c in cs] == [("tema", "")]
    cs, _ = shorts.candidatos_de_temas(_temas_de(1, False), _frases_de(1, 59.9), 300.0)
    assert [c.descarte for c in cs] == ["tema_corto"]


def _tema_largo(n: int, segundos: float, inicio_frase: int = 1) -> tuple[shorts.Tema, list]:
    frases = _frases_de(n, segundos)
    return shorts.Tema(inicio_frase, n, "t", False, frases[inicio_frase - 1].inicio,
                       frases[-1].fin), frases


def test_fragmentos_segundos_relativos_al_tema():
    frases = _frases_de(100, 10)
    mensajes = shorts.construir_mensajes_fragmentos(frases, 60, 63, 2, 600.0)
    assert mensajes[1]["content"].split("\n")[1] == f"[61] 0s-10s: {frases[60].texto}"
    assert "hasta 2" in mensajes[0]["content"]


def test_fragmentos_k_por_subventana(monkeypatch):
    tema, frases = _tema_largo(150, 10)  # 25 min
    llamadas = _chat_falso(monkeypatch, {"candidatos": []})
    avances = []
    assert shorts.fragmentos(tema, frases, 1500.0, "m", avances.append) == []
    assert len(llamadas) == 3
    assert ["hasta 3" in l["mensajes"][0]["content"] for l in llamadas] == [True, True, False]
    assert "hasta 1" in llamadas[2]["mensajes"][0]["content"]
    assert all(l["keep_alive"] == shorts.KEEP_ALIVE_SHORTS for l in llamadas)
    assert avances[-1] == 100.0


def test_fragmentos_progreso_relativo_al_tema(monkeypatch):
    tema, frases = _tema_largo(150, 10, inicio_frase=31)  # frases 31-150: 20 min
    _chat_falso(monkeypatch, {"candidatos": []})
    avances = []
    shorts.fragmentos(tema, frases, 1500.0, "m", avances.append)
    assert avances == [50.0, 100.0]


def test_fragmentos_resto_corto_se_pliega_a_la_subventana(monkeypatch):
    tema, frases = _tema_largo(63, 10)  # 630 s: 600 s + 30 s
    llamadas = _chat_falso(monkeypatch, {"candidatos": []})
    shorts.fragmentos(tema, frases, 630.0, "m")
    assert len(llamadas) == 1


def test_fragmentos_fuera_del_tema_se_descarta(monkeypatch):
    tema, frases = _tema_largo(60, 10, inicio_frase=11)  # frases 11-60
    _chat_falso(monkeypatch, {"candidatos": [_cand(1, 8), _cand(11, 20)]})
    cs = shorts.fragmentos(tema, frases, 600.0, "m")
    assert [(c.frase_inicio, c.descarte, c.origen) for c in cs] == [
        (1, "fuera_de_rango", "fragmento"), (11, "", "fragmento")]


def test_fragmentos_corrige_una_vez(monkeypatch):
    tema, frases = _tema_largo(30, 10)  # 300 s
    llamadas = _chat_falso(monkeypatch, [
        {"candidatos": [_cand(1, 22)]},  # 220 s
        {"candidatos": [_cand(1, 10)]},
    ])
    cs = shorts.fragmentos(tema, frases, 300.0, "m")
    assert [(c.frase_fin, c.descarte) for c in cs] == [(10, "")]
    corr = llamadas[1]["mensajes"]
    assert [m["role"] for m in corr] == ["system", "user", "assistant", "user"]
    assert "hasta 1" in corr[0]["content"] and "1-22 dura 220 s" in corr[3]["content"]


def test_fragmentos_correccion_invalida_deja_el_original(monkeypatch):
    tema, frases = _tema_largo(30, 10)
    llamadas = _chat_falso(monkeypatch, [
        {"candidatos": [_cand(1, 22)]}, {"candidatos": [_cand(1, 25)]},
        {"candidatos": [_cand(1, 10)]},
    ])
    cs = shorts.fragmentos(tema, frases, 300.0, "m")
    assert [(c.frase_fin, c.descarte) for c in cs] == [(22, "duracion")]
    assert len(llamadas) == 2


def test_fragmentos_respuesta_invalida_salta_la_subventana(monkeypatch):
    tema, frases = _tema_largo(30, 10)
    _chat_falso(monkeypatch, {"x": 1})
    assert shorts.fragmentos(tema, frases, 300.0, "m") == []


# --- seleccionar --------------------------------------------------------------

def _selec_falsa(monkeypatch, temas, candidatos, notas=(0.9, 3.0)):
    """`chat_json` por esquema, `systemone` con una nota fija y `descargar` anotado."""
    descargados = []
    monkeypatch.setattr(shorts, "descargar", descargados.append)
    monkeypatch.setattr(shorts, "systemone", lambda *a, **kw: _tev1(*notas))

    def chat(modelo, mensajes, esquema, **kw):
        if esquema is shorts.ESQUEMA_TEMAS:
            return temas() if callable(temas) else temas
        return candidatos

    monkeypatch.setattr(shorts, "chat_json", chat)
    return descargados


def test_seleccionar_flujo_completo(monkeypatch):
    frases = _frases_de(120, 10)  # 20 minutos
    # Temas: 1-8 (80 s, tema), 9-14 (60 s) y 15-20 (60 s) seguidos (tramo), 21-60 largo.
    temas = {"temas": [
        {"frase_inicio": 1, "titulo": "uno", "sigue_al_anterior": False},
        {"frase_inicio": 9, "titulo": "dos", "sigue_al_anterior": False},
        {"frase_inicio": 15, "titulo": "tres", "sigue_al_anterior": True},
        {"frase_inicio": 21, "titulo": "largo", "sigue_al_anterior": False},
        {"frase_inicio": 61, "titulo": "otro", "sigue_al_anterior": False},
    ]}
    descargados = _selec_falsa(monkeypatch, temas, {"candidatos": [
        _cand(21, 30, titulo="Dentro"), _cand(21, 30, titulo="Igual")]})
    sel = shorts.seleccionar(frases, 1200.0, "m", on_aviso=lambda t: None)
    assert [t.titulo for t in sel.temas] == ["uno", "dos", "tres", "largo", "otro"]
    origenes = {c.origen for c in sel.candidatos}
    assert {"tema", "tramo", "fragmento"} <= origenes
    assert "repetido" in [c.descarte for c in sel.candidatos if c.titulo == "Igual"]
    assert sel.juez == shorts.JUEZ
    assert 1 <= len(sel.elegidos) <= shorts.maximo_shorts(1200.0)
    assert all(c.interes == 3.0 for c in sel.elegidos)
    assert sel.elegidos and not any(
        shorts._se_solapan(a, b) for a in sel.elegidos for b in sel.elegidos if a is not b)
    assert descargados == ["m"]


def test_seleccionar_descarga_aunque_falle(monkeypatch):
    descargados = _selec_falsa(monkeypatch, {"temas": "no"}, {"candidatos": []})
    with pytest.raises(PasoFallido):
        shorts.seleccionar(_frases_de(60, 10), 600.0, "m", on_aviso=lambda t: None)
    assert descargados == ["m"]


def test_seleccionar_todos_cortos_sin_candidatos(monkeypatch):
    temas = {"temas": [{"frase_inicio": i, "titulo": f"t{i}", "sigue_al_anterior": False}
                       for i in range(1, 60, 3)]}  # temas de 30 s sin seguir
    _selec_falsa(monkeypatch, temas, {"candidatos": []})
    sel = shorts.seleccionar(_frases_de(60, 10), 600.0, "m", on_aviso=lambda t: None)
    assert sel.elegidos == []
    assert {c.descarte for c in sel.candidatos} == {"tema_corto"}


def test_listar_lee_shorts_json_v1(tmp_path):
    carpeta = tmp_path / "shorts"
    carpeta.mkdir()
    (carpeta / "01 - Uno.mp4").write_bytes(b"x")
    (carpeta / "shorts.json").write_text(json.dumps({
        "version": 1, "ficha": "f1", "video": "v", "juez": "tev1:0.8b",
        "maximo": 1, "archivos": ["01 - Uno.mp4"],
        "candidatos": [{"frase_inicio": 1, "frase_fin": 9, "titulo": "Uno",
                        "motivo": "", "inicio": 10.0, "fin": 100.0,
                        "archivo": "01 - Uno.mp4"}]}), encoding="utf-8")
    assert [(c.mp4.name, c.duracion) for c in shorts.listar(carpeta)] == [
        ("01 - Uno.mp4", 90.0)]
    assert shorts._anteriores(carpeta, "f1") == ["01 - Uno.mp4"]
