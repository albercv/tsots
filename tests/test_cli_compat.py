from __future__ import annotations

from pathlib import Path

import pytest

import limpiarAudio
import limpiarVideo
from videopipeline.steps import PasoFallido


def test_limpiar_video_defecto_junto_al_original(tmp_path, monkeypatch):
    video = tmp_path / "charla.mov"
    video.write_bytes(b"VID")
    capturado = {}

    def falso_run(config, on_progress=None):
        capturado["config"] = config
        return config.ruta_salida_final()

    monkeypatch.setattr(limpiarVideo, "run", falso_run)
    monkeypatch.setattr(limpiarVideo, "comprobar_dependencias", lambda: [])
    monkeypatch.setattr(limpiarVideo, "tiene_pista_audio", lambda v: True)
    limpiarVideo.main([str(video)])
    config = capturado["config"]
    assert config.modo == "completo"
    assert config.modelo == "MossFormer2_SE_48K"
    assert config.ruta_salida_final() == tmp_path / "charla_limpio.mp4"


def test_limpiar_video_salida_explicita(tmp_path, monkeypatch):
    video = tmp_path / "charla.mov"
    video.write_bytes(b"VID")
    salida = tmp_path / "sub" / "final.mp4"
    capturado = {}
    monkeypatch.setattr(
        limpiarVideo, "run",
        lambda c, on_progress=None: capturado.setdefault("c", c).ruta_salida_final(),
    )
    monkeypatch.setattr(limpiarVideo, "comprobar_dependencias", lambda: [])
    monkeypatch.setattr(limpiarVideo, "tiene_pista_audio", lambda v: True)
    limpiarVideo.main([str(video), str(salida)])
    assert capturado["c"].ruta_salida_final() == salida


def test_limpiar_video_sin_audio_sale_1(tmp_path, monkeypatch, capsys):
    video = tmp_path / "mudo.mp4"
    video.write_bytes(b"VID")
    monkeypatch.setattr(limpiarVideo, "comprobar_dependencias", lambda: [])
    monkeypatch.setattr(limpiarVideo, "tiene_pista_audio", lambda v: False)
    with pytest.raises(SystemExit) as salida:
        limpiarVideo.main([str(video)])
    assert salida.value.code == 1
    assert "pista de audio" in capsys.readouterr().err


def test_limpiar_video_video_inexistente(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(limpiarVideo, "comprobar_dependencias", lambda: [])
    with pytest.raises(SystemExit) as salida:
        limpiarVideo.main([str(tmp_path / "no.mp4")])
    assert salida.value.code == 1


def test_limpiar_audio_llama_al_paso(tmp_path, monkeypatch):
    entrada = tmp_path / "in.wav"
    entrada.write_bytes(b"RIFF")
    destino = tmp_path / "out.wav"
    capturado = {}

    def falso_paso(entrada_, salida_, tarea, modelo):
        capturado["args"] = (entrada_, salida_, tarea, modelo)
        salida_.write_bytes(b"RIFFOK")

    monkeypatch.setattr(limpiarAudio, "limpiar_audio", falso_paso)
    limpiarAudio.main([str(entrada), str(destino)])
    assert capturado["args"] == (
        entrada, destino, "speech_enhancement", "MossFormer2_SE_48K"
    )


def test_limpiar_audio_entrada_inexistente(tmp_path, capsys):
    with pytest.raises(SystemExit) as salida:
        limpiarAudio.main([str(tmp_path / "no.wav"), str(tmp_path / "o.wav")])
    assert salida.value.code == 1


def test_limpiar_video_dependencias_faltantes(tmp_path, monkeypatch, capsys):
    video = tmp_path / "charla.mov"
    video.write_bytes(b"VID")
    monkeypatch.setattr(limpiarVideo, "comprobar_dependencias", lambda: ["auto-editor"])
    with pytest.raises(SystemExit) as salida:
        limpiarVideo.main([str(video)])
    assert salida.value.code == 1
    err = capsys.readouterr().err
    assert "faltan dependencias" in err
    assert "auto-editor" in err


def test_limpiar_video_salida_igual_entrada(tmp_path, monkeypatch, capsys):
    video = tmp_path / "charla.mov"
    video.write_bytes(b"VID")
    monkeypatch.setattr(limpiarVideo, "comprobar_dependencias", lambda: [])
    monkeypatch.setattr(limpiarVideo, "tiene_pista_audio", lambda v: True)
    with pytest.raises(SystemExit) as salida:
        limpiarVideo.main([str(video), str(video)])
    assert salida.value.code == 1
    assert "mismo archivo" in capsys.readouterr().err


def test_limpiar_video_error_de_pipeline(tmp_path, monkeypatch, capsys):
    video = tmp_path / "charla.mov"
    video.write_bytes(b"VID")

    def falso_run(config, on_progress=None):
        raise PasoFallido("auto-editor falló", detalle="traza")

    monkeypatch.setattr(limpiarVideo, "comprobar_dependencias", lambda: [])
    monkeypatch.setattr(limpiarVideo, "tiene_pista_audio", lambda v: True)
    monkeypatch.setattr(limpiarVideo, "run", falso_run)
    with pytest.raises(SystemExit) as salida:
        limpiarVideo.main([str(video)])
    assert salida.value.code == 1
    err = capsys.readouterr().err
    assert "auto-editor falló" in err
    assert "traza" in err


def test_limpiar_audio_error_de_paso(tmp_path, monkeypatch, capsys):
    entrada = tmp_path / "in.wav"
    entrada.write_bytes(b"RIFF")
    destino = tmp_path / "out.wav"

    def falso_paso(entrada_, salida_, tarea, modelo):
        raise PasoFallido("ClearVoice falló", detalle="det")

    monkeypatch.setattr(limpiarAudio, "limpiar_audio", falso_paso)
    with pytest.raises(SystemExit) as salida:
        limpiarAudio.main([str(entrada), str(destino)])
    assert salida.value.code == 1
    err = capsys.readouterr().err
    assert "ClearVoice falló" in err
    assert "det" in err
