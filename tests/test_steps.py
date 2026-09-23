from __future__ import annotations

import shutil
import stat
import subprocess
import wave
from pathlib import Path

import pytest

from videopipeline import steps
from videopipeline.steps import (
    PasoFallido,
    cmd_cortar_silencios,
    cmd_extraer_audio,
    cmd_remux,
    comprobar_dependencias,
    cortar_silencios,
    extraer_audio,
    limpiar_audio,
    remux,
    tiene_pista_audio,
)


def test_cmd_extraer_audio():
    cmd = cmd_extraer_audio("ffmpeg", Path("v.mp4"), Path("a.wav"), 48000)
    assert cmd[0] == "ffmpeg"
    assert "-ar" in cmd and cmd[cmd.index("-ar") + 1] == "48000"
    assert cmd[-1] == "a.wav"
    assert "-ac" in cmd and cmd[cmd.index("-ac") + 1] == "1"
    assert "pcm_s16le" in cmd
    # Huecos y arranque tardío del audio se rellenan con silencio.
    assert cmd[cmd.index("-af") + 1] == (
        "aresample=async=1:min_hard_comp=0.01:first_pts=0"
    )


def test_cmd_remux():
    cmd = cmd_remux("ffmpeg", Path("v.mp4"), Path("a.wav"), Path("o.mp4"))
    assert "copy" in cmd  # vídeo copiado
    assert "aac" in cmd and "192k" in cmd
    assert "+faststart" in cmd


def test_extraer_audio_rellena_arranque_tardio_y_huecos(tmp_path):
    """El iPhone graba audio que empieza tarde y con cortes entre paquetes.
    El WAV debe conservar esos silencios; si los colapsa, la voz se adelanta
    al vídeo cada vez más (gptDown.MOV: 0,31 s al final). El hueco es menor
    que el umbral por defecto de aresample (0,1 s), como los reales."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg no disponible")
    video = tmp_path / "huecos.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=black:s=160x120:d=3:r=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         # Audio desde 0,3 s y con un salto de 0,08 s en el segundo 1.
         "-af", "asetpts='PTS+0.3/TB+if(gte(T,1),0.08/TB,0)'",
         "-c:v", "libx264", "-c:a", "aac", str(video)],
        check=True,
    )
    wav = tmp_path / "a.wav"
    extraer_audio(video, wav, 16000)
    with wave.open(str(wav)) as w:
        duracion = w.getnframes() / w.getframerate()
    assert duracion == pytest.approx(2.38, abs=0.025)  # sin relleno: 2,0 s


def test_cmd_cortar_silencios_cortar():
    cmd = cmd_cortar_silencios(
        "auto-editor", Path("i.mp4"), Path("o.mp4"), "0.3s", "6%", "cortar", 4
    )
    assert cmd[:2] == ["auto-editor", "i.mp4"]
    assert "--margin" in cmd and cmd[cmd.index("--margin") + 1] == "0.3s"
    assert "--edit" in cmd and cmd[cmd.index("--edit") + 1] == "audio:threshold=6%"
    assert "--when-silent" not in cmd


def test_cmd_cortar_silencios_acelerar():
    cmd = cmd_cortar_silencios(
        "auto-editor", Path("i.mp4"), Path("o.mp4"), "0.2s", "4%", "acelerar", 8
    )
    assert "--when-silent" in cmd
    assert cmd[cmd.index("--when-silent") + 1] == "speed:8"


def test_cortar_silencios_progreso_formato_tilde(tmp_path, monkeypatch):
    """auto-editor 31.2.0 --progress machine no emite '%'; emite líneas
    separadas por '~' como: '(mp4) h264+aac~1497.0~1801.0~0.06'.
    Se usa un ejecutable falso (no el binario real) para comprobar que
    cortar_silencios interpreta ese formato y llama a on_percent."""
    fake = tmp_path / "fake_auto_editor.py"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "argv = sys.argv[1:]\n"
        "salida = None\n"
        "for i, a in enumerate(argv):\n"
        "    if a == '-o':\n"
        "        salida = argv[i + 1]\n"
        "print('(mp4) h264+aac~50.0~200.0~0.01', flush=True)\n"
        "print('(mp4) h264+aac~200.0~200.0~0.04', flush=True)\n"
        "if salida:\n"
        "    with open(salida, 'wb') as f:\n"
        "        f.write(b'FAKEOUTPUT')\n"
        "sys.exit(0)\n"
    )
    modo = fake.stat().st_mode
    fake.chmod(modo | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    monkeypatch.setattr(steps, "_binario", lambda nombre: str(fake))

    entrada = tmp_path / "in.mp4"
    entrada.write_bytes(b"fake video")
    salida = tmp_path / "out.mp4"

    porcentajes: list[float] = []
    cortar_silencios(
        entrada, salida, "0.3s", "6%", "cortar", 4, on_percent=porcentajes.append
    )

    assert 25.0 in porcentajes
    assert 100.0 in porcentajes
    assert salida.is_file() and salida.stat().st_size > 0


def test_comprobar_dependencias_devuelve_lista():
    faltantes = comprobar_dependencias()
    if faltantes:
        pytest.skip(f"faltan: {faltantes}")
    assert faltantes == []


def test_extraer_audio_real(video_sintetico, tmp_path):
    wav = tmp_path / "a.wav"
    extraer_audio(video_sintetico, wav, 16000)
    with wave.open(str(wav)) as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1


def test_extraer_audio_fallo(tmp_path):
    with pytest.raises(PasoFallido):
        extraer_audio(tmp_path / "no_existe.mp4", tmp_path / "a.wav", 16000)


def test_remux_real(video_sintetico, tmp_path):
    wav = tmp_path / "a.wav"
    extraer_audio(video_sintetico, wav, 48000)
    salida = tmp_path / "remux.mp4"
    remux(video_sintetico, wav, salida)
    assert salida.is_file() and salida.stat().st_size > 0
    assert tiene_pista_audio(salida)


def test_tiene_pista_audio(video_sintetico, video_sin_audio):
    assert tiene_pista_audio(video_sintetico) is True
    assert tiene_pista_audio(video_sin_audio) is False


class ClearVoiceFalso:
    def __init__(self):
        self.llamadas = []

    def __call__(self, input_path, online_write):
        self.llamadas.append(("call", input_path, online_write))
        return "AUDIO"

    def write(self, audio, output_path):
        self.llamadas.append(("write", audio, output_path))
        Path(output_path).write_bytes(b"RIFFfake")


def test_limpiar_audio_usa_factoria(tmp_path, monkeypatch):
    falso = ClearVoiceFalso()
    capturado = {}

    def factoria(tarea, modelo):
        capturado["args"] = (tarea, modelo)
        return falso

    monkeypatch.setattr(steps, "_crear_clearvoice", factoria)
    entrada = tmp_path / "in.wav"
    entrada.write_bytes(b"RIFF")
    salida = tmp_path / "out.wav"
    limpiar_audio(entrada, salida, "speech_enhancement", "MossFormer2_SE_48K")
    assert capturado["args"] == ("speech_enhancement", "MossFormer2_SE_48K")
    assert salida.is_file()


def test_limpiar_audio_separacion_recoge_s1(tmp_path, monkeypatch):
    class FalsoSeparacion(ClearVoiceFalso):
        def write(self, audio, output_path):
            base = Path(output_path)
            base.with_name(f"{base.stem}_s1{base.suffix}").write_bytes(b"RIFF1")
            base.with_name(f"{base.stem}_s2{base.suffix}").write_bytes(b"RIFF2")

    monkeypatch.setattr(steps, "_crear_clearvoice", lambda t, m: FalsoSeparacion())
    entrada = tmp_path / "in.wav"
    entrada.write_bytes(b"RIFF")
    salida = tmp_path / "out.wav"
    limpiar_audio(entrada, salida, "speech_separation", "MossFormer2_SS_16K")
    # El primer hablante pasa a ser la salida esperada.
    assert salida.is_file() and salida.read_bytes() == b"RIFF1"


from videopipeline.steps import (
    cmd_quemar_subtitulos,
    duracion_video,
    quemar_subtitulos,
    resolucion_video,
)


def test_cmd_quemar_subtitulos():
    cmd = cmd_quemar_subtitulos("ffmpeg", Path("/a/v.mp4"), "subs.ass",
                                Path("/a/o.mp4"))
    assert "-vf" in cmd and cmd[cmd.index("-vf") + 1] == "ass=subs.ass"
    assert "libx264" in cmd and "18" in cmd and "medium" in cmd
    assert "copy" in cmd
    assert "-progress" in cmd and "pipe:1" in cmd
    assert cmd[-1] == "/a/o.mp4"


def test_resolucion_y_duracion_video(video_sintetico):
    ancho, alto = resolucion_video(video_sintetico)
    assert (ancho, alto) == (160, 120)
    assert 1.5 < duracion_video(video_sintetico) < 2.5


def _mock_ffprobe(monkeypatch, stdout: str) -> None:
    import subprocess as sp

    def falso_run(cmd, **kwargs):
        return sp.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(steps.subprocess, "run", falso_run)
    monkeypatch.setattr(steps, "_binario", lambda n: n)


def test_resolucion_sin_rotacion(tmp_path, monkeypatch):
    _mock_ffprobe(monkeypatch, "width=1920\nheight=1080\n")
    assert resolucion_video(tmp_path / "v.mp4") == (1920, 1080)


def test_resolucion_con_rotacion_90(tmp_path, monkeypatch):
    _mock_ffprobe(monkeypatch, "width=1920\nheight=1080\nrotation=-90\n")
    assert resolucion_video(tmp_path / "v.mp4") == (1080, 1920)


def test_resolucion_con_rotacion_270(tmp_path, monkeypatch):
    _mock_ffprobe(monkeypatch, "width=1920\nheight=1080\nrotation=270\n")
    assert resolucion_video(tmp_path / "v.mp4") == (1080, 1920)


def test_resolucion_rotacion_180_no_intercambia(tmp_path, monkeypatch):
    _mock_ffprobe(monkeypatch, "width=1920\nheight=1080\nrotation=180\n")
    assert resolucion_video(tmp_path / "v.mp4") == (1920, 1080)


def test_resolucion_rotacion_decimal(tmp_path, monkeypatch):
    _mock_ffprobe(monkeypatch, "width=1920\nheight=1080\nrotation=-90.00\n")
    assert resolucion_video(tmp_path / "v.mp4") == (1080, 1920)


def test_resolucion_salida_corrupta(tmp_path, monkeypatch):
    _mock_ffprobe(monkeypatch, "basura sin igual\n")
    with pytest.raises(PasoFallido):
        resolucion_video(tmp_path / "v.mp4")


def test_duracion_video_con_coma_final(tmp_path, monkeypatch):
    import subprocess as sp

    def falso_run(cmd, **kwargs):
        return sp.CompletedProcess(cmd, 0, stdout="3.48,\n", stderr="")

    monkeypatch.setattr(steps.subprocess, "run", falso_run)
    monkeypatch.setattr(steps, "_binario", lambda n: n)
    assert duracion_video(tmp_path / "v.mp4") == 3.48


def test_resolucion_video_sin_pista(tmp_path):
    roto = tmp_path / "roto.mp4"
    roto.write_bytes(b"no es video")
    with pytest.raises(PasoFallido):
        resolucion_video(roto)


def test_ffmpeg_con_ass_disponible():
    """Verifica que ffmpeg con soporte ass esté disponible."""
    ffmpeg = steps.ffmpeg_con_ass()
    assert Path(ffmpeg).is_file()


def test_ffmpeg_con_ass_sin_candidatos(monkeypatch):
    """Verifica que se lanza error si no hay ffmpeg con ass disponible."""
    import shutil
    monkeypatch.setattr(steps, "_ffmpeg_ass_cache", None)
    monkeypatch.setattr(steps, "_RUTAS_FFMPEG_ASS", ())

    def fake_which(cmd):
        if cmd == "ffmpeg":
            return "/fake/ffmpeg"
        return None

    monkeypatch.setattr(shutil, "which", fake_which)

    def fake_run(cmd, **kwargs):
        import subprocess as sp
        return sp.CompletedProcess(
            cmd, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(steps.subprocess, "run", fake_run)

    with pytest.raises(PasoFallido, match="libass"):
        steps.ffmpeg_con_ass()


def test_ffmpeg_con_ass_memoizado(monkeypatch):
    """El segundo call no debe volver a sondear con subprocess."""
    monkeypatch.setattr(steps, "_ffmpeg_ass_cache", None)
    monkeypatch.setattr(steps, "_RUTAS_FFMPEG_ASS", (Path("/fake/ffmpeg"),))
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    llamadas = {"n": 0}

    def fake_run(cmd, **kwargs):
        import subprocess as sp
        llamadas["n"] += 1
        return sp.CompletedProcess(cmd, returncode=0, stdout=" ass ", stderr="")

    monkeypatch.setattr(steps.subprocess, "run", fake_run)

    primero = steps.ffmpeg_con_ass()
    segundo = steps.ffmpeg_con_ass()

    assert llamadas["n"] == 1
    assert primero == segundo == "/fake/ffmpeg"


def test_quemar_subtitulos_real(video_sintetico, tmp_path):
    """Quema subtítulos reales en un vídeo sintético."""
    ffmpeg_path = steps.ffmpeg_con_ass()

    ass = tmp_path / "subs.ass"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 160\nPlayResY: 120\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Sub,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,1,0,2,10,10,20,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.50,Sub,,0,0,0,,hola\n",
        encoding="utf-8",
    )
    salida = tmp_path / "con_subs.mp4"
    percents: list[float] = []
    quemar_subtitulos(video_sintetico, ass, salida, on_percent=percents.append)
    assert salida.is_file() and salida.stat().st_size > 0
    # En un clip de 2s, esperamos al menos un valor de progreso reportado
    assert percents
    assert all(0 <= p <= 100 for p in percents)


def test_quemar_subtitulos_fallo(tmp_path, video_sintetico):
    with pytest.raises(PasoFallido):
        quemar_subtitulos(
            video_sintetico, tmp_path / "no_existe.ass", tmp_path / "o.mp4"
        )


def _auto_editor_falso(tmp_path, cuerpo: str) -> Path:
    fake = tmp_path / "fake_auto_editor.py"
    fake.write_text("#!/usr/bin/env python3\nimport sys\n" + cuerpo)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return fake


_FALLA_SI_NO_NORMALIZADO = """
argv = sys.argv[1:]
entrada, salida = argv[0], argv[argv.index('-o') + 1]
if '_normalizado' not in entrada:
    print('(mp4) h264+aac~389.0~13944.0~28.51', flush=True)
    print('\\x1b[31mError! Could not write packet: Invalid argument '
          '(stream 0, pts 313600, dts 312000)\\x1b[0m', flush=True)
    sys.exit(1)
with open(salida, 'wb') as f:
    f.write(b'EDITADO')
sys.exit(0)
"""


def test_cmd_normalizar_video():
    cmd = steps.cmd_normalizar_video("ffmpeg", Path("i.mp4"), Path("o.mp4"))
    assert cmd[0] == "ffmpeg"
    assert "h264_videotoolbox" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert cmd[-1] == "o.mp4"


def test_cortar_silencios_reintenta_con_video_normalizado(
    video_sintetico, tmp_path, monkeypatch
):
    """auto-editor 31.x falla con 'Could not write packet' en ciertos H.264;
    reencodar la entrada lo arregla. El paso debe reintentar solo una vez,
    avisar de ello, y no dejar el temporal normalizado."""
    fake = _auto_editor_falso(tmp_path, _FALLA_SI_NO_NORMALIZADO)
    real_binario = steps._binario
    monkeypatch.setattr(
        steps, "_binario",
        lambda nombre: str(fake) if nombre == "auto-editor" else real_binario(nombre),
    )
    salida = tmp_path / "out.mp4"
    avisos: list[str] = []
    cortar_silencios(
        video_sintetico, salida, "0.2s", "4%", "cortar", 4, on_aviso=avisos.append
    )
    assert salida.read_bytes() == b"EDITADO"
    assert len(avisos) == 1 and "reencod" in avisos[0].lower()
    assert not list(video_sintetico.parent.glob("*_normalizado*"))
    assert not list(tmp_path.glob("*_normalizado*"))


def test_cortar_silencios_no_reintenta_otros_errores(tmp_path, monkeypatch):
    fake = _auto_editor_falso(
        tmp_path,
        "print('Error! Input file doesn\\'t exist', flush=True)\nsys.exit(1)\n",
    )

    def binario(nombre):
        if nombre == "ffmpeg":
            raise AssertionError("no debe normalizar ante otros errores")
        return str(fake)

    monkeypatch.setattr(steps, "_binario", binario)
    entrada = tmp_path / "in.mp4"
    entrada.write_bytes(b"fake")
    avisos: list[str] = []
    with pytest.raises(PasoFallido) as info:
        cortar_silencios(entrada, tmp_path / "o.mp4", "0.2s", "4%", "cortar", 4,
                         on_aviso=avisos.append)
    assert "Input file doesn't exist" in info.value.detalle
    assert avisos == []


def test_cortar_silencios_falla_si_persiste_tras_normalizar(
    video_sintetico, tmp_path, monkeypatch
):
    fake = _auto_editor_falso(
        tmp_path,
        "print('Error! Could not write packet: Invalid argument', flush=True)\n"
        "sys.exit(1)\n",
    )
    real_binario = steps._binario
    monkeypatch.setattr(
        steps, "_binario",
        lambda nombre: str(fake) if nombre == "auto-editor" else real_binario(nombre),
    )
    with pytest.raises(PasoFallido) as info:
        cortar_silencios(video_sintetico, tmp_path / "o.mp4", "0.2s", "4%",
                         "cortar", 4)
    assert "Could not write packet" in info.value.detalle
    assert "reencod" in str(info.value).lower()  # el mensaje dice que ya se intentó
