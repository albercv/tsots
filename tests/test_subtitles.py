from __future__ import annotations

from pathlib import Path

import pytest

from videopipeline.subtitles import (
    PRESETS,
    Bloque,
    Palabra,
    agrupar,
    generar_ass,
    generar_srt,
)


def _palabras(*tuplas) -> list[Palabra]:
    return [Palabra(texto=t, inicio=i, fin=f) for t, i, f in tuplas]


def test_presets_definidos():
    assert set(PRESETS) == {"reels_bold", "reels_karaoke", "caja", "impacto",
                            "amarillo", "karaoke_verde", "minimal",
                            "caja_blanca"}
    assert PRESETS["reels_bold"].tipo == "palabras"
    assert PRESETS["reels_karaoke"].resaltado == "&H000AD6FF"
    assert PRESETS["caja"].tipo == "frases"
    assert PRESETS["caja"].borde_estilo == 3
    assert PRESETS["caja"].fondo == "&H59000000"


def test_agrupar_reels_max_tres_palabras():
    palabras = _palabras(
        ("hola", 0.0, 0.3), ("qué", 0.35, 0.5), ("tal", 0.55, 0.8),
        ("estás", 0.85, 1.1), ("hoy", 1.15, 1.4),
    )
    bloques = agrupar(palabras, "reels_bold")
    assert [len(b.palabras) for b in bloques] == [3, 2]
    assert bloques[0].texto == "hola qué tal"
    assert bloques[0].inicio == 0.0
    assert bloques[1].inicio == 0.85


def test_agrupar_reels_corta_en_pausa():
    palabras = _palabras(("uno", 0.0, 0.3), ("dos", 1.5, 1.8), ("tres", 1.9, 2.1))
    bloques = agrupar(palabras, "reels_bold")
    # Pausa de 1.2s entre "uno" y "dos" > PAUSA_CORTE → bloque nuevo.
    assert [b.texto for b in bloques] == ["uno", "dos tres"]


def test_agrupar_frases_corta_en_puntuacion():
    palabras = _palabras(
        ("Hola.", 0.0, 0.4), ("Esto", 0.5, 0.7), ("sigue", 0.75, 1.0),
    )
    bloques = agrupar(palabras, "caja")
    assert [b.texto for b in bloques] == ["Hola.", "Esto sigue"]


def test_agrupar_frases_limite_caracteres():
    larga = [(f"palabra{i}", i * 0.3, i * 0.3 + 0.25) for i in range(20)]
    bloques = agrupar(_palabras(*larga), "caja")
    assert all(len(b.texto) <= 84 for b in bloques)
    assert len(bloques) >= 2


def test_duracion_minima_de_bloque():
    bloques = agrupar(_palabras(("sí", 0.0, 0.1)), "reels_bold")
    assert bloques[0].fin - bloques[0].inicio >= 0.5


def test_agrupar_sin_solapes():
    palabras = _palabras(
        ("a", 0.0, 0.05), ("b", 0.10, 0.15), ("c", 0.20, 0.25),
        ("d", 0.30, 0.35),
    )
    bloques = agrupar(palabras, "reels_bold")
    assert len(bloques) == 2
    assert bloques[0].fin <= bloques[1].inicio
    # El último bloque sí conserva el estirado de duración mínima.
    assert bloques[1].fin - bloques[1].inicio >= 0.5


def test_envolver_equilibrado():
    from videopipeline.subtitles import _envolver

    texto = "abc " + "palabra " * 8  # >42 chars, muchos puntos de corte
    resultado = _envolver(texto.strip())
    lineas = resultado.split("\\N")
    assert len(lineas) == 2
    assert all(len(l) <= 42 for l in lineas)


def test_envolver_sin_espacios_no_rompe():
    from videopipeline.subtitles import _envolver

    assert _envolver("x" * 50) == "x" * 50


def test_generar_srt(tmp_path):
    bloques = [
        Bloque(palabras=_palabras(("hola", 0.0, 0.5)), inicio=0.0, fin=0.5),
        Bloque(palabras=_palabras(("adiós", 61.25, 62.0)), inicio=61.25, fin=62.0),
    ]
    ruta = tmp_path / "s.srt"
    generar_srt(bloques, ruta)
    contenido = ruta.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:00,500\nhola\n" in contenido
    assert "2\n00:01:01,250 --> 00:01:02,000\nadiós\n" in contenido


def test_generar_ass_reels_margen_y_mayusculas(tmp_path):
    bloques = [Bloque(palabras=_palabras(("hola", 0.0, 1.0)), inicio=0.0, fin=1.0)]
    ruta = tmp_path / "s.ass"
    generar_ass(bloques, "reels_bold", 75, (1080, 1920), ruta)
    contenido = ruta.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in contenido and "PlayResY: 1920" in contenido
    # MarginV = 1920 * (100-75)/100 = 480
    linea_estilo = next(l for l in contenido.splitlines() if l.startswith("Style:"))
    assert ",480," in linea_estilo
    assert "HOLA" in contenido  # mayúsculas
    assert "Dialogue: 0,0:00:00.00,0:00:01.00," in contenido


def test_generar_ass_karaoke_un_evento_por_palabra(tmp_path):
    bloques = [
        Bloque(
            palabras=_palabras(("mira", 0.0, 0.4), ("esto", 0.4, 0.9)),
            inicio=0.0, fin=0.9,
        )
    ]
    ruta = tmp_path / "s.ass"
    generar_ass(bloques, "reels_karaoke", 75, (1080, 1920), ruta)
    dialogos = [l for l in ruta.read_text(encoding="utf-8").splitlines()
                if l.startswith("Dialogue:")]
    assert len(dialogos) == 2  # un evento por palabra
    # Primera palabra activa coloreada, la otra en primario.
    assert "{\\c&H000AD6FF&}MIRA{\\c&H00FFFFFF&}" in dialogos[0]
    assert "ESTO" in dialogos[0]
    assert "{\\c&H000AD6FF&}ESTO{\\c&H00FFFFFF&}" in dialogos[1]


def test_generar_ass_caja_envuelve_lineas(tmp_path):
    texto_largo = [(f"pal{i}", i * 0.2, i * 0.2 + 0.15) for i in range(12)]
    bloques = agrupar(_palabras(*texto_largo), "caja")
    ruta = tmp_path / "s.ass"
    generar_ass(bloques, "caja", 75, (1920, 1080), ruta)
    contenido = ruta.read_text(encoding="utf-8")
    dialogos = [l for l in contenido.splitlines() if l.startswith("Dialogue:")]
    # Bloques largos parten en dos líneas con \N.
    assert any("\\N" in d for d in dialogos)
    # Sin transformación a mayúsculas en caja.
    assert "PAL0" not in contenido


def test_generar_ass_preset_desconocido(tmp_path):
    with pytest.raises(KeyError):
        generar_ass([], "neon", 75, (100, 100), tmp_path / "s.ass")


from types import SimpleNamespace

from videopipeline import subtitles
from videopipeline.subtitles import transcribir


class WhisperFalso:
    def __init__(self, segmentos):
        self._segmentos = segmentos
        self.kwargs = None

    def transcribe(self, ruta, **kwargs):
        self.kwargs = kwargs
        return iter(self._segmentos), SimpleNamespace(language="es")


def _segmento(*palabras):
    return SimpleNamespace(
        words=[SimpleNamespace(word=t, start=i, end=f) for t, i, f in palabras]
    )


def test_transcribir_devuelve_palabras(tmp_path, monkeypatch):
    falso = WhisperFalso([_segmento((" hola", 0.0, 0.4), ("mundo ", 0.5, 0.9))])
    monkeypatch.setattr(subtitles, "usa_mlx", lambda: False)
    monkeypatch.setattr(subtitles, "_crear_whisper", lambda modelo: falso)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"VID")
    palabras = transcribir(video, "es", "small")
    assert [p.texto for p in palabras] == ["hola", "mundo"]
    assert palabras[0].inicio == 0.0 and palabras[1].fin == 0.9
    assert falso.kwargs["language"] == "es"
    assert falso.kwargs["word_timestamps"] is True
    assert falso.kwargs["vad_filter"] is True


def test_transcribir_auto_pasa_none(tmp_path, monkeypatch):
    falso = WhisperFalso([])
    monkeypatch.setattr(subtitles, "usa_mlx", lambda: False)
    monkeypatch.setattr(subtitles, "_crear_whisper", lambda modelo: falso)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"VID")
    assert transcribir(video, "auto", "small") == []
    assert falso.kwargs["language"] is None


def test_transcribir_ignora_segmentos_sin_words(tmp_path, monkeypatch):
    seg_sin = SimpleNamespace(words=None)
    falso = WhisperFalso([seg_sin, _segmento(("ok", 0.0, 0.2))])
    monkeypatch.setattr(subtitles, "usa_mlx", lambda: False)
    monkeypatch.setattr(subtitles, "_crear_whisper", lambda modelo: falso)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"VID")
    assert [p.texto for p in transcribir(video, "es", "small")] == ["ok"]


def _fontsize_de(contenido: str) -> int:
    linea = next(l for l in contenido.splitlines() if l.startswith("Style:"))
    return int(linea.split(",")[2])


def test_generar_ass_tamano_escala(tmp_path):
    bloques = [Bloque(palabras=_palabras(("hola", 0.0, 1.0)), inicio=0.0, fin=1.0)]
    ruta100 = tmp_path / "s100.ass"
    ruta150 = tmp_path / "s150.ass"
    generar_ass(bloques, "reels_bold", 75, (1080, 1920), ruta100, tamano=100)
    generar_ass(bloques, "reels_bold", 75, (1080, 1920), ruta150, tamano=150)
    f100 = _fontsize_de(ruta100.read_text(encoding="utf-8"))
    f150 = _fontsize_de(ruta150.read_text(encoding="utf-8"))
    assert f100 == int(1920 * 0.075)
    assert f150 == int(1920 * 0.075 * 1.5)


def test_generar_ass_antidesborde_aplica_fs(tmp_path):
    # Vídeo estrecho + texto largo a tamaño grande → override \fs que cabe.
    from videopipeline.subtitles import ANCHO_CARACTER, MARGEN_LATERAL

    palabras = _palabras(
        ("palabralarga", 0.0, 0.3), ("otralarga", 0.35, 0.7), ("mas", 0.75, 1.0)
    )
    bloques = agrupar(palabras, "reels_bold")
    ruta = tmp_path / "s.ass"
    generar_ass(bloques, "reels_bold", 75, (480, 854), ruta, tamano=150)
    contenido = ruta.read_text(encoding="utf-8")
    dialogos = [l for l in contenido.splitlines() if l.startswith("Dialogue:")]
    assert any("{\\fs" in d for d in dialogos)
    # El fs reducido cabe en el ancho útil.
    import re

    fs = int(re.search(r"\\fs(\d+)", contenido).group(1))
    texto = "PALABRALARGA OTRALARGA MAS"
    assert len(texto) * ANCHO_CARACTER * fs <= 480 - 2 * MARGEN_LATERAL


def test_generar_ass_texto_corto_sin_override(tmp_path):
    bloques = [Bloque(palabras=_palabras(("sí", 0.0, 1.0)), inicio=0.0, fin=1.0)]
    ruta = tmp_path / "s.ass"
    generar_ass(bloques, "reels_bold", 75, (1080, 1920), ruta, tamano=100)
    assert "\\fs" not in ruta.read_text(encoding="utf-8")


def test_generar_ass_tamano_defecto_retrocompatible(tmp_path):
    # Sin pasar tamano, mismo resultado que antes (100%).
    bloques = [Bloque(palabras=_palabras(("hola", 0.0, 1.0)), inicio=0.0, fin=1.0)]
    ruta = tmp_path / "s.ass"
    generar_ass(bloques, "reels_bold", 75, (1080, 1920), ruta)
    assert _fontsize_de(ruta.read_text(encoding="utf-8")) == int(1920 * 0.075)


# --- estilos añadidos --------------------------------------------------------

def test_estilos_nuevos_tienen_rasgos_propios():
    assert PRESETS["impacto"].fuente == "Impact"
    assert PRESETS["amarillo"].primario == "&H0000D4FF"
    assert PRESETS["karaoke_verde"].resaltado == "&H006BE62E"
    assert PRESETS["minimal"].tipo == "frases" and not PRESETS["minimal"].mayusculas
    assert PRESETS["caja_blanca"].borde_estilo == 3
    assert PRESETS["caja_blanca"].primario == "&H00000000"


def test_ningun_estilo_duplica_otro():
    firmas = [tuple(vars(p).values()) for p in PRESETS.values()]
    assert len(firmas) == len(set(firmas))


@pytest.mark.parametrize("preset_id", sorted(PRESETS))
def test_cada_estilo_genera_ass_valido(tmp_path, preset_id):
    palabras = _palabras(("hola", 0.0, 0.4), ("qué", 0.5, 0.8),
                         ("tal", 0.9, 1.2), ("estás.", 1.3, 1.8))
    bloques = agrupar(palabras, preset_id)
    ruta = tmp_path / f"{preset_id}.ass"
    generar_ass(bloques, preset_id, 75, (1080, 1920), ruta)
    texto = ruta.read_text(encoding="utf-8")
    assert f"Style: Sub,{PRESETS[preset_id].fuente}," in texto
    assert "Dialogue:" in texto


# --- mlx-whisper (GPU) y respaldo ----------------------------------------------

def _mlx_falso(monkeypatch, segmentos):
    llamadas = []

    def transcribe(audio, **kwargs):
        llamadas.append((audio, kwargs))
        return {"text": "", "segments": segmentos, "language": "es"}

    monkeypatch.setattr(subtitles, "usa_mlx", lambda: True)
    monkeypatch.setattr(subtitles, "_cargar_audio", lambda video: "AUDIO")
    monkeypatch.setattr(subtitles, "_mlx_transcribe", transcribe)
    return llamadas


def test_transcribir_mlx_devuelve_palabras(tmp_path, monkeypatch):
    llamadas = _mlx_falso(monkeypatch, [
        {"words": [{"word": " hola", "start": 0.0, "end": 0.4},
                   {"word": "mundo ", "start": 0.5, "end": 0.9}]},
        {"words": []},
        {},
    ])
    palabras = transcribir(tmp_path / "v.mp4", "es", "turbo")
    assert [p.texto for p in palabras] == ["hola", "mundo"]
    assert palabras[1].fin == 0.9
    audio, kwargs = llamadas[0]
    assert audio == "AUDIO"
    assert kwargs["path_or_hf_repo"] == "mlx-community/whisper-large-v3-turbo"
    assert kwargs["language"] == "es"
    assert kwargs["word_timestamps"] is True


def test_transcribir_mlx_auto_pasa_none(tmp_path, monkeypatch):
    llamadas = _mlx_falso(monkeypatch, [])
    assert transcribir(tmp_path / "v.mp4", "auto", "small") == []
    assert llamadas[0][1]["language"] is None
    assert llamadas[0][1]["path_or_hf_repo"] == "mlx-community/whisper-small-mlx"


def test_respaldo_faster_whisper_traduce_turbo(tmp_path, monkeypatch):
    creados = []
    monkeypatch.setattr(subtitles, "usa_mlx", lambda: False)
    monkeypatch.setattr(subtitles, "_crear_whisper",
                        lambda modelo: creados.append(modelo) or WhisperFalso([]))
    transcribir(tmp_path / "v.mp4", "es", "turbo")
    assert creados == ["large-v3-turbo"]


def test_todos_los_modelos_tienen_repo_y_tamano():
    from videopipeline.config import MODELOS_WHISPER

    for m in MODELOS_WHISPER:
        assert m in subtitles.MODELOS_MLX
        assert m in subtitles.MODELOS_FASTER
        assert m in subtitles.TAMANO_DESCARGA


def test_modelo_en_cache_segun_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(subtitles, "usa_mlx", lambda: True)
    assert not subtitles.modelo_en_cache("turbo", tmp_path)
    (tmp_path / "models--mlx-community--whisper-large-v3-turbo").mkdir()
    assert subtitles.modelo_en_cache("turbo", tmp_path)

    monkeypatch.setattr(subtitles, "usa_mlx", lambda: False)
    assert not subtitles.modelo_en_cache("turbo", tmp_path)
    (tmp_path / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo").mkdir()
    assert subtitles.modelo_en_cache("turbo", tmp_path)
    assert not subtitles.modelo_en_cache("small", tmp_path / "no-existe")
