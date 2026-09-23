"""Llavero: `subprocess.run` siempre falso; nunca se ejecuta `security`."""
from __future__ import annotations

import subprocess

import pytest

from app import credenciales

CLAVE = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.firma-_123"


class Grabador:
    def __init__(self, respuestas=None):
        self.llamadas: list[dict] = []
        self.respuestas = list(respuestas or [])

    def __call__(self, args, *a, **kw):
        self.llamadas.append({"args": list(args), **kw})
        codigo, salida = self.respuestas.pop(0) if self.respuestas else (0, "")
        return subprocess.CompletedProcess(args, codigo, salida, "")


@pytest.fixture
def grabador(monkeypatch):
    def poner(respuestas=None):
        g = Grabador(respuestas)
        monkeypatch.setattr(subprocess, "run", g)
        return g
    return poner


def test_servicio_por_proveedor():
    assert credenciales.servicio("prov") == "tsots-prov"


def test_guardar_usa_add_generic_password_por_stdin(grabador):
    g = grabador([(0, ""), (0, CLAVE + "\n")])
    credenciales.guardar("prov", f"  {CLAVE} ")
    guardar, comprobar = g.llamadas
    assert guardar["args"] == ["/usr/bin/security", "-i"]
    assert guardar["input"] == (
        f"add-generic-password -U -s tsots-prov -a api-key -w {CLAVE}\n")
    # La clave nunca va en la línea de órdenes (visible con ps).
    assert all(CLAVE not in arg for llamada in g.llamadas for arg in llamada["args"])
    assert comprobar["args"] == ["/usr/bin/security", "find-generic-password",
                                 "-s", "tsots-prov", "-a", "api-key", "-w"]
    assert guardar["capture_output"] is True


def test_guardar_falla_si_no_se_puede_leer_de_vuelta(grabador):
    grabador([(0, ""), (44, "")])
    with pytest.raises(credenciales.ErrorLlavero) as info:
        credenciales.guardar("prov", CLAVE)
    assert CLAVE not in str(info.value)


@pytest.mark.parametrize("mala", ["", "  ", "con espacio", 'com"illa', "a\nb", "a;b"])
def test_guardar_rechaza_claves_raras_sin_ejecutar(grabador, mala):
    g = grabador()
    with pytest.raises(credenciales.ErrorLlavero) as info:
        credenciales.guardar("prov", mala)
    assert g.llamadas == []
    assert mala.strip() == "" or mala not in str(info.value)


def test_leer_usa_find_generic_password(grabador):
    g = grabador([(0, CLAVE + "\n")])
    assert credenciales.leer("prov") == CLAVE
    assert g.llamadas[0]["args"] == ["/usr/bin/security", "find-generic-password",
                                     "-s", "tsots-prov", "-a", "api-key", "-w"]


def test_clave_ausente_devuelve_none(grabador):
    grabador([(44, "")])
    assert credenciales.leer("prov") is None


def test_error_al_leer_no_muestra_nada_sensible(grabador):
    grabador([(51, CLAVE)])
    with pytest.raises(credenciales.ErrorLlavero) as info:
        credenciales.leer("prov")
    assert CLAVE not in str(info.value) and "51" in str(info.value)


def test_hay_clave_no_pide_el_secreto(grabador):
    g = grabador([(0, "keychain: ..."), (44, "")])
    assert credenciales.hay_clave("prov") is True
    assert credenciales.hay_clave("prov") is False
    assert all("-w" not in llamada["args"] for llamada in g.llamadas)


def test_borrar(grabador):
    g = grabador([(0, ""), (44, "")])
    assert credenciales.borrar("prov") is True
    assert credenciales.borrar("prov") is False
    assert g.llamadas[0]["args"] == ["/usr/bin/security", "delete-generic-password",
                                     "-s", "tsots-prov", "-a", "api-key"]


def test_security_ausente(monkeypatch):
    def falta(*a, **k):
        raise FileNotFoundError("security")
    monkeypatch.setattr(subprocess, "run", falta)
    with pytest.raises(credenciales.ErrorLlavero):
        credenciales.leer("prov")
    assert credenciales.hay_clave("prov") is False


def test_llavero_falso_de_la_red_de_seguridad(llavero_falso):
    """Sin mock explícito, los tests usan el Llavero en memoria."""
    assert credenciales.leer("prov") is None
    credenciales.guardar("prov", CLAVE)
    assert credenciales.hay_clave("prov")
    assert credenciales.leer("prov") == CLAVE
    assert llavero_falso.elementos == {("tsots-prov", "api-key"): CLAVE}
    assert credenciales.borrar("prov")
    assert credenciales.leer("prov") is None


def test_red_bloqueada_en_tests():
    import httpx

    with pytest.raises(RuntimeError, match="Red bloqueada"):
        httpx.get("https://example.com")
