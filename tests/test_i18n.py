from __future__ import annotations

import subprocess
from pathlib import Path

from videopipeline import i18n


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


def test_sin_instalar_devuelve_el_texto_fuente():
    i18n.instalar("es")
    assert i18n._("Extrayendo audio") == "Extrayendo audio"


def test_instalar_en_traduce_y_es_vuelve_al_origen(tmp_path):
    ruta = _catalogo(tmp_path, "en", {"Extrayendo audio": "Extracting audio"})
    i18n.instalar("en", dir_locale=ruta)
    assert i18n._("Extrayendo audio") == "Extracting audio"
    assert i18n._("Sin traducción") == "Sin traducción"  # fallback al msgid
    i18n.instalar("es", dir_locale=ruta)
    assert i18n._("Extrayendo audio") == "Extrayendo audio"


def test_idioma_actual_y_normalizacion(tmp_path):
    i18n.instalar("en_US", dir_locale=tmp_path)
    assert i18n.idioma_actual() == "en"
    i18n.instalar("es-ES", dir_locale=tmp_path)
    assert i18n.idioma_actual() == "es"
    i18n.instalar("fr", dir_locale=tmp_path)  # no soportado → fuente
    assert i18n.idioma_actual() == "es"


def test_detectar_prefiere_variable_de_entorno(monkeypatch):
    monkeypatch.setenv("TSOTS_LANG", "en")
    assert i18n.detectar() == "en"
    monkeypatch.setenv("TSOTS_LANG", "sistema")
    monkeypatch.setenv("LANG", "en_GB.UTF-8")
    assert i18n.detectar() == "en"
    monkeypatch.setenv("LANG", "es_ES.UTF-8")
    assert i18n.detectar() == "es"
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.detectar() == "es"  # idioma no soportado → fuente


def test_N_marca_sin_traducir():
    assert i18n.N_("en espera") == "en espera"


def test_catalogo_real_ingles_existe_y_traduce_una_cadena_clave():
    """El .mo real del proyecto (locale/en) debe existir y cubrir la GUI."""
    i18n.instalar("en")
    try:
        assert i18n._("Título, caption y hashtags") == "Title, caption and hashtags"
        assert i18n._("Extrayendo audio") == "Extracting audio"
    finally:
        i18n.instalar("es")
