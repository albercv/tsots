from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from videopipeline import i18n, runner
from videopipeline.config import PipelineConfig
from videopipeline.ficha import Ficha, Huella
from videopipeline.reproceso_plan import Accion, Decisiones, Plan
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


def _run_que_escribe_vertical(escribir: bool):
    def falso_run(config, on_progress):
        if escribir:
            config.ruta_salida_vertical().write_bytes(b"V")
        return config.ruta_salida_final()
    return falso_run


@pytest.mark.parametrize("vertical, escribir, esperado", [
    (True, True, "out_vertical.mp4"), (False, False, None), (True, False, None)])
def test_done_salida_vertical(tmp_path, monkeypatch, capsys, vertical, escribir,
                              esperado):
    ruta = _config_json(tmp_path, paso_vertical=vertical)
    monkeypatch.setattr(runner, "run", _run_que_escribe_vertical(escribir))
    monkeypatch.setattr(runner.os, "chdir", lambda r: None)
    assert runner.main(["--config", str(ruta)]) == 0
    final = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    if esperado is None:
        assert final["salida_vertical"] is None
    else:
        assert final["salida_vertical"].endswith(esperado)


def test_done_ignora_vertical_de_ejecucion_anterior(tmp_path, monkeypatch, capsys):
    ruta = _config_json(tmp_path, paso_vertical=True)
    viejo = tmp_path / "out_vertical.mp4"
    viejo.write_bytes(b"VIEJO")
    os.utime(viejo, (1_000_000, 1_000_000))  # de una ejecución previa
    monkeypatch.setattr(runner, "run", _run_que_escribe_vertical(False))
    monkeypatch.setattr(runner.os, "chdir", lambda r: None)
    assert runner.main(["--config", str(ruta)]) == 0
    final = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert final["salida_vertical"] is None


def test_runner_sin_reproceso_igual_que_hoy(tmp_path, monkeypatch, capsys):
    """Sin la clave `reproceso` corre `run`, sin tocar fichas, y `done` no
    lleva `ficha`."""
    ruta = _config_json(tmp_path, paso_vertical=True)

    def no_debe_llamarse(*args, **kwargs):
        raise AssertionError("sin `reproceso` no se usa la ficha")

    for nombre in ("cargar", "planificar", "ejecutar"):
        monkeypatch.setattr(runner, nombre, no_debe_llamarse)
    monkeypatch.setattr(runner, "run", _run_que_escribe_vertical(True))
    monkeypatch.setattr(runner, "DIR_LOGS", tmp_path / "logs")
    monkeypatch.setattr(runner.os, "chdir", lambda r: None)
    assert runner.main(["--config", str(ruta)]) == 0
    final = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert final == {
        "done": True,
        "salida": str(tmp_path / "out.mp4"),
        "salida_vertical": str((tmp_path / "out_vertical.mp4").resolve()),
    }


ID_FICHA = "abc123def456"


def _ficha(tmp_path: Path, vertical: bool = False, final: bool = True) -> Ficha:
    """Una ficha con el horizontal (y, si se pide, su vertical) ya en disco, de
    una ejecución anterior."""
    huellas = {}
    for campo, nombre in (("final", "v_limpio.mp4"), ("vertical", "v_limpio_vertical.mp4")):
        if (campo == "final" and final) or (campo == "vertical" and vertical):
            archivo = tmp_path / "salidas" / nombre
            archivo.parent.mkdir(exist_ok=True)
            archivo.write_bytes(b"X")
            os.utime(archivo, (1_000_000, 1_000_000))
            huellas[campo] = Huella.de(archivo)
    return Ficha(id=ID_FICHA, nombre="v", carpeta_salida=tmp_path / "salidas",
                 **huellas)


def _reprocesar(tmp_path, monkeypatch, capsys, ficha, reproceso=None,
                acciones=(Accion.CORTAR,), error="", escribe_vertical=False,
                **config):
    """Corre el runner con `reproceso` y la ficha/plan/ejecutor falsos.

    Devuelve (código, líneas de stdout, llamadas registradas)."""
    reproceso = {"ficha": ID_FICHA} if reproceso is None else reproceso
    ruta = _config_json(tmp_path, **config)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    ruta.write_text(json.dumps({**datos, "reproceso": reproceso}), encoding="utf-8")
    llamadas = {"cargar": [], "planificar": [], "ejecutar": []}

    def falso_cargar(id_):
        llamadas["cargar"].append(id_)
        return ficha

    def falso_planificar(ficha_, config_, decisiones):
        llamadas["planificar"].append((ficha_, config_, decisiones))
        return Plan(list(acciones), config_, [], error)

    def falso_ejecutar(ficha_, plan, on_progress):
        llamadas["ejecutar"].append((ficha_, plan, on_progress))
        on_progress({"step": 1, "total": 1, "label": "Cortando", "percent": None})
        if escribe_vertical:
            ficha_.vertical.ruta.write_bytes(b"NUEVO")
        return ficha_.final.ruta

    monkeypatch.setattr(runner, "cargar", falso_cargar)
    monkeypatch.setattr(runner, "planificar", falso_planificar)
    monkeypatch.setattr(runner, "ejecutar", falso_ejecutar)
    monkeypatch.setattr(runner, "DIR_LOGS", tmp_path / "logs")
    monkeypatch.setattr(runner.os, "chdir", lambda r: None)
    codigo = runner.main(["--config", str(ruta)])
    lineas = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines()]
    return codigo, lineas, llamadas


def test_runner_con_reproceso_planifica_y_ejecuta(tmp_path, monkeypatch, capsys):
    ficha = _ficha(tmp_path, vertical=True)
    codigo, lineas, llamadas = _reprocesar(
        tmp_path, monkeypatch, capsys, ficha,
        {"ficha": ID_FICHA, "rehacer": ["audio", "caption"],
         "regenerar_vertical": True},
        escribe_vertical=True, paso_vertical=True, margen="0.5s")
    assert codigo == 0
    assert llamadas["cargar"] == [ID_FICHA]
    (ficha_p, config, decisiones), = llamadas["planificar"]
    assert ficha_p is ficha
    assert config.margen == "0.5s" and config.video == tmp_path / "v.mp4"
    assert decisiones == Decisiones(frozenset({"audio", "caption"}), True)
    (ficha_e, plan, on_progress), = llamadas["ejecutar"]
    assert ficha_e is ficha and plan.acciones == [Accion.CORTAR]
    assert callable(on_progress)
    assert lineas[0]["label"] == "Cortando"  # el progreso del ejecutor llega a stdout
    assert lineas[-1] == {
        "done": True,
        "salida": str(ficha.final.ruta),
        "salida_vertical": str(ficha.vertical.ruta),
        "ficha": ID_FICHA,
    }
    assert "OK" in next((tmp_path / "logs").glob("v_*.log")).read_text(encoding="utf-8")


def test_runner_reproceso_sin_decisiones_usa_los_valores_por_defecto(
        tmp_path, monkeypatch, capsys):
    _, _, llamadas = _reprocesar(tmp_path, monkeypatch, capsys, _ficha(tmp_path),
                                 {"ficha": ID_FICHA})
    assert llamadas["planificar"][0][2] == Decisiones()


def test_runner_reproceso_admite_solo_caption(tmp_path, monkeypatch, capsys):
    """Sin ningún paso de vídeo marcado vale «solo caption» (no se exige uno)."""
    codigo, lineas, _ = _reprocesar(
        tmp_path, monkeypatch, capsys, _ficha(tmp_path), paso_audio=False,
        paso_silencios=False, caption_seo=True)
    assert codigo == 0 and lineas[-1]["done"] is True


def test_runner_reproceso_valida_el_resto_de_la_config(tmp_path, monkeypatch, capsys):
    codigo, lineas, llamadas = _reprocesar(
        tmp_path, monkeypatch, capsys, _ficha(tmp_path), encuadre="inventado")
    assert codigo == 1 and "encuadre" in lineas[-1]["error"]
    assert llamadas["cargar"] == []


def test_runner_ficha_inexistente_falla(tmp_path, monkeypatch, capsys):
    codigo, lineas, llamadas = _reprocesar(tmp_path, monkeypatch, capsys, None)
    assert codigo == 1
    assert ID_FICHA in lineas[-1]["error"]
    assert llamadas["planificar"] == [] and llamadas["ejecutar"] == []


def test_runner_plan_con_error_falla_con_su_texto(tmp_path, monkeypatch, capsys):
    codigo, lineas, llamadas = _reprocesar(
        tmp_path, monkeypatch, capsys, _ficha(tmp_path),
        acciones=(), error="Falta el original de v.")
    assert codigo == 1
    assert lineas[-1]["error"] == "Falta el original de v."
    assert "log" in lineas[-1] and "diagnostico" in lineas[-1]
    assert llamadas["ejecutar"] == []


def test_runner_plan_vacio_termina_sin_ejecutar(tmp_path, monkeypatch, capsys):
    ficha = _ficha(tmp_path, vertical=True)
    codigo, lineas, llamadas = _reprocesar(
        tmp_path, monkeypatch, capsys, ficha, acciones=())
    assert codigo == 0
    assert llamadas["ejecutar"] == []
    # No escribió nada: el vertical que ya había no cuenta como nuevo.
    assert lineas[-1] == {
        "done": True, "salida": str(ficha.final.ruta), "salida_vertical": None,
        "ficha": ID_FICHA}


def test_runner_plan_vacio_sin_salida_falla(tmp_path, monkeypatch, capsys):
    codigo, lineas, llamadas = _reprocesar(
        tmp_path, monkeypatch, capsys, _ficha(tmp_path, final=False), acciones=())
    assert codigo == 1 and "error" in lineas[-1]
    assert llamadas["ejecutar"] == []


@pytest.mark.parametrize("escribe", [True, False])
def test_runner_reproceso_vertical_solo_si_es_de_esta_ejecucion(
        tmp_path, monkeypatch, capsys, escribe):
    ficha = _ficha(tmp_path, vertical=True)
    _, lineas, _ = _reprocesar(tmp_path, monkeypatch, capsys, ficha,
                               escribe_vertical=escribe)
    esperada = str(ficha.vertical.ruta) if escribe else None
    assert lineas[-1]["salida_vertical"] == esperada


def test_runner_reproceso_de_un_vertical_unico(tmp_path, monkeypatch, capsys):
    """Sin horizontal la salida es el propio vertical y no hay compañero."""
    unico = tmp_path / "salidas" / "v_vertical.mp4"
    unico.parent.mkdir()
    unico.write_bytes(b"V")
    ficha = Ficha(id=ID_FICHA, nombre="v", carpeta_salida=unico.parent,
                  final=Huella.de(unico))
    _, lineas, _ = _reprocesar(tmp_path, monkeypatch, capsys, ficha)
    assert lineas[-1]["salida"] == str(ficha.final.ruta)
    assert lineas[-1]["salida_vertical"] is None
