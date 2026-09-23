from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

PAUSA_CORTE = 0.6
MAX_PALABRAS_REELS = 3
MAX_CHARS_FRASE = 84
MAX_CHARS_LINEA = 42
DURACION_MINIMA = 0.5
ANCHO_CARACTER = 0.55
MARGEN_LATERAL = 40

_PUNTUACION_FINAL = (".", "!", "?", "…")


@dataclass
class Palabra:
    texto: str
    inicio: float
    fin: float


@dataclass
class Bloque:
    palabras: list[Palabra]
    inicio: float
    fin: float

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palabras)


@dataclass
class EstiloPreset:
    fuente: str
    tamano_rel: float
    primario: str
    contorno_color: str
    fondo: str
    negrita: int
    borde_estilo: int
    grosor_contorno: int
    sombra: int
    mayusculas: bool
    tipo: str  # "palabras" | "frases"
    resaltado: str | None


PRESETS: dict[str, EstiloPreset] = {
    "reels_bold": EstiloPreset(
        fuente="Arial Black", tamano_rel=0.075,
        primario="&H00FFFFFF", contorno_color="&H00000000", fondo="&H00000000",
        negrita=-1, borde_estilo=1, grosor_contorno=3, sombra=2,
        mayusculas=True, tipo="palabras", resaltado=None,
    ),
    "reels_karaoke": EstiloPreset(
        fuente="Arial Black", tamano_rel=0.07,
        primario="&H00FFFFFF", contorno_color="&H00000000", fondo="&H00000000",
        negrita=-1, borde_estilo=1, grosor_contorno=3, sombra=2,
        mayusculas=True, tipo="palabras", resaltado="&H000AD6FF",
    ),
    "caja": EstiloPreset(
        fuente="Helvetica", tamano_rel=0.045,
        primario="&H00FFFFFF", contorno_color="&H00000000", fondo="&H59000000",
        negrita=0, borde_estilo=3, grosor_contorno=1, sombra=0,
        mayusculas=False, tipo="frases", resaltado=None,
    ),
    # Colores en formato ASS: &HAABBGGRR (alfa, azul, verde, rojo).
    "impacto": EstiloPreset(
        fuente="Impact", tamano_rel=0.08,
        primario="&H00FFFFFF", contorno_color="&H00000000", fondo="&H00000000",
        negrita=0, borde_estilo=1, grosor_contorno=5, sombra=0,
        mayusculas=True, tipo="palabras", resaltado=None,
    ),
    "amarillo": EstiloPreset(
        fuente="Arial Black", tamano_rel=0.072,
        primario="&H0000D4FF", contorno_color="&H00000000", fondo="&H80000000",
        negrita=-1, borde_estilo=1, grosor_contorno=4, sombra=3,
        mayusculas=True, tipo="palabras", resaltado=None,
    ),
    "karaoke_verde": EstiloPreset(
        fuente="Arial Black", tamano_rel=0.07,
        primario="&H00FFFFFF", contorno_color="&H00000000", fondo="&H00000000",
        negrita=-1, borde_estilo=1, grosor_contorno=3, sombra=2,
        mayusculas=True, tipo="palabras", resaltado="&H006BE62E",
    ),
    "minimal": EstiloPreset(
        fuente="Avenir Next", tamano_rel=0.042,
        primario="&H00FFFFFF", contorno_color="&H00000000", fondo="&H80000000",
        negrita=0, borde_estilo=1, grosor_contorno=1, sombra=1,
        mayusculas=False, tipo="frases", resaltado=None,
    ),
    "caja_blanca": EstiloPreset(
        fuente="Helvetica", tamano_rel=0.045,
        primario="&H00000000", contorno_color="&H00FFFFFF", fondo="&H00FFFFFF",
        negrita=-1, borde_estilo=3, grosor_contorno=1, sombra=0,
        mayusculas=False, tipo="frases", resaltado=None,
    ),
}


def _cerrar_bloque(palabras: list[Palabra]) -> Bloque:
    inicio = palabras[0].inicio
    fin = max(palabras[-1].fin, inicio + DURACION_MINIMA)
    return Bloque(palabras=list(palabras), inicio=inicio, fin=fin)


def agrupar(palabras: list[Palabra], preset_id: str) -> list[Bloque]:
    preset = PRESETS[preset_id]
    bloques: list[Bloque] = []
    actual: list[Palabra] = []
    for palabra in palabras:
        if actual:
            pausa = palabra.inicio - actual[-1].fin
            texto_actual = " ".join(p.texto for p in actual)
            if preset.tipo == "palabras":
                corta = len(actual) >= MAX_PALABRAS_REELS or pausa > PAUSA_CORTE
            else:
                corta = (
                    pausa > PAUSA_CORTE
                    or actual[-1].texto.endswith(_PUNTUACION_FINAL)
                    or len(texto_actual) + 1 + len(palabra.texto) > MAX_CHARS_FRASE
                )
            if corta:
                bloques.append(_cerrar_bloque(actual))
                actual = []
        actual.append(palabra)
    if actual:
        bloques.append(_cerrar_bloque(actual))

    for anterior, siguiente in zip(bloques, bloques[1:]):
        natural = anterior.palabras[-1].fin
        anterior.fin = max(natural, min(anterior.fin, siguiente.inicio))

    return bloques


def _tiempo_srt(segundos: float) -> str:
    ms = round(segundos * 1000)
    h, resto = divmod(ms, 3_600_000)
    m, resto = divmod(resto, 60_000)
    s, ms = divmod(resto, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generar_srt(bloques: list[Bloque], ruta: Path) -> None:
    lineas: list[str] = []
    for indice, bloque in enumerate(bloques, start=1):
        lineas.append(str(indice))
        lineas.append(f"{_tiempo_srt(bloque.inicio)} --> {_tiempo_srt(bloque.fin)}")
        lineas.append(bloque.texto)
        lineas.append("")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(lineas), encoding="utf-8")


def _tiempo_ass(segundos: float) -> str:
    cs = round(segundos * 100)
    h, resto = divmod(cs, 360_000)
    m, resto = divmod(resto, 6_000)
    s, cs = divmod(resto, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _envolver(texto: str) -> str:
    if len(texto) <= MAX_CHARS_LINEA:
        return texto
    posiciones_espacio = [i for i, c in enumerate(texto) if c == " "]
    if not posiciones_espacio:
        return texto
    mejor_corte = min(
        posiciones_espacio,
        key=lambda i: max(len(texto[:i]), len(texto[i + 1:])),
    )
    return texto[:mejor_corte] + "\\N" + texto[mejor_corte + 1:]


def _fs_ajustado(texto_plano: str, tamano_fuente: int, ancho: int) -> int | None:
    """Fuente reducida para que la línea más larga quepa; None si ya cabe."""
    util = ancho - 2 * MARGEN_LATERAL
    lineas = texto_plano.split("\\N")
    max_chars = max((len(l) for l in lineas), default=0)
    if max_chars == 0:
        return None
    if max_chars * ANCHO_CARACTER * tamano_fuente <= util:
        return None
    return max(8, int(util / (max_chars * ANCHO_CARACTER)))


def _texto_bloque(bloque: Bloque, preset: EstiloPreset,
                  palabra_activa: int | None = None) -> str:
    piezas: list[str] = []
    for indice, palabra in enumerate(bloque.palabras):
        texto = palabra.texto.upper() if preset.mayusculas else palabra.texto
        if palabra_activa is not None and indice == palabra_activa:
            texto = (
                f"{{\\c{preset.resaltado}&}}{texto}"
                f"{{\\c{preset.primario}&}}"
            ).replace("&&", "&")
        piezas.append(texto)
    unido = " ".join(piezas)
    if preset.tipo == "frases":
        unido = _envolver(unido)
    return unido


def generar_ass(bloques: list[Bloque], preset_id: str, posicion: int,
                resolucion: tuple[int, int], ruta: Path, tamano: int = 100) -> None:
    preset = PRESETS[preset_id]
    ancho, alto = resolucion
    margen_v = int(alto * (100 - posicion) / 100)
    tamano_fuente = int(alto * preset.tamano_rel * tamano / 100)

    cabecera = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {ancho}",
        f"PlayResY: {alto}",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Sub,{preset.fuente},{tamano_fuente},{preset.primario},&H00FFFFFF,"
        f"{preset.contorno_color},{preset.fondo},{preset.negrita},0,0,0,"
        f"100,100,0,0,{preset.borde_estilo},{preset.grosor_contorno},"
        f"{preset.sombra},2,{MARGEN_LATERAL},{MARGEN_LATERAL},{margen_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text",
    ]

    eventos: list[str] = []
    for bloque in bloques:
        texto_plano = bloque.texto.upper() if preset.mayusculas else bloque.texto
        if preset.tipo == "frases":
            texto_plano = _envolver(texto_plano)
        ajuste = _fs_ajustado(texto_plano, tamano_fuente, ancho)
        prefijo = f"{{\\fs{ajuste}}}" if ajuste is not None else ""
        if preset.resaltado is not None:
            for indice, palabra in enumerate(bloque.palabras):
                fin = (
                    bloque.palabras[indice + 1].inicio
                    if indice + 1 < len(bloque.palabras)
                    else bloque.fin
                )
                eventos.append(
                    f"Dialogue: 0,{_tiempo_ass(palabra.inicio)},"
                    f"{_tiempo_ass(fin)},Sub,,0,0,0,,"
                    f"{prefijo}{_texto_bloque(bloque, preset, palabra_activa=indice)}"
                )
        else:
            eventos.append(
                f"Dialogue: 0,{_tiempo_ass(bloque.inicio)},"
                f"{_tiempo_ass(bloque.fin)},Sub,,0,0,0,,"
                f"{prefijo}{_texto_bloque(bloque, preset)}"
            )

    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(cabecera + eventos) + "\n", encoding="utf-8")


# --- Transcripción ------------------------------------------------------------
#
# Dos motores con los mismos nombres de modelo ("small", "medium", "turbo"):
# - mlx-whisper: usa la GPU de Apple Silicon (unas 10 veces más rápido). Necesita
#   macOS 14 o posterior.
# - faster-whisper: respaldo en CPU para macOS 13, donde mlx no se instala.

CACHE_HF = Path.home() / ".cache" / "huggingface" / "hub"

MODELOS_MLX = {
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}
MODELOS_FASTER = {"small": "small", "medium": "medium", "turbo": "large-v3-turbo"}
TAMANO_DESCARGA = {"small": "~500 MB", "medium": "~1,5 GB", "turbo": "~1,6 GB"}

# Segundos de silencio a partir de los cuales mlx-whisper descarta texto
# inventado (sustituye al filtro VAD de faster-whisper).
SILENCIO_ALUCINACION = 2.0


def usa_mlx() -> bool:
    return importlib.util.find_spec("mlx_whisper") is not None


def modelo_en_cache(modelo: str, cache_dir: Path = CACHE_HF) -> bool:
    """True si el modelo ya está descargado para el motor que se va a usar."""
    if not cache_dir.is_dir():
        return False
    if usa_mlx():
        carpeta = "models--" + MODELOS_MLX[modelo].replace("/", "--")
        return (cache_dir / carpeta).is_dir()
    return any(cache_dir.glob(f"models--*faster-whisper-{MODELOS_FASTER[modelo]}"))


def _cargar_audio(video: Path):
    # PyAV (vía faster-whisper): no depende del ffmpeg del PATH, que dentro de
    # la app no siempre es el de Homebrew.
    from faster_whisper.audio import decode_audio

    return decode_audio(str(video), sampling_rate=16000)


def _mlx_transcribe(audio, **kwargs) -> dict:
    # Import perezoso: mlx solo se carga en el subproceso del runner.
    import mlx_whisper

    return mlx_whisper.transcribe(audio, **kwargs)


def _crear_whisper(modelo: str):
    # Import perezoso: faster-whisper solo se carga en el subproceso del runner.
    from faster_whisper import WhisperModel

    return WhisperModel(modelo, device="auto", compute_type="auto")


def transcribir(video: Path, idioma: str, modelo: str) -> list[Palabra]:
    lengua = None if idioma == "auto" else idioma
    if usa_mlx():
        return _transcribir_mlx(video, lengua, modelo)
    return _transcribir_faster(video, lengua, modelo)


def _transcribir_mlx(video: Path, lengua: str | None, modelo: str) -> list[Palabra]:
    resultado = _mlx_transcribe(
        _cargar_audio(video),
        path_or_hf_repo=MODELOS_MLX[modelo],
        language=lengua,
        word_timestamps=True,
        hallucination_silence_threshold=SILENCIO_ALUCINACION,
        verbose=None,
    )
    palabras: list[Palabra] = []
    for segmento in resultado.get("segments", []):
        for palabra in segmento.get("words") or []:
            texto = palabra["word"].strip()
            if texto:
                palabras.append(
                    Palabra(texto=texto, inicio=palabra["start"], fin=palabra["end"])
                )
    return palabras


def _transcribir_faster(video: Path, lengua: str | None,
                        modelo: str) -> list[Palabra]:
    whisper = _crear_whisper(MODELOS_FASTER[modelo])
    segmentos, _info = whisper.transcribe(
        str(video),
        language=lengua,
        word_timestamps=True,
        vad_filter=True,
    )
    palabras: list[Palabra] = []
    for segmento in segmentos:
        for palabra in segmento.words or []:
            texto = palabra.word.strip()
            if texto:
                palabras.append(
                    Palabra(texto=texto, inicio=palabra.start, fin=palabra.end)
                )
    return palabras
