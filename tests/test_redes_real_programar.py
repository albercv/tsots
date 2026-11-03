"""Prueba real de programar y cancelar. Nunca corre por defecto.

    QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m lenta tests/test_redes_real_programar.py -s

Usa la API key del Llavero y el perfil guardado en Redes… (o la variable
TSOTS_PERFIL_REDES). Programa un vídeo de prueba de 5 s SOLO en TikTok, como
borrador y para dentro de 30 días; comprueba que aparece en lo programado y lo
cancela enseguida (también si algo falla a medias). No se publica nada y
Upload-Post devuelve el crédito. Sin clave en el Llavero, se salta.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.lenta


def test_programar_y_cancelar_en_tiktok(tmp_path):
    from app import credenciales
    from app.settings import Ajustes
    from app.widgets.dialogo_publicar import zona_local
    from videopipeline.redes import proveedor, publicador
    from videopipeline.redes.modelo import ModoTikTok, Opciones, Plataforma, Publicacion

    ajustes = Ajustes()
    nombre = ajustes.proveedor_redes
    try:
        clave = credenciales.leer(nombre)
    except credenciales.ErrorLlavero:
        clave = None
    if not clave:
        pytest.skip("no hay API key en el Llavero (guárdala desde Redes…)")
    perfil = os.environ.get("TSOTS_PERFIL_REDES") or ajustes.perfil_redes
    if proveedor.usa_perfil(nombre) and not perfil:
        pytest.skip("falta el perfil (Redes… o TSOTS_PERFIL_REDES)")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg no disponible")

    video = tmp_path / "tsots_prueba_programar.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=0x43a047:s=1080x1920:d=5:r=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(video)],
        check=True,
    )
    publicacion = Publicacion(
        video=video, titulo="Prueba de TSOTS (programada, se cancela)",
        caption="Prueba de programar de The Silence of the Shorts. Se cancela sola.",
        hashtags=("#prueba",))
    cuando = (datetime.now(zona_local()) + timedelta(days=30)).replace(
        hour=12, minute=0, second=0, microsecond=0)
    opciones = Opciones(tiktok_modo=ModoTikTok.BORRADOR, programada=cuando)
    plataformas = [Plataforma.TIKTOK]
    # Salvaguarda: solo un borrador de TikTok, y programado lejos.
    assert opciones.tiktok_modo == ModoTikTok.BORRADOR and plataformas == [Plataforma.TIKTOK]
    assert opciones.programada > datetime.now(zona_local()) + timedelta(days=7)

    servicio = proveedor.crear(nombre, clave, {"perfil": perfil})
    resultado = publicador.publicar(servicio, publicacion, opciones, plataformas,
                                    registrar=False)[Plataforma.TIKTOK]
    print(f"resultado: ok={resultado.ok} programada={resultado.programada} "
          f"referencia={resultado.referencia!r} error={resultado.error!r}")
    referencia = resultado.referencia
    try:
        assert resultado.ok and resultado.programada == cuando, resultado.error
        assert referencia, "el servicio no devolvió job_id: cancélala desde Programadas…"
        pendientes = {p.referencia: p for p in servicio.programadas()}
        assert referencia in pendientes
        propia = pendientes[referencia]
        print(f"en el servicio: {propia.fecha.isoformat()} {propia.plataformas} "
              f"{propia.titulo!r} {propia.modos}")
        assert propia.fecha == cuando  # mismo instante, aunque venga en UTC
        assert propia.plataformas == (Plataforma.TIKTOK,)
    finally:
        if referencia:
            servicio.cancelar(referencia)
            print(f"cancelada {referencia}")
    assert referencia not in {p.referencia for p in servicio.programadas()}
