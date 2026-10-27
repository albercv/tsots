from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import pytest

from videopipeline import seguimiento
from videopipeline.seguimiento import (
    ID_PESOS,
    asegurar_pesos_s3fd,
    FPS_MUESTREO,
    SALTO_PLANO,
    ZONA_MUERTA,
    dispositivo,
    escribir_comandos,
    muestrear_centros,
    posiciones_recorte,
    preparar_seguimiento,
    suavizar,
)
from videopipeline.steps import PasoFallido
from videopipeline.vertical import convertir_vertical, filtro_vertical


def test_suavizar_sin_caras():
    assert suavizar([None, None]) is None


def test_suavizar_rellena_inicio_y_huecos():
    assert suavizar([None, 0.5, None, 0.5]) == [0.5, 0.5, 0.5, 0.5]


def test_suavizar_sin_temblor():
    ruido = [0.5, 0.53, 0.48, 0.52, 0.47, 0.51, 0.49, 0.53]
    resultado = suavizar(ruido)
    assert set(resultado) == {resultado[0]}


def test_suavizar_ignora_deteccion_suelta():
    assert set(suavizar([0.5] * 5 + [0.9] + [0.5] * 5)) == {0.5}


def test_suavizar_salta_en_cambio_de_plano():
    s = suavizar([0.2] * 10 + [0.8] * 10)
    assert s[9] == 0.2 and s[10] == 0.8


def test_suavizar_sigue_deriva_lenta():
    centros = [0.3 + 0.01 * i for i in range(31)] + [0.6] * 10
    s = suavizar(centros)
    pasos = [b - a for a, b in zip(s, s[1:])]
    assert all(0 <= p < SALTO_PLANO for p in pasos)
    assert abs(s[-1] - 0.6) <= ZONA_MUERTA


def test_posiciones_recorte_limites():
    assert posiciones_recorte([0.0, 0.5, 1.0], 1920, 606) == [0, 657, 1314]


def test_escribir_comandos_deduplica(tmp_path):
    ruta = tmp_path / "cara.cmd"
    escribir_comandos([100, 100, 100], ruta)
    assert ruta.read_text().strip() == "0.000 crop@v x 100;"


def test_escribir_comandos_interpola(tmp_path):
    ruta = tmp_path / "cara.cmd"
    escribir_comandos([0, 40], ruta, fps_muestreo=4, fps_comandos=8)
    assert ruta.read_text().split("\n")[:3] == [
        "0.000 crop@v x 0;", "0.125 crop@v x 20;", "0.250 crop@v x 40;"]


def test_escribir_comandos_no_interpola_saltos(tmp_path):
    ruta = tmp_path / "cara.cmd"
    escribir_comandos([0, 0, 500], ruta, fps_muestreo=4, fps_comandos=8,
                      salto_px=200)
    assert ruta.read_text().split() == [
        "0.000", "crop@v", "x", "0;", "0.500", "crop@v", "x", "500;"]


def _detector_fijo(frame):
    # Dos caras; la grande (x 100..300) tiene centro x=200 en el fotograma de 480.
    return np.array([[10, 10, 50, 50, 0.9], [100, 20, 300, 220, 0.95]])


def _sin_caras(frame):
    return np.empty((0, 5))


def test_dispositivo_valido():
    assert dispositivo() in ("cpu", "mps")


def test_muestrear_centros_elige_cara_grande(video_720p):
    formas: list[tuple] = []
    porcentajes: list[float] = []

    def detector(frame):
        formas.append(frame.shape)
        return _detector_fijo(frame)

    centros = muestrear_centros(video_720p, 1280, 720, porcentajes.append, detector)
    assert abs(len(centros) - 2 * FPS_MUESTREO) <= 1
    assert formas[0] == (270, 480, 3)
    assert centros[0] == pytest.approx(200 / 480)
    assert porcentajes and all(0 <= p <= 100 for p in porcentajes)


def test_muestrear_sin_caras(video_720p):
    centros = muestrear_centros(video_720p, 1280, 720, detector=_sin_caras)
    assert centros and all(c is None for c in centros)


def test_muestrear_video_invalido(tmp_path):
    falso = tmp_path / "basura.mp4"
    falso.write_bytes(b"basura")
    with pytest.raises(PasoFallido):
        muestrear_centros(falso, 1280, 720, detector=_sin_caras)


def test_preparar_sin_caras_devuelve_none(video_720p, tmp_path):
    ruta = tmp_path / "cara.cmd"
    assert preparar_seguimiento(video_720p, 1280, 720, ruta,
                                detector=_sin_caras) is None
    assert not ruta.exists()


def test_preparar_escribe_comandos(video_720p, tmp_path):
    ruta = tmp_path / "cara.cmd"
    x0 = preparar_seguimiento(video_720p, 1280, 720, ruta, detector=_detector_fijo)
    assert x0 == posiciones_recorte([200 / 480], 1280, 404)[0] == 331
    assert ruta.read_text().startswith("0.000 crop@v x 331;")


def test_cara_real_ffmpeg_aplica_comandos(video_720p, tmp_path):
    (tmp_path / "cara.cmd").write_text("0.000 crop@v x 0;\n1.000 crop@v x 876;\n")
    salida = tmp_path / "cara.mp4"
    convertir_vertical(video_720p, salida,
                       filtro_vertical("cara", 1280, 720, x_cara=0),
                       cwd=tmp_path, usa_ass=False)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(salida)],
        capture_output=True, text=True, check=True).stdout.strip()
    assert out == "1080,1920"


@pytest.mark.slow
def test_s3fd_real_carga_y_corre(video_720p, tmp_path):
    x0 = preparar_seguimiento(video_720p, 1280, 720, tmp_path / "cara.cmd")
    assert x0 is None or 0 <= x0 <= 1280 - 404


def test_muestrear_no_se_bloquea_con_mucho_stderr(video_720p, tmp_path, monkeypatch):
    # Un archivo dañado puede llenar el pipe de stderr antes de que se lea.
    falso = tmp_path / "ffmpeg_ruidoso"
    falso.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "sys.stderr.write('x' * 300_000)\n"
        "sys.stderr.flush()\n"
        "sys.stdout.buffer.write(bytes(480 * 270 * 3 * 3))\n"
    )
    falso.chmod(0o755)
    monkeypatch.setattr(seguimiento, "_binario", lambda nombre: str(falso))
    resultado: dict = {}
    hilo = threading.Thread(
        target=lambda: resultado.update(
            centros=muestrear_centros(video_720p, 1280, 720, detector=_sin_caras)),
        daemon=True,
    )
    hilo.start()
    hilo.join(20)
    assert not hilo.is_alive(), "muestrear_centros se bloqueó"
    assert resultado["centros"] == [None, None, None]


def test_muestrear_mata_ffmpeg_si_falla_el_detector(video_720p, monkeypatch):
    procesos = []
    original = subprocess.Popen

    def espia(*args, **kwargs):
        proceso = original(*args, **kwargs)
        procesos.append(proceso)
        return proceso

    monkeypatch.setattr(seguimiento.subprocess, "Popen", espia)

    def revienta(frame):
        raise RuntimeError("detector roto")

    with pytest.raises(RuntimeError):
        muestrear_centros(video_720p, 1280, 720, detector=revienta)
    assert procesos and procesos[-1].poll() is not None


def test_suavizar_inicio_largo_sin_cara_va_al_centro():
    # Spec: al inicio sin cara, centro (p. ej. una cabecera de 5 s).
    s = suavizar([None] * 10 + [0.2] * 10)
    assert s[0] == 0.5 and s[-1] == 0.2


def test_suavizar_inicio_corto_sin_cara_usa_la_primera():
    # Un fallo suelto de detección al empezar no debe dar un salto desde el centro.
    assert suavizar([None] + [0.2] * 10)[0] == 0.2


def test_pesos_ya_presentes_no_descarga(tmp_path, monkeypatch):
    ruta = tmp_path / "sfd_face.pth"
    ruta.write_bytes(b"W")
    monkeypatch.setattr(seguimiento.gdown, "download",
                        lambda **k: pytest.fail("descargó"))
    assert asegurar_pesos_s3fd(ruta) is True


def test_pesos_descarga_atomica(tmp_path, monkeypatch):
    ruta = tmp_path / "sfd_face.pth"

    def falso(id, output, quiet):
        assert id == ID_PESOS and output.endswith(".tmp")
        Path(output).write_bytes(b"PESOS")

    monkeypatch.setattr(seguimiento.gdown, "download", falso)
    assert asegurar_pesos_s3fd(ruta) is False
    assert ruta.read_bytes() == b"PESOS"
    assert not ruta.with_suffix(".pth.tmp").exists()


def test_pesos_fallo_no_deja_temporal(tmp_path, monkeypatch):
    ruta = tmp_path / "sfd_face.pth"

    def falso(id, output, quiet):
        Path(output).write_bytes(b"MEDIO")
        raise OSError("sin red")

    monkeypatch.setattr(seguimiento.gdown, "download", falso)
    with pytest.raises(PasoFallido):
        asegurar_pesos_s3fd(ruta)
    assert not ruta.exists() and not ruta.with_suffix(".pth.tmp").exists()


def test_pesos_descarga_vacia_es_fallo(tmp_path, monkeypatch):
    # gdown devuelve sin error pero sin fichero cuando Drive limita la cuota.
    ruta = tmp_path / "sfd_face.pth"
    monkeypatch.setattr(seguimiento.gdown, "download", lambda **k: None)
    with pytest.raises(PasoFallido):
        asegurar_pesos_s3fd(ruta)
    assert not ruta.exists()
