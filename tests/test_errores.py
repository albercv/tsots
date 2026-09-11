from __future__ import annotations

import subprocess
from pathlib import Path

from videopipeline import i18n
from videopipeline.errores import (
    Diagnostico,
    explicar,
    explicar_codigo_salida,
    limpiar_salida,
)


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


def test_limpiar_salida_quita_ansi_y_progreso_de_auto_editor():
    crudo = (
        "(mp4) \x1b[95mh264\x1b[0m+\x1b[96maac\x1b[0m~38.0~13944.0~8.48\r"
        "(mp4) \x1b[95mh264\x1b[0m+\x1b[96maac\x1b[0m~52.0~13944.0~8.49\r"
        "        \x1b[31m\x1b[40mError! Could not write packet: Invalid argument "
        "(stream 0, pts 313600, dts 312000)\x1b[0m\x1b[0m\n"
    )
    limpio = limpiar_salida(crudo)
    assert "\x1b" not in limpio
    assert "~13944.0~" not in limpio
    assert limpio == (
        "Error! Could not write packet: Invalid argument "
        "(stream 0, pts 313600, dts 312000)"
    )


def test_limpiar_salida_conserva_lineas_normales_y_orden():
    assert limpiar_salida("a\r\nb\n\n  c  \n") == "a\nb\nc"


def test_explicar_could_not_write_packet_de_auto_editor():
    d = explicar(
        "auto-editor falló (código 1)",
        "Error! Could not write packet: Invalid argument (stream 0, pts 1, dts 0)",
    )
    assert isinstance(d, Diagnostico)
    assert d.titulo == "auto-editor no pudo escribir el vídeo"
    assert "auto-editor" in d.causa
    assert "reencod" in d.solucion.lower()
    assert d.conocido is True


def test_explicar_disco_lleno():
    d = explicar("Extracción de audio falló (código 1)",
                 "av_interleaved_write_frame(): No space left on device")
    assert d.conocido
    assert "disco" in d.titulo.lower()


def test_explicar_moov_atom():
    d = explicar("Sustitución de la pista de audio falló (código 1)",
                 "moov atom not found\nInvalid data found when processing input")
    assert d.conocido
    assert "incompleto" in d.causa.lower() or "corrupto" in d.causa.lower()


def test_explicar_memoria_torch():
    d = explicar("RuntimeError", "MPS backend out of memory (MPS allocated: 30.1 GB)")
    assert d.conocido
    assert "memoria" in d.titulo.lower()


def test_explicar_desconocido_conserva_mensaje_original():
    d = explicar("KeyError", "'width'")
    assert d.conocido is False
    assert d.titulo == "KeyError"
    assert "'width'" in d.detalle
    assert "desconocido" in d.causa.lower()


def test_explicar_codigo_salida_senales():
    assert explicar_codigo_salida(0) == ""
    assert "SIGKILL" in explicar_codigo_salida(-9)
    assert "memoria" in explicar_codigo_salida(-9).lower()
    assert "SIGSEGV" in explicar_codigo_salida(-11)
    # macOS/Qt: procesos matados por señal pueden llegar como 128+N
    assert "SIGKILL" in explicar_codigo_salida(137)
    assert explicar_codigo_salida(1) == ""


def test_diagnostico_texto_es_multilinea_legible():
    d = explicar(
        "auto-editor falló (código 1)",
        "Error! Could not write packet: Invalid argument",
    )
    texto = d.texto()
    lineas = texto.splitlines()
    assert lineas[0] == d.titulo
    assert any(l.startswith("Causa: ") for l in lineas)
    assert any(l.startswith("Qué hacer: ") for l in lineas)
    assert texto.rstrip().endswith("Error! Could not write packet: Invalid argument")


def test_explicar_ollama_no_instalado():
    d = explicar("Ollama no está instalado (no se encuentra 'ollama' en PATH)")
    assert d.conocido
    assert "brew install ollama" in d.solucion


def test_explicar_modelo_ollama_no_descargado():
    d = explicar("Modelo no descargado: qwen3.5:9b",
                 '{"error":"model \'qwen3.5:9b\' not found"}')
    assert d.conocido
    assert "ollama pull" in d.solucion


def test_explicar_ollama_no_responde():
    d = explicar("Ollama no responde en http://localhost:11434 tras 15 s")
    assert d.conocido
    assert "11434" in d.causa or "11434" in d.solucion


def test_explicar_reconoce_mensaje_traducido_al_ingles(tmp_path):
    """Los mensajes que lanza nuestro propio código se traducen al lanzarse;
    el patrón de Ollama no instalado debe seguir reconociéndolos en inglés."""
    ruta = _catalogo(tmp_path, "en", {
        "Ollama no está instalado (no se encuentra 'ollama' en PATH)":
            "Ollama is not installed ('ollama' not found in PATH)",
    })
    try:
        i18n.instalar("en", dir_locale=ruta)
        mensaje = i18n._("Ollama no está instalado (no se encuentra 'ollama' en PATH)")
        assert mensaje == "Ollama is not installed ('ollama' not found in PATH)"
        d = explicar(mensaje)
        assert d.conocido is True
    finally:
        i18n.instalar("es")
