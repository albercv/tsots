from __future__ import annotations

import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import gdown
import numpy as np

from .i18n import _
from .steps import BASE_DIR, PasoFallido, _binario, duracion_video
from .vertical import ancho_recorte

Detector = Callable[[np.ndarray], np.ndarray]

# medido 2026-10-27 (S3FD, 480x270): mps 129 ms/frame, cpu 85 ms/frame.
# A 4 fps, 30 min de vídeo serían ~10,2 min > 10 → 2 fps (~5 min) en cpu.
FPS_MUESTREO = 2.0
ANCHO_DETECCION = 480
UMBRAL_CONFIANZA = 0.8
VENTANA_MEDIANA = 5
SALTO_PLANO = 0.25  # fracción del ancho: más que esto entre muestras = cambio de plano
ZONA_MUERTA = 0.08  # la cámara no se mueve si la cara está a menos de esto
ALFA = 0.3
FPS_COMANDOS = 30
HUECO_INICIAL_MAX = 2.0  # s: un inicio sin cara más largo se encuadra al centro


def dispositivo() -> str:
    # cpu medido más rápido que mps para S3FD en este equipo (ver FPS_MUESTREO).
    return "cpu"


RUTA_PESOS = (
    BASE_DIR / "clearvoice/models/av_mossformer2_tse/faceDetector/s3fd/sfd_face.pth"
)
ID_PESOS = "1KafnHz7ccT-3IyddBsL5yi2xGtxAKypt"  # Google Drive, el mismo que usa S3FD


def asegurar_pesos_s3fd(ruta: Path = RUTA_PESOS) -> bool:
    """Descarga los pesos del detector si faltan. True si ya estaban.

    La autodescarga de S3FD llama a `gdown --id`, que ya no existe en el gdown
    instalado, e ignora el error: se descarga aquí con la API de Python.
    """
    if ruta.is_file() and ruta.stat().st_size > 0:
        return True
    tmp = ruta.with_suffix(".pth.tmp")
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        gdown.download(id=ID_PESOS, output=str(tmp), quiet=True)
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise RuntimeError(_("la descarga no produjo ningún fichero"))
        tmp.replace(ruta)
    except Exception as error:  # noqa: BLE001 — cualquier fallo de red o de Drive
        tmp.unlink(missing_ok=True)
        raise PasoFallido(
            _("No se pudieron descargar los pesos del detector de caras: "
              "{error}").format(error=error)
        ) from error
    return False


def _detector_s3fd() -> Detector:
    asegurar_pesos_s3fd()
    # Import perezoso: torch solo se carga en el subproceso del runner.
    from clearvoice.models.av_mossformer2_tse.faceDetector.s3fd import S3FD

    detector = S3FD(device=dispositivo())
    return lambda frame: detector.detect_faces(frame, conf_th=UMBRAL_CONFIANZA)


def muestrear_centros(
    video: Path,
    ancho: int,
    alto: int,
    on_percent: Callable[[float], None] | None = None,
    detector: Detector | None = None,
) -> list[float | None]:
    """Centro x (0..1) de la cara más grande en cada muestra, o None."""
    detector = detector or _detector_s3fd()
    alto_det = round(ANCHO_DETECCION * alto / ancho / 2) * 2
    tamano = ANCHO_DETECCION * alto_det * 3
    esperadas = max(1.0, duracion_video(video) * FPS_MUESTREO)
    # stderr a fichero: un pipe sin leer se llena con vídeos dañados y bloquea.
    with tempfile.TemporaryFile() as errores:
        proceso = subprocess.Popen(
            [
                _binario("ffmpeg"), "-hide_banner", "-loglevel", "error",
                "-i", str(video),
                "-vf", f"fps={FPS_MUESTREO},scale={ANCHO_DETECCION}:{alto_det}",
                "-f", "rawvideo", "-pix_fmt", "rgb24",  # S3FD espera RGB
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=errores,
        )
        assert proceso.stdout is not None
        centros: list[float | None] = []
        try:
            while len(datos := proceso.stdout.read(tamano)) == tamano:
                fotograma = np.frombuffer(datos, np.uint8).reshape(
                    alto_det, ANCHO_DETECCION, 3
                )
                cajas = detector(fotograma)
                if len(cajas):
                    areas = (cajas[:, 2] - cajas[:, 0]) * (cajas[:, 3] - cajas[:, 1])
                    x1, _y1, x2, _y2 = cajas[int(np.argmax(areas)), :4]
                    centros.append(float((x1 + x2) / 2 / ANCHO_DETECCION))
                else:
                    centros.append(None)
                if on_percent is not None:
                    on_percent(min(100.0, len(centros) / esperadas * 100.0))
        except BaseException:
            proceso.kill()
            proceso.wait()
            raise
        proceso.wait()
        if proceso.returncode != 0:
            errores.seek(0)
            raise PasoFallido(
                _("La detección de caras falló (código {codigo})").format(
                    codigo=proceso.returncode),
                detalle=errores.read().decode("utf-8", errors="replace").strip()[-4000:],
            )
    return centros


def preparar_seguimiento(
    video: Path,
    ancho: int,
    alto: int,
    ruta_cmd: Path,
    on_percent: Callable[[float], None] | None = None,
    detector: Detector | None = None,
) -> int | None:
    """Escribe ``ruta_cmd`` y devuelve la x inicial del recorte; None sin caras."""
    camara = suavizar(muestrear_centros(video, ancho, alto, on_percent, detector))
    if camara is None:
        return None
    posiciones = posiciones_recorte(camara, ancho, ancho_recorte(alto))
    # Por encima de este salto es un cambio de plano: se corta, no se interpola.
    escribir_comandos(posiciones, ruta_cmd,
                      salto_px=int((SALTO_PLANO - ZONA_MUERTA) * ancho))
    return posiciones[0]


def suavizar(centros: list[float | None]) -> list[float] | None:
    """Trayectoria de cámara (0..1 del ancho) a partir de centros de cara."""
    conocidos = [c for c in centros if c is not None]
    if not conocidos:
        return None
    # Huecos: mantener la última posición. Al inicio, la primera cara si el
    # hueco es un fallo corto; si es largo (cabecera, título), el centro.
    relleno: list[float] = []
    hueco_inicial = centros.index(conocidos[0])
    ultimo = conocidos[0] if hueco_inicial <= HUECO_INICIAL_MAX * FPS_MUESTREO else 0.5
    for c in centros:
        ultimo = ultimo if c is None else c
        relleno.append(ultimo)
    # Mediana móvil: quita detecciones sueltas de otra cara.
    m = VENTANA_MEDIANA // 2
    mediana = [
        statistics.median(relleno[max(0, i - m):i + m + 1])
        for i in range(len(relleno))
    ]
    camara = [mediana[0]]
    for i in range(1, len(mediana)):
        actual, objetivo = camara[-1], mediana[i]
        if abs(mediana[i] - mediana[i - 1]) > SALTO_PLANO:
            actual = objetivo  # cambio de plano: salto directo, sin barrido
        elif abs(objetivo - actual) > ZONA_MUERTA:
            actual += ALFA * (objetivo - actual)
        camara.append(actual)
    return camara


def posiciones_recorte(
    centros: list[float], ancho: int, ancho_recorte: int
) -> list[int]:
    """x en píxeles del recorte centrado en cada centro, sin salirse del fotograma."""
    maximo = ancho - ancho_recorte
    return [
        min(maximo, max(0, round(c * ancho - ancho_recorte / 2)))
        for c in centros
    ]


def escribir_comandos(
    posiciones: list[int],
    ruta: Path,
    fps_muestreo: float = FPS_MUESTREO,
    fps_comandos: float = FPS_COMANDOS,
    salto_px: int | None = None,
) -> None:
    """Fichero ``sendcmd`` que mueve ``crop@v`` interpolando entre muestras.

    Los saltos mayores que ``salto_px`` no se interpolan: el valor nuevo
    entra de golpe en el instante de su muestra.
    """
    duracion = (len(posiciones) - 1) / fps_muestreo
    lineas: list[str] = []
    anterior: int | None = None
    for k in range(int(round(duracion * fps_comandos)) + 1):
        t = k / fps_comandos
        pos = min(t * fps_muestreo, len(posiciones) - 1)
        i = min(int(pos), len(posiciones) - 2) if len(posiciones) > 1 else 0
        frac = pos - i
        siguiente = posiciones[i + 1] if len(posiciones) > 1 else posiciones[i]
        if salto_px is not None and abs(siguiente - posiciones[i]) > salto_px:
            x = siguiente if frac >= 1 else posiciones[i]
        else:
            x = round(posiciones[i] + frac * (siguiente - posiciones[i]))
        if x != anterior:
            lineas.append(f"{t:.3f} crop@v x {x};")
            anterior = x
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
