from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from videopipeline import i18n, runner
from videopipeline.config import PipelineConfig
from videopipeline.steps import PasoFallido


def _catalogo(tmp_path: Path, idioma: str, pares: dict[str, str]) -> Path:
    """Compila un catálogo mínimo en tmp_path/<idioma>/LC_MESSAGES/tsots.mo."""
    carpeta = tmp_path / idioma / "LC_MESSAGES"
    carpeta.mkdir(parents=True)
    po = carpeta / "tsots.po"
    lineas = ['msgid ""', 'msgstr ""', '"Content-Type: text/plain; charset=UTF-8\\n"', ""]
    for origen, destino in pares.items():
        lineas += [f'msgid "{origen}"', f'msgstr "{destino}"', ""]
    po.write_text("\n".join(lineas), encoding="utf-8")
    subprocess.run(["msgfmt", "-o", str(carpeta / "tsots.mo"), str(po)], check=True)
    return tmp_path


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


def test_error_incluye_diagnostico_y_log(tmp_path, monkeypatch, capsys):
    ruta = _config_json(tmp_path)
    monkeypatch.setattr(runner, "DIR_LOGS", tmp_path / "logs")

    def falso_run(config, on_progress):
        on_progress({"step": 4, "total": 4, "label": "Recortando silencios",
                     "percent": 2.8})
        raise PasoFallido(
            "auto-editor falló (código 1)",
            detalle="(mp4) h264+aac~38.0~13944.0~8.48\r"
                    "\x1b[31mError! Could not write packet: Invalid argument\x1b[0m",
        )

    monkeypatch.setattr(runner, "run", falso_run)
    monkeypatch.setattr(runner.os, "chdir", lambda ruta_: None)
    assert runner.main(["--config", str(ruta)]) == 1
    ultimo = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    diag = ultimo["diagnostico"]
    assert diag["titulo"] == "auto-editor no pudo escribir el vídeo"
    assert diag["conocido"] is True
    assert "\x1b" not in diag["detalle"]
    assert ultimo["paso"] == "Recortando silencios"
    log = Path(ultimo["log"])
    assert log.is_file() and log.parent == tmp_path / "logs"
    contenido = log.read_text(encoding="utf-8")
    assert '"modelo": "MossFormer2_SE_48K"' in contenido  # config completa
    assert "Recortando silencios" in contenido  # eventos de progreso
    assert "Could not write packet" in contenido  # detalle técnico
    assert "auto-editor no pudo escribir el vídeo" in contenido  # diagnóstico


def test_excepcion_inesperada_lleva_tipo_y_traceback(tmp_path, monkeypatch,
                                                      capsys):
    ruta = _config_json(tmp_path)
    monkeypatch.setattr(runner, "DIR_LOGS", tmp_path / "logs")

    def falso_run(config, on_progress):
        raise KeyError("width")

    monkeypatch.setattr(runner, "run", falso_run)
    monkeypatch.setattr(runner.os, "chdir", lambda ruta_: None)
    assert runner.main(["--config", str(ruta)]) == 1
    ultimo = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert ultimo["error"].startswith("KeyError: 'width'")
    diag = ultimo["diagnostico"]
    assert diag["conocido"] is False
    assert "Traceback" in diag["detalle"]
    assert "falso_run" in diag["detalle"]
    assert "Traceback" in Path(ultimo["log"]).read_text(encoding="utf-8")


def test_exito_tambien_escribe_log(tmp_path, monkeypatch, capsys):
    ruta = _config_json(tmp_path)
    monkeypatch.setattr(runner, "DIR_LOGS", tmp_path / "logs")
    monkeypatch.setattr(runner, "run", lambda c, p: c.ruta_salida_final())
    monkeypatch.setattr(runner.os, "chdir", lambda ruta_: None)
    assert runner.main(["--config", str(ruta)]) == 0
    ultimo = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert ultimo["done"] is True
    logs = list((tmp_path / "logs").glob("v_*.log"))
    assert len(logs) == 1
    assert "OK" in logs[0].read_text(encoding="utf-8")


def test_main_instala_idioma_ui_de_la_config(tmp_path, monkeypatch, capsys):
    """config.idioma_ui='en' debe instalar el catálogo inglés antes de correr
    el pipeline, así que las etiquetas de progreso llegan traducidas."""
    ruta_locale = _catalogo(tmp_path / "locale", "en", {
        "Extrayendo audio": "Extracting audio",
    })
    monkeypatch.setattr(i18n, "DIR_LOCALE", ruta_locale)
    ruta = _config_json(tmp_path, idioma_ui="en")

    def falso_run(config, on_progress):
        from videopipeline.i18n import _
        on_progress({"step": 1, "total": 1, "label": _("Extrayendo audio"),
                     "percent": None})
        return config.ruta_salida_final()

    monkeypatch.setattr(runner, "run", falso_run)
    monkeypatch.setattr(runner.os, "chdir", lambda ruta_: None)
    try:
        codigo = runner.main(["--config", str(ruta)])
    finally:
        i18n.instalar("es")
    assert codigo == 0
    lineas = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines()]
    assert lineas[0]["label"] == "Extracting audio"


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
