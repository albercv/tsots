from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import SAMPLE_RATE_POR_MODELO, PipelineConfig
from .seguimiento import RUTA_PESOS, preparar_seguimiento
from .steps import (
    BASE_DIR,
    PasoFallido,
    cortar_silencios,
    extraer_audio,
    limpiar_audio,
    quemar_subtitulos,
    rellenar_huecos_audio,
    remux,
    resolucion_video,
)
from .subtitles import (
    agrupar, generar_ass, generar_srt, modelo_en_cache, transcribir,
)
from .caption import escribir_md, texto_plano
from .caption import generar as generar_caption
from .errores import explicar
from .glosario import corregir as corregir_glosario
from .glosario import parsear as parsear_glosario
from .glosario import prompt_whisper, terminos_caption
from .i18n import _
from .ollama import asegurar_servidor
from .subtitles import Bloque, Palabra
from .vertical import (
    ALTO_VERTICAL,
    ANCHO_VERTICAL,
    convertir_vertical,
    es_ya_vertical,
    filtro_vertical,
)

Progreso = Callable[[dict], None]


def _emitir(on_progress: Progreso | None, step: int, total: int, label: str,
            percent: float | None = None) -> None:
    if on_progress is not None:
        on_progress(
            {"step": step, "total": total, "label": label, "percent": percent}
        )


def _avisar(on_progress: Progreso | None, texto: str) -> None:
    if on_progress is not None:
        on_progress({"warning": texto})


def _transcribir(config: PipelineConfig, video: Path,
                 on_progress: Progreso | None) -> list[Palabra]:
    """Transcribe con la pista del glosario y corrige los errores conocidos.

    Si el glosario falla, avisa y devuelve la transcripción sin corregir.
    """
    glosario = parsear_glosario(config.glosario)
    palabras = transcribir(video, config.idioma_subs, config.modelo_whisper,
                           prompt=prompt_whisper(glosario))
    try:
        return corregir_glosario(palabras, glosario)
    except Exception as error:  # noqa: BLE001 — degradación deliberada
        _avisar(on_progress,
                _("El glosario de términos falló: {error}. Se usa la "
                  "transcripción sin corregir.").format(error=error))
        return palabras


def _transcribir_subs(config: PipelineConfig, fuente: Path, final: Path,
                      on_progress: Progreso | None, paso: int, total: int,
                      degradar: bool, wav_continuo: Path | None = None
                      ) -> tuple[list[Palabra] | None, list[Bloque] | None]:
    """Transcribe `fuente` una vez y escribe el .srt. Devuelve (palabras, bloques).

    Con `wav_continuo`, se transcribe una pista de audio con los huecos
    rellenos extraída de `fuente`: Whisper encadena el audio sin respetar los
    huecos del iPhone y los subtítulos se adelantarían a la voz.
    Con `degradar`, un fallo avisa y devuelve (None, None): el vídeo se guarda
    sin subtítulos. Sin él (los subtítulos son el único paso), el error sube.
    """
    try:
        en_cache = modelo_en_cache(config.modelo_whisper)
        _emitir(
            on_progress, paso, total,
            _("Transcribiendo") if en_cache
            else _("Descargando modelo Whisper y transcribiendo"),
        )
        if wav_continuo is not None:
            wav_continuo.parent.mkdir(parents=True, exist_ok=True)
            extraer_audio(fuente, wav_continuo, 16000)
            fuente = wav_continuo
        palabras = _transcribir(config, fuente, on_progress)
        if not palabras:
            raise RuntimeError("la transcripción no produjo palabras")
        bloques = agrupar(palabras, config.diseno)
        generar_srt(bloques, final.with_suffix(".srt"))
    except Exception as error:  # noqa: BLE001 — degradación deliberada
        if not degradar:
            raise
        _avisar(on_progress,
                _("Subtítulos fallaron: {error}. "
                  "Vídeo guardado sin subtítulos.").format(error=error))
        return None, None
    finally:
        if wav_continuo is not None:
            wav_continuo.unlink(missing_ok=True)
    return palabras, bloques


def _quemar_subs(config: PipelineConfig, bloques: list[Bloque], fuente: Path,
                 final: Path, trabajo: Path, on_progress: Progreso | None,
                 paso: int, total: int, desde_original: bool,
                 degradar: bool) -> Path | None:
    """Quema los subtítulos de `fuente` en un temporal y lo devuelve.

    No toca `fuente`: la fase vertical la usa sin subtítulos. Con `degradar`,
    un fallo avisa y devuelve None; sin él, el error sube.
    """
    ass = trabajo / "subs.ass"
    tmp_subs = final.with_name(f".{final.stem}_subs_tmp{final.suffix}")
    try:
        trabajo.mkdir(parents=True, exist_ok=True)
        generar_ass(bloques, config.diseno, config.posicion_subs,
                    resolucion_video(fuente), ass, tamano=config.tamano_subs)
        tmp_subs.unlink(missing_ok=True)
        _emitir(on_progress, paso, total, _("Quemando subtítulos"))
        quemar_subtitulos(
            fuente, ass, tmp_subs,
            on_percent=lambda p: _emitir(
                on_progress, paso, total, _("Quemando subtítulos"), p
            ),
            desde_original=desde_original,
        )
        return tmp_subs
    except Exception as error:  # noqa: BLE001 — degradación deliberada
        tmp_subs.unlink(missing_ok=True)
        if not degradar:
            raise
        _avisar(on_progress,
                _("Subtítulos fallaron: {error}. "
                  "Vídeo guardado sin subtítulos (.srt conservado)."
                  ).format(error=error))
        return None
    finally:
        ass.unlink(missing_ok=True)


def _fase_caption(config: PipelineConfig, video_publicable: Path, final: Path,
                  palabras: list[Palabra] | None, on_progress: Progreso | None,
                  paso: int, total: int) -> None:
    """Genera final.with_suffix('.md'). Nunca hace fallar el vídeo."""
    ruta_md = final.with_suffix(".md")
    servidor = None
    try:
        ruta_md.unlink(missing_ok=True)  # nunca dejar un caption obsoleto
        if palabras is None:
            _emitir(on_progress, paso, total, _("Transcribiendo"))
            palabras = _transcribir(config, video_publicable, on_progress)
            paso += 1
        _emitir(on_progress, paso, total, _("Generando caption SEO"))
        servidor = asegurar_servidor()
        caption = generar_caption(
            texto_plano(palabras), config.contexto_marca, config.modelo_caption,
            idioma=config.idioma_subs if config.idioma_subs in ("es", "en") else "es",
            terminos=terminos_caption(parsear_glosario(config.glosario)),
        )
        escribir_md(caption, ruta_md)
    except Exception as error:  # noqa: BLE001 — degradación deliberada
        ruta_md.unlink(missing_ok=True)
        diag = explicar(str(error), getattr(error, "detalle", ""))
        sugerencia = (
            _(" Qué hacer: {solucion}").format(solucion=diag.solucion)
            if diag.conocido else ""
        )
        _avisar(on_progress,
                _("Caption SEO falló: {error}. Vídeo guardado sin caption."
                  "{sugerencia}").format(error=error, sugerencia=sugerencia))
    finally:
        if servidor is not None:
            try:
                servidor.cerrar()
            except Exception as error:  # noqa: BLE001
                _avisar(on_progress,
                        _("No se pudo cerrar ollama serve: {error}").format(error=error))


def pasos_extra(config: PipelineConfig) -> int:
    """Pasos añadidos por subtítulos (2) y caption (1, o 2 si transcribe él)."""
    extra = 2 if config.subtitulos else 0
    if config.caption_seo:
        extra += 1 if config.subtitulos else 2
    return extra


def total_pasos(config: PipelineConfig) -> int:
    """Pasos que verá el usuario según los pasos pedidos."""
    total = 3 * config.paso_audio + config.paso_silencios
    if config.subtitulos:
        # Transcribir y, si hay horizontal, quemar (el vertical quema al convertir).
        total += 1 + config.hay_horizontal()
    if config.caption_seo:
        total += 1 if config.subtitulos else 2
    if config.paso_vertical:
        total += 1 + (config.encuadre == "cara")
    return total


def _fase_base(config: PipelineConfig, video: Path, tmp_final: Path,
               trabajo: Path, on_progress: Progreso | None, total: int) -> None:
    """Audio y/o silencios sobre `video`; deja el resultado en `tmp_final`."""
    nombre = video.stem
    entrada_silencios: Path | None = None
    if config.paso_audio:
        trabajo.mkdir(parents=True, exist_ok=True)
        wav_original = trabajo / f"{nombre}_original.wav"
        wav_limpio = trabajo / f"{nombre}_audio_limpio.wav"
        _emitir(on_progress, 1, total, _("Extrayendo audio"))
        extraer_audio(video, wav_original, SAMPLE_RATE_POR_MODELO[config.modelo])
        checkpoint = BASE_DIR / "checkpoints" / config.modelo
        etiqueta_limpieza = (
            _("Limpiando audio")
            if checkpoint.is_dir()
            else _("Descargando modelo y limpiando audio")
        )
        _emitir(on_progress, 2, total, etiqueta_limpieza)
        limpiar_audio(wav_original, wav_limpio, config.tarea, config.modelo)
        _emitir(on_progress, 3, total, _("Sustituyendo pista de audio"))
        if config.paso_silencios:
            # PCM intermedio: auto-editor no hereda el retardo de arranque del AAC.
            entrada_silencios = trabajo / f"{nombre}_solo_audio_limpio.mov"
            remux(video, wav_limpio, entrada_silencios, intermedio=True)
        else:
            remux(video, wav_limpio, tmp_final)
    if not config.paso_silencios:
        return
    paso = 4 if config.paso_audio else 1
    try:
        _emitir(on_progress, paso, total, _("Recortando silencios"))
        if entrada_silencios is None:
            # auto-editor colapsa los huecos del audio del iPhone y desincroniza:
            # se le pasa una copia con los huecos rellenos.
            entrada_silencios = trabajo / f"{nombre}_audio_relleno.mov"
            rellenar_huecos_audio(video, entrada_silencios)
        cortar_silencios(
            entrada_silencios, tmp_final, config.margen, config.umbral,
            config.silencios, config.velocidad_silencios,
            on_percent=lambda p: _emitir(
                on_progress, paso, total, _("Recortando silencios"), p
            ),
            on_aviso=lambda texto: _avisar(on_progress, texto),
        )
    finally:
        if entrada_silencios is not None:
            entrada_silencios.unlink(missing_ok=True)


def _fase_vertical(config: PipelineConfig, fuente: Path, destino: Path,
                   bloques: list[Bloque] | None, trabajo: Path,
                   on_progress: Progreso | None, paso: int, total: int,
                   degradar: bool, desde_original: bool) -> None:
    """Convierte `fuente` (sin subtítulos) a vertical y lo publica en `destino`.

    Con `degradar`, un fallo deja solo un aviso (el horizontal ya está
    publicado); sin él, el error se propaga.
    """
    tmp = destino.with_name(f".{destino.stem}_tmp{destino.suffix}")
    ass = trabajo / "subs_vertical.ass"
    comandos = trabajo / "cara.cmd"
    try:
        trabajo.mkdir(parents=True, exist_ok=True)
        ancho, alto = resolucion_video(fuente)
        encuadre = config.encuadre
        x_cara = None
        if es_ya_vertical(ancho, alto):
            _avisar(on_progress,
                    _("El vídeo ya era vertical: se reescala con barras."))
            encuadre = "barras"
        if config.encuadre == "cara":
            if encuadre == "cara":
                etiqueta = (
                    _("Detectando caras") if RUTA_PESOS.is_file()
                    else _("Descargando detector de caras")
                )
                _emitir(on_progress, paso, total, etiqueta)
                try:
                    x_cara = preparar_seguimiento(
                        fuente, ancho, alto, comandos,
                        on_percent=lambda p: _emitir(
                            on_progress, paso, total, _("Detectando caras"), p
                        ),
                    )
                    if x_cara is None:
                        _avisar(on_progress, _("No se detectó ninguna cara: "
                                               "se usa recorte central."))
                except Exception as error:  # noqa: BLE001 — degradación deliberada
                    _avisar(on_progress,
                            _("No se pudo preparar el detector de caras: "
                              "{error}. Se usa recorte central.").format(error=error))
                if x_cara is None:
                    encuadre = "central"
            paso += 1  # el total cuenta el paso aunque se salte
        if bloques:
            generar_ass(bloques, config.diseno, config.posicion_subs,
                        (ANCHO_VERTICAL, ALTO_VERTICAL), ass,
                        tamano=config.tamano_subs)
        tmp.unlink(missing_ok=True)
        _emitir(on_progress, paso, total, _("Convirtiendo a vertical"))
        convertir_vertical(
            fuente, tmp,
            filtro_vertical(encuadre, ancho, alto, x_cara=x_cara,
                            ass_nombre=ass.name if bloques else None),
            cwd=trabajo, usa_ass=bool(bloques), desde_original=desde_original,
            on_percent=lambda p: _emitir(
                on_progress, paso, total, _("Convirtiendo a vertical"), p
            ),
        )
        tmp.replace(destino)
    except Exception as error:  # noqa: BLE001 — degradación deliberada
        tmp.unlink(missing_ok=True)
        # Un vertical de una ejecución anterior no debe pasar por el de esta.
        destino.unlink(missing_ok=True)
        if not degradar:
            raise
        _avisar(on_progress,
                _("Versión vertical falló: {error}. Se conserva el vídeo "
                  "horizontal.").format(error=error))
    finally:
        ass.unlink(missing_ok=True)
        comandos.unlink(missing_ok=True)


def run(config: PipelineConfig, on_progress: Progreso | None = None) -> Path:
    config.validar()
    video = config.video.expanduser().resolve()
    if not video.is_file():
        raise FileNotFoundError(f"No existe el vídeo: {video}")

    final = config.ruta_salida_final().expanduser().resolve()
    if final == video:
        raise ValueError("La salida no puede ser el mismo archivo que la entrada.")
    vertical = config.ruta_salida_vertical()
    if vertical is not None and vertical.expanduser().resolve() == video:
        raise ValueError(
            "La salida vertical no puede ser el mismo archivo que la entrada."
        )
    final.parent.mkdir(parents=True, exist_ok=True)

    # tmp_final: horizontal sin subtítulos (fuente también del vertical).
    tmp_final = final.with_name(f".{final.stem}_tmp{final.suffix}")
    tmp_final.unlink(missing_ok=True)
    trabajo = BASE_DIR / "audio_procesado" / video.stem
    total = total_pasos(config)
    horizontal = config.hay_horizontal()
    hay_base = config.paso_audio or config.paso_silencios
    # Si los subtítulos son el único paso, su fallo es el fallo del trabajo.
    solo_subs = not (hay_base or config.paso_vertical)

    try:
        if hay_base:
            _fase_base(config, video, tmp_final, trabajo, on_progress, total)
        base = tmp_final if hay_base else video
        paso = 3 * config.paso_audio + config.paso_silencios + 1

        palabras = bloques = None
        if config.subtitulos:
            palabras, bloques = _transcribir_subs(
                config, base, final, on_progress, paso, total,
                degradar=not solo_subs,
                wav_continuo=None if hay_base else trabajo / f"{video.stem}_subs.wav",
            )
            paso += 1

        fuente_v = video
        if horizontal:
            publicar = base
            if config.subtitulos:
                if bloques:
                    quemado = _quemar_subs(
                        config, bloques, base, final, trabajo, on_progress,
                        paso, total, desde_original=not hay_base,
                        degradar=not solo_subs,
                    )
                    publicar = quemado or base
                paso += 1
            if config.caption_seo:
                _fase_caption(config, publicar, final, palabras, on_progress,
                              paso, total)
                paso += 1 if config.subtitulos else 2
            else:
                final.with_suffix(".md").unlink(missing_ok=True)
            if publicar == video:
                # Nada se aplicó: publicar sería mover el original del usuario.
                raise PasoFallido(
                    _("No se pudieron añadir los subtítulos: la transcripción "
                      "no dio texto que mostrar.")
                )
            publicar.replace(final)  # el horizontal se publica antes del vertical
            if hay_base:
                fuente_v = final if publicar == tmp_final else tmp_final

        if config.paso_vertical:
            destino = (
                config.ruta_salida_vertical().expanduser().resolve()
                if horizontal else final
            )
            _fase_vertical(config, fuente_v, destino, bloques, trabajo,
                           on_progress, paso, total, degradar=horizontal,
                           desde_original=fuente_v == video)
            if not horizontal:
                paso += 1 + (config.encuadre == "cara")
                if config.caption_seo:
                    _fase_caption(config, final, final, palabras, on_progress,
                                  paso, total)
                else:
                    final.with_suffix(".md").unlink(missing_ok=True)
        return final
    finally:
        tmp_final.unlink(missing_ok=True)
