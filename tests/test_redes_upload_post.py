"""Proveedor Upload-Post contra un transporte HTTP falso: nunca sale a la red."""
from __future__ import annotations

from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path

import httpx
import pytest

from videopipeline.redes import publicador, upload_post
from videopipeline.redes.modelo import (
    Cuenta,
    ModoFacebook,
    ModoInstagram,
    ModoTikTok,
    Opciones,
    Pagina,
    Plataforma,
    Publicacion,
)
from videopipeline.redes.proveedor import ErrorConsulta
from videopipeline.redes.textos import longitud_x

CLAVE = "clave-secreta-123"


def _formulario(request: httpx.Request) -> tuple[dict[str, list[str]], dict[str, tuple[str, bytes]]]:
    cuerpo = request.read()
    cabecera = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
    mensaje = BytesParser(policy=HTTP).parsebytes(cabecera + cuerpo)
    campos: dict[str, list[str]] = {}
    ficheros: dict[str, tuple[str, bytes]] = {}
    for parte in mensaje.iter_parts():
        nombre = parte.get_param("name", header="content-disposition")
        datos = parte.get_payload(decode=True)
        if parte.get_filename():
            ficheros[nombre] = (parte.get_filename(), datos)
        else:
            campos.setdefault(nombre, []).append(datos.decode("utf-8"))
    return campos, ficheros


class Servidor:
    """Transporte falso que registra peticiones y responde con una función."""

    def __init__(self, responder):
        self.peticiones: list[httpx.Request] = []
        self.formularios: list[dict[str, list[str]]] = []
        self.ficheros: list[dict[str, tuple[str, bytes]]] = []
        self._responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.peticiones.append(request)
        if request.method == "POST":
            campos, ficheros = _formulario(request)
            self.formularios.append(campos)
            self.ficheros.append(ficheros)
        return self._responder(request, self)

    def cliente(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def _ok_sync(request, servidor):
    plataforma = servidor.formularios[-1]["platform[]"][0]
    return httpx.Response(200, json={
        "success": True,
        "results": {plataforma: {"success": True, "url": f"https://{plataforma}.example/v/1",
                                 "post_id": "1"}},
        "usage": {"count": 3, "limit": 10},
    })


@pytest.fixture
def video(tmp_path) -> Path:
    ruta = tmp_path / "clip_limpio.mp4"
    ruta.write_bytes(b"MP4DATA")
    return ruta


def _pub(video: Path) -> Publicacion:
    return Publicacion(video=video, titulo="Cómo usar IA en tu pyme",
                       caption="Tres ideas clave.", hashtags=("#ia", "#pymes"),
                       palabras_clave=("ia", "pymes", "automatización"))


def _proveedor(servidor: Servidor, esperas=None, perfil="mi_perfil", pagina="1234567890"):
    return upload_post.ProveedorUploadPost(
        CLAVE, perfil, http=servidor.cliente(),
        espera=(esperas.append if esperas is not None else (lambda s: None)),
        pagina_facebook=pagina)


def test_tiktok_borrador_campos_cabecera_y_video(video):
    servidor = Servidor(_ok_sync)
    r = _proveedor(servidor).publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert r.ok and r.url == "https://tiktok.example/v/1"
    peticion = servidor.peticiones[0]
    assert str(peticion.url) == "https://api.upload-post.com/api/upload"
    assert peticion.headers["authorization"] == f"Apikey {CLAVE}"
    campos = servidor.formularios[0]
    assert campos["user"] == ["mi_perfil"]
    assert campos["platform[]"] == ["tiktok"]
    assert campos["post_mode"] == ["MEDIA_UPLOAD"]
    assert "privacy_level" not in campos
    assert campos["tiktok_title"] == ["Tres ideas clave.\n\n#ia #pymes"]
    assert campos["is_aigc"] == ["false"]
    assert servidor.ficheros[0]["video"] == ("clip_limpio.mp4", b"MP4DATA")
    assert r.extra == {"uso": "3/10"}


def test_tiktok_publico(video):
    servidor = Servidor(_ok_sync)
    _proveedor(servidor).publicar(Plataforma.TIKTOK, _pub(video),
                                  Opciones(tiktok_modo=ModoTikTok.PUBLICO))
    campos = servidor.formularios[0]
    assert campos["post_mode"] == ["DIRECT_POST"]
    assert campos["privacy_level"] == ["PUBLIC_TO_EVERYONE"]


def test_youtube_short_publico_con_tags_y_categoria(video):
    servidor = Servidor(_ok_sync)
    r = _proveedor(servidor).publicar(Plataforma.YOUTUBE, _pub(video),
                                      Opciones(youtube_categoria="28"))
    assert r.ok
    campos = servidor.formularios[0]
    assert campos["platform[]"] == ["youtube"]
    assert campos["title"] == ["Cómo usar IA en tu pyme"]
    assert campos["youtube_title"] == ["Cómo usar IA en tu pyme"]
    assert campos["youtube_description"] == ["Tres ideas clave.\n\n#ia #pymes"]
    assert campos["tags[]"] == ["ia", "pymes", "automatización"]
    assert campos["categoryId"] == ["28"]
    assert campos["privacyStatus"] == ["public"]
    assert campos["containsSyntheticMedia"] == ["false"]


def test_instagram_reel_de_prueba_por_defecto(video):
    servidor = Servidor(_ok_sync)
    _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())
    campos = servidor.formularios[0]
    assert campos["platform[]"] == ["instagram"]
    assert campos["media_type"] == ["REELS"]
    assert campos["share_mode"] == ["TRIAL_REELS_SHARE_TO_FOLLOWERS_IF_LIKED"]
    assert "share_to_feed" not in campos
    assert campos["instagram_title"] == ["Tres ideas clave.\n\n#ia #pymes"]
    assert campos["is_ai_generated"] == ["false"]


def test_instagram_reel_normal(video):
    servidor = Servidor(_ok_sync)
    _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video),
                                  Opciones(instagram_modo=ModoInstagram.NORMAL))
    campos = servidor.formularios[0]
    assert campos["share_mode"] == ["CUSTOM"]
    assert campos["share_to_feed"] == ["true"]


def test_resultado_de_plataforma_fallido(video):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "success": True, "results": {"instagram": {"success": False,
                                                   "error": "Expired access token"}}}))
    r = _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())
    assert not r.ok and not r.pendiente
    assert "Expired access token" in r.error


def test_asincrono_request_id_y_sondeo_hasta_terminar(video):
    estados = iter([
        {"request_id": "req-1", "status": "pending", "completed": 0, "total": 1},
        {"request_id": "req-1", "status": "in_progress", "results": []},
        {"request_id": "req-1", "status": "completed", "completed": 1, "total": 1,
         "results": [{"platform": "tiktok", "success": True,
                      "message": "Publicado en https://www.tiktok.com/@yo/video/9."}]},
    ])

    def responder(request, servidor):
        if request.method == "POST":
            return httpx.Response(200, json={"success": True, "request_id": "req-1",
                                             "total_platforms": 1})
        assert str(request.url).startswith("https://api.upload-post.com/api/uploadposts/status")
        assert request.url.params["request_id"] == "req-1"
        assert request.headers["authorization"] == f"Apikey {CLAVE}"
        return httpx.Response(200, json=next(estados))

    proveedor = _proveedor(Servidor(responder))
    r = proveedor.publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert r.pendiente and r.referencia == "req-1" and not r.ok
    esperas: list[float] = []
    final = publicador.publicar(
        proveedor, _pub(video), Opciones(), [Plataforma.TIKTOK], registrar=False,
        espera=esperas.append, intervalo=1.0)
    assert final[Plataforma.TIKTOK].ok
    assert final[Plataforma.TIKTOK].url == "https://www.tiktok.com/@yo/video/9"
    assert len(esperas) == 3


def test_estado_resultados_como_diccionario_y_fallo(video):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "status": "completed", "results": {"youtube": {"success": False,
                                                       "message": "quota"}}}))
    r = _proveedor(servidor).estado(Plataforma.YOUTUBE, "req-9")
    assert not r.ok and not r.pendiente and "quota" in r.error


def test_estado_completado_sin_resultado_queda_por_confirmar():
    """Sin resultado no hay fallo explícito: nunca un error rotundo."""
    servidor = Servidor(lambda req, s: httpx.Response(200, json={"status": "completed",
                                                                 "results": []}))
    r = _proveedor(servidor).estado(Plataforma.INSTAGRAM, "req-9")
    assert not r.ok and r.pendiente and r.referencia == ""  # nada más que consultar
    assert "Instagram" in r.error and "antes de volver a publicar" in r.error


def test_estado_fallido_sin_resultados_es_error():
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "status": "failed", "message": "Upload rejected by platform"}))
    r = _proveedor(servidor).estado(Plataforma.INSTAGRAM, "req-9")
    assert not r.ok and not r.pendiente and "Upload rejected by platform" in r.error


def test_estado_forma_desconocida_sigue_pendiente():
    servidor = Servidor(lambda req, s: httpx.Response(200, json={"foo": "bar"}))
    r = _proveedor(servidor).estado(Plataforma.TIKTOK, "req-9")
    assert r.pendiente and r.referencia == "req-9"


@pytest.mark.parametrize("codigo, texto", [
    (400, "400"), (401, "401"), (403, "403"), (429, "429"),
])
def test_errores_http_no_llevan_la_clave(video, codigo, texto):
    servidor = Servidor(lambda req, s: httpx.Response(
        codigo, json={"success": False, "message": f"mal: {CLAVE}"}))
    r = _proveedor(servidor).publicar(Plataforma.YOUTUBE, _pub(video), Opciones())
    assert not r.ok and texto in r.error
    assert CLAVE not in r.error
    assert len(servidor.peticiones) == 1  # sin reintentos


# --- la subida NUNCA se repite sola: un clic, un POST ---


@pytest.mark.parametrize("codigo", [500, 502, 503, 504])
def test_5xx_en_la_subida_no_reintenta_y_queda_por_confirmar(video, codigo):
    """Un 5xx tras enviar 287 MB puede llegar cuando el servicio ya aceptó el
    vídeo: repetir el POST lo publicaría dos o tres veces."""
    esperas: list[float] = []
    servidor = Servidor(lambda req, s: httpx.Response(codigo, text="gateway timeout"))
    r = _proveedor(servidor, esperas).publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert len([p for p in servidor.peticiones if p.method == "POST"]) == 1
    assert len(servidor.peticiones) == 1 and esperas == []
    assert not r.ok and r.pendiente and r.referencia == ""
    assert str(codigo) in r.error
    assert "Revisa TikTok antes de volver a publicar" in r.error


@pytest.mark.parametrize("excepcion", [httpx.ReadTimeout, httpx.ReadError,
                                       httpx.RemoteProtocolError])
def test_sin_respuesta_tras_enviar_no_reintenta_y_queda_por_confirmar(video, excepcion):
    def responder(request, servidor):
        raise excepcion("sin respuesta", request=request)

    servidor = Servidor(responder)
    r = _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())
    assert len(servidor.peticiones) == 1
    assert not r.ok and r.pendiente and excepcion.__name__ in r.error
    assert "Revisa Instagram antes de volver a publicar" in r.error


@pytest.mark.parametrize("excepcion", [httpx.ConnectError, httpx.ConnectTimeout,
                                       httpx.WriteTimeout, httpx.WriteError])
def test_si_el_video_no_llego_entero_es_error(video, excepcion):
    def responder(request, servidor):
        raise excepcion("cortado", request=request)

    servidor = Servidor(responder)
    r = _proveedor(servidor).publicar(Plataforma.YOUTUBE, _pub(video), Opciones())
    assert len(servidor.peticiones) == 1
    assert not r.ok and not r.pendiente and excepcion.__name__ in r.error


def test_la_consulta_de_estado_si_reintenta_el_503():
    respuestas = iter([httpx.Response(503), httpx.Response(200, json={
        "status": "completed", "results": [{"platform": "tiktok", "success": True,
                                            "url": "https://tt/1"}]})])
    esperas: list[float] = []
    servidor = Servidor(lambda req, s: next(respuestas))
    r = _proveedor(servidor, esperas).estado(Plataforma.TIKTOK, "req-1")
    assert r.ok and len(servidor.peticiones) == 2
    assert all(p.method == "GET" for p in servidor.peticiones)
    assert esperas == [upload_post.ESPERAS_503[0]]


def test_subida_asincrona_con_external_id_registrado(video, tmp_path, monkeypatch):
    from videopipeline.redes import diario

    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "success": True, "request_id": "req-1"}))
    monkeypatch.setattr(diario, "DIR_LOGS", tmp_path / "logs")
    d = diario.Diario(video)
    try:
        r = _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())
    finally:
        d.cerrar()
    campos = servidor.formularios[0]
    assert campos["async_upload"] == ["true"]
    [externo] = campos["external_id"]
    assert externo.startswith("tsots-instagram-")
    assert r.pendiente and r.referencia == "req-1"
    assert externo in d.ruta.read_text(encoding="utf-8")
    # Otro intento lleva otro identificador.
    _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())
    assert servidor.formularios[1]["external_id"] != [externo]


def test_error_401_en_youtube_no_impide_instagram(video):
    def responder(request, servidor):
        if servidor.formularios[-1]["platform[]"] == ["youtube"]:
            return httpx.Response(401, json={"success": False,
                                             "message": "Invalid or expired token"})
        return _ok_sync(request, servidor)

    servidor = Servidor(responder)
    resultados = publicador.publicar(
        _proveedor(servidor), _pub(video), Opciones(), list(Plataforma), registrar=False)
    assert [p for p in resultados] == [Plataforma.TIKTOK, Plataforma.YOUTUBE,
                                       Plataforma.INSTAGRAM, Plataforma.X,
                                       Plataforma.FACEBOOK]
    assert resultados[Plataforma.TIKTOK].ok
    assert not resultados[Plataforma.YOUTUBE].ok
    assert "401" in resultados[Plataforma.YOUTUBE].error
    assert resultados[Plataforma.INSTAGRAM].ok
    assert [f["platform[]"][0] for f in servidor.formularios] == [
        "tiktok", "youtube", "instagram", "x", "facebook"]


def test_error_de_red_no_lanza(video):
    def responder(request, servidor):
        raise httpx.ConnectError("sin red", request=request)

    r = _proveedor(Servidor(responder)).publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert not r.ok and "ConnectError" in r.error


def test_sin_video_o_sin_perfil_no_envia_nada(tmp_path, video):
    servidor = Servidor(_ok_sync)
    r = _proveedor(servidor).publicar(
        Plataforma.TIKTOK, _pub(tmp_path / "no.mp4"), Opciones())
    assert not r.ok and "no.mp4" in r.error
    r = _proveedor(servidor, perfil=" ").publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert not r.ok and "perfil" in r.error.lower()
    assert servidor.peticiones == []


def test_repr_y_crear_no_muestran_la_clave():
    proveedor = upload_post.crear(CLAVE, {"perfil": "yo"})
    assert CLAVE not in repr(proveedor)
    assert CLAVE not in str(proveedor)
    assert proveedor.nombre == "Upload-Post"


# --- vídeos grandes: tiempos de espera ---


def test_tiempos_crecen_con_el_tamano_del_video():
    pequeno = upload_post.tiempos(10 * 1024 * 1024)
    grande = upload_post.tiempos(287 * 1024 * 1024)
    # 287 MB por una conexión doméstica tarda minutos: ninguna espera corta.
    assert pequeno.write >= 600 and grande.write >= 1200
    assert grande.write > pequeno.write
    assert grande.read >= 300 and grande.connect >= 30


def test_la_subida_usa_tiempos_segun_el_tamano(video):
    servidor = Servidor(_ok_sync)
    _proveedor(servidor).publicar(Plataforma.YOUTUBE, _pub(video), Opciones())
    tiempos = servidor.peticiones[0].extensions["timeout"]
    esperado = upload_post.tiempos(video.stat().st_size)
    assert tiempos["write"] == esperado.write and tiempos["read"] == esperado.read


# --- errores legibles ---


def test_413_video_demasiado_grande(video):
    servidor = Servidor(lambda req, s: httpx.Response(
        413, text="<html><body><h1>413 Request Entity Too Large</h1></body></html>"))
    r = _proveedor(servidor).publicar(Plataforma.YOUTUBE, _pub(video), Opciones())
    assert not r.ok and "413" in r.error and "grande" in r.error
    assert "<h1>" not in r.error


def test_error_http_sin_json_muestra_el_texto_sin_html(video):
    servidor = Servidor(lambda req, s: httpx.Response(
        502, text="<html><title>Bad gateway</title><p>upstream timed out</p></html>"))
    r = _proveedor(servidor).publicar(Plataforma.YOUTUBE, _pub(video), Opciones())
    assert not r.ok and "502" in r.error and "upstream timed out" in r.error
    assert "<p>" not in r.error


def test_success_false_sin_resultados_muestra_el_motivo(video):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "success": False, "message": "Profile mi_perfil not found"}))
    r = _proveedor(servidor).publicar(Plataforma.YOUTUBE, _pub(video), Opciones())
    assert not r.ok and "Profile mi_perfil not found" in r.error


def test_tiktok_fuera_del_plan_en_results_con_error_anidado(video):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "success": False,
        "results": {"tiktok": {"success": False, "error": {
            "code": "PLAN_LIMIT", "message": "TikTok is not included in your plan"}}}}))
    r = _proveedor(servidor).publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert not r.ok and not r.pendiente
    assert "TikTok is not included in your plan" in r.error


def test_4xx_con_resultado_de_la_plataforma_usa_su_motivo(video):
    servidor = Servidor(lambda req, s: httpx.Response(403, json={
        "success": False, "message": "Some platforms failed",
        "results": {"tiktok": {"success": False,
                               "message": "Platform not available on the free plan"}}}))
    r = _proveedor(servidor).publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert not r.ok and "403" in r.error
    assert "Platform not available on the free plan" in r.error


def test_detalle_en_lista_estilo_fastapi(video):
    servidor = Servidor(lambda req, s: httpx.Response(422, json={
        "detail": [{"loc": ["body", "user"], "msg": "field required"}]}))
    r = _proveedor(servidor).publicar(Plataforma.YOUTUBE, _pub(video), Opciones())
    assert not r.ok and "422" in r.error and "field required" in r.error


def test_exito_sin_resultado_de_la_plataforma_lo_dice(video):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "success": True, "results": {"youtube": {"success": True, "url": "https://y/1"}},
        "message": "tiktok skipped: not in plan"}))
    r = _proveedor(servidor).publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert not r.ok and "TikTok" in r.error and "not in plan" in r.error


def test_success_como_texto_false_en_results(video):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "results": {"instagram": {"success": "false", "message": "Media too long"}}}))
    r = _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())
    assert not r.ok and "Media too long" in r.error


# --- registro de diagnóstico ---


def test_registra_peticiones_respuestas_y_sondeos_sin_la_clave(video, tmp_path, monkeypatch):
    from videopipeline.redes import diario

    estados = iter([
        {"status": "in_progress", "results": []},
        {"status": "completed", "results": [
            {"platform": "youtube", "success": True, "url": "https://youtu.be/xyz"}]},
    ])

    def responder(request, servidor):
        if request.method == "POST":
            return httpx.Response(200, json={"success": True, "request_id": "req-77",
                                             "eco": f"Apikey {CLAVE}"})
        return httpx.Response(200, json=next(estados))

    monkeypatch.setattr(diario, "DIR_LOGS", tmp_path / "logs")
    d = diario.Diario(video)
    try:
        final = publicador.publicar(
            _proveedor(Servidor(responder)), _pub(video), Opciones(), [Plataforma.YOUTUBE],
            registrar=False, espera=lambda s: None, intervalo=1.0)
    finally:
        d.cerrar()
    assert final[Plataforma.YOUTUBE].ok
    texto = d.ruta.read_text(encoding="utf-8")
    assert CLAVE not in texto
    assert "POST https://api.upload-post.com/api/upload" in texto
    assert "HTTP 200" in texto
    assert "req-77" in texto
    assert texto.count("request_id=req-77") >= 2  # cada sondeo
    assert "in_progress" in texto and "completed" in texto
    assert str(video.stat().st_size) in texto
    assert "mi_perfil" not in texto  # el perfil no se escribe en el log


def test_registra_fallo_de_red_con_su_tipo(video, tmp_path, monkeypatch):
    from videopipeline.redes import diario

    def responder(request, servidor):
        raise httpx.WriteTimeout(f"timed out {CLAVE}", request=request)

    monkeypatch.setattr(diario, "DIR_LOGS", tmp_path / "logs")
    d = diario.Diario(video)
    try:
        r = _proveedor(Servidor(responder)).publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    finally:
        d.cerrar()
    assert not r.ok and "WriteTimeout" in r.error
    texto = d.ruta.read_text(encoding="utf-8")
    assert "WriteTimeout" in texto and CLAVE not in texto


# --- perfil equivocado (p. ej. el email de la cuenta) ---


@pytest.mark.parametrize("codigo, cuerpo", [
    (400, {"success": False, "message": "Username not associated with any profile"}),
    (200, {"success": False, "error": "Username not associated with any profile"}),
    (200, {"results": {"youtube": {"success": False,
                                   "error": "Username not associated with any profile"}}}),
])
def test_perfil_inexistente_explica_que_usar(video, codigo, cuerpo):
    servidor = Servidor(lambda req, s: httpx.Response(codigo, json=cuerpo))
    r = upload_post.ProveedorUploadPost(
        CLAVE, "yo@example.com", http=servidor.cliente()).publicar(
        Plataforma.YOUTUBE, _pub(video), Opciones())
    assert not r.ok
    assert "El perfil «yo@example.com» no existe en Upload-Post" in r.error
    assert "Manage Users" in r.error and "email" in r.error
    assert "Username not associated with any profile" in r.error  # el original, para diagnosticar


def test_ayuda_del_perfil_viene_del_proveedor():
    from videopipeline.redes import proveedor

    ayuda = proveedor.ayuda_perfil("upload_post")
    assert "Manage Users" in ayuda and "email" in ayuda


# --- motivos anidados (p. ej. Instagram / Meta) ---


@pytest.mark.parametrize("resultado, esperados", [
    # Error de Meta tal cual: mensaje para el usuario primero, y sus códigos.
    ({"success": False, "error": {
        "message": "Invalid parameter", "type": "OAuthException", "code": 100,
        "error_subcode": 2207026, "error_user_title": "Unsupported format",
        "error_user_msg": "The video format is not supported. Please check the specs."}},
     ["The video format is not supported", "Invalid parameter", "100", "2207026"]),
    ({"success": False, "error_message": "Reel duration must be between 3 and 90 s"},
     ["Reel duration must be between 3 and 90 s"]),
    ({"success": False, "reason": "Account is not a professional account"},
     ["Account is not a professional account"]),
    ({"success": False, "details": [{"message": "Media upload timed out"},
                                    {"message": "Container status ERROR"}]},
     ["Media upload timed out", "Container status ERROR"]),
    ({"success": False, "errors": ["Trial reels not available for this account"]},
     ["Trial reels not available for this account"]),
    ({"success": False, "message": "Instagram upload failed",
      "error": {"error": {"message": "(#9004) The media could not be fetched",
                          "code": 9004, "error_subcode": 2207052}}},
     ["Instagram upload failed", "The media could not be fetched", "2207052"]),
])
def test_motivo_anidado_de_instagram_no_se_pierde(video, resultado, esperados):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "success": False, "results": {"instagram": resultado}}))
    r = _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())
    assert not r.ok
    assert "rechazó la publicación" not in r.error
    for texto in esperados:
        assert texto in r.error, (texto, r.error)
    assert len(r.error) <= 400


def test_motivo_anidado_en_la_consulta_de_estado():
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "status": "completed", "results": [{"platform": "instagram", "success": False,
                                            "error": {"error_user_msg": "Aspect ratio not supported",
                                                      "code": 36003}}]}))
    r = _proveedor(servidor).estado(Plataforma.INSTAGRAM, "req-1")
    assert not r.ok and "Aspect ratio not supported" in r.error and "36003" in r.error


def test_motivo_largo_se_acota_y_no_lleva_la_clave(video):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={"results": {"instagram": {
        "success": False, "error": {"message": ("x" * 900) + f" {CLAVE}"}}}}))
    r = _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())
    assert len(r.error) <= 400 and CLAVE not in r.error


def test_el_resultado_crudo_de_la_plataforma_va_al_registro(video, tmp_path, monkeypatch):
    from videopipeline.redes import diario

    servidor = Servidor(lambda req, s: httpx.Response(200, json={"results": {"instagram": {
        "success": False, "error": {"error_user_msg": "Formato no válido", "code": 352,
                                    "fbtrace_id": "AbC", "token": CLAVE}}}}))
    monkeypatch.setattr(diario, "DIR_LOGS", tmp_path / "logs")
    d = diario.Diario(video)
    try:
        _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())
    finally:
        d.cerrar()
    texto = d.ruta.read_text(encoding="utf-8")
    assert "Instagram: resultado del servicio:" in texto
    assert "fbtrace_id" in texto and "352" in texto
    assert CLAVE not in texto


# --- resultados en curso o ambiguos: nunca un falso «rechazó» ---


def _publicar_instagram(video, cuerpo):
    servidor = Servidor(lambda req, s: httpx.Response(200, json=cuerpo))
    return _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())


@pytest.mark.parametrize("propio", [
    {"success": False, "status": "IN_PROGRESS"},
    {"success": None, "status": "processing"},
    {"status": "queued"},
    {"success": False, "message": "Your reel is being processed"},
])
def test_instagram_en_curso_con_request_id_se_consulta(video, propio):
    r = _publicar_instagram(video, {"success": True, "request_id": "req-5",
                                    "results": {"instagram": propio}})
    assert not r.ok and r.pendiente and r.referencia == "req-5"
    assert "rechazó" not in r.error


def test_instagram_en_curso_con_id_propio(video):
    r = _publicar_instagram(video, {"results": {"instagram": {
        "success": False, "status": "pending", "job_id": "job-1"}}})
    assert r.pendiente and r.referencia == "job-1"


@pytest.mark.parametrize("propio", [
    {"success": False},
    {"success": None},
    {},
    {"status": "unknown_state"},
])
def test_instagram_ambiguo_sin_referencia_queda_por_confirmar(video, propio):
    r = _publicar_instagram(video, {"success": True, "results": {"instagram": propio}})
    assert not r.ok and r.pendiente and r.referencia == ""
    assert "rechazó" not in r.error
    assert "Revisa Instagram" in r.error and "antes de volver a publicar" in r.error


@pytest.mark.parametrize("propio, texto", [
    ({"success": False, "status": "failed", "error": "Media fetch failed"}, "Media fetch failed"),
    ({"success": False, "error": "Invalid access token"}, "Invalid access token"),
    ({"status": "error", "message": "Container status ERROR"}, "Container status ERROR"),
])
def test_instagram_fallo_explicito_es_error(video, propio, texto):
    r = _publicar_instagram(video, {"success": False, "results": {"instagram": propio}})
    assert not r.ok and not r.pendiente and texto in r.error


def test_estado_instagram_aun_procesando_sigue_pendiente():
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "status": "completed", "results": [
            {"platform": "instagram", "success": False, "status": "processing"}]}))
    r = _proveedor(servidor).estado(Plataforma.INSTAGRAM, "req-9")
    assert r.pendiente and r.referencia == "req-9"


def test_exito_sin_resultado_de_la_plataforma_queda_por_confirmar(video):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "success": True, "results": {"youtube": {"success": True, "url": "https://y/1"}}}))
    r = _proveedor(servidor).publicar(Plataforma.INSTAGRAM, _pub(video), Opciones())
    assert not r.ok and r.pendiente and "antes de volver a publicar" in r.error


# --- X ---


def test_x_campos_con_texto_corto(video):
    servidor = Servidor(_ok_sync)
    r = _proveedor(servidor).publicar(Plataforma.X, _pub(video), Opciones())
    assert r.ok and r.url == "https://x.example/v/1"
    campos = servidor.formularios[0]
    assert campos["platform[]"] == ["x"]
    assert campos["x_title"] == ["Cómo usar IA en tu pyme\n\n#ia #pymes"]
    assert campos["x_long_text_as_post"] == ["false"]
    assert campos["made_with_ai"] == ["false"]
    assert campos["async_upload"] == ["true"]
    # Nada de subtítulos por URL pública ni campos que no se usan.
    for campo in ("x_subtitles_url", "reply_settings", "nullcast", "community_id",
                  "x_paid_partnership", "x_alt_text"):
        assert campo not in campos


def test_x_texto_propio_largo_sin_premium_se_recorta_a_280(video):
    servidor = Servidor(_ok_sync)
    pub = Publicacion(video=video, titulo="t", caption="c", texto_x="frase " * 80)
    _proveedor(servidor).publicar(Plataforma.X, pub, Opciones())
    campos = servidor.formularios[0]
    assert longitud_x(campos["x_title"][0]) <= 280
    assert campos["x_long_text_as_post"] == ["false"]


def test_x_con_premium_y_texto_largo_va_en_un_solo_post(video):
    servidor = Servidor(_ok_sync)
    largo = "frase " * 80
    pub = Publicacion(video=video, titulo="t", caption="c", texto_x=largo)
    _proveedor(servidor).publicar(Plataforma.X, pub, Opciones(x_premium=True))
    campos = servidor.formularios[0]
    assert campos["x_title"] == [largo.strip()]
    assert campos["x_long_text_as_post"] == ["true"]


def test_x_con_premium_y_texto_corto_no_pide_post_largo(video):
    servidor = Servidor(_ok_sync)
    _proveedor(servidor).publicar(Plataforma.X, _pub(video), Opciones(x_premium=True))
    assert servidor.formularios[0]["x_long_text_as_post"] == ["false"]


def test_x_resultado_como_twitter_tambien_vale(video):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "success": True, "results": {"twitter": {"success": True,
                                                 "url": "https://x.com/yo/status/1"}}}))
    r = _proveedor(servidor).publicar(Plataforma.X, _pub(video), Opciones())
    assert r.ok and r.url == "https://x.com/yo/status/1"


def test_x_fuera_del_plan_se_lee(video):
    servidor = Servidor(lambda req, s: httpx.Response(403, json={
        "success": False, "message": "X is not available on the free plan"}))
    r = _proveedor(servidor).publicar(Plataforma.X, _pub(video), Opciones())
    assert not r.ok and not r.pendiente
    assert "403" in r.error and "free plan" in r.error


def test_x_asincrono_se_sondea(video):
    def responder(request, servidor):
        if request.method == "POST":
            return httpx.Response(200, json={"success": True, "request_id": "req-x"})
        return httpx.Response(200, json={"status": "completed", "results": [
            {"platform": "x", "success": True, "url": "https://x.com/yo/status/2"}]})
    servidor = Servidor(responder)
    resultados = publicador.publicar(
        _proveedor(servidor), _pub(video), Opciones(), [Plataforma.X],
        registrar=False, espera=lambda s: None)
    assert resultados[Plataforma.X].ok
    assert resultados[Plataforma.X].url == "https://x.com/yo/status/2"


# --- Facebook ---


@pytest.mark.parametrize("modo, tipo, estado", [
    (ModoFacebook.REEL, "REELS", "PUBLISHED"),
    (ModoFacebook.VIDEO, "VIDEO", "PUBLISHED"),
    (ModoFacebook.BORRADOR, "REELS", "DRAFT"),
])
def test_facebook_campos_por_modo(video, modo, tipo, estado):
    servidor = Servidor(_ok_sync)
    r = _proveedor(servidor).publicar(Plataforma.FACEBOOK, _pub(video),
                                      Opciones(facebook_modo=modo))
    assert r.ok
    campos = servidor.formularios[0]
    assert campos["platform[]"] == ["facebook"]
    assert campos["facebook_page_id"] == ["1234567890"]
    assert campos["facebook_title"] == ["Cómo usar IA en tu pyme"]
    assert campos["facebook_description"] == ["Tres ideas clave.\n\n#ia #pymes"]
    assert campos["facebook_media_type"] == [tipo]
    assert campos["video_state"] == [estado]
    assert campos["facebook_is_ai_generated"] == ["false"]


def test_facebook_por_defecto_es_reel_publicado(video):
    servidor = Servidor(_ok_sync)
    _proveedor(servidor).publicar(Plataforma.FACEBOOK, _pub(video), Opciones())
    campos = servidor.formularios[0]
    assert campos["facebook_media_type"] == ["REELS"]
    assert campos["video_state"] == ["PUBLISHED"]


def test_facebook_sin_pagina_no_envia_nada(video):
    servidor = Servidor(_ok_sync)
    r = _proveedor(servidor, pagina=" ").publicar(Plataforma.FACEBOOK, _pub(video), Opciones())
    assert not r.ok and not r.pendiente
    assert "página de Facebook" in r.error
    assert servidor.peticiones == []
    # Las demás plataformas no la necesitan.
    r = _proveedor(servidor, pagina="").publicar(Plataforma.TIKTOK, _pub(video), Opciones())
    assert r.ok


def test_crear_lee_la_pagina_de_los_ajustes_neutros(video):
    servidor = Servidor(_ok_sync)
    proveedor = upload_post.crear(CLAVE, {"perfil": "yo", "pagina_facebook": " 987 "},
                                  http=servidor.cliente())
    proveedor.publicar(Plataforma.FACEBOOK, _pub(video), Opciones())
    assert servidor.formularios[0]["facebook_page_id"] == ["987"]


def test_facebook_error_de_la_plataforma(video):
    servidor = Servidor(lambda req, s: httpx.Response(200, json={
        "success": True, "results": {"facebook": {
            "success": False, "error": {"message": "(#200) Page publishing not allowed"}}}}))
    r = _proveedor(servidor).publicar(Plataforma.FACEBOOK, _pub(video), Opciones())
    assert not r.ok and "Page publishing not allowed" in r.error


# --- cuentas conectadas y páginas de Facebook ---


def _cuentas_json(**cuentas):
    base = {"tiktok": None, "youtube": "", "instagram": None, "x": None, "facebook": None}
    base.update(cuentas)
    return base


def _responder_json(cuerpo, codigo=200):
    return lambda request, servidor: httpx.Response(codigo, json=cuerpo)


@pytest.mark.parametrize("envoltorio", [
    lambda sa: {"success": True, "profile": {"username": "mi_perfil", "social_accounts": sa}},
    lambda sa: {"username": "mi_perfil", "social_accounts": sa},
    lambda sa: {"success": True, "data": {"profile": {"social_accounts": sa}}},
])
def test_cuentas_formas_de_respuesta(envoltorio):
    sa = _cuentas_json(
        tiktok={"display_name": "Mi TikTok", "handle": "@yo_tt", "username": "yo_tt",
                "social_images": "https://img", "reauth_required": False,
                "capabilities": ["video"]},
        instagram={"display_name": "Insta", "username": "yo_ig", "reauth_required": True},
        x={"display_name": "Yo en X", "handle": "yo_x", "reauth_required": "false",
           "capabilities": ["post", "long_video_upload"]},
        facebook={"display_name": "Mi página", "reauth_required": False})
    servidor = Servidor(_responder_json(envoltorio(sa)))
    cuentas = _proveedor(servidor).cuentas()
    peticion = servidor.peticiones[0]
    assert peticion.method == "GET"
    assert str(peticion.url) == "https://api.upload-post.com/api/uploadposts/users/mi_perfil"
    assert peticion.headers["authorization"] == f"Apikey {CLAVE}"
    assert set(cuentas) == set(Plataforma)
    assert cuentas[Plataforma.TIKTOK] == Cuenta(
        Plataforma.TIKTOK, nombre="Mi TikTok", usuario="yo_tt", capacidades=("video",))
    assert cuentas[Plataforma.YOUTUBE] is None  # "" = no conectada
    assert cuentas[Plataforma.INSTAGRAM].reconectar is True
    assert cuentas[Plataforma.INSTAGRAM].visible == "@yo_ig"
    assert cuentas[Plataforma.X].reconectar is False
    assert cuentas[Plataforma.X].premium is True  # capacidad de vídeo largo
    assert cuentas[Plataforma.FACEBOOK].visible == "Mi página"
    assert cuentas[Plataforma.FACEBOOK].premium is None


def test_cuentas_x_sin_capacidad_clara_no_decide_premium():
    sa = _cuentas_json(x={"handle": "yo", "capabilities": ["post", "video"]})
    cuentas = _proveedor(Servidor(_responder_json({"social_accounts": sa}))).cuentas()
    assert cuentas[Plataforma.X].premium is None


def test_cuentas_twitter_como_x_y_plataformas_ausentes():
    cuerpo = {"profile": {"social_accounts": {"twitter": {"username": "yo"}}}}
    cuentas = _proveedor(Servidor(_responder_json(cuerpo))).cuentas()
    assert cuentas[Plataforma.X].usuario == "yo"
    assert cuentas[Plataforma.TIKTOK] is None and cuentas[Plataforma.FACEBOOK] is None


def test_cuentas_perfil_con_caracteres_raros_va_codificado():
    servidor = Servidor(_responder_json({"social_accounts": {}}))
    _proveedor(servidor, perfil="mi perfil/1").cuentas()
    assert servidor.peticiones[0].url.raw_path.endswith(b"/users/mi%20perfil%2F1")


@pytest.mark.parametrize("codigo, cuerpo, texto", [
    (401, {"message": "Invalid API key"}, "API key"),
    (404, {"message": "User not found"}, "Manage Users"),
    (500, {"message": f"boom {CLAVE}"}, "500"),
    (200, {"success": True}, "inesperada"),
])
def test_cuentas_errores_legibles_y_sin_clave(codigo, cuerpo, texto):
    servidor = Servidor(_responder_json(cuerpo, codigo))
    with pytest.raises(ErrorConsulta) as error:
        _proveedor(servidor).cuentas()
    assert texto in str(error.value)
    assert CLAVE not in str(error.value)


def test_cuentas_sin_red_o_sin_perfil():
    def sin_red(request, servidor):
        raise httpx.ConnectError("sin red", request=request)
    with pytest.raises(ErrorConsulta):
        _proveedor(Servidor(sin_red)).cuentas()
    servidor = Servidor(_responder_json({}))
    with pytest.raises(ErrorConsulta) as error:
        _proveedor(servidor, perfil="").cuentas()
    assert "perfil" in str(error.value)
    assert servidor.peticiones == []


@pytest.mark.parametrize("cuerpo", [
    [{"page_id": "111", "page_name": "Uno", "profile": "mi_perfil"},
     {"page_id": "222", "page_name": "Dos", "profile": "mi_perfil"}],
    {"pages": [{"page_id": "111", "page_name": "Uno"}, {"id": 222, "name": "Dos"}]},
    {"success": True, "profile": "mi_perfil",
     "pages": [{"page_id": "111", "page_name": "Uno"}, {"page_id": "222", "page_name": "Dos"}]},
    {"data": [{"page_id": "111", "page_name": "Uno"}, {"page_id": "222", "page_name": "Dos"},
              {"page_name": "sin id"}]},
])
def test_paginas_facebook_formas_de_respuesta(cuerpo):
    servidor = Servidor(_responder_json(cuerpo))
    paginas = _proveedor(servidor).paginas_facebook()
    assert paginas == [Pagina("111", "Uno"), Pagina("222", "Dos")]
    peticion = servidor.peticiones[0]
    assert peticion.method == "GET"
    assert peticion.url.path == "/api/uploadposts/facebook/pages"
    assert peticion.url.params["profile"] == "mi_perfil"


def test_paginas_de_otro_perfil_se_descartan():
    cuerpo = [{"page_id": "1", "page_name": "Mía", "profile": "mi_perfil"},
              {"page_id": "2", "page_name": "Ajena", "profile": "otro"}]
    paginas = _proveedor(Servidor(_responder_json(cuerpo))).paginas_facebook()
    assert paginas == [Pagina("1", "Mía")]


@pytest.mark.parametrize("codigo, cuerpo", [(500, {"error": "x"}), (200, {"raro": 1}),
                                            (403, {"message": "Not in your plan"})])
def test_paginas_errores(codigo, cuerpo):
    with pytest.raises(ErrorConsulta) as error:
        _proveedor(Servidor(_responder_json(cuerpo, codigo))).paginas_facebook()
    assert CLAVE not in str(error.value)


def test_consultas_quedan_en_el_registro_sin_la_clave_ni_el_perfil(tmp_path, monkeypatch):
    from videopipeline.redes import diario

    monkeypatch.setattr(diario, "DIR_LOGS", tmp_path / "logs")
    sa = _cuentas_json(x={"handle": "yo_x"})
    servidor = Servidor(lambda req, s: httpx.Response(
        200, json={"social_accounts": sa} if "users" in req.url.path
        else [{"page_id": "1", "page_name": "P"}]))
    d = diario.Diario(tmp_path / "v.mp4")
    d.ocultar(CLAVE)
    proveedor = _proveedor(servidor, perfil="perfil_secreto")
    proveedor.cuentas()
    proveedor.paginas_facebook()
    d.cerrar()
    texto = d.ruta.read_text(encoding="utf-8")
    assert "uploadposts/users" in texto and "facebook/pages" in texto
    assert "HTTP 200" in texto
    assert CLAVE not in texto
    assert "perfil_secreto" not in texto.split("cuerpo:")[0]
