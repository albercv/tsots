from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import SAMPLE_RATE_POR_MODELO, PipelineConfig
from .steps import (
    BASE_DIR,
    cortar_silencios,
    extraer_audio,
    limpiar_audio,
    quemar_subtitulos,
    remux,
    resolucion_video,
)
from .subtitles import agrupar, generar_ass, generar_srt, transcribir

Progreso = Callable[[dict], None]


def _emitir(on_progress: Progreso | None, step: int, total: int, label: str,
            percent: float | None = None) -> None:
    if on_progress is not None:
        on_progress(
            {"step": step, "total": total, "label": label, "percent": percent}
        )


def _fase_subtitulos(config: PipelineConfig, tmp_final: Path, final: Path,
                     trabajo: Path, on_progress: Progreso | None,
                     paso: int, total: int) -> Path:
    """Añade subtítulos a tmp_final. Devuelve la ruta a publicar.

    Si algo falla, emite {"warning": ...} y devuelve tmp_final sin tocar:
    el pipeline nunca falla por subtítulos.
    """
    try:
        cache_whisper = Path.home() / ".cache" / "huggingface" / "hub"
        en_cache = cache_whisper.is_dir() and any(
            cache_whisper.glob(f"models--*faster-whisper-{config.modelo_whisper}*")
        )
        _emitir(
            on_progress, paso, total,
            "Transcribiendo" if en_cache
            else "Descargando modelo Whisper y transcribiendo",
        )
        palabras = transcribir(tmp_final, config.idioma_subs,
                               config.modelo_whisper)
        if not palabras:
            raise RuntimeError("la transcripción no produjo palabras")
        bloques = agrupar(palabras, config.diseno)
        generar_srt(bloques, final.with_suffix(".srt"))
    except Exception as error:  # noqa: BLE001 — degradación deliberada
        if on_progress is not None:
            on_progress({
                "warning": f"Subtítulos fallaron: {error}. "
                           "Vídeo guardado sin subtítulos."
            })
        return tmp_final

    ass = trabajo / "subs.ass"
    tmp_subs = final.with_name(f".{final.stem}_subs_tmp{final.suffix}")
    try:
        trabajo.mkdir(parents=True, exist_ok=True)
        generar_ass(bloques, config.diseno, config.posicion_subs,
                    resolucion_video(tmp_final), ass, tamano=config.tamano_subs)
        tmp_subs.unlink(missing_ok=True)
        _emitir(on_progress, paso + 1, total, "Quemando subtítulos")
        quemar_subtitulos(
            tmp_final, ass, tmp_subs,
            on_percent=lambda p: _emitir(
                on_progress, paso + 1, total, "Quemando subtítulos", p
            ),
        )
        ass.unlink(missing_ok=True)
        tmp_final.unlink(missing_ok=True)
        return tmp_subs
    except Exception as error:  # noqa: BLE001 — degradación deliberada
        ass.unlink(missing_ok=True)
        tmp_subs.unlink(missing_ok=True)
        if on_progress is not None:
            on_progress({
                "warning": f"Subtítulos fallaron: {error}. "
                           "Vídeo guardado sin subtítulos (.srt conservado)."
            })
        return tmp_final


def run(config: PipelineConfig, on_progress: Progreso | None = None) -> Path:
    config.validar()
    video = config.video.expanduser().resolve()
    if not video.is_file():
        raise FileNotFoundError(f"No existe el vídeo: {video}")

    final = config.ruta_salida_final().expanduser().resolve()
    if final == video:
        raise ValueError("La salida no puede ser el mismo archivo que la entrada.")
    final.parent.mkdir(parents=True, exist_ok=True)

    nombre = video.stem
    tmp_final = final.with_name(f".{final.stem}_tmp{final.suffix}")
    tmp_final.unlink(missing_ok=True)

    extra = 2 if config.subtitulos else 0
    trabajo = BASE_DIR / "audio_procesado" / nombre

    if config.modo == "solo_silencios":
        total = 1 + extra
        _emitir(on_progress, 1, total, "Recortando silencios")
        cortar_silencios(
            video, tmp_final, config.margen, config.umbral,
            config.silencios, config.velocidad_silencios,
            on_percent=lambda p: _emitir(
                on_progress, 1, total, "Recortando silencios", p
            ),
        )
        publicar = tmp_final
        if config.subtitulos:
            publicar = _fase_subtitulos(
                config, tmp_final, final, trabajo, on_progress, 2, total
            )
        publicar.replace(final)
        return final

    trabajo.mkdir(parents=True, exist_ok=True)
    wav_original = trabajo / f"{nombre}_original.wav"
    wav_limpio = trabajo / f"{nombre}_audio_limpio.wav"

    total = (4 if config.modo == "completo" else 3) + extra
    sample_rate = SAMPLE_RATE_POR_MODELO[config.modelo]

    _emitir(on_progress, 1, total, "Extrayendo audio")
    extraer_audio(video, wav_original, sample_rate)

    checkpoint = BASE_DIR / "checkpoints" / config.modelo
    etiqueta_limpieza = (
        "Limpiando audio"
        if checkpoint.is_dir()
        else "Descargando modelo y limpiando audio"
    )
    _emitir(on_progress, 2, total, etiqueta_limpieza)
    limpiar_audio(wav_original, wav_limpio, config.tarea, config.modelo)

    if config.modo == "solo_audio":
        _emitir(on_progress, 3, total, "Sustituyendo pista de audio")
        remux(video, wav_limpio, tmp_final)
    else:
        video_intermedio = trabajo / f"{nombre}_solo_audio_limpio.mp4"
        _emitir(on_progress, 3, total, "Sustituyendo pista de audio")
        remux(video, wav_limpio, video_intermedio)
        _emitir(on_progress, 4, total, "Recortando silencios")
        cortar_silencios(
            video_intermedio, tmp_final, config.margen, config.umbral,
            config.silencios, config.velocidad_silencios,
            on_percent=lambda p: _emitir(
                on_progress, 4, total, "Recortando silencios", p
            ),
        )
        video_intermedio.unlink(missing_ok=True)

    publicar = tmp_final
    if config.subtitulos:
        paso_subs = total - 1  # penúltimo paso
        publicar = _fase_subtitulos(
            config, tmp_final, final, trabajo, on_progress, paso_subs, total
        )
    publicar.replace(final)
    return final
