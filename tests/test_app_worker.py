from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from app.worker import EjecutorCola


def _runner_falso(tmp_path: Path, cuerpo: str) -> Path:
    """Script python que sustituye a videopipeline.runner en tests."""
    script = tmp_path / "runner_falso.py"
    script.write_text(textwrap.dedent(cuerpo), encoding="utf-8")
    return script


def test_exito_emite_progreso_y_terminado(qtbot, tmp_path):
    script = _runner_falso(
        tmp_path,
        """
        import json, sys
        print(json.dumps({"step": 1, "total": 2, "label": "Paso uno",
                          "percent": None}), flush=True)
        print(json.dumps({"done": True, "salida": "/tmp/out.mp4"}), flush=True)
        """,
    )
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = [sys.executable, str(script)]
    eventos, terminados = [], []
    ejecutor.progreso.connect(lambda fila, e: eventos.append((fila, e)))
    ejecutor.trabajo_terminado.connect(
        lambda fila, ok, salida, error: terminados.append((fila, ok, salida, error))
    )
    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=10000):
        ejecutor.iniciar([(0, "{}")])
    assert eventos[0][1]["label"] == "Paso uno"
    assert terminados == [(0, True, "/tmp/out.mp4", "")]


def test_error_marca_trabajo_y_continua(qtbot, tmp_path):
    script = _runner_falso(
        tmp_path,
        """
        import json, sys
        config = sys.argv[sys.argv.index("--config") + 1]
        if "MAL" in open(config).read():
            print(json.dumps({"error": "algo falló", "step": 2}), flush=True)
            sys.exit(1)
        print(json.dumps({"done": True, "salida": "/tmp/ok.mp4"}), flush=True)
        """,
    )
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = [sys.executable, str(script)]
    terminados = []
    ejecutor.trabajo_terminado.connect(
        lambda fila, ok, salida, error: terminados.append((fila, ok, error))
    )
    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=10000):
        ejecutor.iniciar([(0, '{"marca": "MAL"}'), (1, "{}")])
    assert terminados[0][0] == 0 and terminados[0][1] is False
    assert "algo falló" in terminados[0][2]
    assert terminados[1] == (1, True, "")


def test_cancelar_detiene_cola(qtbot, tmp_path):
    script = _runner_falso(
        tmp_path,
        """
        import time
        time.sleep(30)
        """,
    )
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = [sys.executable, str(script)]
    terminados = []
    ejecutor.trabajo_terminado.connect(
        lambda fila, ok, salida, error: terminados.append((fila, ok))
    )
    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=10000):
        ejecutor.iniciar([(0, "{}"), (1, "{}")])
        qtbot.wait(500)
        ejecutor.cancelar()
    # El trabajo 0 termina como no-ok; el 1 nunca se lanza.
    assert terminados == [(0, False)]


def test_iniciar_reentrante_ignorado(qtbot, tmp_path):
    script = _runner_falso(
        tmp_path,
        """
        import json, sys, time
        time.sleep(5)
        print(json.dumps({"done": True, "salida": "/tmp/out.mp4"}), flush=True)
        """,
    )
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = [sys.executable, str(script)]
    terminados = []
    ejecutor.trabajo_terminado.connect(
        lambda fila, ok, salida, error: terminados.append((fila, ok))
    )
    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=10000):
        ejecutor.iniciar([(0, "{}")])
        qtbot.wait(200)
        # Reentrante: ya hay un proceso en marcha, debe ignorarse en silencio.
        ejecutor.iniciar([(1, "{}")])
        ejecutor.cancelar()
    # Solo la fila 0 (del primer iniciar) aparece; la reentrada no se lanzó.
    assert [fila for fila, _ok in terminados] == [0]


def test_failed_to_start_no_cuelga(qtbot):
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = ["/nonexistent/binary/xyz"]
    terminados = []
    ejecutor.trabajo_terminado.connect(
        lambda fila, ok, salida, error: terminados.append((fila, ok, error))
    )
    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=5000):
        ejecutor.iniciar([(0, "{}"), (1, "{}")])
    assert [(fila, ok) for fila, ok, _error in terminados] == [
        (0, False),
        (1, False),
    ]
    assert all(error for _fila, _ok, error in terminados)


def test_cancelar_borra_config_temporal(qtbot, tmp_path):
    script = _runner_falso(
        tmp_path,
        """
        import time
        time.sleep(30)
        """,
    )
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = [sys.executable, str(script)]
    config_tmp = None
    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=10000):
        ejecutor.iniciar([(0, "{}"), (1, "{}")])
        qtbot.wait(200)
        config_tmp = ejecutor._config_tmp
        ejecutor.cancelar()
    assert config_tmp is not None
    assert not config_tmp.exists()


def test_trabajo_iniciado_por_trabajo(qtbot, tmp_path):
    script = _runner_falso(
        tmp_path,
        """
        import json, sys
        print(json.dumps({"done": True, "salida": "/tmp/out.mp4"}), flush=True)
        """,
    )
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = [sys.executable, str(script)]
    iniciados = []
    eventos = []
    ejecutor.trabajo_iniciado.connect(
        lambda fila: (iniciados.append(fila), eventos.append(("ini", fila)))
    )
    ejecutor.trabajo_terminado.connect(
        lambda fila, ok, salida, error: eventos.append(("fin", fila))
    )
    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=10000):
        ejecutor.iniciar([(0, "{}"), (1, "{}")])
    assert iniciados == [0, 1]
    assert eventos == [("ini", 0), ("fin", 0), ("ini", 1), ("fin", 1)]


def test_lineas_con_retorno_de_carro(qtbot, tmp_path):
    script = _runner_falso(
        tmp_path,
        """
        import json, sys
        sys.stdout.write("ruido tqdm\\r")
        sys.stdout.flush()
        print(json.dumps({"step": 1, "total": 2, "label": "Paso uno",
                          "percent": 10.0}), flush=True)
        print(json.dumps({"done": True, "salida": "/tmp/out.mp4"}), flush=True)
        """,
    )
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = [sys.executable, str(script)]
    eventos = []
    ejecutor.progreso.connect(lambda fila, e: eventos.append((fila, e)))
    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=10000):
        ejecutor.iniciar([(0, "{}")])
    assert eventos
    assert eventos[0][1]["label"] == "Paso uno"


def test_iniciar_desde_slot_trabajo_terminado_ignorado(qtbot, tmp_path):
    script = _runner_falso(
        tmp_path,
        """
        import json, sys
        print(json.dumps({"done": True, "salida": "/tmp/out.mp4"}), flush=True)
        """,
    )
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = [sys.executable, str(script)]
    terminados = []
    ya_reentro = {"hecho": False}

    def _en_trabajo_terminado(fila, ok, salida, error):
        terminados.append(fila)
        if not ya_reentro["hecho"]:
            ya_reentro["hecho"] = True
            # Reentrada síncrona desde el propio slot de trabajo_terminado:
            # en este punto _proceso ya es None pero _activo sigue en True,
            # así que debe ignorarse en silencio (no debe colarse un
            # segundo QProcess ni una segunda cola_terminada prematura).
            ejecutor.iniciar([(9, "{}")])

    ejecutor.trabajo_terminado.connect(_en_trabajo_terminado)

    conteo_cola_terminada = {"n": 0}

    def _en_cola_terminada():
        conteo_cola_terminada["n"] += 1

    ejecutor.cola_terminada.connect(_en_cola_terminada)

    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=10000):
        ejecutor.iniciar([(0, "{}")])
    qtbot.wait(200)
    assert terminados == [0]
    assert conteo_cola_terminada["n"] == 1


def test_warning_emite_senal_aviso(qtbot, tmp_path):
    script = _runner_falso(
        tmp_path,
        """
        import json, sys
        print(json.dumps({"warning": "subs fallaron"}), flush=True)
        print(json.dumps({"done": True, "salida": "/tmp/out.mp4"}), flush=True)
        """,
    )
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = [sys.executable, str(script)]
    avisos = []
    ejecutor.aviso.connect(lambda fila, texto: avisos.append((fila, texto)))
    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=10000):
        ejecutor.iniciar([(0, "{}")])
    assert avisos == [(0, "subs fallaron")]


def test_crash_sin_json_conserva_la_salida_cruda(qtbot, tmp_path):
    """Si el runner muere sin emitir JSON de error (traceback, crash nativo),
    el texto crudo NO se descarta como ruido: es la única pista."""
    script = _runner_falso(
        tmp_path,
        """
        import json, sys
        print(json.dumps({"step": 2, "total": 4, "label": "Limpiando audio",
                          "percent": None}), flush=True)
        print("algo de ruido de una librería", flush=True)
        1 / 0
        """,
    )
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = [sys.executable, str(script)]
    terminados = []
    ejecutor.trabajo_terminado.connect(
        lambda fila, ok, salida, error: terminados.append((ok, error))
    )
    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=10000):
        ejecutor.iniciar([(0, "{}")])
    ok, error = terminados[0]
    assert ok is False
    assert "código 1" in error
    assert "Limpiando audio" in error  # último paso conocido
    assert "ZeroDivisionError" in error
    assert "algo de ruido" in error


def test_muerte_por_senal_se_explica(qtbot, tmp_path):
    script = _runner_falso(
        tmp_path,
        """
        import os, signal
        os.kill(os.getpid(), signal.SIGKILL)
        """,
    )
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = [sys.executable, str(script)]
    terminados = []
    ejecutor.trabajo_terminado.connect(
        lambda fila, ok, salida, error: terminados.append(error)
    )
    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=10000):
        ejecutor.iniciar([(0, "{}")])
    assert "SIGKILL" in terminados[0]
    assert "memoria" in terminados[0].lower()


def test_error_estructurado_emite_diagnostico(qtbot, tmp_path):
    script = _runner_falso(
        tmp_path,
        """
        import json, sys
        print(json.dumps({
            "error": "auto-editor falló (código 1)\\nError! Could not write packet",
            "step": 4, "paso": "Recortando silencios",
            "diagnostico": {"titulo": "auto-editor no pudo escribir el vídeo",
                            "causa": "porque sí", "solucion": "reencodar",
                            "detalle": "Error! Could not write packet",
                            "conocido": True},
            "log": "/tmp/x.log",
        }), flush=True)
        sys.exit(1)
        """,
    )
    ejecutor = EjecutorCola()
    ejecutor.PROGRAMA = [sys.executable, str(script)]
    terminados, diagnosticos = [], []
    ejecutor.trabajo_terminado.connect(
        lambda fila, ok, salida, error: terminados.append(error)
    )
    ejecutor.diagnostico.connect(lambda fila, d: diagnosticos.append((fila, d)))
    with qtbot.waitSignal(ejecutor.cola_terminada, timeout=10000):
        ejecutor.iniciar([(0, "{}")])
    assert diagnosticos[0][0] == 0
    assert diagnosticos[0][1]["titulo"] == "auto-editor no pudo escribir el vídeo"
    assert diagnosticos[0][1]["log"] == "/tmp/x.log"
    assert diagnosticos[0][1]["paso"] == "Recortando silencios"
    # El texto de error empieza por el título legible, no por el mensaje crudo.
    assert terminados[0].startswith("auto-editor no pudo escribir el vídeo")
    assert "Qué hacer: reencodar" in terminados[0]
