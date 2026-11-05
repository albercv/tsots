from __future__ import annotations

import pytest

from videopipeline import shorts
from videopipeline.steps import PasoFallido
from videopipeline.subtitles import Palabra


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


def test_trocear_frases_vacio():
    assert shorts.trocear_frases([]) == []


def test_maximo_shorts():
    assert [shorts.maximo_shorts(d) for d in (179, 180, 350, 1800)] == [0, 1, 1, 10]


def test_partes_una_sola_hasta_20_minutos():
    frases = _frases_de(120, 10)  # justo 20 minutos
    assert shorts.partes(frases) == [(0, 120)]
    assert shorts.partes([]) == []


def test_partes_largas_se_solapan():
    frases = _frases_de(360, 10)  # 60 minutos
    partes = shorts.partes(frases)
    assert len(partes) > 1
    for desde, hasta in partes:
        assert frases[hasta - 1].fin - frases[desde].inicio <= 20 * 60
    assert frases[partes[1][0]].inicio == 18 * 60
    assert partes[0][1] > partes[1][0]  # se solapan
    assert partes[-1][1] == len(frases)
    # Sin huecos: cada parte empieza antes de que acabe la anterior.
    assert all(b[0] < a[1] for a, b in zip(partes, partes[1:]))


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


def test_validar_sin_lista_falla():
    frases = _frases_de(10, 10)
    for datos in ({}, {"candidatos": "no"}, {"candidatos": None}):
        with pytest.raises(PasoFallido):
            shorts.validar(datos, frases, duracion=100.0)


def _nota(ini: float, fin: float, interes: float, indep: float
          ) -> shorts.Candidato:
    return shorts.Candidato(1, 2, "t", "m", inicio=ini, fin=fin,
                            interes=interes, independiente=indep)


def test_elegir_umbrales_orden_solapes_y_maximo():
    flojo = _nota(0, 70, 1.9, 0.9)
    no_solo = _nota(100, 170, 3.0, 0.4)
    mejor = _nota(200, 270, 3.5, 0.9)
    solapa = _nota(250, 320, 3.0, 0.8)  # pisa a `mejor`
    segundo = _nota(400, 470, 2.5, 0.8)
    de_mas = _nota(600, 670, 2.0, 0.7)
    todos = [flojo, no_solo, solapa, de_mas, segundo, mejor]
    elegidos = shorts.elegir(todos, maximo=2)
    assert elegidos == [mejor, segundo]
    assert [c.descarte for c in (flojo, no_solo, mejor, solapa, segundo, de_mas)] == [
        "flojo", "no_se_entiende_solo", "", "solapa", "", "sobra",
    ]


def test_elegir_desempata_por_independiente_y_luego_inicio():
    a = _nota(0, 70, 3.0, 0.6)
    b = _nota(100, 170, 3.0, 0.9)
    c = _nota(200, 270, 3.0, 0.9)
    assert shorts.elegir([a, c, b], maximo=3) == [b, c, a]


def test_elegir_deja_tocarse_los_extremos_y_ignora_los_ya_descartados():
    a = _nota(0, 70, 3.0, 0.9)
    b = _nota(70, 140, 2.5, 0.9)  # empieza donde acaba `a`: no se pisan
    ya = _nota(0, 70, 4.0, 1.0)
    ya.descarte = "duracion"
    assert shorts.elegir([ya, a, b], maximo=5) == [a, b]
    assert ya.descarte == "duracion"


def test_elegir_sin_notas_no_pasa():
    sin_notas = shorts.Candidato(1, 2, "t", "m", inicio=0.0, fin=70.0)
    assert shorts.elegir([sin_notas], maximo=3) == []
    assert sin_notas.descarte == "flojo"


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
