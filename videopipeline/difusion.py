"""Prepara lo que se difunde de un vídeo: sidecars de LinkedIn y carpeta del blog.

Junta fotogramas (`fotogramas`), portadas (`portada`) y texto (`linkedin`). La
carpeta del blog se escribe oculta y se renombra al final para que el agente del
blog no vea nunca una carpeta a medias. `lanzar_agente` lo arranca.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PIL import Image

from . import linkedin
from .caption import leer_md, texto_plano
from .fotogramas import Candidato, extraer_candidatos
from .i18n import _
from .ollama import chat_json
from .portada import TAM_BLOG, TAM_LINKEDIN, componer_portada
from .steps import BASE_DIR, PasoFallido, codificar_web
from .subtitles import Palabra

log = logging.getLogger(__name__)

DIR_BLOG = Path.home() / "TSOTS" / "blog"
AGENTE = BASE_DIR / "lanzador" / "blog" / "procesar_pendientes.sh"
MAX_CAPTURAS = 2  # fotogramas sin cara (pantalla, demo): los de cara a cámara no aportan
LINEAS_IDEA = 5  # una idea es más larga que el título de la portada


@dataclass(frozen=True)
class Resultado:
    linkedin_md: Path | None  # None si no se pidió o falló el texto: el blog sigue
    carpeta_blog: Path | None  # None si no se pidió el blog
    fallo_linkedin: Exception | None = None


def _elegir_portada(candidatos: list[Candidato]) -> Candidato:
    con_cara = [c for c in candidatos if c.cara]
    return max(con_cara or candidatos, key=lambda c: c.nitidez)


def _repartidos(candidatos: list[Candidato], n: int) -> list[Candidato]:
    """`n` candidatos repartidos en el tiempo (primero, medio, último...)."""
    if len(candidatos) <= n:
        return candidatos
    return [candidatos[round(i * (len(candidatos) - 1) / (n - 1))] for i in range(n)]


def _componer(c: Candidato, titulo: str, tamano, destino: Path, **kw) -> None:
    with Image.open(c.archivo) as img:  # JPEG completo: `cara` está en sus píxeles
        componer_portada(img.convert("RGB"), titulo, tamano, cara=c.cara, **kw).save(destino)


def _carpeta_libre(dir_blog: Path, nombre: str) -> Path:
    candidato, n = nombre, 1
    while any((dir_blog / sub / candidato).exists()
              for sub in ("pendientes", "hechos", "errores")):
        n += 1
        candidato = f"{nombre}-{n}"
    return dir_blog / "pendientes" / candidato


def _enlazar_o_copiar(origen: Path, destino: Path) -> None:
    try:
        os.link(origen, destino)
    except OSError:
        shutil.copy2(origen, destino)


def preparar(*, nombre: str, base: Path, video_blog: Path, final: Path,
             palabras: list[Palabra], titulo: str, idioma: str, contexto_marca: str,
             modelo: str, con_blog: bool = True, con_linkedin: bool = True,
             dir_blog: Path = DIR_BLOG, cliente=chat_json,
             detector=None, leer=None, hoy: date | None = None,
             duracion: float | None = None, codificar=codificar_web) -> Resultado:
    hoy = hoy or date.today()
    md, car = linkedin.rutas(final)
    if con_linkedin:
        shutil.rmtree(car, ignore_errors=True)  # que no sobrevivan candidatos de otra pasada
    # Solo el blog: los candidatos van aparte para no tocar un post ya preparado.
    with tempfile.TemporaryDirectory() as aparte:
        dir_candidatos = car / "candidatos" if con_linkedin else Path(aparte)
        candidatos = extraer_candidatos(base, palabras, dir_candidatos,
                                        detector=detector, leer=leer, duracion=duracion)
        if not candidatos:
            if con_linkedin:
                shutil.rmtree(car, ignore_errors=True)
            raise PasoFallido(_("No se ha encontrado ningún fotograma válido para la portada"))
        portada = _elegir_portada(candidatos)
        transcripcion = texto_plano(palabras)
        texto, fallo = None, None
        if con_linkedin:
            texto, fallo = _post_linkedin(candidatos, portada, titulo, final, car,
                                          transcripcion, contexto_marca, modelo,
                                          cliente, idioma)
        destino = None
        if con_blog:
            destino = _carpeta_libre(dir_blog, f"{hoy:%Y-%m-%d}-{nombre}")
            tmp = destino.parent / f".{nombre}.tmp"  # oculta: se renombra al final
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            try:
                try:  # 190 MB hacían fallar la subida (502): se sube una versión de 720 px
                    codificar(video_blog, tmp / "video.mp4")
                except Exception:  # noqa: BLE001 — sin codificación se sube el original
                    (tmp / "video.mp4").unlink(missing_ok=True)
                    _enlazar_o_copiar(video_blog, tmp / "video.mp4")
                trozos = transcripcion.split()  # en líneas cortas: `Read` corta las muy largas
                (tmp / "transcripcion.txt").write_text(
                    "\n".join(" ".join(trozos[i:i + 15]) for i in range(0, len(trozos), 15)),
                    encoding="utf-8")
                _componer(portada, titulo, TAM_BLOG, tmp / "portada.png")
                shutil.copytree(dir_candidatos, tmp / "candidatos")
                caption = leer_md(final.with_suffix(".md"))
                meta = {
                    "idioma": idioma, "nombre": nombre, "titulo_corto": titulo,
                    "titulo_seo": caption.titulo if caption else None,
                    "palabras_clave": caption.palabras_clave if caption else [],
                    "contexto_marca": contexto_marca,
                    "candidatos": [{"archivo": f"candidatos/{c.archivo.name}",
                                    "segundo": round(c.segundo, 1), "texto": c.texto}
                                   for c in candidatos],
                }
                (tmp / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
                tmp.rename(destino)
            except BaseException:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
    return Resultado(md if texto is not None else None, destino, fallo)


def _post_linkedin(candidatos: list[Candidato], portada: Candidato, titulo: str,
                   final: Path, car: Path, transcripcion: str, contexto_marca: str,
                   modelo: str, cliente, idioma: str) -> tuple[str | None, Exception | None]:
    """Fotos y texto del post; (texto, fallo): sin texto las fotos quedan igual."""
    texto, ideas, fallo = None, [], None
    try:
        texto, ideas = linkedin.generar(transcripcion, contexto_marca, modelo, cliente, idioma)
    except Exception as error:  # noqa: BLE001 — sin texto de LinkedIn el blog sigue
        fallo = error
    # Portada, una tarjeta por idea clave y capturas sin cara
    _componer(portada, titulo, TAM_LINKEDIN, car / "01_portada.png", con_logo=True)
    fondos = [c for c in candidatos if c.cara and c is not portada] or [portada]
    for i, idea in enumerate(ideas):
        _componer(fondos[i % len(fondos)], idea, TAM_LINKEDIN, car / f"{i + 2:02d}_idea.png",
                  con_logo=True, max_lineas=LINEAS_IDEA)
    capturas = _repartidos([c for c in candidatos if not c.cara and c is not portada],
                           MAX_CAPTURAS)
    for i, c in enumerate(capturas, start=len(ideas) + 2):
        shutil.copy2(c.archivo, car / f"{i:02d}_{c.archivo.name}")
    if texto is not None:
        linkedin.escribir(texto, final)
    return texto, fallo


def lanzar_agente(dir_blog: Path = DIR_BLOG) -> bool:
    """Arranca el agente del blog suelto, sin esperarlo, si hay carpetas en
    `pendientes/`. Lo lanza la app y no launchd: launchd no puede ejecutar el
    script desde ~/Documents (privacidad de macOS). Si ya hay uno en marcha, su
    bloqueo hace que el nuevo salga sin hacer nada. Nunca lanza excepciones."""
    try:
        # Como el `*/` del script: las ocultas aún se escriben o están apartadas.
        if not AGENTE.is_file() or not any(
                p.is_dir() and not p.name.startswith(".")
                for p in (dir_blog / "pendientes").iterdir()):
            return False
        with open(dir_blog / "agente.log", "ab") as registro:
            subprocess.Popen([str(AGENTE), str(dir_blog)], stdin=subprocess.DEVNULL,
                             stdout=registro, stderr=registro,
                             start_new_session=True, close_fds=True)
    except FileNotFoundError:  # aún no hay pendientes/
        return False
    except OSError as error:
        log.warning("No se pudo lanzar el agente del blog (%s): %s", AGENTE, error)
        return False
    return True
