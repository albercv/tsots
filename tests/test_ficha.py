from __future__ import annotations

import json
from pathlib import Path

import pytest

from videopipeline import ficha as modulo
from videopipeline.caption import Caption, escribir_md, leer_md
from videopipeline.ficha import (
    AUDIO, BASE, CAPTION, HORIZONTAL, PASOS, SEGUIMIENTO, TRANSCRIPCION,
    VERTICAL,
    Artefacto, Ficha, Huella,
    cargar, guardar, limpiar_temporales, ocupa, olvidar, reconocer, todas,
)
from videopipeline.subtitles import Bloque, Palabra, generar_srt, leer_srt


@pytest.fixture(autouse=True)
def dir_fichas(tmp_path, monkeypatch):
    """Las fichas de los tests nunca van al proyecto."""
    destino = tmp_path / "fichas"
    monkeypatch.setattr(modulo, "DIR_FICHAS", destino)
    return destino


def _archivo(ruta: Path, contenido: bytes = b"video") -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(contenido)
    return ruta


def _caption() -> Caption:
    return Caption(titulo="Título", caption="Texto del caption.",
                   hashtags=["#uno", "#dos"], palabras_clave=["clave"])


def test_guardar_y_cargar_ida_y_vuelta(tmp_path):
    original = _archivo(tmp_path / "orig" / "charla.mov")
    final = _archivo(tmp_path / "salida" / "charla_limpio.mp4")
    vertical = _archivo(tmp_path / "salida" / "charla_limpio_vertical.mp4")
    ficha = Ficha(
        id="abc123def456", nombre="charla", carpeta_salida=tmp_path / "salida",
        original=Huella.de(original), final=Huella.de(final),
        vertical=Huella.de(vertical), legado=True, subs_quemados_sin_base=True,
        desactualizado={"vertical"},
        artefactos={
            BASE: Artefacto("k1", None, {"audio": {"modelo": "m"},
                                         "silencios": {"margen": 0.2}}, "lt1"),
            CAPTION: Artefacto("k2", "caption.md"),
        },
    )
    guardar(ficha)

    assert cargar("abc123def456") == ficha
    assert not (ficha.carpeta / ".ficha_tmp.json").exists()


def test_cargar_ficha_danada_devuelve_none_y_avisa_en_el_log(caplog):
    carpeta = modulo.DIR_FICHAS / "rota"
    carpeta.mkdir(parents=True)
    (carpeta / "ficha.json").write_text("{", encoding="utf-8")

    assert cargar("rota") is None
    assert "dañado" in caplog.text
    caplog.clear()
    assert cargar("no_existe") is None
    assert caplog.text == ""


def _ficha_json_valida(tmp_path) -> dict:
    """El contenido de un `ficha.json` correcto, para estropearlo luego."""
    ficha = Ficha(
        id="mala", nombre="x", carpeta_salida=tmp_path,
        original=Huella.de(_archivo(tmp_path / "x.mov")),
        desactualizado={"vertical"},
        artefactos={BASE: Artefacto("k", None, {"audio": {}}, "lt")},
    )
    guardar(ficha)
    return json.loads(ficha.ruta("ficha.json").read_text(encoding="utf-8"))


# Cada caso cambia una parte de la ficha por algo del tipo equivocado.
FORMAS_ERRONEAS = [
    ("artefactos", []),
    ("artefactos", None),
    ("artefactos", {"base": 5}),
    ("artefactos", {"base": {"clave": 5, "archivo": None, "ajustes": {},
                             "linea_tiempo": ""}}),
    ("artefactos", {"base": {"clave": "k", "archivo": None, "ajustes": 5,
                             "linea_tiempo": ""}}),
    ("artefactos", {"base": {"clave": "k"}}),
    ("original", 5),
    ("original", "x.mov"),
    ("original", {"ruta": "x", "tamano": "grande", "mtime_ns": 1}),
    ("final", []),
    ("desactualizado", 5),
    ("desactualizado", None),
    ("desactualizado", [5]),
    ("legado", "si"),
    ("subs_quemados_sin_base", None),
    ("carpeta_salida", None),
    ("nombre", 5),
    ("id", None),
]


def _escribir_ficha_mala(datos) -> None:
    carpeta = modulo.DIR_FICHAS / "mala"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "ficha.json").write_text(json.dumps(datos), encoding="utf-8")


@pytest.mark.parametrize("clave, valor", FORMAS_ERRONEAS)
def test_cargar_json_valido_de_otra_forma_devuelve_none(tmp_path, clave, valor):
    datos = _ficha_json_valida(tmp_path)
    datos[clave] = valor
    _escribir_ficha_mala(datos)

    assert cargar("mala") is None


@pytest.mark.parametrize("datos", [[], None, 5, "ficha", {}])
def test_cargar_json_que_no_es_una_ficha_devuelve_none(datos):
    _escribir_ficha_mala(datos)

    assert cargar("mala") is None


@pytest.mark.parametrize("clave, valor", FORMAS_ERRONEAS)
def test_todas_y_reconocer_siguen_con_una_ficha_de_forma_erronea(
        tmp_path, clave, valor):
    datos = _ficha_json_valida(tmp_path)
    datos[clave] = valor
    _escribir_ficha_mala(datos)
    buena = Ficha(id="buena", nombre="y", carpeta_salida=tmp_path)
    guardar(buena)

    assert todas() == [buena]
    nueva, aviso = reconocer(_archivo(tmp_path / "z.mov"), None)
    assert aviso == ""
    assert nueva.nombre == "z"
    assert {f.id for f in todas()} == {"buena", nueva.id}


def test_cargar_ficha_con_otro_id_devuelve_none(tmp_path):
    ficha = Ficha(id="uno", nombre="x", carpeta_salida=tmp_path)
    guardar(ficha)
    (modulo.DIR_FICHAS / "uno").rename(modulo.DIR_FICHAS / "copiada")

    assert cargar("copiada") is None


def test_todas_ignora_las_danadas(tmp_path):
    buena = Ficha(id="buena", nombre="x", carpeta_salida=tmp_path)
    guardar(buena)
    rota = modulo.DIR_FICHAS / "rota"
    rota.mkdir()
    (rota / "ficha.json").write_text("{", encoding="utf-8")
    vacia = modulo.DIR_FICHAS / "sin_json"
    vacia.mkdir()

    assert todas() == [buena]


def test_todas_sin_carpeta_de_fichas_es_vacio():
    assert todas() == []


def test_reconocer_original_nuevo_crea_ficha(tmp_path):
    video = _archivo(tmp_path / "orig" / "charla.mov")
    salida = tmp_path / "salida"

    ficha, aviso = reconocer(video, salida)

    assert aviso == ""
    assert ficha.nombre == "charla"
    assert ficha.carpeta_salida == salida
    assert ficha.original == Huella.de(video)
    assert not ficha.legado
    assert cargar(ficha.id) == ficha

    otra, _ = reconocer(_archivo(tmp_path / "otra" / "hablar.mov"), None)
    assert otra.carpeta_salida == tmp_path / "otra"


def test_reconocer_mismo_original_devuelve_la_misma_ficha(tmp_path):
    video = _archivo(tmp_path / "charla.mov")

    primera, _ = reconocer(video, None)
    segunda, aviso = reconocer(video, None)

    assert segunda.id == primera.id
    assert aviso == ""
    assert len(todas()) == 1


def test_reconocer_una_salida_devuelve_su_ficha(tmp_path):
    video = _archivo(tmp_path / "charla.mov")
    ficha, _ = reconocer(video, None)
    salida = _archivo(tmp_path / "charla_limpio.mp4")
    ficha.final = Huella.de(salida)
    guardar(ficha)

    encontrada, aviso = reconocer(salida, None)

    assert encontrada.id == ficha.id
    assert aviso == ""


def test_reconocer_el_vertical_devuelve_su_ficha(tmp_path):
    video = _archivo(tmp_path / "charla.mov")
    ficha, _ = reconocer(video, None)
    vertical = _archivo(tmp_path / "charla_limpio_vertical.mp4")
    ficha.vertical = Huella.de(vertical)
    guardar(ficha)

    assert reconocer(vertical, None) == (ficha, "")


def test_archivo_editado_fuera_crea_ficha_nueva_y_avisa(tmp_path):
    video = _archivo(tmp_path / "charla.mov")
    vieja, _ = reconocer(video, None)

    video.write_bytes(b"editado fuera de la app y mas largo")
    nueva, aviso = reconocer(video, None)

    assert nueva.id != vieja.id
    assert aviso
    assert "charla.mov" in aviso
    assert not vieja.carpeta.exists()
    assert nueva.original == Huella.de(video)
    assert [f.id for f in todas()] == [nueva.id]


def test_salida_editada_fuera_crea_ficha_nueva_y_avisa(tmp_path):
    video = _archivo(tmp_path / "charla.mov")
    vieja, _ = reconocer(video, None)
    salida = _archivo(tmp_path / "charla_limpio.mp4")
    vieja.final = Huella.de(salida)
    guardar(vieja)

    salida.write_bytes(b"recortado a mano en otro programa")
    nueva, aviso = reconocer(salida, None)

    assert nueva.id != vieja.id
    assert aviso
    assert not vieja.carpeta.exists()
    # Sin original conocido: pasa a ser una salida antigua que se sobrescribe a sí misma.
    assert nueva.legado
    assert nueva.final == Huella.de(salida)


def test_legado_limpio_limpio_es_su_propio_final(tmp_path):
    salida = _archivo(tmp_path / "carpeta" / "x_limpio_limpio.mp4")

    ficha, aviso = reconocer(salida, tmp_path / "otra_carpeta")

    assert aviso == ""
    assert ficha.nombre == "x_limpio"
    assert ficha.final.ruta == salida
    assert ficha.final == Huella.de(salida)
    assert ficha.original is None
    assert ficha.legado
    # La salida es la del propio archivo, no la carpeta que se pasó.
    assert ficha.carpeta_salida == salida.parent
    assert ficha.ruta_final(True) == salida
    assert ficha.hay_horizontal()
    assert not ficha.subs_quemados_sin_base
    assert reconocer(salida, None)[0].id == ficha.id


@pytest.mark.parametrize("nombre", ["foo_limpio.mov", "foo_limpio.MOV",
                                    "foo_limpio.mkv", "foo_vertical.mov"])
def test_original_con_sufijo_de_salida_pero_otra_extension_es_un_original(
        tmp_path, nombre):
    fuente = _archivo(tmp_path / "orig" / nombre)

    ficha, aviso = reconocer(fuente, tmp_path / "salida")

    assert aviso == ""
    assert ficha.legado is False
    assert ficha.nombre == fuente.stem
    assert ficha.original == Huella.de(fuente)
    assert ficha.final is None
    assert ficha.carpeta_salida == tmp_path / "salida"
    assert ficha.ruta_final(True) != fuente
    assert ficha.ruta_final(True).name == f"{fuente.stem}_limpio.mp4"


def test_original_foo_limpio_mov_nunca_es_su_propio_final(tmp_path):
    fuente = _archivo(tmp_path / "foo_limpio.mov")

    ficha, _ = reconocer(fuente, None)

    assert ficha.nombre == "foo_limpio"
    assert ficha.ruta_final(True).name == "foo_limpio_limpio.mp4"
    assert ficha.ruta_final(True) != fuente


@pytest.mark.parametrize("nombre", ["x_limpio.MP4", "x_vertical.Mp4"])
def test_salida_antigua_con_mp4_en_mayusculas_es_legado(tmp_path, nombre):
    ficha, _ = reconocer(_archivo(tmp_path / nombre), None)

    assert ficha.legado is True
    assert ficha.nombre == "x"


def test_legado_vertical_solo(tmp_path):
    salida = _archivo(tmp_path / "x_vertical.mp4")

    ficha, _ = reconocer(salida, None)

    assert ficha.nombre == "x"
    assert ficha.legado
    assert not ficha.hay_horizontal()
    assert ficha.ruta_final(False) == salida
    assert ficha.ruta_final(True) == tmp_path / "x_limpio.mp4"


def test_legado_importa_md_y_srt(tmp_path):
    salida = _archivo(tmp_path / "x_limpio.mp4")
    escribir_md(_caption(), tmp_path / "x_limpio.md")
    generar_srt(
        [Bloque([Palabra("hola", 0.0, 0.5), Palabra("mundo", 0.5, 1.0)], 0.0, 1.0)],
        tmp_path / "x_limpio.srt",
    )

    ficha, _ = reconocer(salida, None)

    assert ficha.artefactos[CAPTION].archivo == "caption.md"
    assert ficha.artefactos[CAPTION].clave == "importado"
    assert leer_md(ficha.ruta("caption.md")) == _caption()
    transcripcion = ficha.artefactos[TRANSCRIPCION]
    assert transcripcion.linea_tiempo == "legado"
    assert json.loads(ficha.ruta(transcripcion.archivo).read_text("utf-8")) == [
        {"texto": "hola", "inicio": 0.0, "fin": 0.5},
        {"texto": "mundo", "inicio": 0.5, "fin": 1.0},
    ]
    assert ficha.subs_quemados_sin_base is True
    # El .md y el .srt de la salida siguen donde estaban.
    assert (tmp_path / "x_limpio.md").exists()
    assert (tmp_path / "x_limpio.srt").exists()
    assert cargar(ficha.id) == ficha


def test_legado_srt_ilegible_bloquea_subtitulos_sin_transcripcion(tmp_path):
    salida = _archivo(tmp_path / "x_limpio.mp4")
    (tmp_path / "x_limpio.srt").write_text("no es un srt", encoding="utf-8")

    ficha, _ = reconocer(salida, None)

    assert ficha.subs_quemados_sin_base is True
    assert TRANSCRIPCION not in ficha.artefactos


def test_legado_sin_md_ni_srt_no_importa_nada(tmp_path):
    ficha, _ = reconocer(_archivo(tmp_path / "x_limpio.mp4"), None)

    assert ficha.artefactos == {}
    assert ficha.subs_quemados_sin_base is False


def test_original_adopta_ficha_de_legado(tmp_path):
    salida = tmp_path / "salida"
    antigua = _archivo(salida / "x_limpio.mp4")
    legado, _ = reconocer(antigua, None)
    original = _archivo(tmp_path / "orig" / "x.mov")

    ficha, aviso = reconocer(original, salida)

    assert aviso == ""
    assert ficha.id == legado.id
    assert ficha.original == Huella.de(original)
    assert ficha.legado is False
    assert ficha.final.ruta == antigua
    assert len(todas()) == 1
    assert cargar(ficha.id) == ficha


def test_original_adopta_ficha_de_legado_solo_vertical(tmp_path):
    salida = tmp_path / "salida"
    antigua = _archivo(salida / "x_vertical.mp4")
    legado, _ = reconocer(antigua, None)
    original = _archivo(tmp_path / "orig" / "x.mov")

    ficha, aviso = reconocer(original, salida)

    assert aviso == ""
    assert ficha.id == legado.id
    assert ficha.original == Huella.de(original)
    assert ficha.legado is False
    assert ficha.final.ruta == antigua
    assert not ficha.hay_horizontal()
    assert len(todas()) == 1
    assert cargar(ficha.id) == ficha


def test_original_no_adopta_legado_de_otra_carpeta_de_salida(tmp_path):
    antigua = _archivo(tmp_path / "salida" / "x_vertical.mp4")
    legado, _ = reconocer(antigua, None)

    ficha, _ = reconocer(_archivo(tmp_path / "orig" / "x.mov"),
                         tmp_path / "otra_salida")

    assert ficha.id != legado.id
    assert ficha.legado is False
    assert len(todas()) == 2


def test_original_adopta_primero_el_legado_horizontal(tmp_path):
    salida = tmp_path / "salida"
    vertical, _ = reconocer(_archivo(salida / "x_vertical.mp4"), None)
    horizontal, _ = reconocer(_archivo(salida / "x_limpio.mp4"), None)

    ficha, _ = reconocer(_archivo(tmp_path / "orig" / "x.mov"), salida)

    assert ficha.id == horizontal.id
    assert cargar(vertical.id).original is None


def test_mismo_nombre_otra_carpeta_no_pisa_salidas(tmp_path):
    salida = tmp_path / "salida"
    a = _archivo(tmp_path / "a" / "x.mov")
    b = _archivo(tmp_path / "b" / "x.mov", b"otro video")

    primera, _ = reconocer(a, salida)
    segunda, _ = reconocer(b, salida)
    tercera, _ = reconocer(_archivo(tmp_path / "c" / "x.mov", b"y otro"), salida)

    assert primera.nombre == "x"
    assert segunda.nombre == "x (2)"
    assert segunda.ruta_final(True).name == "x (2)_limpio.mp4"
    assert tercera.nombre == "x (3)"
    # Volver a arrastrar cada uno devuelve su ficha, no crea más.
    assert reconocer(b, salida)[0].id == segunda.id
    assert len(todas()) == 3


def test_mismo_nombre_en_carpetas_de_salida_distintas_no_se_renombra(tmp_path):
    a, _ = reconocer(_archivo(tmp_path / "a" / "x.mov"), tmp_path / "sa")
    b, _ = reconocer(_archivo(tmp_path / "b" / "x.mov", b"otro"), tmp_path / "sb")

    assert a.nombre == b.nombre == "x"


def test_ficha_nueva_no_pisa_un_vertical_unico_de_otra(tmp_path):
    # `x_vertical.mp4` de una ficha con original es salida de esa ficha.
    salida = tmp_path / "salida"
    primera, _ = reconocer(_archivo(tmp_path / "a" / "x.mov"), salida)
    vertical = _archivo(salida / "x_vertical.mp4")
    primera.final = Huella.de(vertical)
    guardar(primera)

    segunda, _ = reconocer(_archivo(tmp_path / "b" / "x.mov", b"otro"), salida)

    assert segunda.nombre == "x (2)"


@pytest.mark.parametrize("artefactos, esperado", [
    ({}, []),
    ({BASE: Artefacto("k", None, {})}, []),
    ({BASE: Artefacto("k", None, {"audio": {}})}, ["audio"]),
    ({BASE: Artefacto("k", None, {"silencios": {}})}, ["silencios"]),
    ({BASE: Artefacto("k", None, {"audio": {}, "silencios": {}})},
     ["audio", "silencios"]),
    ({HORIZONTAL: Artefacto("k", None, {"subtitulos": {}})}, ["subtitulos"]),
    ({HORIZONTAL: Artefacto("k", None, {})}, []),
    ({VERTICAL: Artefacto("k", "v.mp4", {"subtitulos": {}})},
     ["subtitulos", "vertical"]),
    ({HORIZONTAL: Artefacto("k", None, {}),
      VERTICAL: Artefacto("k", "v.mp4", {"subtitulos": {}})}, ["vertical"]),
    ({VERTICAL: Artefacto("k", "v.mp4", {})}, ["vertical"]),
    ({CAPTION: Artefacto("k", "caption.md")}, ["caption"]),
    ({SEGUIMIENTO: Artefacto("k", "s.json")}, []),
    ({
        BASE: Artefacto("k", None, {"audio": {}, "silencios": {}}),
        HORIZONTAL: Artefacto("k", None, {"subtitulos": {}}),
        CAPTION: Artefacto("k", "caption.md"),
        VERTICAL: Artefacto("k", "v.mp4", {}),
    }, list(PASOS)),
])
def test_pasos_hechos_segun_artefactos(tmp_path, artefactos, esperado):
    ficha = Ficha(id="p", nombre="x", carpeta_salida=tmp_path,
                  artefactos=artefactos)

    assert ficha.pasos_hechos() == esperado


def test_rutas_de_salida_de_una_ficha_nueva(tmp_path):
    ficha = Ficha(id="p", nombre="x", carpeta_salida=tmp_path)

    assert not ficha.hay_horizontal()
    assert ficha.ruta_final(True) == tmp_path / "x_limpio.mp4"
    assert ficha.ruta_final(False) == tmp_path / "x_vertical.mp4"
    assert ficha.ruta_vertical() == tmp_path / "x_limpio_vertical.mp4"
    assert ficha.carpeta == modulo.DIR_FICHAS / "p"
    assert ficha.ruta("caption.md") == modulo.DIR_FICHAS / "p" / "caption.md"


def test_hay_horizontal_con_artefacto_horizontal(tmp_path):
    ficha = Ficha(id="p", nombre="x", carpeta_salida=tmp_path,
                  artefactos={HORIZONTAL: Artefacto("k", None)})

    assert ficha.hay_horizontal()


def test_olvidar_borra_la_carpeta_y_no_las_salidas(tmp_path):
    video = _archivo(tmp_path / "charla.mov")
    ficha, _ = reconocer(video, None)
    salida = _archivo(tmp_path / "charla_limpio.mp4")
    md = _archivo(tmp_path / "charla_limpio.md")
    _archivo(ficha.ruta("transcripcion.json"), b"[]")

    olvidar(ficha)
    olvidar(ficha)  # olvidar dos veces no falla

    assert not ficha.carpeta.exists()
    assert cargar(ficha.id) is None
    assert video.exists() and salida.exists() and md.exists()


def test_cambiar_carpeta_no_mueve_fichas_existentes(tmp_path):
    video = _archivo(tmp_path / "charla.mov")
    primera, _ = reconocer(video, tmp_path / "salida_vieja")

    segunda, aviso = reconocer(video, tmp_path / "salida_nueva")

    assert segunda.id == primera.id
    assert aviso == ""
    assert segunda.carpeta_salida == tmp_path / "salida_vieja"


def test_ocupa_suma_los_bytes_de_la_carpeta(tmp_path):
    ficha, _ = reconocer(_archivo(tmp_path / "charla.mov"), None)
    _archivo(ficha.ruta("audio.flac"), b"a" * 100)
    _archivo(ficha.ruta("tmp/x.wav"), b"b" * 50)

    assert ocupa(ficha) == 150 + ficha.ruta("ficha.json").stat().st_size


def test_limpiar_temporales_borra_tmp_y_ocultos_de_sus_salidas(tmp_path):
    ficha, _ = reconocer(_archivo(tmp_path / "charla.mov"), None)
    _archivo(ficha.ruta("tmp/_original.wav"))
    _archivo(ficha.ruta("audio.flac"))
    real = _archivo(tmp_path / "charla_limpio.mp4")
    ocultos = [
        _archivo(tmp_path / ".charla_limpio_tmp.mp4"),
        _archivo(tmp_path / ".charla_limpio_subs_tmp.mp4"),
        _archivo(tmp_path / ".charla_limpio_vertical_tmp.mp4"),
    ]
    ajeno = _archivo(tmp_path / ".otro_tmp.mp4")

    limpiar_temporales(ficha)
    limpiar_temporales(ficha)  # sin nada que borrar tampoco falla

    assert not ficha.ruta("tmp").exists()
    assert not any(o.exists() for o in ocultos)
    assert ficha.ruta("audio.flac").exists() and ficha.ruta("ficha.json").exists()
    assert real.exists() and ajeno.exists()


def test_leer_srt_reparte_palabras_en_el_bloque(tmp_path):
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhola mundo\n",
                   encoding="utf-8")

    assert leer_srt(srt) == [Palabra("hola", 0.0, 0.5), Palabra("mundo", 0.5, 1.0)]


def test_leer_srt_ida_y_vuelta_con_varios_bloques(tmp_path):
    srt = tmp_path / "s.srt"
    bloques = [
        Bloque([Palabra("uno", 0.0, 0.5)], 0.0, 0.5),
        Bloque([Palabra("dos", 61.25, 62.0), Palabra("tres", 62.0, 62.5)],
               61.25, 62.5),
    ]
    generar_srt(bloques, srt)

    palabras = leer_srt(srt)

    assert [p.texto for p in palabras] == ["uno", "dos", "tres"]
    assert palabras[1].inicio == pytest.approx(61.25)
    assert palabras[2].fin == pytest.approx(62.5)


def test_leer_srt_acepta_bom_y_saltos_de_windows(tmp_path):
    srt = tmp_path / "s.srt"
    srt.write_bytes("﻿1\r\n00:00:01,000 --> 00:00:02,000\r\nhola\r\n".encode())

    assert leer_srt(srt) == [Palabra("hola", 1.0, 2.0)]


def test_leer_srt_ilegible_devuelve_lista_vacia(tmp_path):
    basura = tmp_path / "b.srt"
    basura.write_bytes(b"\xff\xfe\x00 no es texto \x80")

    assert leer_srt(tmp_path / "no_existe.srt") == []
    assert leer_srt(basura) == []
    assert leer_srt(_archivo(tmp_path / "t.srt", b"sin tiempos")) == []
