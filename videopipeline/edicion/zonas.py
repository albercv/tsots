"""Zonas de la pantalla vertical (1080x1920) que el plan de edición debe respetar."""
from videopipeline.config import PipelineConfig
from videopipeline.subtitles import PRESETS
from videopipeline.titulo import DURACION, MARGEN_SUPERIOR, TAMANO_VERTICAL
from videopipeline.vertical import ALTO_VERTICAL, ANCHO_VERTICAL, ancho_ventana_cara

MIN_FRANJA = 200


def calcular(config: PipelineConfig, encuadre: str, resolucion_fuente: tuple[int, int],
             con_titulo: bool) -> dict:
    ancho, alto = resolucion_fuente
    if encuadre == "central":
        contenido = [0, 0, ANCHO_VERTICAL, ALTO_VERTICAL]
    else:
        if encuadre == "cara":
            ancho = ancho_ventana_cara(ancho, alto)
        h = round(ANCHO_VERTICAL * alto / ancho) // 2 * 2
        contenido = [0, (ALTO_VERTICAL - h) // 2, ANCHO_VERTICAL, h]

    fuente = int(ALTO_VERTICAL * PRESETS[config.diseno].tamano_rel * config.tamano_subs / 100)
    subtitulos = None
    if config.subtitulos:
        y1 = ALTO_VERTICAL - int(ALTO_VERTICAL * (100 - config.posicion_subs) / 100)
        # shortcut: asume subtítulos de 1 línea; si un preset parte en 2, la franja de zoom puede pisar la de arriba — ampliar a 2 líneas si pasa
        subtitulos = [y1 - round(0.85 * fuente), y1]

    franja = None
    if contenido[1] > 0:  # a marco completo no hay franja de vídeo reencuadrable
        fin = contenido[1] + contenido[3]
        if subtitulos:
            fin = min(fin, subtitulos[0])
        if fin - contenido[1] >= MIN_FRANJA:
            franja = [contenido[1], fin]

    titulo = None
    if con_titulo:
        y0 = round(MARGEN_SUPERIOR * ALTO_VERTICAL)
        titulo = {"y": [y0, round(y0 + 2.4 * TAMANO_VERTICAL * ALTO_VERTICAL)], "hasta": DURACION}

    if contenido[1] > 0:
        graficos_hasta = contenido[1]
    else:
        graficos_hasta = (subtitulos[0] if subtitulos else round(ALTO_VERTICAL * 0.6)) - (fuente if subtitulos else 0)
    return {"contenido": contenido, "subtitulos": subtitulos, "titulo": titulo,
            "franja_zoom": franja, "graficos_hasta": graficos_hasta}
