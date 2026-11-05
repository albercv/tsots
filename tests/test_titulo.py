from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from videopipeline import steps

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
