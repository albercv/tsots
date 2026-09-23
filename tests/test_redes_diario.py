"""Registro de diagnóstico de la publicación: nunca contiene la clave."""
from __future__ import annotations

import logging
import re

import pytest

from videopipeline import steps
from videopipeline.redes import diario

from tests.secretos_falsos import jwt_falso

CLAVE = jwt_falso(sub="yo")
CLAVE_CORTA = "k3y-muy+secreta/42=="


# --- limpiar ---


def test_limpiar_quita_la_clave_exacta_y_codificada():
    texto = f"a {CLAVE_CORTA} b k3y-muy%2Bsecreta%2F42%3D%3D c"
    limpio = diario.limpiar(texto, [CLAVE_CORTA])
    assert CLAVE_CORTA not in limpio
    assert "k3y-muy%2Bsecreta" not in limpio
    assert limpio.startswith("a ***") and limpio.endswith("c")


@pytest.mark.parametrize("texto, secreto", [
    ("Authorization: Basic abcdefgh12345678", "abcdefgh12345678"),
    ("{'authorization': 'Token zzzzzzzz9999'}", "zzzzzzzz9999"),
    ("Bearer abcdefghijklmnop1234", "abcdefghijklmnop1234"),
    ('{"api_key": "sk_live_987654321"}', "sk_live_987654321"),
    ("token=abc123def456&x=1", "abc123def456"),
    ('"password":"hunter2hunter2"', "hunter2hunter2"),
    (f"jwt {CLAVE} fin", CLAVE),
    ("larga Q2hhdmVzRGVBY2Nlc29NdXlMYXJnYXNZT3BhY2FzMTIzNDU2Nzg5MA fin",
     "Q2hhdmVzRGVBY2Nlc29NdXlMYXJnYXNZT3BhY2FzMTIzNDU2Nzg5MA"),
])
def test_limpiar_quita_lo_que_parece_un_token(texto, secreto):
    limpio = diario.limpiar(texto)
    assert secreto not in limpio
    assert "***" in limpio


def test_limpiar_conserva_lo_util_para_diagnosticar():
    texto = ("request_id=3f2b8c1e-9a7d-4e21-b5c3-0d6e8f9a1b2c "
             "https://www.youtube.com/shorts/AbC123xyz "
             "/Users/yo/Downloads/amazin_5_5_limpio.mp4 "
             "Falta la API key del servicio: guárdala en Redes… "
             "TikTok is not included in your plan")
    assert diario.limpiar(texto) == texto


def test_truncar():
    assert diario.truncar("abc", 10) == "abc"
    corto = diario.truncar("x" * 5000, 100)
    assert len(corto) < 200 and "5000" in corto


# --- Diario ---


def test_ruta_en_la_carpeta_de_logs_del_proyecto():
    assert diario.DIR_LOGS_PROYECTO == steps.BASE_DIR / "logs"


def test_crea_el_fichero_con_nombre_y_marcas_de_tiempo(tmp_path, monkeypatch):
    monkeypatch.setattr(diario, "DIR_LOGS", tmp_path / "logs")
    d = diario.Diario(tmp_path / "amazin_5_5_limpio.mp4")
    try:
        d.log.info("hola %s", "mundo")
        logging.getLogger("videopipeline.redes.cualquiera").info("desde un proveedor")
    finally:
        d.cerrar()
    assert d.ruta.parent == tmp_path / "logs"
    assert re.fullmatch(r"publicacion_amazin_5_5_limpio_\d{8}-\d{6}\.log", d.ruta.name)
    texto = d.ruta.read_text(encoding="utf-8")
    assert "hola mundo" in texto and "desde un proveedor" in texto
    assert re.search(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} ", texto, re.M)
    # Cerrado: lo siguiente ya no se escribe.
    logging.getLogger("videopipeline.redes").info("después de cerrar")
    assert "después de cerrar" not in d.ruta.read_text(encoding="utf-8")


def test_la_clave_nunca_llega_al_log_ni_en_una_excepcion(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(diario, "DIR_LOGS", tmp_path / "logs")
    d = diario.Diario(tmp_path / "v.mp4")
    d.ocultar(CLAVE_CORTA)
    try:
        d.log.info("cabecera %s", {"Authorization": f"X {CLAVE_CORTA}"})
        try:
            raise RuntimeError(f"fallo con la clave {CLAVE_CORTA} dentro")
        except RuntimeError:
            logging.getLogger("videopipeline.redes.proveedor_x").exception("inesperado")
        d.log.warning("aviso %s", CLAVE_CORTA)
    finally:
        d.cerrar()
    texto = d.ruta.read_text(encoding="utf-8")
    assert "Traceback" in texto and "RuntimeError" in texto
    assert CLAVE_CORTA not in texto
    assert "k3y-muy" not in texto
    # Tampoco sale por la consola (que acaba en logs/lanzador.log).
    salida = capsys.readouterr()
    assert CLAVE_CORTA not in salida.out + salida.err


def test_carpeta_no_escribible_no_rompe(tmp_path, monkeypatch):
    bloqueo = tmp_path / "fichero"
    bloqueo.write_text("x")
    monkeypatch.setattr(diario, "DIR_LOGS", bloqueo / "logs")
    d = diario.Diario(tmp_path / "v.mp4")
    d.log.info("no pasa nada")
    d.cerrar()
    assert d.ruta is None
