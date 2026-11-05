from __future__ import annotations

from .subtitles import _tiempo_ass, partir_en_dos

DURACION = 5.0
FUENTE = "Titan One"
TAMANO_HORIZONTAL = 0.07
TAMANO_VERTICAL = 0.055  # fracción de la altura; vertical si alto > ancho
ANCHO_UTIL = 0.90
MARGEN_SUPERIOR = 0.08
# Avance medio de una mayúscula de Titan One por punto de `Fontsize` de libass.
ANCHO_CARACTER = 0.62
# BORDE, BORDE_DORADO y DESPLAZAMIENTO: fracciones del tamaño de letra.
BORDE = 0.08
BORDE_DORADO = 0.16
DESPLAZAMIENTO = 0.06
DORADO = "&H0000C8FF"  # #FFC800 en &HAABBGGRR
FUNDIDO_MS = 300


def _ancho_en_fs(n: int) -> float:
    return n * ANCHO_CARACTER + 2 * BORDE_DORADO + DESPLAZAMIENTO


def lineas_titulo(texto: str, resolucion: tuple[int, int], inicio: float = 0.0,
                  duracion: float = DURACION) -> tuple[list[str], list[str]]:
    """(líneas `Style:`, líneas `Dialogue:`) del título, para `generar_ass(extra=…)`
    o para añadir a cualquier `.ass`. `([], [])` si el texto queda vacío."""
    ancho, alto = resolucion
    for c in "{}\\":
        texto = texto.replace(c, "")
    texto = " ".join(texto.split()).upper()
    if not texto:
        return [], []

    fs = round(alto * (TAMANO_VERTICAL if alto > ancho else TAMANO_HORIZONTAL))
    if _ancho_en_fs(len(texto)) * fs > ANCHO_UTIL * ancho:
        texto = partir_en_dos(texto)
    n = max(len(linea) for linea in texto.split("\\N"))
    fs = max(8, min(fs, int(ANCHO_UTIL * ancho / _ancho_en_fs(n))))
    borde = max(1, round(fs * BORDE))
    dorado = round(fs * BORDE_DORADO)
    d = max(1, round(fs * DESPLAZAMIENTO))
    x, y = ancho // 2, round(alto * MARGEN_SUPERIOR)

    estilos = [
        f"Style: TituloDorado,{FUENTE},{fs},{DORADO},&H00FFFFFF,{DORADO},"
        f"&H00000000,0,0,0,0,100,100,0,0,1,{dorado},0,8,0,0,0,1",
        f"Style: Titulo,{FUENTE},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,"
        f"&H00000000,0,0,0,0,100,100,0,0,1,{borde},0,8,0,0,0,1",
    ]
    tiempos = f"{_tiempo_ass(inicio)},{_tiempo_ass(inicio + duracion)}"
    fundido = f"\\fad({FUNDIDO_MS},{FUNDIDO_MS})"
    eventos = [
        f"Dialogue: 0,{tiempos},TituloDorado,,0,0,0,,"
        f"{{\\an8\\pos({x + d},{y + d}){fundido}}}{texto}",
        f"Dialogue: 1,{tiempos},Titulo,,0,0,0,,"
        f"{{\\an8\\pos({x},{y}){fundido}}}{texto}",
    ]
    return estilos, eventos
