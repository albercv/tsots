"""Tipos neutros de la publicación: no saben nada del proveedor."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..i18n import N_


class Plataforma(str, Enum):
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    X = "x"
    FACEBOOK = "facebook"

    @property
    def nombre(self) -> str:
        return NOMBRES[self]


# Orden fijo de publicación.
ORDEN: tuple[Plataforma, ...] = (
    Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM,
    Plataforma.X, Plataforma.FACEBOOK,
)

# Marcas: no se traducen.
NOMBRES = {
    Plataforma.TIKTOK: "TikTok",
    Plataforma.YOUTUBE: "YouTube",
    Plataforma.INSTAGRAM: "Instagram",
    Plataforma.X: "X",
    Plataforma.FACEBOOK: "Facebook",
}


class ModoTikTok(str, Enum):
    BORRADOR = "borrador"  # llega a los borradores; se termina en la app
    PUBLICO = "publico"    # se publica directamente, visible para todos


class ModoInstagram(str, Enum):
    PRUEBA = "prueba"  # reel de prueba: se comparte con seguidores si funciona
    NORMAL = "normal"  # reel normal, también en el feed


class ModoFacebook(str, Enum):
    REEL = "reel"          # reel publicado
    VIDEO = "video"        # vídeo normal publicado
    BORRADOR = "borrador"  # reel sin publicar; se termina en Facebook


# Categoría "People & Blogs" de YouTube.
YOUTUBE_CATEGORIA_POR_DEFECTO = "22"

# Textos de interfaz (se traducen al mostrarlos con `_`).
ETIQUETAS_TIKTOK = {
    ModoTikTok.BORRADOR: N_("Borrador (lo terminas en la app)"),
    ModoTikTok.PUBLICO: N_("Público"),
}
ETIQUETAS_INSTAGRAM = {
    ModoInstagram.PRUEBA: N_("Reel de prueba (a seguidores si funciona)"),
    ModoInstagram.NORMAL: N_("Reel normal"),
}
ETIQUETAS_FACEBOOK = {
    ModoFacebook.REEL: N_("Reel"),
    ModoFacebook.VIDEO: N_("Vídeo normal"),
    ModoFacebook.BORRADOR: N_("Borrador (lo terminas en Facebook)"),
}
# Categorías de YouTube (id de la API de YouTube → nombre).
CATEGORIAS_YOUTUBE = {
    "22": N_("Personas y blogs"),
    "27": N_("Educación"),
    "28": N_("Ciencia y tecnología"),
    "26": N_("Consejos y estilo"),
    "24": N_("Entretenimiento"),
    "25": N_("Noticias y política"),
    "23": N_("Humor"),
    "19": N_("Viajes y eventos"),
    "17": N_("Deportes"),
    "10": N_("Música"),
}


_RE_ID_X = re.compile(r"[0-9a-fA-F]+")


def id_instagram_valido(texto: str) -> bool:
    """Instagram etiqueta con el ID numérico de una página o lugar de Facebook."""
    return (texto or "").strip().isdigit()


def id_x_valido(texto: str) -> bool:
    """Los lugares de X tienen un ID hexadecimal (p. ej. 01a9a39529b27f36)."""
    return bool(_RE_ID_X.fullmatch((texto or "").strip()))


@dataclass(frozen=True)
class Lugar:
    """Lugar de TikTok, tal como lo devuelve la búsqueda del proveedor. Su
    `id` solo vale para la cuenta con que se buscó."""

    id: str
    nombre: str
    direccion: str = ""

    @property
    def visible(self) -> str:
        return f"{self.nombre} · {self.direccion}" if self.direccion else self.nombre


@dataclass(frozen=True)
class Ubicacion:
    """Ubicación de una publicación. Solo TikTok, Instagram y X la admiten y
    cada una la identifica a su manera; lo que falta o no es válido no se
    envía.

    `nombre`: lo que escribe el usuario («Madrid»). Si no hay `tiktok`
    elegido, al publicar se busca en TikTok un lugar que se llame así."""

    nombre: str = ""
    tiktok: Lugar | None = None
    instagram_id: str = ""
    x_id: str = ""

    def plataformas(self) -> tuple[Plataforma, ...]:
        """Redes en las que irá la ubicación, en el orden de publicación."""
        con = {
            Plataforma.TIKTOK: self.tiktok is not None or bool(self.nombre.strip()),
            Plataforma.INSTAGRAM: id_instagram_valido(self.instagram_id),
            Plataforma.X: id_x_valido(self.x_id),
        }
        return tuple(p for p in ORDEN if con.get(p))

    @property
    def visible(self) -> str:
        return self.nombre.strip() or (self.tiktok.nombre if self.tiktok else "")


# Ubicación con que se etiquetan las publicaciones si el usuario no elige otra.
# Instagram: ID de Facebook Places de Madrid (Wikidata Q2807, propiedad P1997).
# X: lugar «Madrid, España» de tipo ciudad. TikTok lo busca por el nombre.
UBICACION_POR_DEFECTO = Ubicacion("Madrid", instagram_id="106504859386230",
                                  x_id="206c436ce43a43a3")
# Lugares cuyos IDs de Instagram y X se rellenan solos al escribir su nombre.
_CONOCIDAS = (UBICACION_POR_DEFECTO,)


def ubicacion_conocida(nombre: str) -> Ubicacion | None:
    """La ubicación completa de un lugar conocido que se llama `nombre`."""
    buscado = _normalizado(nombre)
    return next((u for u in _CONOCIDAS if _normalizado(u.nombre) == buscado and buscado),
                None)


def _normalizado(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFKD", texto)
                         if not unicodedata.combining(c))
    return " ".join(sin_tildes.casefold().split())


def elegir_lugar(lugares: list[Lugar], nombre: str) -> Lugar | None:
    """El primer lugar que se llama `nombre` (sin distinguir mayúsculas ni
    tildes; «Madrid, Spain» vale por «Madrid»). Ninguno: `None`, sin adivinar."""
    buscado = _normalizado(nombre)
    if not buscado:
        return None
    for lugar in lugares:
        propio = _normalizado(lugar.nombre)
        if buscado in (propio, propio.split(",")[0].strip()):
            return lugar
    return None


@dataclass(frozen=True)
class Publicacion:
    video: Path
    titulo: str
    caption: str
    hashtags: tuple[str, ...] = ()
    palabras_clave: tuple[str, ...] = ()
    # Texto propio del post de X, revisado por el usuario. Vacío: se usa el
    # de por defecto (título + hashtags, ver `textos.texto_x_por_defecto`).
    texto_x: str = ""


@dataclass(frozen=True)
class Opciones:
    tiktok_modo: ModoTikTok = ModoTikTok.BORRADOR
    instagram_modo: ModoInstagram = ModoInstagram.PRUEBA
    youtube_categoria: str = YOUTUBE_CATEGORIA_POR_DEFECTO
    # Lo declara el usuario en Redes…: con Premium, X admite vídeos largos y
    # textos de más de 280 caracteres en un solo post.
    x_premium: bool = False
    facebook_modo: ModoFacebook = ModoFacebook.REEL
    ubicacion: Ubicacion = Ubicacion()


@dataclass(frozen=True)
class Resultado:
    """Resultado de publicar en una plataforma.

    `pendiente`: el proveedor aceptó el vídeo y lo sigue procesando; se
    consulta después con `Proveedor.estado(plataforma, referencia)`.
    `referencia` es opaca para la app: solo la entiende el proveedor.
    """

    plataforma: Plataforma
    ok: bool
    url: str = ""
    error: str = ""
    pendiente: bool = False
    referencia: str = ""
    extra: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Cuenta:
    """Cuenta de una plataforma conectada en el proveedor.

    `premium`: solo X. `True` si el proveedor lo indica claramente, `None`
    si no lo sabe (nunca se deduce que no lo tenga).
    `ubicacion`: solo TikTok, que pide un permiso propio para etiquetar
    lugares. `None` si el proveedor no lo dice."""

    plataforma: Plataforma
    nombre: str = ""
    usuario: str = ""  # sin «@»
    reconectar: bool = False
    capacidades: tuple[str, ...] = ()
    premium: bool | None = None
    ubicacion: bool | None = None

    @property
    def visible(self) -> str:
        """«@usuario», o el nombre si no hay usuario."""
        return f"@{self.usuario}" if self.usuario else self.nombre


@dataclass(frozen=True)
class Pagina:
    """Página de Facebook (Meta solo deja publicar en páginas)."""

    id: str
    nombre: str = ""

    @property
    def visible(self) -> str:
        return f"{self.nombre} ({self.id})" if self.nombre else self.id
