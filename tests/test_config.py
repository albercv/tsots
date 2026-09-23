from __future__ import annotations

import json
from pathlib import Path

import pytest

from videopipeline.config import (
    MODELOS_POR_TAREA,
    MODOS,
    SAMPLE_RATE_POR_MODELO,
    PipelineConfig,
)


def _config_minima(**extra) -> PipelineConfig:
    valores = {"video": Path("/tmp/entrada.mp4")}
    valores.update(extra)
    return PipelineConfig(**valores)


def test_defectos():
    c = _config_minima()
    assert c.modo == "completo"
    assert c.tarea == "speech_enhancement"
    assert c.modelo == "MossFormer2_SE_48K"
    assert c.margen == "0.2s"
    assert c.umbral == "4%"
    assert c.silencios == "cortar"
    assert c.velocidad_silencios == 4
    assert c.salida is None


def test_json_ida_y_vuelta():
    c = _config_minima(salida=Path("/tmp/out"), modo="solo_audio")
    texto = c.to_json()
    datos = json.loads(texto)
    assert datos["video"] == "/tmp/entrada.mp4"
    c2 = PipelineConfig.from_json(texto)
    assert c2 == c


def test_validar_modo_invalido():
    with pytest.raises(ValueError, match="modo"):
        _config_minima(modo="turbo").validar()


def test_validar_modelo_incoherente_con_tarea():
    with pytest.raises(ValueError, match="modelo"):
        _config_minima(
            tarea="speech_separation", modelo="MossFormer2_SE_48K"
        ).validar()


def test_validar_silencios():
    with pytest.raises(ValueError, match="silencios"):
        _config_minima(silencios="borrar").validar()


def test_salida_final_por_defecto():
    c = _config_minima(video=Path("/videos/charla.mov"))
    assert c.ruta_salida_final() == Path("/videos/charla_limpio.mp4")


def test_salida_final_carpeta(tmp_path):
    c = _config_minima(video=Path("/videos/charla.mov"), salida=tmp_path)
    assert c.ruta_salida_final() == tmp_path / "charla_limpio.mp4"


def test_salida_final_archivo():
    c = _config_minima(salida=Path("/out/final.mp4"))
    assert c.ruta_salida_final() == Path("/out/final.mp4")


def test_tablas_de_modelos():
    assert MODOS == ("completo", "solo_audio", "solo_silencios")
    assert MODELOS_POR_TAREA["speech_enhancement"] == [
        "MossFormer2_SE_48K",
        "FRCRN_SE_16K",
        "MossFormerGAN_SE_16K",
    ]
    assert MODELOS_POR_TAREA["speech_separation"] == ["MossFormer2_SS_16K"]
    assert MODELOS_POR_TAREA["speech_super_resolution"] == ["MossFormer2_SR_48K"]
    assert SAMPLE_RATE_POR_MODELO["MossFormer2_SE_48K"] == 48000
    assert SAMPLE_RATE_POR_MODELO["FRCRN_SE_16K"] == 16000


def test_defectos_subtitulos():
    c = _config_minima()
    assert c.subtitulos is False
    assert c.diseno == "reels_bold"
    assert c.posicion_subs == 75
    assert c.idioma_subs == "es"
    assert c.modelo_whisper == "turbo"


def test_json_incluye_subtitulos():
    c = _config_minima(subtitulos=True, diseno="caja", posicion_subs=80)
    c2 = PipelineConfig.from_json(c.to_json())
    assert c2 == c


def test_validar_diseno_invalido():
    with pytest.raises(ValueError, match="diseno"):
        _config_minima(diseno="neon").validar()


def test_validar_posicion_fuera_de_rango():
    with pytest.raises(ValueError, match="posicion_subs"):
        _config_minima(posicion_subs=40).validar()
    with pytest.raises(ValueError, match="posicion_subs"):
        _config_minima(posicion_subs=96).validar()


def test_validar_idioma_y_modelo_whisper():
    with pytest.raises(ValueError, match="idioma_subs"):
        _config_minima(idioma_subs="fr").validar()
    with pytest.raises(ValueError, match="modelo_whisper"):
        _config_minima(modelo_whisper="large").validar()


def test_tablas_subtitulos():
    from videopipeline.config import DISENOS, IDIOMAS_SUBS, MODELOS_WHISPER

    from videopipeline.subtitles import PRESETS

    assert DISENOS == ("reels_bold", "reels_karaoke", "caja", "impacto",
                       "amarillo", "karaoke_verde", "minimal", "caja_blanca")
    assert set(DISENOS) == set(PRESETS)
    assert IDIOMAS_SUBS == ("es", "auto", "en")
    assert MODELOS_WHISPER == ("small", "medium", "turbo")


def test_defecto_tamano_subs():
    assert _config_minima().tamano_subs == 100


def test_json_incluye_tamano_subs():
    c = _config_minima(tamano_subs=130)
    assert PipelineConfig.from_json(c.to_json()) == c


def test_validar_tamano_subs_fuera_de_rango():
    with pytest.raises(ValueError, match="tamano_subs"):
        _config_minima(tamano_subs=49).validar()
    with pytest.raises(ValueError, match="tamano_subs"):
        _config_minima(tamano_subs=151).validar()


def test_caption_defectos():
    c = _config_minima()
    assert c.caption_seo is False
    assert c.contexto_marca == ""
    assert c.modelo_caption == "qwen3.5:9b"


def test_caption_json_ida_y_vuelta():
    c = _config_minima(caption_seo=True, contexto_marca="Soy Alberto, tono cercano",
                       modelo_caption="qwen3.5:9b-q8_0")
    c2 = PipelineConfig.from_json(c.to_json())
    assert c2 == c
    assert c2.caption_seo is True
    assert c2.contexto_marca == "Soy Alberto, tono cercano"


def test_caption_modelo_vacio_invalido():
    with pytest.raises(ValueError, match="modelo_caption"):
        _config_minima(caption_seo=True, modelo_caption="").validar()


def test_idioma_ui_por_defecto_y_json():
    c = _config_minima()
    assert c.idioma_ui == "es"
    c2 = PipelineConfig.from_json(_config_minima(idioma_ui="en").to_json())
    assert c2.idioma_ui == "en"


def test_glosario_por_defecto_vacio_y_viaja_en_json():
    c = _config_minima()
    assert c.glosario == ""
    c = _config_minima(glosario="Claude Code = Cloud Code\nAnthropic")
    assert PipelineConfig.from_json(c.to_json()).glosario == c.glosario
