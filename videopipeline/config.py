from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

MODOS = ("completo", "solo_audio", "solo_silencios")

MODELOS_POR_TAREA: dict[str, list[str]] = {
    "speech_enhancement": [
        "MossFormer2_SE_48K",
        "FRCRN_SE_16K",
        "MossFormerGAN_SE_16K",
    ],
    "speech_separation": ["MossFormer2_SS_16K"],
    "speech_super_resolution": ["MossFormer2_SR_48K"],
}

SAMPLE_RATE_POR_MODELO: dict[str, int] = {
    "MossFormer2_SE_48K": 48000,
    "FRCRN_SE_16K": 16000,
    "MossFormerGAN_SE_16K": 16000,
    "MossFormer2_SS_16K": 16000,
    "MossFormer2_SR_48K": 48000,
}

SILENCIOS = ("cortar", "acelerar")

DISENOS = ("reels_bold", "reels_karaoke", "caja", "impacto", "amarillo",
           "karaoke_verde", "minimal", "caja_blanca")
IDIOMAS_SUBS = ("es", "auto", "en")
MODELOS_WHISPER = ("small", "medium")


@dataclass
class PipelineConfig:
    video: Path
    salida: Path | None = None
    modo: str = "completo"
    tarea: str = "speech_enhancement"
    modelo: str = "MossFormer2_SE_48K"
    margen: str = "0.2s"
    umbral: str = "4%"
    silencios: str = "cortar"
    velocidad_silencios: int = 4
    subtitulos: bool = False
    diseno: str = "reels_bold"
    posicion_subs: int = 75
    idioma_subs: str = "es"
    modelo_whisper: str = "small"
    tamano_subs: int = 100
    caption_seo: bool = False
    contexto_marca: str = ""
    modelo_caption: str = "qwen3.5:9b"
    idioma_ui: str = "es"  # idioma de etiquetas, avisos y diagnósticos del runner

    def validar(self) -> None:
        if self.modo not in MODOS:
            raise ValueError(f"modo inválido: {self.modo!r} (esperado uno de {MODOS})")
        if self.tarea not in MODELOS_POR_TAREA:
            raise ValueError(
                f"tarea inválida: {self.tarea!r} "
                f"(esperada una de {tuple(MODELOS_POR_TAREA)})"
            )
        if self.modelo not in MODELOS_POR_TAREA[self.tarea]:
            raise ValueError(
                f"modelo {self.modelo!r} no válido para la tarea {self.tarea!r}"
            )
        if self.silencios not in SILENCIOS:
            raise ValueError(
                f"silencios inválido: {self.silencios!r} (esperado uno de {SILENCIOS})"
            )
        if self.diseno not in DISENOS:
            raise ValueError(f"diseno inválido: {self.diseno!r} (esperado uno de {DISENOS})")
        if not 50 <= self.posicion_subs <= 95:
            raise ValueError(
                f"posicion_subs fuera de rango: {self.posicion_subs} (esperado 50-95)"
            )
        if self.idioma_subs not in IDIOMAS_SUBS:
            raise ValueError(
                f"idioma_subs inválido: {self.idioma_subs!r} (esperado uno de {IDIOMAS_SUBS})"
            )
        if self.modelo_whisper not in MODELOS_WHISPER:
            raise ValueError(
                f"modelo_whisper inválido: {self.modelo_whisper!r} "
                f"(esperado uno de {MODELOS_WHISPER})"
            )
        if not 50 <= self.tamano_subs <= 150:
            raise ValueError(
                f"tamano_subs fuera de rango: {self.tamano_subs} (esperado 50-150)"
            )
        if not self.modelo_caption.strip():
            raise ValueError("modelo_caption no puede estar vacío")

    def to_json(self) -> str:
        datos = asdict(self)
        datos["video"] = str(self.video)
        datos["salida"] = str(self.salida) if self.salida is not None else None
        return json.dumps(datos, ensure_ascii=False)

    @classmethod
    def from_json(cls, texto: str) -> "PipelineConfig":
        datos = json.loads(texto)
        datos["video"] = Path(datos["video"])
        if datos.get("salida") is not None:
            datos["salida"] = Path(datos["salida"])
        return cls(**datos)

    def ruta_salida_final(self) -> Path:
        nombre = f"{self.video.stem}_limpio.mp4"
        if self.salida is None:
            return self.video.with_name(nombre)
        # Una ruta sin sufijo (o un directorio existente) se trata como carpeta.
        if self.salida.suffix == "" or self.salida.is_dir():
            return self.salida / nombre
        return self.salida
