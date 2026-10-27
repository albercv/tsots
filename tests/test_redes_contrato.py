"""Contrato común de todo proveedor registrado y desacoplamiento del resto.

- El contrato se ejecuta contra cada entrada de `PROVEEDORES`: un proveedor
  nuevo lo hereda sin escribir tests aquí.
- El desacoplamiento comprueba que nada fuera del módulo de Upload-Post
  contiene cadenas propias de Upload-Post.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import httpx
import pytest

from videopipeline.redes import proveedor as registro_proveedores
from videopipeline.redes.modelo import (
    ORDEN,
    Opciones,
    Plataforma,
    Publicacion,
    Resultado,
)
from videopipeline.redes.proveedor import PROVEEDORES, ErrorConsulta, Proveedor

RAIZ = Path(__file__).resolve().parent.parent
CLAVE = "clave-contrato-XYZ"
# Datos no secretos que la app pasa a `crear` (ver `Ajustes.ajustes_proveedor`).
AJUSTES = {"perfil": "perfil", "pagina_facebook": "123"}


# --- contrato ---


def _cliente(responder, peticiones):
    def manejar(request):
        peticiones.append(request)
        return responder(request)
    return httpx.Client(transport=httpx.MockTransport(manejar))


def _pub(video: Path) -> Publicacion:
    return Publicacion(video=video, titulo="t", caption="c", hashtags=("#a",),
                       palabras_clave=("k",))


def _error_500(request):
    return httpx.Response(500, json={"message": f"fallo interno {CLAVE}"})


def _sin_red(request):
    raise httpx.ConnectError("sin red", request=request)


def _basura(request):
    return httpx.Response(200, text="<html>no es json</html>")


@pytest.fixture(params=sorted(PROVEEDORES))
def nombre(request) -> str:
    return request.param


def test_modulo_expone_la_interfaz(nombre):
    modulo = registro_proveedores.modulo(nombre)
    assert isinstance(modulo.NOMBRE, str) and modulo.NOMBRE
    assert isinstance(modulo.USA_PERFIL, bool)
    assert callable(modulo.crear)
    assert registro_proveedores.nombre_visible(nombre) == modulo.NOMBRE


def test_crear_devuelve_un_proveedor_que_no_muestra_la_clave(nombre):
    p = registro_proveedores.crear(nombre, CLAVE, AJUSTES,
                                   http=_cliente(_error_500, []))
    assert isinstance(p, Proveedor)
    assert isinstance(p.nombre, str) and p.nombre
    assert CLAVE not in repr(p) and CLAVE not in str(p)


def test_proveedor_desconocido():
    with pytest.raises(ValueError):
        registro_proveedores.crear("no_existe", CLAVE)


def test_por_defecto_esta_registrado():
    assert registro_proveedores.PROVEEDOR_POR_DEFECTO in PROVEEDORES


def test_video_ausente_no_envia_nada(nombre, tmp_path):
    peticiones: list = []
    p = registro_proveedores.crear(nombre, CLAVE, AJUSTES,
                                   http=_cliente(_error_500, peticiones))
    for plataforma in ORDEN:
        r = p.publicar(plataforma, _pub(tmp_path / "falta.mp4"), Opciones())
        assert isinstance(r, Resultado) and r.plataforma == plataforma
        assert not r.ok and r.error
    assert peticiones == []


@pytest.mark.parametrize("responder", [_error_500, _sin_red, _basura])
def test_fallos_del_servicio_no_lanzan_ni_filtran_la_clave(nombre, tmp_path, responder):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"MP4")
    peticiones: list = []
    p = registro_proveedores.crear(nombre, CLAVE, AJUSTES,
                                   http=_cliente(responder, peticiones))
    for plataforma in ORDEN:
        r = p.publicar(plataforma, _pub(video), Opciones())
        assert isinstance(r, Resultado) and r.plataforma == plataforma
        assert not r.ok
        assert r.error or r.pendiente
        assert CLAVE not in r.error
        e = p.estado(plataforma, "ref-1")
        assert isinstance(e, Resultado) and e.plataforma == plataforma
        assert not e.ok and CLAVE not in e.error
    assert peticiones, "el proveedor debe usar el cliente HTTP inyectado"
    assert all(req.url.scheme == "https" for req in peticiones)
    # Todas las plataformas llegan al servicio (Facebook, con su página).
    assert len([r for r in peticiones if r.method == "POST"]) == len(ORDEN)


@pytest.mark.parametrize("responder", [_error_500, _sin_red, _basura])
def test_consultas_fallidas_lanzan_error_consulta_sin_la_clave(nombre, responder):
    peticiones: list = []
    p = registro_proveedores.crear(nombre, CLAVE, AJUSTES,
                                   http=_cliente(responder, peticiones))
    for consulta in (p.cuentas, p.paginas_facebook):
        with pytest.raises(ErrorConsulta) as error:
            consulta()
        assert str(error.value)
        assert CLAVE not in str(error.value)
    assert peticiones and all(req.url.scheme == "https" for req in peticiones)
    assert all(req.method == "GET" for req in peticiones)


def test_error_consulta_es_una_excepcion_neutra():
    assert issubclass(ErrorConsulta, Exception)
    assert ErrorConsulta.__module__ == "videopipeline.redes.proveedor"


# --- desacoplamiento ---

MODULO_PROVEEDOR = RAIZ / "videopipeline" / "redes" / "upload_post.py"

# Cadenas que solo tienen sentido en Upload-Post: su nombre, su dominio, su
# cabecera y los nombres de campo de su API.
PROHIBIDAS = re.compile(
    r"upload[-_ ]?post|api\.upload|Apikey|post_mode|share_mode|share_to_feed|"
    r"privacyStatus|privacy_level|categoryId|containsSyntheticMedia|is_aigc|"
    r"is_ai_generated|tiktok_title|youtube_title|youtube_description|instagram_title|"
    r"MEDIA_UPLOAD|DIRECT_POST|PUBLIC_TO_EVERYONE|TRIAL_REELS|uploadposts|"
    r"x_title|x_long_text_as_post|made_with_ai|facebook_page_id|facebook_title|"
    r"facebook_description|facebook_media_type|facebook_is_ai_generated|video_state|"
    r"social_accounts|reauth_required|display_name|page_id|page_name",
    re.IGNORECASE,
)

# Únicas menciones permitidas fuera del módulo del proveedor: su entrada en
# el registro y el proveedor por defecto (que también usan los ajustes, a
# través de esta constante). Las líneas deben coincidir exactamente.
PERMITIDAS = {
    ("videopipeline/redes/proveedor.py",
     'PROVEEDORES: dict[str, str] = {"upload_post": "videopipeline.redes.upload_post"}'),
    ("videopipeline/redes/proveedor.py", 'PROVEEDOR_POR_DEFECTO = "upload_post"'),
}


def _fuentes():
    for carpeta in ("app", "videopipeline"):
        for ruta in sorted((RAIZ / carpeta).rglob("*.py")):
            if ruta != MODULO_PROVEEDOR:
                yield ruta


def test_cadenas_del_proveedor_solo_en_su_modulo():
    encontradas = set()
    for ruta in _fuentes():
        relativa = ruta.relative_to(RAIZ).as_posix()
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if PROHIBIDAS.search(linea):
                encontradas.add((relativa, linea.strip()))
    assert encontradas - PERMITIDAS == set()
    # La lista de permitidas no se queda obsoleta.
    assert encontradas == PERMITIDAS


def test_nadie_importa_el_modulo_del_proveedor():
    for ruta in _fuentes():
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                nombres = [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom):
                nombres = [nodo.module or ""] + [a.name for a in nodo.names]
            else:
                continue
            assert not any("upload_post" in n for n in nombres), ruta


def test_el_modulo_del_proveedor_contiene_lo_especifico():
    """Si alguien mueve los campos a otro sitio, este test lo detecta."""
    texto = MODULO_PROVEEDOR.read_text(encoding="utf-8")
    for cadena in ("api.upload-post.com", "Apikey", "post_mode", "share_mode",
                   "privacyStatus", "x_title", "x_long_text_as_post", "facebook_page_id",
                   "facebook_media_type", "video_state", "social_accounts",
                   "reauth_required", "facebook/pages"):
        assert cadena in texto


def test_plataformas_neutras():
    assert {p.value for p in Plataforma} == {"tiktok", "youtube", "instagram", "x", "facebook"}


def test_ayuda_del_perfil_es_texto(nombre):
    assert isinstance(registro_proveedores.ayuda_perfil(nombre), str)


@pytest.mark.parametrize("texto, esperado", [
    ("yo@example.com", True), (" yo@dominio.es ", True),
    ("mi_perfil", False), ("", False), ("@yo", False),
])
def test_parece_email(texto, esperado):
    assert registro_proveedores.parece_email(texto) is esperado
