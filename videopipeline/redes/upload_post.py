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
- X (`platform[]=x`): `x_title` es el texto del post. Si pasa de 280
  caracteres, el servicio lo publica como hilo salvo con
  `x_long_text_as_post=true` (solo cuentas Premium): la app garantiza ≤ 280
  sin Premium. No se usan `reply_settings`, `nullcast`, `community_id`,
  `x_alt_text`, `x_paid_partnership` ni `x_subtitles_url` (solo admite una
  URL pública). Los resultados pueden venir como `x` o como `twitter`.
- Facebook (`platform[]=facebook`): `facebook_page_id` (obligatorio; Meta
  solo deja publicar en páginas), `facebook_title`, `facebook_description`,
  `facebook_media_type` (REELS | VIDEO | STORIES) y `video_state`
  (PUBLISHED | DRAFT). Supuesto: el borrador es un reel en DRAFT.
- Cuentas conectadas: `GET /api/uploadposts/users/{perfil}` → perfil con
  `social_accounts`: por plataforma, `null`/`""` si no está conectada o un
  objeto con `display_name`, `handle`, `username`, `reauth_required` y
  `capabilities`. Supuesto: una capacidad de X que nombra Premium o vídeo o
  texto largo indica una cuenta Premium; si no hay ninguna, no se sabe.
- Páginas de Facebook: `GET /api/uploadposts/facebook/pages?profile=` →
  lista de `{page_id, page_name, profile}` (se aceptan envoltorios como
  `{"pages": [...]}`).

Cada petición, su código HTTP, su cuerpo (limpio y acotado) y cada sondeo
se anotan con `logging` en el registro de la publicación (`diario`).

La subida (`POST /upload`) nunca se repite sola: un 5xx o una respuesta que
no llega después de enviar el vídeo pueden ocurrir cuando el servicio ya lo
aceptó, y repetir el POST lo publicaría varias veces. Esos casos quedan «por
confirmar» (pendiente sin referencia): la app pide revisarlo antes de volver
a publicar. Solo la consulta de estado (GET, idempotente) se reintenta. Se
pide `async_upload=true` para que la subida devuelva enseguida un
`request_id` que se consulta después, y cada intento lleva un `external_id`
propio que queda en el registro para rastrear duplicados.
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import quote

import httpx

from ..i18n import N_, _
from . import diario
from .modelo import (
    Cuenta,
    ModoFacebook,
    ModoInstagram,
    ModoTikTok,
    Opciones,
    Pagina,
    Plataforma,
    Publicacion,
    Resultado,
)
from .proveedor import ErrorConsulta
from .textos import MAX_TEXTO_X, etiquetas_youtube, longitud_x, texto_para, titulo_para

NOMBRE = "Upload-Post"
USA_PERFIL = True
AYUDA_PERFIL = N_(
    "En Upload-Post es el nombre del perfil que aparece en Manage Users "
    "(app.upload-post.com/manage-users), donde conectaste tus redes. "
    "No es el email de tu cuenta.")

URL_API = "https://api.upload-post.com/api"
URL_SUBIDA = f"{URL_API}/upload"
URL_ESTADO = f"{URL_API}/uploadposts/status"
URL_USUARIOS = f"{URL_API}/uploadposts/users"
URL_PAGINAS_FACEBOOK = f"{URL_API}/uploadposts/facebook/pages"
# Las consultas de cuentas y páginas se hacen al abrir los diálogos: si el
# servicio no responde pronto, la app sigue con lo último que sabía.
ESPERA_CONSULTA = httpx.Timeout(10.0, connect=5.0)

# Solo la consulta de estado (GET) reintenta un 503. La subida, nunca.
ESPERAS_503 = (2.0, 5.0)
_CODIGOS_SERVIDOR = (500, 502, 503, 504)
# Fallos de red en los que el vídeo no llegó entero: es seguro reintentar a mano.
_SIN_ENVIAR = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout,
               httpx.WriteError, httpx.WriteTimeout)

# httpx aplica cada límite a cada operación (conectar, enviar un trozo, leer),
# no a la petición entera; aun así, un vídeo de cientos de MB por una conexión
# doméstica puede tardar muchos minutos y el envío se atasca a ratos. Ninguna
# espera es corta, y la de escritura crece con el tamaño del vídeo.
VELOCIDAD_MINIMA = 250_000  # bytes/s que se dan por buenos en el peor caso
ESPERA_ESCRITURA_MINIMA = 600.0
ESPERA_LECTURA = 300.0  # tras enviar todo, el servicio puede tardar en responder
ESPERA_CONEXION = 30.0

log = logging.getLogger(__name__)

_PLATAFORMAS = {
    Plataforma.TIKTOK: "tiktok",
    Plataforma.YOUTUBE: "youtube",
    Plataforma.INSTAGRAM: "instagram",
    Plataforma.X: "x",
    Plataforma.FACEBOOK: "facebook",
}
# Nombres con que el servicio puede devolver cada plataforma.
_NOMBRES_RESPUESTA = {plataforma: (nombre,) for plataforma, nombre in _PLATAFORMAS.items()}
_NOMBRES_RESPUESTA[Plataforma.X] = ("x", "twitter")
# Capacidades de una cuenta de X que indican Premium (supuesto, ver arriba).
_RE_PREMIUM = re.compile(r"premium|long[\s_-]?(?:video|form|post|text)", re.IGNORECASE)
# Estados (de la petición o de una plataforma) que da el servicio.
_ESTADOS_EN_CURSO = {"pending", "processing", "in_progress", "in progress", "queued",
                     "scheduled", "uploading", "started", "submitted", "running", "waiting"}
_ESTADOS_FALLIDOS = {"failed", "failure", "error", "rejected", "cancelled", "canceled"}
_ESTADOS_HECHOS = {"completed", "complete", "finished", "done", "success", "succeeded",
                   "published"}
_RE_EN_CURSO = re.compile(
    r"\b(processing|in progress|pending|queued|being processed|scheduled|uploading)\b",
    re.IGNORECASE)
# Campos que, si traen texto, indican un fallo explícito de la plataforma.
_CAMPOS_ERROR = ("error", "error_message", "errors", "error_user_msg", "reason")
_RE_URL = re.compile(r"https?://\S+")
_RE_ETIQUETA = re.compile(r"<[^>]+>")
_RE_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
# Dónde buscar el motivo de un fallo, por prioridad: primero el texto pensado
# para el usuario (Meta: `error_user_msg`), luego el mensaje técnico y, al
# final, los códigos. Vale para `{"error": {...}}` anidados y listas.
_CAMPOS_USUARIO = ("error_user_msg", "user_message", "error_user_title")
_CAMPOS_MOTIVO = ("error_message", "message", "error", "errors", "details", "detail",
                  "msg", "reason", "description", "error_description")
_CAMPOS_CODIGO = ("code", "error_code", "error_subcode", "subcode", "type")
MAX_DETALLE = 200
# Respuesta del servicio cuando `user` no es un perfil de Manage Users (p. ej.
# cuando se escribe el email de la cuenta).
_RE_PERFIL_DESCONOCIDO = re.compile(
    r"not associated with any profile|profile\s+(?:was\s+)?not\s+found|"
    r"user(?:name)?\s+(?:was\s+)?not\s+found", re.IGNORECASE)


def tiempos(tamano: int) -> httpx.Timeout:
    """Límites de espera para subir un vídeo de `tamano` bytes."""
    escritura = max(ESPERA_ESCRITURA_MINIMA, tamano / VELOCIDAD_MINIMA)
    return httpx.Timeout(connect=ESPERA_CONEXION, read=ESPERA_LECTURA,
                         write=escritura, pool=ESPERA_CONEXION)


def campos(plataforma: Plataforma, publicacion: Publicacion, opciones: Opciones,
           perfil: str, pagina_facebook: str = "") -> dict[str, str | list[str]]:
    """Campos del formulario multipart (sin el vídeo) para una plataforma."""
    datos: dict[str, str | list[str]] = {
        "user": perfil,
        "platform[]": [_PLATAFORMAS[plataforma]],
        # Responde enseguida con un request_id: sin petición larga que pueda
        # cortarse después de que el servicio ya aceptó el vídeo.
        "async_upload": "true",
        # Obligatorio para YouTube; las demás usan su título propio.
        "title": titulo_para(Plataforma.YOUTUBE, publicacion),
    }
    texto = texto_para(plataforma, publicacion, x_premium=opciones.x_premium)
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
    elif plataforma == Plataforma.X:
        # Sin Premium, `texto_para` ya lo deja en 280: nunca sale un hilo.
        datos["x_title"] = texto
        largo = opciones.x_premium and longitud_x(texto) > MAX_TEXTO_X
        datos["x_long_text_as_post"] = "true" if largo else "false"
        datos["made_with_ai"] = "false"
    elif plataforma == Plataforma.FACEBOOK:
        datos["facebook_page_id"] = pagina_facebook
        datos["facebook_title"] = titulo_para(Plataforma.FACEBOOK, publicacion)
        datos["facebook_description"] = texto
        datos["facebook_media_type"] = (
            "VIDEO" if opciones.facebook_modo == ModoFacebook.VIDEO else "REELS")
        datos["video_state"] = (
            "DRAFT" if opciones.facebook_modo == ModoFacebook.BORRADOR else "PUBLISHED")
        datos["facebook_is_ai_generated"] = "false"
    return datos


class ProveedorUploadPost:
    nombre = NOMBRE

    def __init__(self, clave: str, perfil: str, http: httpx.Client | None = None,
                 espera: Callable[[float], None] = time.sleep, pagina_facebook: str = ""):
        self._clave = clave
        self._perfil = perfil.strip()
        self._pagina_facebook = (pagina_facebook or "").strip()
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
        if plataforma == Plataforma.FACEBOOK and not self._pagina_facebook:
            return self._error(plataforma, _(
                "Falta la página de Facebook. Elígela en Redes…"))
        if not video.is_file():
            return self._error(plataforma, _("No se encuentra el vídeo: {nombre}").format(
                nombre=video.name))
        datos = campos(plataforma, publicacion, opciones, self._perfil, self._pagina_facebook)
        try:
            estado_video = video.stat()
            tamano = estado_video.st_size
        except OSError:
            estado_video, tamano = None, 0
        datos["external_id"] = identificador_externo(
            plataforma, video, tamano, estado_video.st_mtime if estado_video else 0.0)
        limites = tiempos(tamano)
        # El perfil (`user`) no va al registro.
        log.info("%s: POST %s (un único intento) · external_id %s · vídeo %s (%d bytes) · "
                 "campos %s · esperas máx.: "
                 "conexión %.0f s, escritura %.0f s, lectura %.0f s",
                 plataforma.nombre, URL_SUBIDA, datos["external_id"], video, tamano,
                 {k: v for k, v in datos.items() if k not in ("user", "external_id")},
                 limites.connect, limites.write, limites.read)

        def enviar(http: httpx.Client) -> httpx.Response:
            with video.open("rb") as fichero:
                return http.post(
                    URL_SUBIDA, headers=self._cabeceras(), data=datos,
                    files={"video": (video.name, fichero, "video/mp4")},
                    timeout=limites,
                )

        inicio = time.monotonic()
        try:
            with self._cliente() as http:
                respuesta = enviar(http)  # sin reintentos: ver el docstring del módulo
        except _SIN_ENVIAR as e:
            log.warning("%s: el vídeo no llegó a enviarse entero tras %.1f s: %s",
                        plataforma.nombre, time.monotonic() - inicio, self._traza(e))
            return self._error(plataforma, _("No se pudo conectar con el servicio ({tipo}).").format(
                tipo=type(e).__name__))
        except httpx.HTTPError as e:
            log.warning("%s: sin respuesta tras enviar el vídeo (%.1f s): %s",
                        plataforma.nombre, time.monotonic() - inicio, self._traza(e))
            resultado = self._por_confirmar(plataforma, _(
                "El vídeo se envió pero no llegó la respuesta del servicio ({tipo}).").format(
                tipo=type(e).__name__))
            self._registrar_resultado(resultado)
            return resultado
        except OSError as e:
            log.warning("%s: no se pudo leer el vídeo: %s", plataforma.nombre, self._traza(e))
            return self._error(plataforma, _("No se pudo leer el vídeo ({tipo}).").format(
                tipo=type(e).__name__))
        self._registrar_respuesta(plataforma, "subida", respuesta, time.monotonic() - inicio)
        resultado = self._interpretar_subida(plataforma, respuesta)
        self._registrar_resultado(resultado)
        return resultado

    def estado(self, plataforma: Plataforma, referencia: str) -> Resultado:
        if not referencia:
            return self._por_confirmar(plataforma, _("Publicación sin referencia para consultar."))
        log.info("%s: GET %s request_id=%s", plataforma.nombre, URL_ESTADO, referencia)
        inicio = time.monotonic()
        try:
            respuesta = self._con_reintentos(lambda http: http.get(
                URL_ESTADO, headers=self._cabeceras(), params={"request_id": referencia},
                timeout=tiempos(0)))
        except httpx.HTTPError as e:
            # Fallo de red pasajero: se sigue esperando.
            log.warning("%s: consulta request_id=%s falló: %s: %s", plataforma.nombre,
                        referencia, type(e).__name__, self._limpiar(str(e)))
            return Resultado(plataforma, ok=False, pendiente=True, referencia=referencia)
        self._registrar_respuesta(plataforma, f"estado request_id={referencia}", respuesta,
                                  time.monotonic() - inicio)
        resultado = self._interpretar_estado(plataforma, referencia, respuesta)
        self._registrar_resultado(resultado)
        return resultado

    def cuentas(self) -> dict[Plataforma, Cuenta | None]:
        cuerpo = self._consultar("cuentas", URL_USUARIOS + "/{perfil}",
                                 f"{URL_USUARIOS}/{quote(self._perfil, safe='')}")
        sociales = self._buscar(cuerpo, "social_accounts")
        if not isinstance(sociales, dict):
            raise ErrorConsulta(_(
                "Respuesta inesperada del servicio: no trae las cuentas conectadas."))
        por_nombre = {str(nombre).strip().lower(): valor for nombre, valor in sociales.items()}
        cuentas: dict[Plataforma, Cuenta | None] = {}
        for plataforma in Plataforma:
            valor = next((por_nombre[n] for n in _NOMBRES_RESPUESTA[plataforma]
                          if n in por_nombre), None)
            cuentas[plataforma] = self._cuenta(plataforma, valor)
        log.info("Cuentas: %s", ", ".join(
            f"{p.nombre} " + ("no conectada" if c is None else (c.visible or "conectada")
                             + (" (reconectar)" if c.reconectar else "")
                             + (" (Premium)" if c.premium else ""))
            for p, c in cuentas.items()))
        return cuentas

    def paginas_facebook(self) -> list[Pagina]:
        cuerpo = self._consultar("páginas de Facebook", URL_PAGINAS_FACEBOOK + "?profile={perfil}",
                                 URL_PAGINAS_FACEBOOK, {"profile": self._perfil})
        lista = cuerpo if isinstance(cuerpo, list) else None
        for campo in ("pages", "data", "facebook_pages", "results"):
            if lista is not None:
                break
            encontrada = self._buscar(cuerpo, campo)
            lista = encontrada if isinstance(encontrada, list) else None
        if lista is None:
            raise ErrorConsulta(_(
                "Respuesta inesperada del servicio: no trae las páginas de Facebook."))
        paginas: list[Pagina] = []
        for elemento in lista:
            if not isinstance(elemento, dict):
                continue
            ident = str(elemento.get("page_id") or elemento.get("id") or "").strip()
            perfil = elemento.get("profile")
            if not ident or (isinstance(perfil, str) and perfil.strip()
                             and perfil.strip().lower() != self._perfil.lower()):
                continue
            nombre = str(elemento.get("page_name") or elemento.get("name") or "").strip()
            paginas.append(Pagina(ident, nombre))
        log.info("Páginas de Facebook: %s",
                 ", ".join(p.visible for p in paginas) or "(ninguna)")
        return paginas

    def _consultar(self, que: str, plantilla: str, url: str,
                   parametros: dict | None = None) -> Any:
        """GET de consulta (cuentas, páginas). Lanza `ErrorConsulta` con un
        motivo legible. `plantilla` es la URL que va al registro, sin el perfil."""
        if not self._clave:
            raise ErrorConsulta(_("Falta la API key. Guárdala en Redes…"))
        if not self._perfil:
            raise ErrorConsulta(_("Falta el perfil. Escríbelo en Redes…"))
        log.info("Consulta de %s: GET %s", que, plantilla)
        inicio = time.monotonic()
        try:
            with self._cliente() as http:
                respuesta = http.get(url, headers=self._cabeceras(), params=parametros,
                                     timeout=ESPERA_CONSULTA)
        except httpx.HTTPError as e:
            log.warning("Consulta de %s fallida tras %.1f s: %s", que,
                        time.monotonic() - inicio, self._traza(e))
            raise ErrorConsulta(_("No se pudo conectar con el servicio ({tipo}).").format(
                tipo=type(e).__name__)) from None
        log.info("Consulta de %s → HTTP %d en %.1f s · cuerpo: %s", que, respuesta.status_code,
                 time.monotonic() - inicio,
                 diario.cuerpo(respuesta.text, [self._clave]) or "(vacío)")
        if respuesta.status_code >= 400:
            raise ErrorConsulta(self._mensaje_http(respuesta))
        cuerpo = self._json(respuesta)
        if not isinstance(cuerpo, (dict, list)):
            raise ErrorConsulta(self._limpiar(_(
                "Respuesta inesperada del servicio (HTTP {codigo}).").format(
                codigo=respuesta.status_code)))
        return cuerpo

    @classmethod
    def _buscar(cls, datos: Any, campo: str, profundidad: int = 0) -> Any:
        """Valor de `campo` en `datos` o en un diccionario anidado (envoltorios
        como `{"profile": {...}}` o `{"data": {...}}`)."""
        if not isinstance(datos, dict) or profundidad > 3:
            return None
        if campo in datos:
            return datos[campo]
        for valor in datos.values():
            encontrado = cls._buscar(valor, campo, profundidad + 1)
            if encontrado is not None:
                return encontrado
        return None

    @staticmethod
    def _cuenta(plataforma: Plataforma, valor: Any) -> Cuenta | None:
        if isinstance(valor, str):
            usuario = valor.strip().lstrip("@")
            return Cuenta(plataforma, usuario=usuario) if usuario else None
        if not isinstance(valor, dict) or not valor:
            return None
        nombre = str(valor.get("display_name") or valor.get("name") or "").strip()
        usuario = str(valor.get("handle") or valor.get("username") or "").strip().lstrip("@")
        bruto = valor.get("capabilities")
        if isinstance(bruto, dict):
            capacidades = [str(k) for k, v in bruto.items() if v]
        elif isinstance(bruto, list):
            capacidades = [str(c if not isinstance(c, dict) else
                               c.get("name") or c.get("id") or c.get("capability") or "")
                           for c in bruto]
        else:
            capacidades = []
        capacidades = [c.strip() for c in capacidades if c and c.strip()]
        premium = None
        if plataforma == Plataforma.X and any(_RE_PREMIUM.search(c) for c in capacidades):
            premium = True
        return Cuenta(plataforma, nombre=nombre, usuario=usuario,
                      reconectar=_verdadero(valor.get("reauth_required")),
                      capacidades=tuple(capacidades), premium=premium)

    def _interpretar_estado(self, plataforma: Plataforma, referencia: str,
                            respuesta: httpx.Response) -> Resultado:
        if respuesta.status_code >= 400:
            if respuesta.status_code in _CODIGOS_SERVIDOR:
                return Resultado(plataforma, ok=False, pendiente=True, referencia=referencia)
            # La consulta falló, no la publicación: no se sabe cómo acabó.
            return self._por_confirmar(plataforma, self._mensaje_http(respuesta, plataforma))
        cuerpo = self._json(respuesta)
        if not isinstance(cuerpo, dict):
            return Resultado(plataforma, ok=False, pendiente=True, referencia=referencia)
        propio = self._resultado_de(cuerpo.get("results"), plataforma)
        if propio is not None:
            return self._resultado_plataforma(plataforma, propio, referencia)
        estado = str(cuerpo.get("status", "")).strip().lower()
        if estado in _ESTADOS_FALLIDOS:
            return self._error(plataforma, self._legible(
                self._texto(cuerpo) or _("{plataforma} rechazó la publicación.").format(
                    plataforma=plataforma.nombre)))
        if estado in _ESTADOS_HECHOS:
            return self._por_confirmar(plataforma, _(
                "El servicio terminó sin dar el resultado de {plataforma}.").format(
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
        with httpx.Client(timeout=tiempos(0)) as http:
            yield http

    def _con_reintentos(self, llamada: Callable[[httpx.Client], httpx.Response]) -> httpx.Response:
        with self._cliente() as http:
            respuesta = llamada(http)
            for segundos in ESPERAS_503:
                if respuesta.status_code != 503:
                    break
                log.info("HTTP 503: nuevo intento en %.0f s", segundos)
                self._espera(segundos)
                respuesta = llamada(http)
            return respuesta

    def _registrar_respuesta(self, plataforma: Plataforma, que: str,
                             respuesta: httpx.Response, segundos: float) -> None:
        log.info("%s: %s → HTTP %d en %.1f s · cuerpo: %s", plataforma.nombre, que,
                 respuesta.status_code, segundos,
                 diario.cuerpo(respuesta.text, [self._clave]) or "(vacío)")

    @staticmethod
    def _registrar_resultado(resultado: Resultado) -> None:
        nombre = resultado.plataforma.nombre
        if resultado.ok:
            log.info("%s: publicado %s", nombre, resultado.url or "(sin enlace)")
        elif resultado.pendiente:
            log.info("%s: pendiente en el servicio, request_id=%s", nombre, resultado.referencia)
        else:
            log.warning("%s: error: %s", nombre, resultado.error)

    def _interpretar_subida(self, plataforma: Plataforma, respuesta: httpx.Response) -> Resultado:
        if respuesta.status_code in _CODIGOS_SERVIDOR:
            # Tras enviar el vídeo, un 5xx no dice si el servicio lo aceptó.
            return self._por_confirmar(plataforma, self._mensaje_http(respuesta, plataforma))
        if respuesta.status_code >= 400:
            return self._error(plataforma, self._mensaje_http(respuesta, plataforma))
        cuerpo = self._json(respuesta)
        if not isinstance(cuerpo, dict):
            texto = self._texto_plano(respuesta.text)
            return self._por_confirmar(plataforma, _(
                "Respuesta inesperada del servicio (HTTP {codigo}).").format(
                codigo=respuesta.status_code) + (f" {texto}" if texto else ""))
        extra = self._uso(cuerpo)
        propio = self._resultado_de(cuerpo.get("results"), plataforma)
        if propio is not None:
            resultado = self._resultado_plataforma(
                plataforma, propio, str(cuerpo.get("request_id") or ""))
            return replace(resultado, extra=extra)
        if cuerpo.get("request_id"):
            return Resultado(plataforma, ok=False, pendiente=True,
                             referencia=str(cuerpo["request_id"]), extra=extra)
        if cuerpo.get("success") is False or str(cuerpo.get("success")).lower() == "false":
            return self._error(plataforma, self._legible(
                self._texto(cuerpo) or _("El servicio rechazó la publicación.")))
        motivo = self._texto(cuerpo)
        if motivo:
            return self._por_confirmar(plataforma, _(
                "El servicio no devolvió resultado para {plataforma}: {motivo}").format(
                plataforma=plataforma.nombre, motivo=motivo))
        return self._por_confirmar(plataforma, _(
            "Respuesta inesperada del servicio: no trae resultado para {plataforma}.").format(
            plataforma=plataforma.nombre))

    @staticmethod
    def _resultado_de(resultados: Any, plataforma: Plataforma) -> dict | None:
        """Resultado de una plataforma, sea `{plataforma: {...}}` o
        `[{"platform": ..., ...}]`."""
        nombres = _NOMBRES_RESPUESTA[plataforma]
        if isinstance(resultados, dict):
            for nombre, valor in resultados.items():
                if str(nombre).lower() in nombres and isinstance(valor, dict):
                    return valor
        elif isinstance(resultados, list):
            for valor in resultados:
                if (isinstance(valor, dict)
                        and str(valor.get("platform", "")).lower() in nombres):
                    return valor
        return None

    def _resultado_plataforma(self, plataforma: Plataforma, datos: dict,
                              referencia: str = "") -> Resultado:
        """Clasifica el resultado de una plataforma en publicado, en curso o
        fallido. Solo es fallo lo explícito (texto de error o estado fallido);
        lo ambiguo nunca se muestra como error: queda por confirmar."""
        log.info("%s: resultado del servicio: %s", plataforma.nombre, diario.cuerpo(
            json.dumps(datos, ensure_ascii=False, default=str), [self._clave]))
        exito = datos.get("success")
        if exito is True or str(exito).lower() == "true":
            return Resultado(plataforma, ok=True, url=self._url(datos))
        estado = str(datos.get("status") or "").strip().lower()
        propia = str(datos.get("request_id") or datos.get("job_id") or "") or referencia
        texto = self._texto(datos)
        texto_error = self._texto({c: datos[c] for c in _CAMPOS_ERROR if c in datos})
        if estado in _ESTADOS_FALLIDOS or texto_error:
            return self._error(plataforma, self._legible(texto or _(
                "{plataforma} rechazó la publicación.").format(plataforma=plataforma.nombre)))
        if estado in _ESTADOS_EN_CURSO or _RE_EN_CURSO.search(texto):
            if propia:
                return Resultado(plataforma, ok=False, pendiente=True, referencia=propia)
            return self._por_confirmar(plataforma, texto)
        if estado in _ESTADOS_HECHOS:
            return Resultado(plataforma, ok=True, url=self._url(datos))
        if (exito is False or str(exito).lower() == "false") and texto:
            return self._error(plataforma, self._legible(texto))
        return self._por_confirmar(plataforma, texto)

    def _por_confirmar(self, plataforma: Plataforma, motivo: str = "") -> Resultado:
        """Puede que se haya publicado: nada de reintentar a ciegas."""
        texto = _("No se pudo confirmar si se publicó. Revisa {plataforma} antes de volver "
                  "a publicar.").format(plataforma=plataforma.nombre)
        if motivo:
            texto = f"{texto} ({motivo})"
        return Resultado(plataforma, ok=False, pendiente=True, error=self._limpiar(texto))

    def _perfil_desconocido(self) -> str:
        return _("El perfil «{perfil}» no existe en Upload-Post. Usa el nombre del "
                 "perfil que aparece en Manage Users, no el email de tu cuenta.").format(
            perfil=self._perfil)

    def _legible(self, motivo: str) -> str:
        """Motivo del servicio; los que tienen arreglo conocido, explicados."""
        if _RE_PERFIL_DESCONOCIDO.search(motivo):
            return f"{self._perfil_desconocido()} ({motivo})"
        return motivo

    @staticmethod
    def _url(datos: dict) -> str:
        for campo in ("url", "post_url", "platform_post_url", "permalink", "link"):
            valor = datos.get(campo)
            if isinstance(valor, str) and valor.startswith("http"):
                return valor
        encontrada = _RE_URL.search(str(datos.get("message", "")))
        return encontrada.group(0).rstrip(".,)") if encontrada else ""

    @classmethod
    def _texto(cls, datos: Any, profundidad: int = 0) -> str:
        """Motivo legible de una respuesta o de un resultado, aunque venga
        anidado (`{"error": {"message": ...}}`), en lista o con códigos."""
        if isinstance(datos, str):
            return " ".join(datos.split())
        if isinstance(datos, bool) or datos is None or profundidad > 4:
            return ""
        if isinstance(datos, (int, float)):
            return str(datos)
        if isinstance(datos, list):
            return cls._unir(cls._texto(v, profundidad + 1) for v in datos[:5])
        if not isinstance(datos, dict):
            return ""
        textos = [cls._texto(datos.get(campo), profundidad + 1)
                  for campo in _CAMPOS_USUARIO + _CAMPOS_MOTIVO]
        texto = cls._unir(textos)
        codigos = [f"{campo} {datos[campo]}" for campo in _CAMPOS_CODIGO
                   if isinstance(datos.get(campo), (str, int)) and not isinstance(
                       datos.get(campo), bool) and str(datos[campo]).strip()]
        if codigos and texto:
            return f"{texto} ({', '.join(codigos)})"
        return texto or ", ".join(codigos)

    @staticmethod
    def _unir(textos) -> str:
        """Junta textos sin repetir (ni los contenidos en otro ya elegido)."""
        elegidos: list[str] = []
        for texto in textos:
            if texto and not any(texto in otro for otro in elegidos):
                elegidos = [otro for otro in elegidos if otro not in texto] + [texto]
        return " · ".join(elegidos[:3])

    @staticmethod
    def _texto_plano(texto: str) -> str:
        """Texto de una respuesta que no es JSON (p. ej. la página HTML de un
        proxy), sin etiquetas y acotado."""
        texto = _RE_ETIQUETA.sub(" ", _RE_SCRIPT.sub(" ", texto or ""))
        texto = " ".join(html.unescape(texto).split())
        return texto if len(texto) <= MAX_DETALLE else texto[:MAX_DETALLE - 1] + "…"

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

    def _mensaje_http(self, respuesta: httpx.Response,
                      plataforma: Plataforma | None = None) -> str:
        codigo = respuesta.status_code
        cuerpo = self._json(respuesta)
        if isinstance(cuerpo, dict):
            # El motivo propio de la plataforma (p. ej. «fuera del plan») antes que el general.
            propio = (self._resultado_de(cuerpo.get("results"), plataforma)
                      if plataforma is not None else None)
            detalle = (self._texto(propio) if propio else "") or self._texto(cuerpo)
        elif cuerpo is None:
            detalle = self._texto_plano(respuesta.text)
        else:
            detalle = self._texto(cuerpo)
        if _RE_PERFIL_DESCONOCIDO.search(detalle):
            return self._limpiar(f"{self._perfil_desconocido()} ({codigo}: {detalle})")
        if codigo == 401:
            base = _("La API key no es válida o ha caducado (401). Revísala en Redes…")
        elif codigo == 403:
            base = _("Sin permiso o fuera del plan contratado (403).")
        elif codigo == 413:
            base = _("El vídeo es demasiado grande para el servicio (413).")
        elif codigo == 429:
            base = _("Límite de subidas del plan alcanzado (429).")
        elif codigo == 503:
            base = _("Servicio no disponible (503). Prueba más tarde.")
        else:
            base = _("Error {codigo} del servicio.").format(codigo=codigo)
        return self._limpiar(f"{base} {detalle}".strip())

    def _traza(self, excepcion: BaseException) -> str:
        """Traceback completo, sin la clave (el mensaje de la excepción podría
        llevarla: p. ej. una URL o una cabecera repetidas por la librería)."""
        return diario.limpiar("".join(traceback.format_exception(excepcion)).rstrip(),
                              [self._clave])

    def _limpiar(self, texto: str) -> str:
        """Quita la clave (por si el servicio la repite) y acota la longitud."""
        texto = diario.limpiar(texto, [self._clave])
        return texto if len(texto) <= 400 else texto[:399] + "…"

    def _error(self, plataforma: Plataforma, texto: str) -> Resultado:
        return Resultado(plataforma, ok=False, error=self._limpiar(texto))


def _verdadero(valor: Any) -> bool:
    return valor is True or str(valor).strip().lower() in ("true", "1", "yes")


def identificador_externo(plataforma: Plataforma, video: Path, tamano: int,
                          modificado: float) -> str:
    """`external_id` de un intento: huella del vídeo + plataforma + momento.
    Queda en el registro para relacionar un duplicado con su intento."""
    huella = hashlib.sha256(f"{video.name}|{tamano}|{modificado}".encode()).hexdigest()[:12]
    return (f"tsots-{_PLATAFORMAS[plataforma]}-{huella}-"
            f"{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}")


def crear(clave: str, ajustes: dict, http: httpx.Client | None = None) -> ProveedorUploadPost:
    return ProveedorUploadPost(clave, str(ajustes.get("perfil", "") or ""), http=http,
                               pagina_facebook=str(ajustes.get("pagina_facebook", "") or ""))
