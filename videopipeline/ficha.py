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
from .steps import BASE_DIR
from .subtitles import leer_srt

log = logging.getLogger(__name__)

DIR_FICHAS = BASE_DIR / "fichas"
SUFIJOS_SALIDA = ("_limpio", "_vertical")

# Claves de los artefactos de una ficha.
AUDIO, BASE, TRANSCRIPCION, HORIZONTAL, CAPTION, SEGUIMIENTO, VERTICAL = (
    "audio", "base", "transcripcion", "horizontal", "caption", "seguimiento",
    "vertical")

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

    def hay_horizontal(self) -> bool:
        if HORIZONTAL in self.artefactos:
            return True
        return self.legado and self.final is not None and not _es_vertical(self.final)

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


def _ficha_de_original(original: Path, carpeta_salida: Path,
                       fichas: list[Ficha]) -> Ficha:
    nueva = Ficha(id=_nueva_id(), nombre=original.stem,
                  carpeta_salida=carpeta_salida, original=Huella.de(original))

    # Su salida (horizontal, o si no vertical único) es el final de una salida
    # antigua sin original: el original pasa a ser de esa ficha en vez de crear
    # otra con la misma salida.
    for salida in (nueva.ruta_final(True), nueva.ruta_final(False)):
        for ficha in fichas:
            if (ficha.original is None and ficha.final is not None
                    and ficha.final.ruta == salida.resolve()):
                ficha.original, ficha.legado = nueva.original, False
                guardar(ficha)
                return ficha

    # Otro original con el mismo nombre ya usa esas salidas: no se pisan.
    nombre, n = nueva.nombre, 1
    while any(ficha._salidas() & nueva._salidas() for ficha in fichas):
        n += 1
        nueva.nombre = f"{nombre} ({n})"
    guardar(nueva)
    return nueva


def reconocer(ruta: Path, carpeta_salida: Path | None) -> tuple[Ficha, str]:
    """La ficha del vídeo arrastrado y un aviso para el usuario ("" si no hay).

    Si `ruta` es el original o una salida de una ficha (misma ruta real,
    tamaño y fecha), es esa ficha. Si no, se crea una nueva. `ruta` tiene que
    existir. `carpeta_salida` solo cuenta para fichas nuevas: las demás
    conservan la suya.
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

    aviso = ""
    if obsoletas:
        # Editado fuera de la app: ya no vale lo que se sabía. Se olvida la
        # ficha para que no haya dos con las mismas salidas.
        for ficha in obsoletas:
            olvidar(ficha)
        fichas = [f for f in fichas if all(f.id != o.id for o in obsoletas)]
        aviso = _('"{nombre}" ha cambiado fuera de la app: '
                  'se empieza una ficha nueva').format(nombre=ruta.name)

    if _es_salida_antigua(ruta):
        return _ficha_de_legado(ruta), aviso
    carpeta = ruta.parent if carpeta_salida is None else carpeta_salida
    return _ficha_de_original(ruta, carpeta, fichas), aviso
