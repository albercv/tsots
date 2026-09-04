from __future__ import annotations

import json
from pathlib import Path

import pytest

from videopipeline import runner
from videopipeline.config import PipelineConfig
from videopipeline.steps import PasoFallido


def _config_json(tmp_path: Path, **extra) -> Path:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"VID")
    config = PipelineConfig(video=video, salida=tmp_path / "out.mp4", **extra)
    ruta = tmp_path / "config.json"
    ruta.write_text(config.to_json(), encoding="utf-8")
    return ruta


def test_exito_emite_progreso_y_done(tmp_path, monkeypatch, capsys):
    ruta = _config_json(tmp_path)

    def falso_run(config, on_progress):
        on_progress({"step": 1, "total": 4, "label": "Extrayendo audio",
                     "percent": None})
        return config.ruta_salida_final()

    monkeypatch.setattr(runner, "run", falso_run)
    monkeypatch.setattr(runner.os, "chdir", lambda ruta_: None)
    codigo = runner.main(["--config", str(ruta)])
    assert codigo == 0
    lineas = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines()]
    assert lineas[0]["step"] == 1
    assert lineas[-1]["done"] is True
    assert lineas[-1]["salida"].endswith("out.mp4")


def test_error_de_paso(tmp_path, monkeypatch, capsys):
    ruta = _config_json(tmp_path)

    def falso_run(config, on_progress):
        on_progress({"step": 2, "total": 4, "label": "Limpiando audio",
                     "percent": None})
        raise PasoFallido("ClearVoice falló", detalle="traza larga")

    monkeypatch.setattr(runner, "run", falso_run)
    monkeypatch.setattr(runner.os, "chdir", lambda ruta_: None)
    codigo = runner.main(["--config", str(ruta)])
    assert codigo == 1
    lineas = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines()]
    ultimo = lineas[-1]
    assert "ClearVoice falló" in ultimo["error"]
    assert "traza larga" in ultimo["error"]
    assert ultimo["step"] == 2


def test_config_invalida(tmp_path, monkeypatch, capsys):
    ruta = tmp_path / "config.json"
    ruta.write_text("{esto no es json", encoding="utf-8")
    monkeypatch.setattr(runner.os, "chdir", lambda ruta_: None)
    codigo = runner.main(["--config", str(ruta)])
    assert codigo == 1
    ultimo = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "error" in ultimo


def test_chdir_a_base(tmp_path, monkeypatch):
    ruta = _config_json(tmp_path)
    registrado = {}
    monkeypatch.setattr(runner.os, "chdir", lambda p: registrado.setdefault("p", p))
    monkeypatch.setattr(runner, "run", lambda c, p: c.ruta_salida_final())
    runner.main(["--config", str(ruta)])
    assert registrado["p"] == runner.BASE_DIR


def test_config_relativo_resuelto_antes_de_chdir(tmp_path, monkeypatch):
    ruta = _config_json(tmp_path)
    monkeypatch.chdir(tmp_path)
    # No se stubea runner.os.chdir: el runner SÍ cambia de cwd a BASE_DIR de
    # verdad. Si la resolución de config_path ocurriera después del chdir
    # (regresión), la lectura relativa fallaría con FileNotFoundError.
    monkeypatch.setattr(runner, "run", lambda c, p: c.ruta_salida_final())
    codigo = runner.main(["--config", ruta.name])
    assert codigo == 0


def test_argumentos_invalidos_emiten_json(capsys):
    codigo = runner.main([])
    assert codigo == 1
    ultimo = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "error" in ultimo
    assert ultimo["step"] == 0


def test_help_sale_limpio(capsys):
    codigo = runner.main(["--help"])
    assert codigo == 0


def test_warning_pasa_por_stdout(tmp_path, monkeypatch, capsys):
    ruta = _config_json(tmp_path)

    def falso_run(config, on_progress):
        on_progress({"warning": "Subtítulos fallaron: X. Vídeo sin subtítulos."})
        return config.ruta_salida_final()

    monkeypatch.setattr(runner, "run", falso_run)
    monkeypatch.setattr(runner.os, "chdir", lambda ruta_: None)
    assert runner.main(["--config", str(ruta)]) == 0
    lineas = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines()]
    assert any("warning" in l for l in lineas)
