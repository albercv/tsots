"""Proveedor Upload-Post (https://www.upload-post.com).

Único módulo de la app que conoce Upload-Post: URLs, cabecera, nombres de
campo y formato de las respuestas. El resto solo ve `Proveedor`.

API (docs y openapi.json consultados el 2026-09-23):
- `POST /api/upload`, multipart, cabecera `Authorization: Apikey <clave>`.
  Campos comunes: `user` (perfil), `platform[]`, `video`, `title`.
- Respuesta síncrona: `{"success", "results": {plataforma: {success, url,
  post_id, error}}, "usage": {count, limit}}`.
- Si la subida pasa de ~59 s pasa a segundo plano: `{"success", "request_id",
  "total_platforms"}`; se consulta en `GET /api/uploadposts/status?request_id=`.
  Según openapi.json: `{"status": "pending|in_progress|completed", "results":
  [{"platform", "success", "message"}]}`. No documenta la URL de la
  publicación en esa respuesta: se busca en varios campos y en el mensaje.
  Pendiente de confirmar con la prueba real.
"""
from __future__ import annotations

import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx

from ..i18n import _
from .modelo import (
    ModoInstagram,
    ModoTikTok,
    Opciones,
    Plataforma,
    Publicacion,
    Resultado,
)
from .textos import etiquetas_youtube, texto_para, titulo_para

NOMBRE = "Upload-Post"
USA_PERFIL = True

URL_API = "https://api.upload-post.com/api"
URL_SUBIDA = f"{URL_API}/upload"
URL_ESTADO = f"{URL_API}/uploadposts/status"

# Solo el 503 (servicio no disponible) se reintenta: el resto de errores no
# cambian al repetir y un reintento tras un 429 gastaría cuota.
ESPERAS_503 = (2.0, 5.0)
TIEMPOS = httpx.Timeout(connect=15.0, read=180.0, write=600.0, pool=15.0)

_PLATAFORMAS = {
    Plataforma.TIKTOK: "tiktok",
    Plataforma.YOUTUBE: "youtube",
    Plataforma.INSTAGRAM: "instagram",
}
_ESTADOS_TERMINADOS = {"completed", "complete", "finished", "done", "success", "failed", "error"}
_RE_URL = re.compile(r"https?://\S+")


def campos(plataforma: Plataforma, publicacion: Publicacion, opciones: Opciones,
           perfil: str) -> dict[str, str | list[str]]:
    """Campos del formulario multipart (sin el vídeo) para una plataforma."""
    datos: dict[str, str | list[str]] = {
        "user": perfil,
        "platform[]": [_PLATAFORMAS[plataforma]],
        # Obligatorio para YouTube; las demás usan su título propio.
        "title": titulo_para(Plataforma.YOUTUBE, publicacion),
    }
    texto = texto_para(plataforma, publicacion)
    if plataforma == Plataforma.TIKTOK:
        datos["tiktok_title"] = texto
        datos["is_aigc"] = "false"
        if opciones.tiktok_modo == ModoTikTok.PUBLICO:
            datos["post_mode"] = "DIRECT_POST"
            datos["privacy_level"] = "PUBLIC_TO_EVERYONE"
        else:
            datos["post_mode"] = "MEDIA_UPLOAD"
    elif plataforma == Plataforma.YOUTUBE:
        datos["youtube_title"] = titulo_para(Plataforma.YOUTUBE, publicacion)
        datos["youtube_description"] = texto
        etiquetas = etiquetas_youtube(publicacion)
        if etiquetas:
            datos["tags[]"] = etiquetas
        datos["categoryId"] = opciones.youtube_categoria or "22"
        datos["privacyStatus"] = "public"
        datos["containsSyntheticMedia"] = "false"
    elif plataforma == Plataforma.INSTAGRAM:
        datos["instagram_title"] = texto
        datos["media_type"] = "REELS"
        datos["is_ai_generated"] = "false"
        if opciones.instagram_modo == ModoInstagram.NORMAL:
            datos["share_mode"] = "CUSTOM"
            datos["share_to_feed"] = "true"
        else:
            datos["share_mode"] = "TRIAL_REELS_SHARE_TO_FOLLOWERS_IF_LIKED"
    return datos


class ProveedorUploadPost:
    nombre = NOMBRE

    def __init__(self, clave: str, perfil: str, http: httpx.Client | None = None,
                 espera: Callable[[float], None] = time.sleep):
        self._clave = clave
        self._perfil = perfil.strip()
        self._http = http
        self._espera = espera

    def __repr__(self) -> str:  # nunca la clave
        return f"ProveedorUploadPost(perfil={self._perfil!r})"

    # --- API neutra ---

    def publicar(self, plataforma: Plataforma, publicacion: Publicacion,
                 opciones: Opciones) -> Resultado:
        video = Path(publicacion.video)
        if not self._clave:
            return self._error(plataforma, _("Falta la API key. Guárdala en Redes…"))
        if not self._perfil:
            return self._error(plataforma, _("Falta el perfil. Escríbelo en Redes…"))
        if not video.is_file():
            return self._error(plataforma, _("No se encuentra el vídeo: {nombre}").format(
                nombre=video.name))
        datos = campos(plataforma, publicacion, opciones, self._perfil)

        def enviar(http: httpx.Client) -> httpx.Response:
            with video.open("rb") as fichero:
                return http.post(
                    URL_SUBIDA, headers=self._cabeceras(), data=datos,
                    files={"video": (video.name, fichero, "video/mp4")},
                )

        try:
            respuesta = self._con_reintentos(enviar)
        except httpx.HTTPError as e:
            return self._error(plataforma, _("No se pudo conectar con el servicio ({tipo}).").format(
                tipo=type(e).__name__))
        except OSError as e:
            return self._error(plataforma, _("No se pudo leer el vídeo ({tipo}).").format(
                tipo=type(e).__name__))
        return self._interpretar_subida(plataforma, respuesta)

    def estado(self, plataforma: Plataforma, referencia: str) -> Resultado:
        if not referencia:
            return self._error(plataforma, _("Publicación sin referencia para consultar."))
        try:
            respuesta = self._con_reintentos(lambda http: http.get(
                URL_ESTADO, headers=self._cabeceras(), params={"request_id": referencia}))
        except httpx.HTTPError:
            # Fallo de red pasajero: se sigue esperando.
            return Resultado(plataforma, ok=False, pendiente=True, referencia=referencia)
        if respuesta.status_code >= 400:
            if respuesta.status_code in (500, 502, 503, 504):
                return Resultado(plataforma, ok=False, pendiente=True, referencia=referencia)
            return self._error(plataforma, self._mensaje_http(respuesta))
        cuerpo = self._json(respuesta)
        if not isinstance(cuerpo, dict):
            return Resultado(plataforma, ok=False, pendiente=True, referencia=referencia)
        propio = self._resultado_de(cuerpo.get("results"), plataforma)
        if propio is not None and "success" in propio:
            return self._resultado_plataforma(plataforma, propio)
        estado = str(cuerpo.get("status", "")).strip().lower()
        if estado in _ESTADOS_TERMINADOS:
            return self._error(plataforma, _("El servicio terminó sin resultado para {plataforma}.").format(
                plataforma=plataforma.nombre))
        return Resultado(plataforma, ok=False, pendiente=True, referencia=referencia)

    # --- detalles ---

    def _cabeceras(self) -> dict[str, str]:
        return {"Authorization": f"Apikey {self._clave}"}

    @contextmanager
    def _cliente(self) -> Iterator[httpx.Client]:
        if self._http is not None:
            yield self._http
            return
        with httpx.Client(timeout=TIEMPOS) as http:
            yield http

    def _con_reintentos(self, llamada: Callable[[httpx.Client], httpx.Response]) -> httpx.Response:
        with self._cliente() as http:
            respuesta = llamada(http)
            for segundos in ESPERAS_503:
                if respuesta.status_code != 503:
                    break
                self._espera(segundos)
                respuesta = llamada(http)
            return respuesta

    def _interpretar_subida(self, plataforma: Plataforma, respuesta: httpx.Response) -> Resultado:
        if respuesta.status_code >= 400:
            return self._error(plataforma, self._mensaje_http(respuesta))
        cuerpo = self._json(respuesta)
        if not isinstance(cuerpo, dict):
            return self._error(plataforma, _("Respuesta inesperada del servicio."))
        extra = self._uso(cuerpo)
        propio = self._resultado_de(cuerpo.get("results"), plataforma)
        if propio is not None:
            resultado = self._resultado_plataforma(plataforma, propio)
            return Resultado(resultado.plataforma, resultado.ok, resultado.url,
                             resultado.error, extra=extra)
        if cuerpo.get("request_id"):
            return Resultado(plataforma, ok=False, pendiente=True,
                             referencia=str(cuerpo["request_id"]), extra=extra)
        if cuerpo.get("success") is False:
            return self._error(plataforma, self._limpiar(
                self._texto(cuerpo) or _("El servicio rechazó la publicación.")))
        return self._error(plataforma, _("Respuesta inesperada del servicio."))

    @staticmethod
    def _resultado_de(resultados: Any, plataforma: Plataforma) -> dict | None:
        """Resultado de una plataforma, sea `{plataforma: {...}}` o
        `[{"platform": ..., ...}]`."""
        clave = _PLATAFORMAS[plataforma]
        if isinstance(resultados, dict):
            for nombre, valor in resultados.items():
                if str(nombre).lower() == clave and isinstance(valor, dict):
                    return valor
        elif isinstance(resultados, list):
            for valor in resultados:
                if isinstance(valor, dict) and str(valor.get("platform", "")).lower() == clave:
                    return valor
        return None

    def _resultado_plataforma(self, plataforma: Plataforma, datos: dict) -> Resultado:
        if datos.get("success") is True or str(datos.get("success")).lower() == "true":
            return Resultado(plataforma, ok=True, url=self._url(datos))
        return self._error(plataforma, self._limpiar(
            self._texto(datos) or _("{plataforma} rechazó la publicación.").format(
                plataforma=plataforma.nombre)))

    @staticmethod
    def _url(datos: dict) -> str:
        for campo in ("url", "post_url", "platform_post_url", "permalink", "link"):
            valor = datos.get(campo)
            if isinstance(valor, str) and valor.startswith("http"):
                return valor
        encontrada = _RE_URL.search(str(datos.get("message", "")))
        return encontrada.group(0).rstrip(".,)") if encontrada else ""

    @staticmethod
    def _texto(datos: dict) -> str:
        for campo in ("error", "message", "detail"):
            valor = datos.get(campo)
            if isinstance(valor, str) and valor.strip():
                return valor.strip()
        return ""

    @staticmethod
    def _uso(cuerpo: dict) -> dict:
        uso = cuerpo.get("usage")
        if isinstance(uso, dict) and "count" in uso:
            return {"uso": f"{uso.get('count')}/{uso.get('limit', '?')}"}
        return {}

    @staticmethod
    def _json(respuesta: httpx.Response) -> Any:
        try:
            return respuesta.json()
        except ValueError:
            return None

    def _mensaje_http(self, respuesta: httpx.Response) -> str:
        codigo = respuesta.status_code
        cuerpo = self._json(respuesta)
        detalle = self._texto(cuerpo) if isinstance(cuerpo, dict) else ""
        if codigo == 401:
            base = _("La API key no es válida o ha caducado (401). Revísala en Redes…")
        elif codigo == 403:
            base = _("Sin permiso o fuera del plan contratado (403).")
        elif codigo == 429:
            base = _("Límite de subidas del plan alcanzado (429).")
        elif codigo == 503:
            base = _("Servicio no disponible (503). Prueba más tarde.")
        else:
            base = _("Error {codigo} del servicio.").format(codigo=codigo)
        return self._limpiar(f"{base} {detalle}".strip())

    def _limpiar(self, texto: str) -> str:
        """Quita la clave (por si el servicio la repite) y acota la longitud."""
        if self._clave:
            texto = texto.replace(self._clave, "***")
        return texto if len(texto) <= 400 else texto[:399] + "…"

    def _error(self, plataforma: Plataforma, texto: str) -> Resultado:
        return Resultado(plataforma, ok=False, error=self._limpiar(texto))


def crear(clave: str, ajustes: dict, http: httpx.Client | None = None) -> ProveedorUploadPost:
    return ProveedorUploadPost(clave, str(ajustes.get("perfil", "") or ""), http=http)
