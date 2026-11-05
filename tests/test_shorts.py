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


def _nota(ini: float, fin: float, interes: float, indep: float,
          frases: tuple[int, int] | None = None) -> shorts.Candidato:
    # Por defecto cada nota tiene sus propias frases (según su inicio): solo se
    # pisan las que comparten alguna.
    f_ini, f_fin = frases or (int(ini) + 1, int(ini) + 2)
    return shorts.Candidato(f_ini, f_fin, "t", "m", inicio=ini, fin=fin,
                            interes=interes, independiente=indep)


def test_elegir_umbrales_orden_solapes_y_maximo():
    flojo = _nota(0, 70, 1.9, 0.9)
    no_solo = _nota(100, 170, 3.0, 0.4)
    mejor = _nota(200, 270, 3.5, 0.9)
    solapa = _nota(250, 320, 3.0, 0.8, frases=(202, 203))  # comparte la 202
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
    assert shorts.elegir([a, b], maximo=2) == [a, b]
    assert (a.descarte, b.descarte) == ("", "")


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
    return {
        "independiente": {"type": "choice", "choice": "si",
                          "probabilities": {"si": si, "no": 1 - si}},
        "interes": {"type": "score", "score": score,
                    "probabilities": {"0": 0.1, "1": 0.2}},
    }


def test_construir_mensajes_numera_globalmente():
    frases = _frases_de(10, 10)
    sistema, usuario = shorts.construir_mensajes(frases, 5, 8, 4)
    assert sistema["role"] == "system"
    assert "hasta 4 fragmentos" in sistema["content"]
    assert usuario["role"] == "user"
    assert usuario["content"].split("\n") == [
        "Transcripción:",
        f"[6] 50s-60s: {frases[5].texto}",
        f"[7] 60s-70s: {frases[6].texto}",
        f"[8] 70s-80s: {frases[7].texto}",
    ]


def test_esquema_candidatos_exige_todos_los_campos():
    item = shorts.ESQUEMA_CANDIDATOS["properties"]["candidatos"]["items"]
    assert shorts.ESQUEMA_CANDIDATOS["required"] == ["candidatos"]
    assert sorted(item["required"]) == ["frase_fin", "frase_inicio", "motivo", "titulo"]
    assert item["properties"]["frase_inicio"]["type"] == "integer"
    assert item["properties"]["titulo"]["type"] == "string"


def test_buscar_candidatos_una_parte_pide_el_doble_del_maximo(monkeypatch):
    frases = _frases_de(54, 10)  # 9 minutos
    llamadas = _chat_falso(monkeypatch, {"candidatos": [_cand(1, 8)]})
    porcentajes = []
    candidatos = shorts.buscar_candidatos(
        frases, 540.0, 3, "gemma4:12b-mlx", porcentajes.append)
    assert len(llamadas) == 1
    assert llamadas[0]["modelo"] == "gemma4:12b-mlx"
    assert llamadas[0]["esquema"] is shorts.ESQUEMA_CANDIDATOS
    assert "hasta 6 fragmentos" in llamadas[0]["mensajes"][0]["content"]
    assert [(c.frase_inicio, c.frase_fin, c.descarte) for c in candidatos] == [(1, 8, "")]
    assert porcentajes == [100.0]


def test_buscar_candidatos_sin_frases_no_llama_al_modelo(monkeypatch):
    llamadas = _chat_falso(monkeypatch, {"candidatos": []})
    assert shorts.buscar_candidatos([], 0.0, 0, "gemma4:12b-mlx") == []
    assert llamadas == []


def test_buscar_candidatos_partes_y_repetidos(monkeypatch):
    frases = _frases_de(270, 10)  # 45 minutos: tres partes
    trozo = _cand(110, 117)  # cae en la zona que comparten las partes 1 y 2
    llamadas = _chat_falso(monkeypatch, [
        {"candidatos": [trozo]}, {"candidatos": [trozo]}, {"candidatos": []},
    ])
    porcentajes = []
    candidatos = shorts.buscar_candidatos(
        frases, 2700.0, 4, "gemma4:12b-mlx", porcentajes.append)
    assert len(llamadas) == len(shorts.partes(frases)) == 3
    # Cada parte numera sus frases con los números globales.
    primeras = [m["mensajes"][1]["content"].split("\n")[1] for m in llamadas]
    assert [p.split("]")[0] for p in primeras] == ["[1", "[109", "[217"]
    assert [c.descarte for c in candidatos] == ["", "repetido"]
    assert porcentajes == pytest.approx([100 / 3, 200 / 3, 100.0])


def test_buscar_candidatos_basura_del_modelo_no_rompe(monkeypatch):
    _chat_falso(monkeypatch, {"candidatos": [_cand(0, 3), _cand("x", 9), "?"]})
    candidatos = shorts.buscar_candidatos(_frases_de(54, 10), 540.0, 3, "m")
    assert [c.descarte for c in candidatos] == ["fuera_de_rango"]


def test_nota_tev1_lee_probabilidad_y_score(monkeypatch):
    respuesta = {
        "independiente": {"type": "choice", "choice": "si", "probabilities": {
            "si": 0.6563623509207749, "no": 0.34363764907922517}},
        "interes": {"type": "score", "score": 2.730191051931489,
                    "probabilities": {"2": 0.4, "3": 0.5}},
    }
    pedidos = []

    def falso(modelo, estado, preguntas, **kw):
        pedidos.append((modelo, estado, preguntas))
        return respuesta

    monkeypatch.setattr(shorts, "systemone", falso)
    assert shorts.nota_tev1("un fragmento") == (
        pytest.approx(0.6563623509207749), pytest.approx(2.730191051931489))
    assert pedidos == [("tev1:0.8b", "un fragmento", shorts.PREGUNTAS)]


@pytest.mark.parametrize("respuesta", [
    {"interes": {}},
    {},
    {"independiente": {"probabilities": {"si": "mucho"}},
     "interes": {"score": 3.0}},
])
def test_nota_tev1_forma_inesperada_falla(monkeypatch, respuesta):
    monkeypatch.setattr(shorts, "systemone", lambda *a, **kw: respuesta)
    with pytest.raises(PasoFallido, match="tev1:0.8b"):
        shorts.nota_tev1("texto")


def test_nota_chat_temperatura_cero(monkeypatch):
    llamadas = _chat_falso(monkeypatch, {"independiente": "no", "interes": 7})
    assert shorts.nota_chat("el fragmento", "gemma4:12b-mlx") == (0.0, 4.0)
    assert llamadas[0]["temperatura"] == 0
    assert llamadas[0]["modelo"] == "gemma4:12b-mlx"
    assert llamadas[0]["esquema"] is shorts.ESQUEMA_JUEZ
    sistema, usuario = llamadas[0]["mensajes"]
    assert sistema == {"role": "system", "content": shorts._SYSTEM_JUEZ}
    assert usuario == {"role": "user", "content": "Fragmento:\nel fragmento"}


def test_nota_chat_si_y_acota_a_cero(monkeypatch):
    _chat_falso(monkeypatch, {"independiente": "si", "interes": -3})
    assert shorts.nota_chat("x", "m") == (1.0, 0.0)


def test_nota_chat_forma_inesperada_falla(monkeypatch):
    _chat_falso(monkeypatch, {"independiente": "si"})
    with pytest.raises(PasoFallido, match="gemma4:12b-mlx"):
        shorts.nota_chat("x", "gemma4:12b-mlx")


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
    juez = shorts.puntuar([a, b, descartado], frases, "gemma4:12b-mlx",
                          avisos.append, porcentajes.append)
    assert juez == "tev1:0.8b"
    assert (a.independiente, a.interes) == (pytest.approx(0.9), pytest.approx(3.5))
    assert (b.independiente, b.interes) == (pytest.approx(0.4), pytest.approx(1.5))
    assert (descartado.independiente, descartado.interes) == (None, None)
    assert estados == [texto(a), texto(b)]
    assert llamadas == [] and avisos == []
    assert porcentajes == [50.0, 100.0]


def test_puntuar_respaldo_si_falla_tev1(monkeypatch):
    frases, a, b, descartado, texto = _para_puntuar()
    n = []

    def falso(modelo, estado, preguntas, **kw):
        n.append(estado)
        if len(n) == 2:
            raise PasoFallido("Ollama no responde")
        return _tev1(0.7, 2.5)

    monkeypatch.setattr(shorts, "systemone", falso)
    llamadas = _chat_falso(monkeypatch, {"independiente": "si", "interes": 3})
    avisos = []
    juez = shorts.puntuar([a, b, descartado], frases, "gemma4:12b-mlx", avisos.append)
    assert juez == "gemma4:12b-mlx"
    assert len(n) == 2  # tras el primer fallo no se insiste con tev1
    assert len(avisos) == 1
    assert "tev1:0.8b" in avisos[0] and "gemma4:12b-mlx" in avisos[0]
    assert "Ollama no responde" in avisos[0]
    # Todos puntuados por el chat, también el primero: sin mezclar escalas.
    assert (a.independiente, a.interes) == (1.0, 3.0)
    assert (b.independiente, b.interes) == (1.0, 3.0)
    assert descartado.interes is None
    assert [l["temperatura"] for l in llamadas] == [0, 0]
    assert [l["mensajes"][1]["content"] for l in llamadas] == [
        "Fragmento:\n" + texto(a), "Fragmento:\n" + texto(b)]


def test_puntuar_sin_ningun_juez_falla_claro(monkeypatch):
    frases, a, b, descartado, texto = _para_puntuar()

    def sin_tev1(*args, **kw):
        raise PasoFallido("sin tev1")

    def sin_chat(*args, **kw):
        raise PasoFallido("sin chat")

    monkeypatch.setattr(shorts, "systemone", sin_tev1)
    monkeypatch.setattr(shorts, "chat_json", sin_chat)
    with pytest.raises(PasoFallido,
                       match="ni tev1:0.8b ni gemma4:12b-mlx responden") as e:
        shorts.puntuar([a, b], frases, "gemma4:12b-mlx", lambda aviso: None)
    assert e.value.detalle == "sin chat"


def test_puntuar_sin_candidatos_vivos_no_llama_a_nadie(monkeypatch):
    frases, a, b, descartado, texto = _para_puntuar()

    def prohibido(*args, **kw):
        raise AssertionError("no debe llamar a Ollama")

    monkeypatch.setattr(shorts, "systemone", prohibido)
    monkeypatch.setattr(shorts, "chat_json", prohibido)
    assert shorts.puntuar([descartado], frases, "m", lambda aviso: None) == shorts.JUEZ
