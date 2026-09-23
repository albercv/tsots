"""Tipos neutros de la publicación: no saben nada del proveedor."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..i18n import N_


class Plataforma(str, Enum):
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"

    @property
    def nombre(self) -> str:
        return NOMBRES[self]


# Orden fijo de publicación.
ORDEN: tuple[Plataforma, ...] = (
    Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM,
)

# Marcas: no se traducen.
NOMBRES = {
    Plataforma.TIKTOK: "TikTok",
    Plataforma.YOUTUBE: "YouTube",
    Plataforma.INSTAGRAM: "Instagram",
}


class ModoTikTok(str, Enum):
    BORRADOR = "borrador"  # llega a los borradores; se termina en la app
    PUBLICO = "publico"    # se publica directamente, visible para todos


class ModoInstagram(str, Enum):
    PRUEBA = "prueba"  # reel de prueba: se comparte con seguidores si funciona
    NORMAL = "normal"  # reel normal, también en el feed


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


@dataclass(frozen=True)
class Publicacion:
    video: Path
    titulo: str
    caption: str
    hashtags: tuple[str, ...] = ()
    palabras_clave: tuple[str, ...] = ()


@dataclass(frozen=True)
class Opciones:
    tiktok_modo: ModoTikTok = ModoTikTok.BORRADOR
    instagram_modo: ModoInstagram = ModoInstagram.PRUEBA
    youtube_categoria: str = YOUTUBE_CATEGORIA_POR_DEFECTO


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
