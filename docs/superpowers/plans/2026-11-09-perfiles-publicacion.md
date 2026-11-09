# Varios perfiles de publicación — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** varios perfiles de upload-post con una sola API key: el perfil se elige y se ve en la ventana principal antes de procesar, cada perfil tiene sus propios datos de publicación, cada vídeo recuerda con qué perfil se hizo y Publicar lo propone (y deja cambiarlo).

**Architecture:**

- **Ajustes:** las propiedades de hoy (`ciudad`, `pagina_facebook`, modos…) leen y escriben en el espacio del **perfil activo** (`redes/perfil_datos/<proveedor>/<huella>/<clave>`). Cambiar el activo cambia lo que leen todas, así que casi ningún diálogo cambia. `Ajustes.de_perfil(proveedor, perfil)` da una vista fija de otro perfil, para Redes….
- **Servicio:** `Proveedor.perfiles()` (upload-post: `GET /api/uploadposts/users`) y `app/cuentas.listar_perfiles`, que nunca lanza.
- **Interfaz:** un `SelectorPerfil(QComboBox)` reutilizado en la cabecera, Publicar (y Publicar shorts, que hereda) y Programadas. Redes… pasa a un combo editable con «Buscar perfiles» y «Quitar perfil».
- **Ficha:** `Ficha.perfil`; `main` lo anota al procesar, al crear shorts y al publicar.

**Tech Stack:** Python 3.11, PySide6, httpx, pytest + pytest-qt (offscreen), gettext.

**Spec:** `docs/superpowers/specs/2026-11-09-perfiles-publicacion-design.md`

## Global Constraints

- **Idioma:** código, comentarios y textos de la GUI en español. Commits en inglés, sin atribución de IA (ni `Co-Authored-By` ni «Generated with»).
- **Traducciones:** todo texto nuevo de la GUI con `_()`; se traduce en `locale/en/LC_MESSAGES/tsots.po` con `lanzador/traducir.sh` (tarea 8).
- **Tests:** desde `/Users/albercv/Documents/personalProjects/tsots-perfiles`, con
  `export PYTEST="env QT_QPA_PLATFORM=offscreen $HOME/Documents/personalProjects/limpiadorVideo/.venv-clearvoice/bin/python -m pytest -q"`.
  Antes de cada commit, la suite rápida: `$PYTEST -m "not lenta and not slow" --ignore=tests/test_redes_real.py --ignore=tests/test_redes_real_programar.py`. Commit solo en verde.
- **Nunca** `-m ""` ni `-m lenta`, y nunca `tests/test_redes_real*.py`: suben de verdad a las cuentas del usuario.
- **No tocar** `~/Documents/personalProjects/limpiadorVideo` (producción): solo se usa su intérprete.
- **Sin dependencias nuevas.**
- **Versiones anteriores** comparten los mismos QSettings y fichas y deben seguir arrancando: `redes/perfil/<proveedor>` se sigue escribiendo; las claves globales viejas no se borran y, con perfil activo, ya no se escriben.
- **Privacidad:** la API key solo en el Llavero; el lugar de TikTok sigue en el Llavero (`credenciales.guardar_lugar_tiktok(proveedor, perfil, ciudad, lugar)`), nunca en ajustes, logs ni repo.
- **Desacoplamiento:** ninguna cadena de Upload-Post fuera de `videopipeline/redes/upload_post.py` (lo vigila `tests/test_redes_contrato.py`).
- **Red siempre en segundo plano** (`segundo_plano.en_segundo_plano`); las funciones de `app/cuentas.py` nunca lanzan.
- **Rama:** `feature/perfiles-subida`; acaba en un PR contra `develop` con la documentación en la misma rama (lo abre quien ejecute, cuando el usuario lo pida).

## Review Focus

1. **Una versión anterior en los mismos ajustes y fichas** debe arrancar y ver lo de siempre: sus claves globales intactas, el perfil activo en `redes/perfil/<proveedor>`, y una ficha con `perfil` se carga (la clave extra se ignora). Tests: tarea 1 (`test_version_anterior_sigue_leyendo_sus_claves`), tarea 3 (ficha sin la clave).
2. **Nombres de perfil con «/», espacios, unicode o muy largos:** nunca rompen una ruta de QSettings (van por huella) ni ensanchan la ventana. Tests: tarea 1 (parametrizado), tarea 4 (nombre de 200 caracteres).
3. **Cambiar de perfil con una publicación o una consulta en marcha:** el selector se bloquea mientras publica (Publicar) o consulta/cancela (Programadas), y una respuesta tardía del perfil anterior nunca se guarda en el nuevo. Tests: tarea 6, tarea 7.
4. **Sin perfiles / sin perfil activo:** el selector muestra «Sin perfil: añádelo en Redes…» deshabilitado, Publicar avisa de que falta, y el contexto de marca de quien nunca configuró Redes sigue funcionando. Tests: tarea 1, tarea 4.
5. **La forma de la respuesta de la lista de perfiles no está verificada:** sin `profiles` → `ErrorConsulta` legible, Redes… lo muestra y escribir el perfil a mano sigue funcionando. Tests: tarea 2, tarea 5.

---

### Task 1: Ajustes por perfil, lista de perfiles y migración

**Files:**
- Modify: `app/credenciales.py` (`_cuenta_lugar`, ~línea 103)
- Modify: `app/settings.py` (sección redes, líneas ~112-330, y `contexto_marca`, ~línea 80)
- Modify: `app/widgets/dialogo_redes.py` (solo las dos llamadas a métodos que desaparecen)
- Modify: `tests/test_app_redes.py` (`test_pagina_de_facebook_por_proveedor_y_borrable`, línea ~185 de `test_cuentas_guardadas_ida_y_vuelta_y_ligadas_al_perfil`)
- Modify: `tests/test_credenciales.py`
- Create: `tests/test_app_perfiles.py`

**Interfaces:**
- Produces:
  - `credenciales.huella_perfil(perfil: str) -> str`: los 16 primeros caracteres hex del sha256 de `perfil.strip()`.
  - `Ajustes.perfiles_de(proveedor: str) -> list[str]`, `Ajustes.anadir_perfil(proveedor: str, perfil: str) -> None`, `Ajustes.quitar_perfil(proveedor: str, perfil: str) -> None`.
  - `Ajustes.de_perfil(proveedor: str, perfil: str) -> Ajustes`: vista que comparte los QSettings y cuyas propiedades por perfil leen y escriben ese perfil, sin cambiar el activo.
  - `Ajustes._clave(nombre: str) -> str`: clave QSettings del dato `nombre` en el contexto actual (los tests la usan para estropear un valor).
  - `guardar_perfil(proveedor, perfil)` y el setter `perfil_redes` añaden además el perfil a la lista.
  - Desaparecen `pagina_facebook_de` y `guardar_pagina_facebook`: se usa `de_perfil(proveedor, perfil).pagina_facebook`.

- [ ] **Step 1: Write the failing tests**

En `tests/test_credenciales.py` (añade `import hashlib`):

```python
def test_huella_del_perfil_es_la_de_siempre():
    """Los lugares de TikTok ya guardados en el Llavero se siguen encontrando."""
    assert credenciales.huella_perfil(" yo ") == hashlib.sha256(b"yo").hexdigest()[:16]
    assert credenciales._cuenta_lugar("yo", "MADRID") == (
        "tiktok-lugar-MADRID-" + credenciales.huella_perfil("yo"))
```

Crea `tests/test_app_perfiles.py`:

```python
"""Varios perfiles de publicación: ajustes, selector y diálogos (sin red ni Llavero real)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings

from app.credenciales import huella_perfil
from app.settings import Ajustes
from videopipeline.redes.modelo import (
    Ciudad, Cuenta, ModoFacebook, ModoInstagram, ModoTikTok, Pagina, Plataforma,
)
from videopipeline.redes.proveedor import PROVEEDOR_POR_DEFECTO as P

T, Y, I, X = Plataforma.TIKTOK, Plataforma.YOUTUBE, Plataforma.INSTAGRAM, Plataforma.X


def _q(tmp_path, nombre="t.ini") -> QSettings:
    return QSettings(str(tmp_path / nombre), QSettings.Format.IniFormat)


@pytest.fixture
def ajustes(tmp_path) -> Ajustes:
    return Ajustes(_q(tmp_path))


def _de_antes(q: QSettings) -> None:
    """Ajustes como los deja la versión de hoy: un perfil y todo global."""
    q.setValue(f"redes/perfil/{P}", "personal")
    q.setValue("redes/ciudad", "SEVILLA")
    q.setValue("caption/contexto_marca", "Soy Alberto")
    q.setValue("redes/tiktok_modo", "publico")
    q.setValue(f"redes/facebook_pagina/{P}", "111")
    q.setValue(f"redes/facebook_pagina_nombre/{P}", "Mi página")
    q.setValue("redes/plataformas", "tiktok,x")


def test_migracion_el_perfil_de_hoy_hereda_y_uno_nuevo_empieza_de_cero(tmp_path):
    q = _q(tmp_path)
    _de_antes(q)
    ajustes = Ajustes(q)
    assert ajustes.perfiles_de(P) == ["personal"]
    assert ajustes.ciudad is Ciudad.SEVILLA
    assert ajustes.contexto_marca == "Soy Alberto"
    assert ajustes.tiktok_modo == ModoTikTok.PUBLICO
    assert ajustes.pagina_facebook == Pagina("111", "Mi página")
    assert ajustes.plataformas_redes == [T, X]
    ajustes.perfil_redes = "sixpodcast"
    assert ajustes.perfiles_de(P) == ["personal", "sixpodcast"]
    assert ajustes.ciudad is Ciudad.MADRID
    assert ajustes.contexto_marca == ""
    assert ajustes.tiktok_modo == ModoTikTok.BORRADOR
    assert ajustes.pagina_facebook is None
    assert ajustes.plataformas_redes == [T, Y, I]


def test_la_migracion_es_una_sola_vez(tmp_path):
    q = _q(tmp_path)
    _de_antes(q)
    Ajustes(q).ciudad = Ciudad.BARCELONA
    q.setValue("redes/ciudad", "VALENCIA")  # una versión anterior la cambia después
    assert Ajustes(q).ciudad is Ciudad.BARCELONA


def test_version_anterior_sigue_leyendo_sus_claves(tmp_path):
    q = _q(tmp_path)
    _de_antes(q)
    ajustes = Ajustes(q)
    ajustes.ciudad = Ciudad.BARCELONA
    ajustes.contexto_marca = "Otra"
    assert q.value("redes/ciudad") == "SEVILLA"
    assert q.value("caption/contexto_marca") == "Soy Alberto"
    ajustes.perfil_redes = "sixpodcast"
    assert q.value(f"redes/perfil/{P}") == "sixpodcast"


def test_cambiar_el_activo_cambia_lo_que_leen_todas(ajustes):
    ajustes.perfil_redes = "personal"
    ajustes.ciudad = Ciudad.SEVILLA
    ajustes.contexto_marca = "A"
    ajustes.x_premium = True
    ajustes.youtube_categoria = "28"
    ajustes.instagram_modo = ModoInstagram.NORMAL
    ajustes.facebook_modo = ModoFacebook.VIDEO
    ajustes.plataformas_redes = [X]
    ajustes.pagina_facebook = Pagina("1", "A")
    ajustes.guardar_cuentas({T: Cuenta(T, "A")})
    ajustes.perfil_redes = "six"
    assert (ajustes.ciudad, ajustes.contexto_marca, ajustes.x_premium,
            ajustes.youtube_categoria, ajustes.instagram_modo, ajustes.facebook_modo,
            ajustes.plataformas_redes, ajustes.pagina_facebook, ajustes.cuentas_guardadas()) == (
        Ciudad.MADRID, "", False, "22", ModoInstagram.PRUEBA, ModoFacebook.REEL,
        [T, Y, I], None, None)
    ajustes.perfil_redes = "personal"
    assert ajustes.ciudad is Ciudad.SEVILLA and ajustes.x_premium is True
    assert ajustes.plataformas_redes == [X]
    assert ajustes.cuentas_guardadas().cuentas == {T: Cuenta(T, "A")}
    assert ajustes.ajustes_proveedor() == {"perfil": "personal", "pagina_facebook": "1"}


def test_sin_perfil_activo_se_usan_las_claves_de_siempre(ajustes):
    """Quien nunca configuró Redes conserva su contexto de marca."""
    ajustes.contexto_marca = "Marca"
    assert ajustes._q.value("caption/contexto_marca") == "Marca"
    assert ajustes.perfiles_de(P) == []
    ajustes.perfil_redes = "yo"  # el primero hereda lo de siempre
    assert ajustes.contexto_marca == "Marca"
    ajustes.perfil_redes = "otro"
    assert ajustes.contexto_marca == ""


def test_anadir_no_duplica_y_quitar_borra_sus_datos(ajustes):
    ajustes.perfil_redes = "personal"
    for nombre in (" six ", "six", ""):
        ajustes.anadir_perfil(P, nombre)
    assert ajustes.perfiles_de(P) == ["personal", "six"]
    six = ajustes.de_perfil(P, "six")
    six.ciudad = Ciudad.SEVILLA
    six.contexto_marca = "S"
    ajustes.quitar_perfil(P, "six")
    assert ajustes.perfiles_de(P) == ["personal"]
    assert ajustes.de_perfil(P, "six").ciudad is Ciudad.MADRID
    assert ajustes.de_perfil(P, "six").contexto_marca == ""
    assert not any(huella_perfil("six") in k for k in ajustes._q.allKeys())
    assert ajustes.perfil_redes == "personal"


def test_quitar_el_activo_deja_activo_el_siguiente_o_ninguno(ajustes):
    ajustes.perfil_redes = "personal"
    ajustes.anadir_perfil(P, "six")
    ajustes.quitar_perfil(P, "personal")
    assert ajustes.perfil_redes == "six"
    ajustes.quitar_perfil(P, "six")
    assert ajustes.perfil_redes == "" and ajustes.perfiles_de(P) == []


def test_de_perfil_lee_y_escribe_otro_sin_cambiar_el_activo(ajustes):
    ajustes.perfil_redes = "personal"
    six = ajustes.de_perfil(P, "six")
    six.tiktok_modo = ModoTikTok.PUBLICO
    six.pagina_facebook = Pagina("2", "Six")
    assert ajustes.perfil_redes == "personal" and ajustes.perfiles_de(P) == ["personal"]
    assert ajustes.tiktok_modo == ModoTikTok.BORRADOR and ajustes.pagina_facebook is None
    assert six.ajustes_proveedor() == {"perfil": "six", "pagina_facebook": "2"}


@pytest.mark.parametrize("nombre", ["mi perfil/2", "  señal ñ 🎙  ", "a/b\\c d"])
def test_perfil_con_barras_espacios_o_unicode(tmp_path, nombre):
    a = Ajustes(_q(tmp_path, "p.ini"))
    a.perfil_redes = nombre
    a.ciudad = Ciudad.SEVILLA
    a.contexto_marca = "M"
    a._q.sync()
    b = Ajustes(_q(tmp_path, "p.ini"))
    assert b.perfil_redes == nombre.strip()
    assert b.perfiles_de(P) == [nombre.strip()]
    assert b.ciudad is Ciudad.SEVILLA and b.contexto_marca == "M"
    assert all(nombre.strip() not in k for k in b._q.allKeys())


def test_lista_de_perfiles_estropeada_es_vacia(ajustes):
    ajustes._q.setValue(f"redes/perfiles/{P}", "{no es json")
    assert ajustes.perfiles_de(P) == []
    ajustes._q.setValue(f"redes/perfiles/{P}", '["ok", 5, "  "]')
    assert ajustes.perfiles_de(P) == ["ok"]
```

En `tests/test_app_redes.py`:
- `test_pagina_de_facebook_por_proveedor_y_borrable`: `ajustes.pagina_facebook_de(X)` pasa a `ajustes.de_perfil(X, "").pagina_facebook` (las dos líneas).
- `test_cuentas_guardadas_ida_y_vuelta_y_ligadas_al_perfil`: la línea que estropea la clave pasa a `ajustes._q.setValue(ajustes._clave("cuentas"), "{no es json")`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_app_perfiles.py tests/test_credenciales.py tests/test_app_redes.py`
Expected: FAIL (`huella_perfil`, `perfiles_de`, `de_perfil`, `_clave` no existen).

- [ ] **Step 3: Implement**

`app/credenciales.py`: `huella_perfil(perfil: str) -> str` con la línea de hoy; `_cuenta_lugar` la usa (mismo resultado).

`app/settings.py`:
- Importa `copy` y `from .credenciales import huella_perfil`.
- Datos por perfil → su clave global de antes (la que leen las versiones anteriores y la que se usa **sin perfil activo**):

```python
_GLOBALES = {
    "contexto_marca": "caption/contexto_marca",
    "ciudad": "redes/ciudad",
    "facebook_pagina": "redes/facebook_pagina/{proveedor}",
    "facebook_pagina_nombre": "redes/facebook_pagina_nombre/{proveedor}",
    "plataformas": "redes/plataformas",
    "tiktok_modo": "redes/tiktok_modo",
    "instagram_modo": "redes/instagram_modo",
    "facebook_modo": "redes/facebook_modo",
    "x_premium": "redes/x_premium",
    "youtube_categoria": "redes/youtube_categoria",
    "cuentas": "redes/cuentas/{proveedor}",
}
```

- `__init__`: `self._fijo: tuple[str, str] | None = None`; después, para cada `proveedor` de `PROVEEDORES` con `perfil_de(proveedor)` no vacío, `self.anadir_perfil(proveedor, activo)` (migración la primera vez; además recoge un activo que una versión anterior puso y no está en la lista).
- `_contexto() -> tuple[str, str]`: `self._fijo` o `(self.proveedor_redes, self.perfil_redes)`.
- `_clave_de(proveedor, perfil, nombre) -> str`: con perfil, `f"redes/perfil_datos/{proveedor}/{huella_perfil(perfil)}/{nombre}"`; sin perfil, `_GLOBALES[nombre].format(proveedor=proveedor)`. `_clave(nombre)` = `_clave_de(*self._contexto(), nombre)`.
- Las propiedades por perfil (`contexto_marca`, `ciudad`, `pagina_facebook`, `plataformas_redes`, `tiktok_modo`, `instagram_modo`, `facebook_modo`, `x_premium`, `youtube_categoria`, `cuentas_guardadas`/`guardar_cuentas`) cambian solo la clave literal por `self._clave("…")`; valores por defecto y lectura tolerante, como hoy. El campo `"perfil"` del JSON de cuentas y el de `ajustes_proveedor()` salen de `self._contexto()[1]`.
- `perfiles_de`: lista JSON en `redes/perfiles/<proveedor>`; JSON roto o que no es lista → `[]`; solo cadenas no vacías tras `strip`.
- `anadir_perfil` (el algoritmo de herencia):

```python
def anadir_perfil(self, proveedor: str, perfil: str) -> None:
    perfil = perfil.strip()
    lista_clave = f"redes/perfiles/{proveedor}"
    if not perfil:
        return
    if not self._q.contains(lista_clave):
        # El primer perfil hereda lo de siempre; solo lo que aún no tiene.
        for nombre, plantilla in _GLOBALES.items():
            origen = plantilla.format(proveedor=proveedor)
            destino = self._clave_de(proveedor, perfil, nombre)
            if self._q.contains(origen) and not self._q.contains(destino):
                self._q.setValue(destino, self._q.value(origen))
    perfiles = self.perfiles_de(proveedor)
    if perfil not in perfiles:
        self._q.setValue(lista_clave, json.dumps([*perfiles, perfil], ensure_ascii=False))
```

- `quitar_perfil`: lo quita de la lista (la clave de la lista se queda, aunque quede vacía, para no volver a heredar), `self._q.remove(f"redes/perfil_datos/{proveedor}/{huella_perfil(perfil)}")`, y si era el activo, escribe en `redes/perfil/<proveedor>` el primero que quede o `""` (con `setValue`, no con `guardar_perfil`, que lo volvería a añadir).
- `guardar_perfil`: como hoy y además `self.anadir_perfil(proveedor, perfil)`.
- `de_perfil`: `copia = copy.copy(self)`, `copia._fijo = (proveedor, perfil.strip())`.
- Borra `pagina_facebook_de` y `guardar_pagina_facebook`; la propiedad `pagina_facebook` usa `_clave("facebook_pagina")` y `_clave("facebook_pagina_nombre")`.

`app/widgets/dialogo_redes.py` (mínimo para seguir funcionando; la tarea 5 lo rehace):
- `_al_cambiar_proveedor`: `pagina = self.ajustes.de_perfil(self.proveedor, self.ajustes.perfil_de(self.proveedor)).pagina_facebook`.
- `accept`: `guardar_pagina_facebook(...)` pasa a `self.ajustes.pagina_facebook = self.pagina_elegida()` (va detrás de fijar proveedor y perfil, así que escribe en el elegido).

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_app_perfiles.py tests/test_credenciales.py tests/test_app_redes.py tests/test_app_programadas.py tests/test_app_programar.py tests/test_app_publicar_shorts.py tests/test_app_main.py`
Expected: PASS.

- [ ] **Step 5: Commit** (tras la suite rápida en verde)

```bash
git add app/credenciales.py app/settings.py app/widgets/dialogo_redes.py tests/test_app_perfiles.py tests/test_app_redes.py tests/test_credenciales.py
git commit -m "feat: keep network settings per publishing profile"
```

---

### Task 2: Lista de perfiles del servicio

**Files:**
- Modify: `videopipeline/redes/proveedor.py` (Protocol)
- Modify: `videopipeline/redes/upload_post.py` (`_consultar` ~línea 567, nuevo `perfiles()` junto a `cuentas()`)
- Modify: `app/cuentas.py`
- Modify: `tests/redes_falsos.py`, `tests/test_redes_contrato.py`, `tests/test_redes_upload_post.py`, `tests/test_app_perfiles.py`

**Interfaces:**
- Produces:
  - `Proveedor.perfiles(self) -> list[str]`: nombres de los perfiles de la cuenta, a partir de la API key (no necesita perfil). Lanza `ErrorConsulta`.
  - `ProveedorUploadPost._consultar(..., registrar_cuerpo: bool = True, pide_perfil: bool = True)`.
  - `cuentas.listar_perfiles(llavero, fabrica: Fabrica, nombre: str, *, clave: str | None = None) -> tuple[list[str] | None, str]`: `(perfiles, "")` o `(None, motivo)`; nunca lanza; crea el proveedor con `{"perfil": "", "pagina_facebook": ""}`.
  - `ProveedorFalso(..., perfiles_cuenta=None)`: lo que devuelve `perfiles()` (por defecto `["mi_perfil"]`) o una excepción a lanzar; anota `"perfiles"` en `consultas`. (No puede llamarse `perfiles`: taparía el método.)

- [ ] **Step 1: Write the failing tests**

`tests/test_redes_upload_post.py`, junto a los de cuentas:

```python
def test_perfiles_de_la_cuenta():
    cuerpo = {"success": True, "profiles": [
        {"username": "personal", "social_accounts": {}}, {"profile": "sixpodcast"},
        {"name": " tercero "}, {"username": "", "name": "cuarto"},
        {"social_accounts": {}}, "basura", {"username": "personal"}]}
    servidor = Servidor(_responder_json(cuerpo))
    assert _proveedor(servidor, perfil="").perfiles() == [
        "personal", "sixpodcast", "tercero", "cuarto"]
    peticion = servidor.peticiones[0]
    assert peticion.method == "GET"
    assert str(peticion.url) == "https://api.upload-post.com/api/uploadposts/users"
    assert peticion.headers["authorization"] == f"Apikey {CLAVE}"


@pytest.mark.parametrize("codigo, cuerpo, texto", [
    (200, {"success": True}, "inesperada"),
    (200, {"profiles": "x"}, "inesperada"),
    (401, {"message": "Invalid API key"}, "API key"),
    (500, {"message": f"boom {CLAVE}"}, "500"),
])
def test_perfiles_errores_legibles_y_sin_clave(codigo, cuerpo, texto):
    with pytest.raises(ErrorConsulta) as error:
        _proveedor(Servidor(_responder_json(cuerpo, codigo))).perfiles()
    assert texto in str(error.value)
    assert CLAVE not in str(error.value)


def test_perfiles_sin_red():
    def sin_red(request, servidor):
        raise httpx.ConnectError(f"sin red {CLAVE}", request=request)
    with pytest.raises(ErrorConsulta) as error:
        _proveedor(Servidor(sin_red)).perfiles()
    assert CLAVE not in str(error.value)
```

`tests/test_redes_contrato.py`, `test_consultas_fallidas_lanzan_error_consulta_sin_la_clave`: añade `p.perfiles` a la tupla de consultas.

`tests/test_app_perfiles.py` (añade a los imports `from app import credenciales`, `from app import cuentas`, `from tests.redes_falsos import ProveedorFalso`, `from videopipeline.redes.proveedor import ErrorConsulta`):

```python
def test_listar_perfiles_nunca_lanza(llavero_falso):
    pedidos = []

    def fabrica(perfiles):
        def crear(nombre, clave, datos):
            pedidos.append((clave, datos))
            return ProveedorFalso(perfiles_cuenta=perfiles)
        return crear

    assert cuentas.listar_perfiles(credenciales, fabrica(["a"]), P) == (
        None, "Falta la API key del servicio: guárdala en Redes…")
    assert cuentas.listar_perfiles(credenciales, fabrica(["a", "b"]), P, clave="k") == (
        ["a", "b"], "")
    assert pedidos[-1] == ("k", {"perfil": "", "pagina_facebook": ""})
    assert cuentas.listar_perfiles(credenciales, fabrica(ErrorConsulta("401 mala")), P,
                                   clave="k") == (None, "401 mala")
    perfiles, motivo = cuentas.listar_perfiles(
        credenciales, fabrica(RuntimeError("clave-secreta")), P, clave="clave-secreta")
    assert perfiles is None and "RuntimeError" in motivo and "clave-secreta" not in motivo
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_redes_upload_post.py tests/test_redes_contrato.py tests/test_app_perfiles.py`
Expected: FAIL (`perfiles` / `listar_perfiles` / `perfiles_cuenta` no existen).

- [ ] **Step 3: Implement**

- `proveedor.py`: método `perfiles` en el Protocol, con la docstring de arriba.
- `upload_post.py`: `_consultar` solo exige el perfil si `pide_perfil`. `perfiles()` hace `self._consultar("perfiles", URL_USUARIOS, URL_USUARIOS, pide_perfil=False)` y `self._buscar(cuerpo, "profiles")`. Si no es lista: `ErrorConsulta(_("Respuesta inesperada del servicio: no trae los perfiles."))`. De cada elemento que sea dict, el primer valor de `username`, `profile` o `name` que sea texto no vacío tras `strip`. Los que no tienen nombre se saltan, los repetidos se quitan conservando el orden. Al final, `log.info("Perfiles: %d", len(...))`.
- `app/cuentas.py`: `listar_perfiles` como `buscar_lugares` (mismo `_servicio`, mismas dos ramas `except`), con `_("Error inesperado al buscar los perfiles ({tipo}).")`.
- `tests/redes_falsos.py`: `perfiles_cuenta` y `perfiles()`, y la docstring de la clase lo menciona.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_redes_upload_post.py tests/test_redes_contrato.py tests/test_app_perfiles.py`
Expected: PASS (incluido `test_cadenas_del_proveedor_solo_en_su_modulo`).

- [ ] **Step 5: Commit**

```bash
git add videopipeline/redes/proveedor.py videopipeline/redes/upload_post.py app/cuentas.py tests/redes_falsos.py tests/test_redes_contrato.py tests/test_redes_upload_post.py tests/test_app_perfiles.py
git commit -m "feat: list the profiles of the publishing account"
```

---

### Task 3: Cada vídeo recuerda su perfil

**Files:**
- Modify: `videopipeline/ficha.py` (`Ficha`, `_a_dict`, `_de_dict`)
- Modify: `app/main.py` (imports de `videopipeline.ficha`, `procesar` ~línea 662, `_crear_shorts` ~línea 759)
- Modify: `tests/test_ficha.py`, `tests/test_app_main.py`

**Interfaces:**
- Produces:
  - `Ficha.perfil: str = ""` (último campo); `_a_dict` escribe `"perfil"`; `_de_dict` lee `_tipo(datos.get("perfil", ""), str)`.
  - `VentanaPrincipal._anotar_perfil(self, ficha_id: str | None, perfil: str) -> None`: si los dos no están vacíos, vuelve a cargar la ficha del disco (`cargar`) y, si su `perfil` es otro, lo cambia y la guarda (`guardar`). Se carga de nuevo para no pisar lo que el runner haya escrito.

- [ ] **Step 1: Write the failing tests**

`tests/test_ficha.py`:
- En `test_guardar_y_cargar_ida_y_vuelta`, añade `perfil="sixpodcast"` al `Ficha(...)`.
- Añade `("perfil", 5)` a `FORMAS_ERRONEAS`.
- Nuevo:

```python
def test_ficha_sin_perfil_carga_con_perfil_vacio(tmp_path):
    datos = _ficha_json_valida(tmp_path)
    del datos["perfil"]
    _escribir_ficha_mala(datos)
    assert cargar("mala").perfil == ""
```

`tests/test_app_main.py`:

```python
def test_procesar_anota_el_perfil_activo_en_la_ficha(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.perfil_redes = "sixpodcast"
    ventana.anadir_videos(_videos(tmp_path, "a.mp4"))
    _lanzando(ventana, monkeypatch)
    ventana.procesar()
    assert cargar(ventana.modelo_cola.trabajo(0).ficha_id).perfil == "sixpodcast"


def test_crear_shorts_anota_el_perfil_activo_en_la_ficha(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    ventana.ajustes.perfil_redes = "personal"
    ventana.anadir_videos([tmp_path / "a.mp4"])
    _eligiendo_la_fila(ventana)
    _lanzando(ventana, monkeypatch)
    ventana.panel.boton_crear_shorts.click()
    assert cargar(ficha.id).perfil == "personal"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_ficha.py tests/test_app_main.py -k "perfil or ida_y_vuelta or forma"`
Expected: FAIL (`Ficha` no acepta `perfil`; la ficha no lo guarda).

- [ ] **Step 3: Implement**

- `ficha.py`: el campo y las dos líneas de (de)serialización.
- `main.py`: importa `guardar`; `_anotar_perfil`. En `procesar`, justo antes de `trabajos.append(...)`, `self._anotar_perfil(trabajo.ficha_id, self.ajustes.perfil_redes)`. En `_crear_shorts`, antes de `self.ejecutor.iniciar(...)`, lo mismo.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_ficha.py tests/test_app_main.py tests/test_reproceso.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add videopipeline/ficha.py app/main.py tests/test_ficha.py tests/test_app_main.py
git commit -m "feat: remember the publishing profile of each video"
```

---

### Task 4: Selector de perfil en la ventana principal

**Files:**
- Create: `app/widgets/selector_perfil.py`
- Modify: `app/widgets/cabecera.py`, `app/widgets/dialogo_marca.py`
- Modify: `app/main.py` (`__init__`, `_editar_marca`, `_publicar`, `_publicar_shorts`, `_abrir_programadas`, `_configurar_redes`)
- Modify: `tests/test_app_perfiles.py`, `tests/test_app_main.py`, `tests/test_app_widgets.py`

**Interfaces:**
- Consumes: `Ajustes.perfiles_de`, `perfil_redes`, `proveedor_redes` (tarea 1).
- Produces:
  - `SelectorPerfil(QComboBox)` en `app/widgets/selector_perfil.py`:
    - `perfil_elegido = Signal(str)`: solo cuando el usuario elige un perfil distinto del marcado. Se conecta a `activated`, que Qt solo emite por acción del usuario, nunca al recargar.
    - `recargar(self, ajustes: Ajustes) -> None`: los perfiles de `ajustes.perfiles_de(ajustes.proveedor_redes)`, con el nombre como texto y como dato, y marca `ajustes.perfil_redes`. Sin perfiles: una sola entrada, `_("Sin perfil: añádelo en Redes…")`, con dato `None` y deshabilitada (`self.model().item(0).setEnabled(False)`).
    - Un nombre largo no ensancha la ventana: `setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)` y `setMinimumContentsLength(14)`.
  - `Cabecera.selector_perfil: SelectorPerfil`, a la derecha de la fila, tras `QLabel(_("Perfil:"))` con `setBuddy`.
  - `DialogoMarca(texto_inicial="", parent=None, perfil: str = "")`: título `_("Contexto de marca · perfil «{perfil}»")` con perfil; `_("Contexto de marca")` sin él.
  - `VentanaPrincipal._recargar_perfil(self) -> None` y `_al_elegir_perfil(self, perfil: str) -> None` (fija `self.ajustes.perfil_redes`).
  - Helper de tests `_elegir(combo, texto)` en `tests/test_app_perfiles.py`, que usan las tareas 5-7.

- [ ] **Step 1: Write the failing tests**

`tests/test_app_perfiles.py` (añade `from app.widgets.selector_perfil import SelectorPerfil`):

```python
def _elegir(combo, texto: str) -> None:
    """Como el usuario: marca la entrada y emite `activated`."""
    indice = combo.findText(texto)
    assert indice >= 0, texto
    combo.setCurrentIndex(indice)
    combo.activated.emit(indice)


def test_selector_lista_los_perfiles_y_avisa_solo_si_el_usuario_cambia(qtbot, ajustes):
    ajustes.perfil_redes = "personal"
    ajustes.anadir_perfil(P, "six")
    selector = SelectorPerfil()
    qtbot.addWidget(selector)
    elegidos: list[str] = []
    selector.perfil_elegido.connect(elegidos.append)
    selector.recargar(ajustes)
    assert [selector.itemText(i) for i in range(selector.count())] == ["personal", "six"]
    assert selector.currentText() == "personal"
    assert elegidos == []
    _elegir(selector, "six")
    assert elegidos == ["six"]
    selector.activated.emit(selector.currentIndex())  # la misma otra vez
    assert elegidos == ["six"]


def test_selector_sin_perfiles(qtbot, ajustes):
    selector = SelectorPerfil()
    qtbot.addWidget(selector)
    elegidos: list[str] = []
    selector.perfil_elegido.connect(elegidos.append)
    selector.recargar(ajustes)
    assert selector.count() == 1
    assert selector.itemText(0) == "Sin perfil: añádelo en Redes…"
    assert not selector.model().item(0).isEnabled()
    selector.activated.emit(0)
    assert elegidos == []
```

`tests/test_app_main.py`:
- `_DialogoFalso`: añade el atributo de clase `perfil_usado = ""` (lo leerá la tarea 6).
- `test_editar_marca_persiste_en_ajustes`: pon `ventana.ajustes.perfil_redes = "six"` al principio. El `__init__` del falso pasa a `(self, texto_inicial="", parent=None, perfil="")` y anota `visto["perfil"] = perfil`. Añade `assert visto["perfil"] == "six"`.
- Nuevos:

```python
def test_selector_de_la_cabecera_fija_el_perfil_y_se_recarga_al_cerrar_redes(
        qtbot, tmp_path, monkeypatch):
    from tests.test_app_perfiles import _elegir

    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    selector = ventana.cabecera.selector_perfil
    assert selector.itemText(0) == "Sin perfil: añádelo en Redes…"
    ventana.ajustes.perfil_redes = "personal"
    ventana.ajustes.anadir_perfil("upload_post", "six")

    class Falso(_DialogoFalso):
        abiertos: list = []

    monkeypatch.setattr("app.main.DialogoRedes", Falso)
    ventana.boton_redes.click()  # Cancelar también recarga
    assert selector.currentText() == "personal"
    _elegir(selector, "six")
    assert ventana.ajustes.perfil_redes == "six"


def test_un_perfil_de_nombre_largo_no_ensancha_la_ventana(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.perfil_redes = "x" * 200
    ventana._recargar_perfil()
    ventana.show()
    assert ventana.minimumSizeHint().width() <= 700
```

`tests/test_app_widgets.py`, junto al test de `DialogoMarca`:

```python
def test_dialogo_marca_nombra_el_perfil(qtbot):
    from app.widgets.dialogo_marca import DialogoMarca

    assert DialogoMarca("x", perfil="six").windowTitle() == "Contexto de marca · perfil «six»"
    assert DialogoMarca("x").windowTitle() == "Contexto de marca"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_app_perfiles.py tests/test_app_main.py tests/test_app_widgets.py`
Expected: FAIL (no existe `selector_perfil`).

- [ ] **Step 3: Implement**

- `selector_perfil.py`: la clase de arriba; guarda el perfil marcado al recargar y compara con él en el manejador de `activated` (ignora el dato `None`).
- `cabecera.py`: crea `self.selector_perfil` y su etiqueta y los añade al final de `fila`. La cabecera no conoce los ajustes: los recarga `main`.
- `dialogo_marca.py`: el parámetro `perfil` y el título.
- `main.py`:
  - en `__init__`, tras crear la cabecera, conecta `self.cabecera.selector_perfil.perfil_elegido` a `_al_elegir_perfil` y llama a `self._recargar_perfil()`;
  - `_editar_marca` pasa `perfil=self.ajustes.perfil_redes`;
  - `_recargar_perfil()` al final de `_publicar`, `_publicar_shorts` y `_abrir_programadas`, tras cerrar el diálogo, y en `_configurar_redes` tras `exec()`, aunque se cancele (Quitar perfil actúa al momento, tarea 5).

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_app_perfiles.py tests/test_app_main.py tests/test_app_widgets.py`
Expected: PASS (incluidos `test_ventana_cabe_en_pantallas_pequenas` y `test_cabecera_encima_de_zona_drop_y_cola`).

- [ ] **Step 5: Commit**

```bash
git add app/widgets/selector_perfil.py app/widgets/cabecera.py app/widgets/dialogo_marca.py app/main.py tests/test_app_perfiles.py tests/test_app_main.py tests/test_app_widgets.py
git commit -m "feat: choose the publishing profile from the main window"
```

---

### Task 5: Redes… con varios perfiles

**Files:**
- Modify: `app/widgets/dialogo_redes.py`
- Modify: `app/main.py` (`_configurar_redes`)
- Modify: `tests/test_app_perfiles.py`, `tests/test_app_main.py`

**Interfaces:**
- Consumes: `Ajustes.perfiles_de / anadir_perfil / quitar_perfil / de_perfil / perfil_de / guardar_perfil` (tarea 1), `cuentas.listar_perfiles` y `ProveedorFalso(perfiles_cuenta=…)` (tarea 2), `_elegir` (tarea 4).
- Produces:
  - `DialogoRedes.combo_perfil`: `QComboBox` editable con `setInsertPolicy(QComboBox.InsertPolicy.NoInsert)`. `self.campo_perfil = self.combo_perfil.lineEdit()`, así los tests y el código de hoy (`setText`, `text`, `textChanged`, aviso de email) siguen valiendo.
  - `boton_buscar_perfiles` (`_("Buscar perfiles")`, tooltip `_("Pregunta al servicio qué perfiles tiene tu cuenta")`) y `boton_quitar_perfil` (`_("Quitar perfil")`), en una fila bajo el campo del perfil.
  - `_poner_perfiles()`, `_cargar_perfil()`, `_datos() -> Ajustes` (vista del perfil escrito: `self.ajustes.de_perfil(self.proveedor, self.campo_perfil.text().strip())`).
  - `VentanaPrincipal._configurar_redes(self, al_cerrar=None, padre=None)`: `al_cerrar()` siempre tras `exec()`, aunque se cancele. Se renombra `al_guardar`; hay dos llamadas en `main.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_app_perfiles.py` (añade a los imports `from PySide6.QtWidgets import QMessageBox`, `from app.widgets.dialogo_redes import DialogoRedes`, `from tests.test_app_redes import CLAVE, _esperar_consultas, _redes` y `Plataforma`):

```python
def _dos_perfiles(ajustes) -> None:
    """«personal» (activo) y «six», con datos distintos."""
    ajustes.perfil_redes = "personal"
    ajustes.tiktok_modo = ModoTikTok.PUBLICO
    ajustes.pagina_facebook = Pagina("111", "Personal")
    ajustes.plataformas_redes = [T]
    ajustes.guardar_cuentas({T: Cuenta(T, "Personal TT")})
    ajustes.anadir_perfil(P, "six")
    six = ajustes.de_perfil(P, "six")
    six.ciudad = Ciudad.SEVILLA
    six.x_premium = True
    six.youtube_categoria = "28"
    six.pagina_facebook = Pagina("222", "Six")
    six.plataformas_redes = [Y]
    six.guardar_cuentas({T: Cuenta(T, "Six TT")})


def _responder_redes(monkeypatch, respuesta):
    preguntas = []

    def pregunta(*args, **kwargs):
        preguntas.append(args[2])
        return respuesta

    monkeypatch.setattr("app.widgets.dialogo_redes.QMessageBox.question", pregunta)
    return preguntas


def test_redes_carga_los_datos_del_perfil_elegido_y_guarda_en_el(qtbot, ajustes,
                                                                  llavero_falso):
    _dos_perfiles(ajustes)
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    combo = dialogo.combo_perfil
    assert [combo.itemText(i) for i in range(combo.count())] == ["personal", "six"]
    assert dialogo.campo_perfil.text() == "personal"
    assert dialogo.combo_tiktok.currentData() == ModoTikTok.PUBLICO.value
    _elegir(combo, "six")
    assert dialogo.combo_tiktok.currentData() == ModoTikTok.BORRADOR.value
    assert dialogo.casilla_x_premium.isChecked()
    assert dialogo.combo_categoria.currentData() == "28"
    assert dialogo.pagina_elegida() == Pagina("222", "Six")
    assert dialogo.etiqueta_ubicacion.text().startswith("Sevilla")
    assert "Six TT" in dialogo.etiquetas_cuentas[T].text()
    dialogo.combo_instagram.setCurrentIndex(
        dialogo.combo_instagram.findData(ModoInstagram.NORMAL.value))
    dialogo.accept()
    assert ajustes.perfil_redes == "six"
    assert ajustes.instagram_modo == ModoInstagram.NORMAL
    personal = ajustes.de_perfil(P, "personal")
    assert personal.tiktok_modo == ModoTikTok.PUBLICO
    assert personal.instagram_modo == ModoInstagram.PRUEBA
    assert personal.pagina_facebook == Pagina("111", "Personal")


def test_escribir_un_perfil_nuevo_empieza_con_los_valores_de_siempre(qtbot, ajustes,
                                                                      llavero_falso):
    _dos_perfiles(ajustes)
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    dialogo.campo_perfil.setText("nuevo")
    dialogo.campo_perfil.editingFinished.emit()
    assert dialogo.combo_tiktok.currentData() == ModoTikTok.BORRADOR.value
    assert dialogo.pagina_elegida() is None
    assert not dialogo.boton_quitar_perfil.isEnabled()
    dialogo.accept()
    assert ajustes.perfiles_de(P) == ["personal", "six", "nuevo"]
    assert ajustes.tiktok_modo == ModoTikTok.BORRADOR


def test_buscar_perfiles_anade_los_del_servicio(qtbot, ajustes, llavero_falso):
    ajustes.perfil_redes = "personal"
    capturado: dict = {}
    dialogo = _redes(qtbot, ajustes, ProveedorFalso(perfiles_cuenta=["personal", "six"]),
                     capturado)
    dialogo.campo_clave.setText(CLAVE)
    dialogo.boton_buscar_perfiles.click()
    _esperar_consultas(qtbot)
    assert capturado["clave"] == CLAVE and capturado["datos"]["perfil"] == ""
    combo = dialogo.combo_perfil
    assert [combo.itemText(i) for i in range(combo.count())] == ["personal", "six"]
    assert ajustes.perfiles_de(P) == ["personal", "six"]
    assert dialogo.campo_perfil.text() == "personal"  # lo escrito no cambia
    assert "six" in dialogo.etiqueta_consulta.text()
    assert dialogo.boton_buscar_perfiles.isEnabled()


def test_si_la_lista_falla_el_perfil_se_escribe_a_mano(qtbot, ajustes, llavero_falso):
    credenciales.guardar(P, CLAVE)
    dialogo = _redes(qtbot, ajustes, ProveedorFalso(perfiles_cuenta=ErrorConsulta(
        "Respuesta inesperada del servicio: no trae los perfiles.")))
    dialogo.boton_buscar_perfiles.click()
    _esperar_consultas(qtbot)
    assert "no trae los perfiles" in dialogo.etiqueta_consulta.text()
    assert CLAVE not in dialogo.etiqueta_consulta.text()
    assert dialogo.boton_buscar_perfiles.isEnabled()
    dialogo.campo_perfil.setText("a_mano")
    dialogo.accept()
    assert ajustes.perfil_redes == "a_mano" and ajustes.perfiles_de(P) == ["a_mano"]


def test_quitar_perfil_pide_confirmacion_y_borra_sus_datos(qtbot, ajustes, llavero_falso,
                                                           monkeypatch):
    _dos_perfiles(ajustes)
    dialogo = DialogoRedes(ajustes)
    qtbot.addWidget(dialogo)
    _elegir(dialogo.combo_perfil, "six")
    assert dialogo.boton_quitar_perfil.isEnabled()
    preguntas = _responder_redes(monkeypatch, QMessageBox.StandardButton.No)
    dialogo.boton_quitar_perfil.click()
    assert "six" in preguntas[0] and ajustes.perfiles_de(P) == ["personal", "six"]
    _responder_redes(monkeypatch, QMessageBox.StandardButton.Yes)
    dialogo.boton_quitar_perfil.click()
    assert ajustes.perfiles_de(P) == ["personal"]
    assert ajustes.de_perfil(P, "six").x_premium is False
    assert dialogo.campo_perfil.text() == "personal"
    assert dialogo.combo_tiktok.currentData() == ModoTikTok.PUBLICO.value
```

`tests/test_app_main.py`:

```python
def test_cerrar_redes_sin_guardar_tambien_avisa(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)

    class Falso(_DialogoFalso):
        abiertos: list = []

    monkeypatch.setattr("app.main.DialogoRedes", Falso)
    avisos = []
    ventana._configurar_redes(lambda: avisos.append(1))
    assert avisos == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_app_perfiles.py tests/test_app_main.py -k "redes or perfil"`
Expected: FAIL (no existen `combo_perfil`, `boton_buscar_perfiles`, `boton_quitar_perfil`).

- [ ] **Step 3: Implement**

En `dialogo_redes.py`:
- **Constructor:** crea los combos de modos y categoría con sus elementos pero sin elegir valor (lo elige `_cargar_perfil`). Conecta `combo_perfil.activated` y `campo_perfil.editingFinished` a `_al_cambiar_perfil`, que llama a `_cargar_perfil()` solo si el texto (con `strip`) no es el perfil ya cargado (`self._perfil_cargado`).
- **`_poner_perfiles()`:** rellena el combo con `perfiles_de(self.proveedor)` y vuelve a poner el texto que había. Ojo: al añadir elementos, `QComboBox` elige el primero y pisa el texto. También habilita «Quitar perfil» solo si el texto está en la lista; esto mismo va conectado a `campo_perfil.textChanged`.
- **`_al_cambiar_proveedor`:** se queda con lo del servicio (habilitar el combo según `usa_perfil`, ayuda, clave y `_refrescar_clave`). Luego `_poner_perfiles()`, `campo_perfil.setText(self.ajustes.perfil_de(self.proveedor))` y `_cargar_perfil()`.
- **`_cargar_perfil()`:** apunta `_perfil_cargado`. Con `datos = self._datos()`, rellena:
  - modos de TikTok, Instagram y Facebook;
  - categoría de YouTube, con la lógica de hoy para una categoría que no está en la lista;
  - X Premium, ocultando `nota_x_premium`.

  Después sube `_consulta_n` y pone `_comprobadas = None` y `boton_comprobar` habilitado. Limpia y oculta la página manual y `aviso_pagina`, y llama a `_poner_paginas` con `datos.pagina_facebook`. Por último, con `datos.cuentas_guardadas()`: `_ubicacion = None`, `_cuenta_tiktok`, `_refrescar_ubicacion()` y lo de cuentas y «Última comprobación» que hoy hace `_al_cambiar_proveedor`.
- **Ubicación:** `_refrescar_ubicacion` lee `self._datos().ciudad`. `_cambiar_ubicacion` llama a `ubicacion_guardada(self._datos(), ...)` con el perfil escrito. El lugar de TikTok se sigue leyendo del Llavero solo al pulsar Cambiar…, ya con ese perfil.
- **«Buscar perfiles»:**
  - Al pulsar: deshabilita el botón y muestra `_poner_consulta(_("Buscando perfiles…"))`. En segundo plano (`"tsots-perfiles"`), `(nombre, consulta_cuentas.listar_perfiles(llavero, fabrica, nombre, clave=clave))`, con la clave escrita o `None`.
  - Al volver: rehabilita el botón y descarta el resultado si `nombre != self.proveedor`.
  - Con error: `_poner_consulta(motivo, COLOR_ERROR)`.
  - Si no: `anadir_perfil` de cada uno y `_poner_perfiles()`. Luego `_poner_consulta(_("Perfiles en el servicio: {lista}.").format(lista=", ".join(perfiles)), COLOR_OK)`, o `_("El servicio no tiene perfiles.")` si no hay ninguno.
- **«Quitar perfil»:** `QMessageBox.question(self, _("Quitar perfil"), _("¿Quitar el perfil «{perfil}» de TSOTS? Se borran sus ajustes de publicación en la app; en {servicio} no cambia nada."), Yes | No, No)`. Con Sí: `quitar_perfil`, `_poner_perfiles()`, `campo_perfil.setText(self.ajustes.perfil_de(self.proveedor))` y `_cargar_perfil()`.
- **`accept()`:**
  1. La clave, como hoy.
  2. `perfil = self.campo_perfil.text().strip()` y `datos = self.ajustes.de_perfil(self.proveedor, perfil)`.
  3. `guardar_ubicacion(datos, …, perfil, …)` si hay `_ubicacion`, con el mismo `try`.
  4. `self.ajustes.proveedor_redes = self.proveedor` y `self.ajustes.guardar_perfil(self.proveedor, perfil)`.
  5. Modos, categoría, X Premium y `pagina_facebook` en `datos`.
  6. `datos.guardar_cuentas(...)` si `_comprobadas[0] == perfil`.

En `main.py`: renombra `al_guardar` a `al_cerrar` y llámalo siempre. El diálogo Publicar recibe así los perfiles quitados aunque se cancele Redes….

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_app_perfiles.py tests/test_app_redes.py tests/test_app_main.py`
Expected: PASS (los tests de Redes… de hoy siguen en verde sin cambios).

- [ ] **Step 5: Commit**

```bash
git add app/widgets/dialogo_redes.py app/main.py tests/test_app_perfiles.py tests/test_app_main.py
git commit -m "feat: manage several profiles in the Networks dialog"
```

---

### Task 6: Elegir el perfil al publicar

**Files:**
- Modify: `app/widgets/dialogo_publicar.py` (`__init__` ~línea 214, fila del servicio ~línea 429, `refrescar_servicio` ~726, `_refrescar_etiqueta_servicio` ~742, `_recordar_eleccion` ~950, `_bloquear` ~1083)
- Modify: `app/main.py` (`_publicar`, `_publicar_shorts`)
- Modify: `tests/test_app_perfiles.py`, `tests/test_app_redes.py` (`test_boton_deshabilitado_sin_clave_perfil_o_plataformas`), `tests/test_app_publicar_shorts.py`, `tests/test_app_main.py`

**Interfaces:**
- Consumes: `SelectorPerfil` (tarea 4), `VentanaPrincipal._anotar_perfil` (tarea 3), `_dos_perfiles` y `_elegir` (tareas 4-5).
- Produces:
  - `DialogoPublicar.__init__(..., zona=None, perfil: str = "", parent=None)`. Justo tras `self.ajustes = ajustes`, antes de leer nada más de los ajustes: si `perfil` está en `ajustes.perfiles_de(ajustes.proveedor_redes)` y no es el activo, `ajustes.perfil_redes = perfil`. `DialogoPublicarShorts` lo recibe por `**kwargs`.
  - `DialogoPublicar.selector_perfil: SelectorPerfil`, en la fila del servicio: `etiqueta_servicio`, `QLabel(_("Perfil:"))`, el selector, «Redes…».
  - `DialogoPublicar.perfil_usado: str`: `""` hasta que se envía; `_recordar_eleccion` lo fija al perfil activo (vale para el diálogo de un vídeo y para el de shorts).
  - Comportamiento:
    - `refrescar_servicio()` empieza con `self.selector_perfil.recargar(self.ajustes)`.
    - Si el perfil activo ya no es `self._perfil_leido`, iniciado al acabar la activación del constructor, lo apunta y vuelve a leer las plataformas deseadas (`_deseadas`) y los tres combos de modos de ese perfil. Quita la ubicación «solo este vídeo» (`_ubicacion_propia = None`): su lugar de TikTok era de otra cuenta. Lo demás (cuentas, ciudad, consulta) sigue como hoy.
    - El selector conecta a `_al_elegir_perfil(perfil)`: `self.ajustes.perfil_redes = perfil` y `self.refrescar_servicio()`. El caption no se toca.
    - `_refrescar_etiqueta_servicio` ya no añade «· perfil «x»»; conserva «Vía {servicio}», el aviso del email y el de las cuentas.
    - `_bloquear` incluye `self.selector_perfil`.

- [ ] **Step 1: Write the failing tests**

`tests/test_app_perfiles.py` (añade `import threading`, `from app.widgets.dialogo_publicar import DialogoPublicar` y, de `tests.test_app_redes`, `_caption`, `duracion_falsa`, `sin_hilos_colgando` y `video`, con `# noqa: F401`: los dos fixtures autouse cuentan en este módulo):

```python
def _publicar(qtbot, video, ajustes, fabrica=None, **kwargs):
    dialogo = DialogoPublicar(video, _caption(), ajustes,
                              fabrica=fabrica or (lambda n, c, d: ProveedorFalso()), **kwargs)
    qtbot.addWidget(dialogo)
    return dialogo


def test_publicar_abre_con_el_perfil_de_la_ficha(qtbot, video, ajustes, llavero_falso):
    _dos_perfiles(ajustes)
    credenciales.guardar(P, CLAVE)
    dialogo = _publicar(qtbot, video, ajustes, perfil="six")
    assert ajustes.perfil_redes == "six"
    assert dialogo.selector_perfil.currentText() == "six"
    assert dialogo.etiqueta_servicio.text().startswith("Vía")
    assert "six" not in dialogo.etiqueta_servicio.text()  # el perfil ya lo dice el selector


def test_publicar_con_un_perfil_que_ya_no_existe_deja_el_activo(qtbot, video, ajustes,
                                                                llavero_falso):
    _dos_perfiles(ajustes)
    dialogo = _publicar(qtbot, video, ajustes, perfil="borrado")
    assert ajustes.perfil_redes == "personal"
    assert dialogo.selector_perfil.currentText() == "personal"


def test_cambiar_de_perfil_al_publicar_recarga_sus_datos(qtbot, video, ajustes,
                                                         llavero_falso):
    _dos_perfiles(ajustes)  # sin clave: no consulta, se ven las cuentas guardadas
    dialogo = _publicar(qtbot, video, ajustes)
    assert dialogo.etiqueta_ubicacion.text().startswith("Madrid")
    assert dialogo._cuentas[T].nombre == "Personal TT"
    assert [p for p, c in dialogo.casillas.items() if c.isChecked()] == [T]
    assert dialogo.combo_tiktok.currentData() == ModoTikTok.PUBLICO.value
    _elegir(dialogo.selector_perfil, "six")
    assert ajustes.perfil_redes == "six"
    assert dialogo.etiqueta_ubicacion.text().startswith("Sevilla")
    assert dialogo._cuentas[T].nombre == "Six TT"
    assert [p for p, c in dialogo.casillas.items() if c.isChecked()] == [Y]
    assert dialogo.combo_tiktok.currentData() == ModoTikTok.BORRADOR.value
    assert dialogo.campo_caption.toPlainText() == "Cuerpo del caption"  # no se regenera


def test_el_selector_se_bloquea_mientras_publica(qtbot, video, ajustes, llavero_falso):
    _dos_perfiles(ajustes)
    dialogo = _publicar(qtbot, video, ajustes)
    dialogo._bloquear(True)
    assert not dialogo.selector_perfil.isEnabled()
    dialogo._bloquear(False)
    assert dialogo.selector_perfil.isEnabled()


def test_respuesta_tardia_de_otro_perfil_no_se_guarda(qtbot, video, ajustes, llavero_falso):
    _dos_perfiles(ajustes)
    credenciales.guardar(P, CLAVE)
    soltar = threading.Event()

    class Lento(ProveedorFalso):
        def cuentas(self):
            soltar.wait(5)
            return super().cuentas()

    def fabrica(nombre, clave, datos):
        if datos["perfil"] == "personal":
            return Lento()
        return ProveedorFalso(cuentas_conectadas=ErrorConsulta("caído"))

    dialogo = _publicar(qtbot, video, ajustes, fabrica)
    _elegir(dialogo.selector_perfil, "six")
    soltar.set()
    _esperar_consultas(qtbot)
    assert ajustes.de_perfil(P, "six").cuentas_guardadas().cuentas[T].nombre == "Six TT"
    assert ajustes.de_perfil(P, "personal").cuentas_guardadas().cuentas[T].nombre == (
        "Personal TT")
```

`tests/test_app_redes.py`, `test_boton_deshabilitado_sin_clave_perfil_o_plataformas`: `assert "yo" in dialogo.etiqueta_servicio.text()` pasa a `assert dialogo.selector_perfil.currentText() == "yo"`.

`tests/test_app_publicar_shorts.py`:

```python
def test_shorts_abre_con_el_perfil_del_video_largo(qtbot, carpeta, ajustes):
    ajustes.anadir_perfil(PROVEEDOR_POR_DEFECTO, "six")
    dialogo = DialogoPublicarShorts(
        shorts.listar(carpeta), ajustes, fabrica=lambda n, c, d: ProveedorFalso(),
        medir=lambda mp4: DURACIONES[Path(mp4).name], ahora=lambda: AHORA, zona=MADRID,
        perfil="six")
    qtbot.addWidget(dialogo)
    assert ajustes.perfil_redes == "six"
    assert dialogo.selector_perfil.currentText() == "six"
```

Y al final de `test_envia_cada_short_con_su_fecha_y_apunta_su_registro`, añade `assert dialogo.perfil_usado == "mi_perfil"`.

`tests/test_app_main.py`:

```python
def test_publicar_propone_el_perfil_de_la_ficha_y_anota_el_usado(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ficha = _ficha_hecha(tmp_path)
    ficha.perfil = "six"
    guardar(ficha)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    _eligiendo_la_fila(ventana)
    propuestos = []

    class Falso(_DialogoFalso):
        abiertos: list = []
        perfil_usado = "personal"

        def __init__(self, *args, perfil="", **kwargs):
            super().__init__(*args, **kwargs)
            propuestos.append(perfil)
            self.ajustes = args[2]

        def exec(self):
            self.ajustes.perfil_redes = "personal"
            return 0

    monkeypatch.setattr("app.main.DialogoPublicar", Falso)
    ventana.panel_caption.boton_publicar.click()
    assert propuestos == ["six"]
    assert cargar(ficha.id).perfil == "personal"
    assert ventana.cabecera.selector_perfil.currentText() == "personal"


def test_publicar_shorts_propone_el_perfil_de_la_ficha(qtbot, tmp_path, monkeypatch):
    ventana = _ventana(qtbot, tmp_path, monkeypatch)
    ventana.ajustes.perfil_redes = "personal"
    ventana.ajustes.anadir_perfil("upload_post", "six")
    ficha = _ficha_hecha(tmp_path)
    carpeta = _con_shorts_hechos(ficha)
    ficha.perfil = "six"
    guardar(ficha)
    ventana.anadir_videos([tmp_path / "a.mp4"])
    ventana.modelo_cola.actualizar(0, shorts=carpeta, n_shorts=1)
    _eligiendo_la_fila(ventana)
    activos = []
    monkeypatch.setattr(
        "app.widgets.dialogo_publicar_shorts.DialogoPublicarShorts.exec",
        lambda self: activos.append(self.ajustes.perfil_redes))
    ventana.panel.boton_publicar_shorts.click()
    assert activos == ["six"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PYTEST tests/test_app_perfiles.py tests/test_app_redes.py tests/test_app_publicar_shorts.py tests/test_app_main.py`
Expected: FAIL (no existen `perfil=` ni `selector_perfil` en Publicar).

- [ ] **Step 3: Implement**

- `dialogo_publicar.py`: lo descrito en **Interfaces**.
- `main.py`, `_publicar`:
  1. El trabajo elegido sale de `self.vista_cola.selectedIndexes()`, como en `_publicar_shorts`, y su ficha de `_ficha_de`.
  2. Se abre con `DialogoPublicar(video, caption, self.ajustes, perfil=ficha.perfil if ficha else "", parent=self)`.
  3. Tras `exec()`: `self._anotar_perfil(trabajo.ficha_id if trabajo else None, dialogo.perfil_usado)` y luego el `_recargar_perfil()` de la tarea 4.
- `main.py`, `_publicar_shorts`: lo mismo con su `trabajo` y `DialogoPublicarShorts(cortos, self.ajustes, perfil=..., parent=self)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_app_perfiles.py tests/test_app_redes.py tests/test_app_publicar_shorts.py tests/test_app_programar.py tests/test_app_main.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/widgets/dialogo_publicar.py app/main.py tests/test_app_perfiles.py tests/test_app_redes.py tests/test_app_publicar_shorts.py tests/test_app_main.py
git commit -m "feat: pick the profile in Publish, starting from the video's"
```

---

### Task 7: Programadas por perfil

**Files:**
- Modify: `app/widgets/dialogo_programadas.py` (`__init__` fila `pie`, `_ocupar`)
- Modify: `tests/test_app_perfiles.py`

**Interfaces:**
- Consumes: `SelectorPerfil` y `_elegir` (tarea 4).
- Produces:
  - `DialogoProgramadas.selector_perfil: SelectorPerfil`, al principio de `pie` tras `QLabel(_("Perfil:"))`, recargado en el constructor.
  - `_ocupar(ocupado)` también hace `self.selector_perfil.setEnabled(not ocupado)`: una respuesta nunca se pinta bajo otro perfil.
  - `_al_elegir_perfil(perfil)`: `self.ajustes.perfil_redes = perfil`, `self._programadas = []`, `self._pintar()`, `self.actualizar()`.

- [ ] **Step 1: Write the failing test**

`tests/test_app_perfiles.py` (añade `from datetime import datetime, timezone`, `from zoneinfo import ZoneInfo`, `from app import segundo_plano`, `from app.widgets.dialogo_programadas import DialogoProgramadas`):

```python
def test_programadas_de_otro_perfil(qtbot, ajustes, llavero_falso):
    ajustes.perfil_redes = "personal"
    ajustes.anadir_perfil(P, "six")
    credenciales.guardar(P, "clave")
    pedidos: list[str] = []

    def fabrica(nombre, clave, datos):
        pedidos.append(datos["perfil"])
        return ProveedorFalso()

    dialogo = DialogoProgramadas(ajustes, fabrica=fabrica, zona=ZoneInfo("Europe/Madrid"),
                                 ahora=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
    qtbot.addWidget(dialogo)
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=5000)
    assert dialogo.selector_perfil.currentText() == "personal" and pedidos == ["personal"]
    _elegir(dialogo.selector_perfil, "six")
    assert not dialogo.selector_perfil.isEnabled()  # consultando
    qtbot.waitUntil(lambda: segundo_plano.vivas() == 0, timeout=5000)
    assert pedidos == ["personal", "six"] and ajustes.perfil_redes == "six"
    assert dialogo.selector_perfil.isEnabled()
    assert "No hay nada programado" in dialogo.etiqueta_estado.text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$PYTEST tests/test_app_perfiles.py -k programadas`
Expected: FAIL (`selector_perfil` no existe).

- [ ] **Step 3: Implement** lo descrito en **Interfaces**.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PYTEST tests/test_app_perfiles.py tests/test_app_programadas.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/widgets/dialogo_programadas.py tests/test_app_perfiles.py
git commit -m "feat: switch profile in the scheduled posts calendar"
```

---

### Task 8: Traducciones y documentación

**Files:**
- Modify: `locale/tsots.pot`, `locale/en/LC_MESSAGES/tsots.po`, `locale/en/LC_MESSAGES/tsots.mo` (los tres los regenera `lanzador/traducir.sh`)
- Modify: `tests/test_i18n.py`
- Modify: `README.md`, `README.es.md`, `docs/DEVELOPMENT.md`, `docs/TODO.md`

- [ ] **Step 1: Write the failing test** (`tests/test_i18n.py`)

```python
def test_catalogo_ingles_traduce_los_perfiles():
    i18n.instalar("en")
    try:
        assert i18n._("Buscar perfiles") == "Find profiles"
        assert i18n._("Quitar perfil") == "Remove profile"
        assert i18n._("Sin perfil: añádelo en Redes…") == "No profile: add one in Networks…"
    finally:
        i18n.instalar("es")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `$PYTEST tests/test_i18n.py`
Expected: FAIL (devuelve el texto en español).

- [ ] **Step 3: Translate**

Ejecuta `lanzador/traducir.sh` y rellena en `tsots.po` los `msgstr` vacíos o `#, fuzzy` (quita la marca `fuzzy`). Las cadenas nuevas:

| msgid | msgstr |
|---|---|
| Sin perfil: añádelo en Redes… | No profile: add one in Networks… |
| Buscar perfiles | Find profiles |
| Pregunta al servicio qué perfiles tiene tu cuenta | Asks the service which profiles your account has |
| Buscando perfiles… | Looking for profiles… |
| Perfiles en el servicio: {lista}. | Profiles in the service: {lista}. |
| El servicio no tiene perfiles. | The service has no profiles. |
| Quitar perfil | Remove profile |
| ¿Quitar el perfil «{perfil}» de TSOTS? Se borran sus ajustes de publicación en la app; en {servicio} no cambia nada. | Remove the profile “{perfil}” from TSOTS? Its publishing settings in the app are deleted; nothing changes in {servicio}. |
| Respuesta inesperada del servicio: no trae los perfiles. | Unexpected response from the service: it does not include the profiles. |
| Error inesperado al buscar los perfiles ({tipo}). | Unexpected error while looking for the profiles ({tipo}). |
| Contexto de marca · perfil «{perfil}» | Brand context · profile “{perfil}” |

Luego `lanzador/traducir.sh --solo-mo`. Comprueba que no queda ninguna: `grep -c '^#, fuzzy' locale/en/LC_MESSAGES/tsots.po` da `0` y `msgfmt --statistics -o /dev/null locale/en/LC_MESSAGES/tsots.po` no cuenta ninguna sin traducir.

- [ ] **Step 4: Run it to verify it passes**

Run: `$PYTEST tests/test_i18n.py`
Expected: PASS.

- [ ] **Step 5: Update the docs**

- `README.md` y `README.es.md`, en la sección de Networks…/Redes…:
  - varios perfiles de upload-post con una sola API key: el selector «Profile:»/«Perfil:» de la cabecera, «Find profiles»/«Buscar perfiles» y «Remove profile»/«Quitar perfil»;
  - qué guarda cada perfil (ubicación, página de Facebook, redes marcadas, modos, X Premium, categoría, cuentas y contexto de marca);
  - Publicar propone el perfil con que se procesó el vídeo y deja cambiarlo; el caption no se regenera.
- `docs/DEVELOPMENT.md`:
  - el párrafo «Settings (QSettings `redes/*`)»: `redes/perfiles/<proveedor>`, `redes/perfil_datos/<proveedor>/<huella>/<clave>`, la migración y la herencia del primer perfil, que sin perfil activo se usan las claves de siempre, `Ajustes.de_perfil` y que las versiones anteriores siguen leyendo `redes/perfil/<proveedor>`;
  - `perfiles()` en la fila de `proveedor.py` y en la de `upload_post.py` (`GET /api/uploadposts/users`);
  - `selector_perfil.py` en la lista de la GUI;
  - el campo `perfil` en la descripción de `ficha.json`.
- `docs/TODO.md`, en Features:
  - verificar contra el servicio real la forma de `GET /api/uploadposts/users` (sin verificar: si falla, el perfil se escribe a mano);
  - los lugares de TikTok de un perfil quitado quedan huérfanos en el Llavero.

- [ ] **Step 6: Full verification**

Run: `$PYTEST --ignore=tests/test_redes_real.py --ignore=tests/test_redes_real_programar.py`
Expected: PASS (los `lenta` quedan fuera por `addopts`).

- [ ] **Step 7: Commit**

```bash
git add locale tests/test_i18n.py README.md README.es.md docs/DEVELOPMENT.md docs/TODO.md docs/superpowers
git commit -m "docs: publishing profiles, with English translations"
```
