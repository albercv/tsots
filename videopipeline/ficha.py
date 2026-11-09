"""La ficha de un vídeo: qué se ha hecho ya y con qué ajustes.

Una carpeta por vídeo en `fichas/<id>/` con `ficha.json` y lo que cuesta rehacer
(audio limpio, base, transcripción, caption, seguimiento). La ficha no guarda
vídeos finales: los registra con una huella (ruta real, tamaño y fecha) para
saber si siguen siendo los que escribió la app. Sin Qt: el pipeline la usa solo.
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from .caption import leer_md
from .i18n import _
from .steps import BASE_DIR, PasoFallido, duracion_video
from .subtitles import leer_srt

log = logging.getLogger(__name__)

DIR_FICHAS = BASE_DIR / "fichas"
SUFIJOS_SALIDA = ("_limpio", "_vertical")

# Claves de los artefactos de una ficha.
AUDIO, BASE, TRANSCRIPCION, HORIZONTAL, CAPTION, SEGUIMIENTO, VERTICAL = (
    "audio", "base", "transcripcion", "horizontal", "caption", "seguimiento",
    "vertical")
TITULO = "titulo"  # texto del título de inicio; sin archivo, vale si está
DIFUSION = "difusion"  # blog y LinkedIn preparados; sin archivo, una vez por vídeo

# Los pasos del panel, en el orden en que se muestran.
PASOS = ("audio", "silencios", "subtitulos", "caption", "vertical")


@dataclass(frozen=True)
class Huella:
    """Identifica un archivo: si cambia el tamaño o la fecha, ya no es el mismo."""
    ruta: Path
    tamano: int
    mtime_ns: int

    @classmethod
    def de(cls, ruta: Path) -> "Huella":
        ruta = ruta.resolve()
        estado = ruta.stat()
        return cls(ruta, estado.st_size, estado.st_mtime_ns)

    def coincide(self, ruta: Path) -> bool:
        try:
            ruta = ruta.resolve()
            estado = ruta.stat()
        except OSError:
            return False
        return (ruta == self.ruta and estado.st_size == self.tamano
                and estado.st_mtime_ns == self.mtime_ns)


@dataclass
class Artefacto:
    clave: str  # de qué depende; si coincide con la actual, el artefacto vale
    archivo: str | None = None  # nombre dentro de la carpeta de la ficha; None = vive fuera
    ajustes: dict = field(default_factory=dict)  # con qué se hizo (R6, R8)
    linea_tiempo: str = ""  # para AUDIO, BASE y TRANSCRIPCION


def _es_vertical(huella: Huella | None) -> bool:
    return huella is not None and huella.ruta.stem.endswith("_vertical")


@dataclass
class Ficha:
    id: str
    nombre: str
    carpeta_salida: Path
    original: Huella | None = None
    final: Huella | None = None  # horizontal o, sin horizontal, el vertical único
    vertical: Huella | None = None  # vertical que acompaña al horizontal
    legado: bool = False  # salida de antes de las fichas, sin original conocido
    subs_quemados_sin_base: bool = False
    desactualizado: set[str] = field(default_factory=set)  # {"vertical"}
    artefactos: dict[str, Artefacto] = field(default_factory=dict)
    perfil: str = ""  # perfil de publicación con el que se procesó

    @property
    def carpeta(self) -> Path:
        return DIR_FICHAS / self.id

    def ruta(self, archivo: str) -> Path:
        return self.carpeta / archivo

    def pasos_hechos(self) -> list[str]:
        base = self.artefactos.get(BASE)
        horizontal = self.artefactos.get(HORIZONTAL)
        vertical = self.artefactos.get(VERTICAL)
        hechos = {
            "audio": base is not None and "audio" in base.ajustes,
            "silencios": base is not None and "silencios" in base.ajustes,
            "subtitulos": (
                (horizontal is not None and "subtitulos" in horizontal.ajustes)
                or (vertical is not None and "subtitulos" in vertical.ajustes
                    and not self.hay_horizontal())
            ),
            "caption": CAPTION in self.artefactos,
            "vertical": vertical is not None,
        }
        return [paso for paso in PASOS if hechos[paso]]

    def original_verdadero(self) -> bool:
        """El original es el que arrastró el usuario. Sin él, hace de original
        el final antiguo (de antes de las fichas) o la copia que la app guardó
        de él en la ficha antes de sobrescribirlo."""
        return (self.original is not None and not self.legado
                and self.original.ruta.parent != self.carpeta.resolve())

    def linea_original(self) -> str:
        """La línea de tiempo del vídeo del que sale la base sin recorte: la del
        original, o la de la salida antigua que hace de original."""
        return "original" if self.original_verdadero() else "legado"

    def hay_horizontal(self) -> bool:
        # Sin artefacto (salida antigua, adoptada o no) lo dice el nombre del
        # final: las salidas son siempre `_limpio.mp4` o `_vertical.mp4`.
        if HORIZONTAL in self.artefactos:
            return True
        return self.final is not None and not _es_vertical(self.final)

    def ruta_final(self, horizontal: bool) -> Path:
        """Donde está, o estará, el final de ese tipo. Una salida antigua
        conserva su propia ruta aunque no siga el esquema de nombres."""
        if self.final is not None and _es_vertical(self.final) != horizontal:
            return self.final.ruta
        sufijo = "_limpio" if horizontal else "_vertical"
        return self.carpeta_salida / f"{self.nombre}{sufijo}.mp4"

    def ruta_vertical(self) -> Path:
        return self.carpeta_salida / f"{self.nombre}_limpio_vertical.mp4"

    def _salidas(self) -> set[Path]:
        """Todos los archivos de vídeo que esta ficha escribe o puede escribir."""
        rutas = {self.ruta_final(True), self.ruta_final(False), self.ruta_vertical()}
        rutas |= {h.ruta for h in (self.final, self.vertical) if h is not None}
        return {ruta.resolve() for ruta in rutas}


# --- Almacenamiento ---------------------------------------------------------

def _escribir_json(destino: Path, datos) -> None:
    """Atómico: temporal oculto y `replace`, para que nunca quede a medias."""
    texto = json.dumps(datos, ensure_ascii=False, indent=2)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(f".{destino.stem}_tmp{destino.suffix}")
    tmp.write_text(texto, encoding="utf-8")
    tmp.replace(destino)


def _huella_a_dict(huella: Huella | None) -> dict | None:
    if huella is None:
        return None
    return {"ruta": str(huella.ruta), "tamano": huella.tamano,
            "mtime_ns": huella.mtime_ns}


def _tipo(valor, *tipos):
    """Un `ficha.json` puede ser JSON válido y no ser una ficha: se comprueba
    cada tipo para que `cargar` falle con TypeError y no más tarde, usándola."""
    if not isinstance(valor, tipos):
        raise TypeError(f"{valor!r} no es {' o '.join(t.__name__ for t in tipos)}")
    return valor


def _huella_de_dict(datos: dict | None) -> Huella | None:
    if datos is None:
        return None
    _tipo(datos, dict)
    return Huella(Path(_tipo(datos["ruta"], str)), _tipo(datos["tamano"], int),
                  _tipo(datos["mtime_ns"], int))


def _artefacto_de_dict(datos: dict) -> Artefacto:
    _tipo(datos, dict)
    return Artefacto(
        clave=_tipo(datos["clave"], str),
        archivo=_tipo(datos["archivo"], str, type(None)),
        ajustes=_tipo(datos["ajustes"], dict),
        linea_tiempo=_tipo(datos["linea_tiempo"], str),
    )


def _a_dict(ficha: Ficha) -> dict:
    return {
        "id": ficha.id,
        "nombre": ficha.nombre,
        "carpeta_salida": str(ficha.carpeta_salida),
        "original": _huella_a_dict(ficha.original),
        "final": _huella_a_dict(ficha.final),
        "vertical": _huella_a_dict(ficha.vertical),
        "legado": ficha.legado,
        "subs_quemados_sin_base": ficha.subs_quemados_sin_base,
        "desactualizado": sorted(ficha.desactualizado),
        "artefactos": {k: asdict(a) for k, a in ficha.artefactos.items()},
        "perfil": ficha.perfil,
    }


def _de_dict(datos: dict) -> Ficha:
    _tipo(datos, dict)
    return Ficha(
        id=_tipo(datos["id"], str),
        nombre=_tipo(datos["nombre"], str),
        carpeta_salida=Path(_tipo(datos["carpeta_salida"], str)),
        original=_huella_de_dict(datos["original"]),
        final=_huella_de_dict(datos["final"]),
        vertical=_huella_de_dict(datos["vertical"]),
        legado=_tipo(datos["legado"], bool),
        subs_quemados_sin_base=_tipo(datos["subs_quemados_sin_base"], bool),
        desactualizado={_tipo(d, str) for d in _tipo(datos["desactualizado"], list)},
        artefactos={_tipo(k, str): _artefacto_de_dict(a)
                    for k, a in _tipo(datos["artefactos"], dict).items()},
        perfil=_tipo(datos.get("perfil", ""), str),
    )


def guardar(ficha: Ficha) -> None:
    _escribir_json(ficha.carpeta / "ficha.json", _a_dict(ficha))


def cargar(id: str) -> Ficha | None:
    """`None` si no existe o está dañada (no se puede leer, o no es una ficha)."""
    ruta = DIR_FICHAS / id / "ficha.json"
    try:
        ficha = _de_dict(json.loads(ruta.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as error:
        log.warning("Ficha ignorada, %s está dañado: %s", ruta, error)
        return None
    if ficha.id != id:
        log.warning("Ficha ignorada, %s es de la ficha «%s»", ruta, ficha.id)
        return None
    return ficha


def todas() -> list[Ficha]:
    if not DIR_FICHAS.is_dir():
        return []
    fichas = (cargar(carpeta.name) for carpeta in sorted(DIR_FICHAS.iterdir()))
    return [ficha for ficha in fichas if ficha is not None]


def olvidar(ficha: Ficha) -> None:
    """Borra los datos de la ficha. No toca las salidas ni el original."""
    shutil.rmtree(ficha.carpeta, ignore_errors=True)


def ocupa(ficha: Ficha) -> int:
    total = 0
    for archivo in ficha.carpeta.rglob("*"):
        try:
            if archivo.is_file():
                total += archivo.stat().st_size
        except OSError:  # se borró mientras se contaba
            pass
    return total


def limpiar_temporales(ficha: Ficha) -> None:
    """Borra `tmp/` y los temporales ocultos que dejan sus salidas."""
    shutil.rmtree(ficha.carpeta / "tmp", ignore_errors=True)
    for salida in ficha._salidas():
        for sufijo in ("_tmp", "_subs_tmp"):
            try:
                salida.with_name(f".{salida.stem}{sufijo}{salida.suffix}").unlink(
                    missing_ok=True)
            except OSError:
                pass


# --- Reconocimiento ---------------------------------------------------------

def _nueva_id() -> str:
    return uuid4().hex[:12]


def _es_salida_antigua(ruta: Path) -> bool:
    """La app solo escribió .mp4: un `foo_limpio.mov` es un original de verdad
    y nunca puede ser el final (que se sobrescribe) de una ficha."""
    return (ruta.suffix.lower() == ".mp4"
            and any(ruta.stem.endswith(sufijo) for sufijo in SUFIJOS_SALIDA))


def _ficha_de_legado(salida: Path) -> Ficha:
    """Una salida de antes de las fichas es su propio final y se sobrescribe a
    sí misma. Si al lado tiene el .md y el .srt, se importan."""
    nombre = salida.stem
    for sufijo in SUFIJOS_SALIDA:
        if nombre.endswith(sufijo):
            nombre = nombre[:-len(sufijo)]
            break
    ficha = Ficha(id=_nueva_id(), nombre=nombre, carpeta_salida=salida.parent,
                  final=Huella.de(salida), legado=True)

    md = salida.with_suffix(".md")
    if leer_md(md) is not None:
        ficha.carpeta.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(md, ficha.ruta("caption.md"))
        ficha.artefactos[CAPTION] = Artefacto("importado", "caption.md")

    srt = salida.with_suffix(".srt")
    if srt.is_file():
        # Probablemente los subtítulos están quemados y no hay base sin ellos.
        ficha.subs_quemados_sin_base = True
        palabras = leer_srt(srt)
        if palabras:
            _escribir_json(ficha.ruta("transcripcion.json"),
                           [asdict(palabra) for palabra in palabras])
            ficha.artefactos[TRANSCRIPCION] = Artefacto(
                "importado", "transcripcion.json", linea_tiempo="legado")
    guardar(ficha)
    return ficha


def _de_nadie(ruta: Path, fichas: list[Ficha]) -> bool:
    return all(ruta.resolve() not in ficha._salidas() for ficha in fichas)


def _soltar(ficha: Ficha, ruta: Path) -> None:
    """`ruta` cambió fuera de la app y deja de ser de `ficha`, que conserva todo
    lo demás: nunca se borra una ficha sin preguntar. Solo se quita lo que
    describía ese archivo."""
    if ficha.original is not None and ficha.original.ruta == ruta:
        ficha.original = None
    if ficha.vertical is not None and ficha.vertical.ruta == ruta:
        ficha.vertical = None
        ficha.artefactos.pop(VERTICAL, None)
        ficha.desactualizado.discard("vertical")
    if ficha.final is not None and ficha.final.ruta == ruta:
        ficha.artefactos.pop(HORIZONTAL if ficha.hay_horizontal() else VERTICAL, None)
        base = ficha.artefactos.get(BASE)
        if base is not None and base.archivo is None:  # la base era ese final (R3)
            del ficha.artefactos[BASE]
        # Su vertical, si lo hay, queda como la única salida.
        ficha.final, ficha.vertical = ficha.vertical, None
    guardar(ficha)


# Lo que se hizo desde el final antiguo tiene su línea de tiempo, no la del
# original verdadero: al adoptarlo se descarta.
_DEL_FINAL_ANTIGUO = (AUDIO, BASE, SEGUIMIENTO, HORIZONTAL, VERTICAL)


def _adoptar(ficha: Ficha, original: Huella, fichas: list[Ficha],
             nombre: str | None = None) -> Ficha:
    """El original verdadero pasa a ser de `ficha`, que no lo tenía (salida
    antigua, o ficha cuyo original se editó fuera). Se quedan el caption y la
    transcripción importada (R5); el vertical, desactualizado. Su vertical
    antiguo también se adopta si no es de otra: no se sabe cómo se hizo."""
    salida = ficha.artefactos.get(HORIZONTAL if ficha.hay_horizontal() else VERTICAL)
    if salida is not None and "subtitulos" in salida.ajustes:
        ficha.subs_quemados_sin_base = True  # el final los lleva; la base, no
    for tipo in _DEL_FINAL_ANTIGUO:
        ficha.artefactos.pop(tipo, None)
    transcripcion = ficha.artefactos.get(TRANSCRIPCION)
    if transcripcion is not None and transcripcion.linea_tiempo != "legado":
        del ficha.artefactos[TRANSCRIPCION]
    ficha.original, ficha.legado = original, False
    if nombre is not None:  # un `x_limpio_vertical.mp4` se llamaba «x_limpio»
        ficha.nombre = nombre
    vertical = ficha.ruta_vertical()
    if (ficha.vertical is None and ficha.hay_horizontal() and vertical.is_file()
            and _de_nadie(vertical, [f for f in fichas if f.id != ficha.id])):
        ficha.vertical = Huella.de(vertical)
    if ficha.vertical is not None or (ficha.final is not None
                                      and not ficha.hay_horizontal()):
        ficha.desactualizado.add("vertical")
    guardar(ficha)
    return ficha


def _mas_larga(salida: Path, original: Path) -> bool:
    """Una salida nunca dura más que su original (+1 s de margen): si dura
    más, es de otro vídeo con el mismo nombre. Sin poder medirlo, no lo es."""
    try:
        duracion, la_del_original = duracion_video(salida), duracion_video(original)
    except (OSError, PasoFallido):  # sin ffprobe
        return False
    return 0 < la_del_original < duracion - 1


def _nombre_libre(ficha: Ficha, fichas: list[Ficha]) -> None:
    """Para una ficha aún sin salidas: si otra ya usa las suyas, o en su sitio
    hay un archivo de otro vídeo con el mismo nombre, se le añade «(n)»."""
    otras = [f for f in fichas if f.id != ficha.id]
    nombre, n = ficha.nombre, 1
    while (any(f._salidas() & ficha._salidas() for f in otras)
           or any(ruta.is_file() for ruta in ficha._salidas())):
        n += 1
        ficha.nombre = f"{nombre} ({n})"


def mover_salidas(ficha: Ficha, carpeta: Path | None) -> None:
    """Una ficha aún sin salidas pasa a escribirlas en `carpeta` (None: junto
    al original), sin pisar las de otra."""
    if ficha.original is None:
        return  # sin original ni salidas no puede escribir nada
    ficha.carpeta_salida = carpeta or ficha.original.ruta.parent
    ficha.nombre = ficha.original.ruta.stem
    _nombre_libre(ficha, todas())
    guardar(ficha)


def _ficha_de_original(original: Path, carpeta_salida: Path,
                       fichas: list[Ficha]) -> tuple[Ficha, str]:
    nueva = Ficha(id=_nueva_id(), nombre=original.stem,
                  carpeta_salida=carpeta_salida, original=Huella.de(original))

    # Su salida (horizontal, vertical único o, sin ellos, el vertical que
    # acompañaría al horizontal) ya existe. Nunca hay dos fichas con la misma.
    for salida in (nueva.ruta_final(True), nueva.ruta_final(False),
                   nueva.ruta_vertical()):
        salida = salida.resolve()
        # Es el final de una ficha sin original verdadero: el original pasa a
        # ser de esa ficha.
        for ficha in fichas:
            if (not ficha.original_verdadero() and ficha.final is not None
                    and ficha.final.ruta == salida):
                return _adoptar(ficha, nueva.original, fichas, nueva.nombre), ""
        # No es de ninguna ficha (de antes de las fichas, o de una olvidada):
        # se adopta como si se hubiera arrastrado antes, salvo que sea de otro
        # vídeo con el mismo nombre.
        if salida.is_file() and _de_nadie(salida, fichas):
            if _mas_larga(salida, original):
                break
            aviso = _('"{salida}" ya estaba en la carpeta de salida: se toma '
                      'como el vídeo procesado de "{original}", con su caption '
                      'si lo tiene. Si no es de este vídeo, muévelo a otra '
                      'carpeta y usa «Olvidar este vídeo».').format(
                salida=salida.name, original=original.name)
            return (_adoptar(_ficha_de_legado(salida), nueva.original, fichas,
                             nueva.nombre), aviso)

    _nombre_libre(nueva, fichas)
    guardar(nueva)
    return nueva, ""


def reconocer(ruta: Path, carpeta_salida: Path | None) -> tuple[Ficha, str]:
    """La ficha del vídeo arrastrado y un aviso para el usuario ("" si no hay).

    Si `ruta` es el original o una salida de una ficha (misma ruta real,
    tamaño y fecha), es esa ficha. Si no, se crea una nueva o se adopta una
    salida antigua. Si coincide la ruta pero no la huella (editado fuera), esa
    ficha lo suelta sin borrar nada; un original editado vuelve a ella. `ruta`
    tiene que existir. `carpeta_salida` solo cuenta para fichas nuevas: las
    demás conservan la suya.
    """
    ruta = ruta.resolve()
    fichas = todas()

    obsoletas = []
    for ficha in fichas:
        huellas = [h for h in (ficha.original, ficha.final, ficha.vertical)
                   if h is not None and h.ruta == ruta]
        if any(h.coincide(ruta) for h in huellas):
            return ficha, ""
        if huellas:
            obsoletas.append(ficha)

    avisos, editada = [], None
    if obsoletas:
        # Editado fuera de la app: lo que se hizo a partir de él ya no vale.
        for ficha in obsoletas:
            if ficha.original is not None and ficha.original.ruta == ruta:
                editada = ficha
            _soltar(ficha, ruta)
        avisos.append(_('"{nombre}" ha cambiado fuera de la app: lo que se hizo '
                        'a partir de él se rehará. No se borra nada de lo '
                        'guardado.').format(nombre=ruta.name))

    if editada is not None:
        # El mismo original, editado: sigue en su ficha (con sus salidas).
        ficha = _adoptar(editada, Huella.de(ruta), fichas)
    elif _es_salida_antigua(ruta):
        ficha = _ficha_de_legado(ruta)
    else:
        carpeta = ruta.parent if carpeta_salida is None else carpeta_salida
        ficha, aviso = _ficha_de_original(ruta, carpeta, fichas)
        avisos.append(aviso)
    return ficha, "\n".join(aviso for aviso in avisos if aviso)
