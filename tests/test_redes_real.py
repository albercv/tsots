"""Prueba real contra el proveedor configurado. Nunca corre por defecto.

    QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m lenta tests/test_redes_real.py -s

Usa la API key del Llavero y el perfil guardado en Redes… (o la variable
TSOTS_PERFIL_REDES). Sube un vídeo de prueba de 5 s SOLO a TikTok y SOLO como
borrador: no se publica nada. Bórralo luego de los borradores de TikTok.
Sin clave en el Llavero, se salta.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.lenta


def test_borrador_real_en_tiktok(tmp_path):
    from app import credenciales
    from app.settings import Ajustes
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

    video = tmp_path / "tsots_prueba_borrador.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=0x1e88e5:s=1080x1920:d=5:r=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(video)],
        check=True,
    )
    publicacion = Publicacion(
        video=video, titulo="Prueba de TSOTS (borrador)",
        caption="Borrador de prueba de The Silence of the Shorts. Bórralo.",
        hashtags=("#prueba",))
    opciones = Opciones(tiktok_modo=ModoTikTok.BORRADOR)
    plataformas = [Plataforma.TIKTOK]
    # Salvaguarda: esta prueba solo puede dejar un borrador en TikTok.
    assert opciones.tiktok_modo == ModoTikTok.BORRADOR and plataformas == [Plataforma.TIKTOK]

    resultados = publicador.publicar(
        proveedor.crear(nombre, clave, {"perfil": perfil}), publicacion, opciones,
        plataformas, registrar=False, espera_maxima=600,
        progreso=lambda p, e, r: print(f"{p.nombre}: {e.value}"),
    )
    resultado = resultados[Plataforma.TIKTOK]
    print(f"resultado: ok={resultado.ok} url={resultado.url!r} extra={resultado.extra}")
    assert resultado.ok, resultado.error
