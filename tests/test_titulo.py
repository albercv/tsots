from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from videopipeline import steps
from videopipeline.titulo import (
    ANCHO_CARACTER,
    ANCHO_UTIL,
    BORDE_DORADO,
    DESPLAZAMIENTO,
    lineas_titulo,
)

ASS = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 320
PlayResY: 240

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Titan One,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,HOLA
"""


@pytest.mark.slow
def test_quema_real_usa_la_fuente_del_repo(tmp_path, monkeypatch):
    try:
        ffmpeg = steps.ffmpeg_con_ass()
    except steps.PasoFallido:
        pytest.skip("ffmpeg sin libass")
    # Ruta con espacio, comilla y coma: ejercita el escape de dos niveles.
    copia = tmp_path / "a b'c,d"
    shutil.copytree(steps.DIR_FUENTES, copia)
    monkeypatch.setattr(steps, "DIR_FUENTES", copia)
    (tmp_path / "t.ass").write_text(ASS, encoding="utf-8")
    resultado = subprocess.run(
        [ffmpeg, "-hide_banner",
         # libass solo cuenta qué fuente carga y elige en `verbose`.
         "-loglevel", "verbose", "-y",
         "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=1",
         "-vf", steps.filtro_ass("t.ass"),
         "-frames:v", "1", "salida.png"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert resultado.returncode == 0, resultado.stderr[-2000:]
    # La línea `fontselect` solo nombra la fuente elegida (TitanOne); que salga
    # del repo lo prueba la línea de carga del fichero dentro de la copia.
    assert f"Loading font file '{copia}/TitanOne-Regular.ttf'" in resultado.stderr
    assert re.search(r"fontselect: \(Titan One, \d+, \d+\) -> TitanOne",
                     resultado.stderr)


def _estilo(linea: str) -> list[str]:
    return linea.split(":", 1)[1].strip().split(",")


def _texto(evento: str) -> str:
    return re.sub(r"^\{[^}]*\}", "", evento.split(",", 9)[9])


def _ancho_en_fs(n: int) -> float:
    return n * ANCHO_CARACTER + 2 * BORDE_DORADO + DESPLAZAMIENTO


def test_dos_capas_arriba_centradas():
    estilos, eventos = lineas_titulo("Audio limpio ya", (1920, 1080))
    assert [_estilo(e)[0] for e in estilos] == ["TituloDorado", "Titulo"]
    assert all(_estilo(e)[1] == "Titan One" and _estilo(e)[2] == "76"
               and _estilo(e)[18] == "8" for e in estilos)
    assert eventos[0].startswith(
        "Dialogue: 0,0:00:00.00,0:00:05.00,TituloDorado,")
    assert "\\pos(965,91)" in eventos[0]
    assert eventos[1].startswith("Dialogue: 1,0:00:00.00,0:00:05.00,Titulo,")
    assert "\\an8\\pos(960,86)\\fad(300,300)" in eventos[1]
    assert _texto(eventos[0]) == _texto(eventos[1]) == "AUDIO LIMPIO YA"


def test_vertical_usa_su_tamano():
    estilos, eventos = lineas_titulo("Audio limpio ya", (1080, 1920))
    assert _estilo(estilos[1])[2] == "106"
    assert "\\pos(540,154)" in eventos[1]


def test_largo_parte_en_dos_y_cabe():
    estilos, eventos = lineas_titulo(
        "Inteligencia artificial para limpiar audio", (1080, 1920))
    texto = _texto(eventos[1])
    assert "\\N" in texto
    n = max(len(linea) for linea in texto.split("\\N"))
    fs = int(_estilo(estilos[1])[2])
    assert _ancho_en_fs(n) * fs <= ANCHO_UTIL * 1080


def test_palabra_sola_larguisima_reduce_la_letra():
    estilos, eventos = lineas_titulo("Supercalifragilisticoespialidoso",
                                     (1080, 1920))
    texto = _texto(eventos[1])
    fs = int(_estilo(estilos[1])[2])
    assert "\\N" not in texto
    assert _ancho_en_fs(len(texto)) * fs <= ANCHO_UTIL * 1080
    assert fs >= 8


def test_quita_llaves_y_barras():
    _, eventos = lineas_titulo("{\\b1}Hola\\N mundo raro", (1920, 1080))
    texto = _texto(eventos[1])
    assert "{" not in texto and "}" not in texto
    assert texto.replace("\\N", "").count("\\") == 0


def test_inicio_y_duracion():
    _, eventos = lineas_titulo("Hola", (1920, 1080), inicio=12.5, duracion=5.0)
    assert all("0:00:12.50,0:00:17.50" in e for e in eventos)


def test_texto_vacio_no_da_nada():
    assert lineas_titulo("  {} ", (1920, 1080)) == ([], [])
