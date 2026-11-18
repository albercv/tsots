# Cumplimiento de normas al publicar y portada con título — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que TSOTS publique cumpliendo lo que exigen TikTok, Instagram y YouTube (y lo que se pueda en el resto) y que cada publicación lleve una portada en la que se vea el título.

**Architecture:** El título baja al 23 % en vertical y aparece entero desde el fotograma 0. `upload_post.campos` envía los campos nuevos según `Opciones` y `Publicacion` ampliadas. El proveedor gana `ajustes_tiktok()`. `HiloPublicacion` elige la portada (fotograma más nítido de 0,5 a 4,5 s) antes de subir. El diálogo de publicar muestra lo que exige la «Required UX» de TikTok y un bloque de contenido comercial común.

**Tech Stack:** Python 3, PySide6, OpenCV (`cv2`, ya instalado), httpx, pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-11-18-cumplimiento-redes-design.md`

## Global Constraints

- Código, comentarios e interfaz en español. Las cadenas nuevas van con `_()` (o `N_()` en tablas) y se traducen al inglés en `locale/en/LC_MESSAGES/tsots.po`: ejecutar `lanzador/traducir.sh` y rellenar los `msgstr`.
- Commits en inglés y **sin atribución de IA** (sin `Co-Authored-By` ni «Generated with»).
- Tests: `QT_QPA_PLATFORM=offscreen ~/Documents/personalProjects/limpiadorVideo/.venv-clearvoice/bin/python -m pytest -q`. Ruido conocido en worktrees: `tests/test_pipeline.py::test_solo_vertical_cara_con_subs`.
- Los tests no salen a la red ni al Llavero (guardas de `tests/conftest.py`). El proveedor falso es `ProveedorFalso` (`tests/redes_falsos.py`).
- `videopipeline/redes/upload_post.py` es el único módulo que conoce Upload-Post (URLs, nombres de campo).
- La app no carga S3FD ni torch: la portada usa solo OpenCV.
- No se leen ni se guardan credenciales nuevas. Publicar de verdad lo autoriza el usuario: ningún test ni paso del plan publica.
- Valores del diseño:
  - título vertical al **23 %** (`MARGEN_SUPERIOR_VERTICAL = 0.23`), horizontal al 8 % (`MARGEN_SUPERIOR = 0.08`);
  - fundido del título `\fad(0,300)`;
  - instantes de portada: 0.5, 1.0, …, 4.5 s, menores que la duración del vídeo;
  - privacidades de TikTok y sus textos:
    - `PUBLIC_TO_EVERYONE` → «Todo el mundo»
    - `FOLLOWER_OF_CREATOR` → «Seguidores»
    - `MUTUAL_FOLLOW_FRIENDS` → «Amigos»
    - `SELF_ONLY` → «Solo yo»
  - textos de TikTok:
    - etiqueta con solo «Tu marca»: «Se etiquetará como "Contenido promocional"»;
    - etiqueta con «Contenido de marca», sola o con «Tu marca»: «Se etiquetará como "Colaboración pagada"»;
    - consentimiento sin contenido de marca: «Al publicar, aceptas la Confirmación de uso de música de TikTok»;
    - consentimiento con contenido de marca: «Al publicar, aceptas la Política de contenido de marca y la Confirmación de uso de música de TikTok»;
    - al elegir «Contenido de marca»: «El contenido de marca no puede ser privado»;
  - contenido comercial encendido sin ninguna casilla: «Indica si promocionas algo tuyo, de un tercero o ambos»;
  - idioma: «es» → `es`/`es-ES`, «en» → `en`/`en-US`, «auto» o desconocido → no se envía.

## Review Focus

1. Publicar en TikTok en modo directo sin privacidad elegida (por una vía que no sea el botón, p. ej. «Publicar shorts» o una programación) **no** debe acabar en `PUBLIC_TO_EVERYONE` por defecto: el proveedor devuelve un error y no envía nada (Task 2).
2. Los permisos de TikTok no cargan (sin red, reconectar, 409): el modo directo queda bloqueado con el motivo y el borrador sigue disponible (Task 5).
3. «Contenido de marca» con «Solo yo» ya elegido: la elección se vacía y «Publicar» se bloquea hasta elegir otra (Task 5).
4. Vídeo ilegible o de menos de 0,5 s: se publica sin campos de portada y sin miniatura, sin romper (Task 4).
5. «Publicar shorts» programa varios shorts: cada uno lleva su propia portada y las elecciones de TikTok valen para todos (Task 5).

---

### Task 1: Título al 23 % en vertical y entero desde el primer fotograma

**Files:**
- Modify: `videopipeline/titulo.py` (constantes y `lineas_titulo`), `videopipeline/edicion/zonas.py:40`
- Test: `tests/test_titulo.py`, los tests de zonas de `videopipeline/edicion` (buscar `zonas.calcular` en `tests/`)

**Interfaces:**
- Produces: `titulo.MARGEN_SUPERIOR_VERTICAL = 0.23`. `lineas_titulo` usa `MARGEN_SUPERIOR_VERTICAL` cuando `alto > ancho` y `MARGEN_SUPERIOR` (0.08) si no. `zonas.calcular` usa `MARGEN_SUPERIOR_VERTICAL` para la franja del título.

- [ ] **Step 1: Tests**:
  - vertical `(1080, 1920)`: `\pos(540,442)` (442 = round(0.23 × 1920)) y `\fad(0,300)`;
  - horizontal `(1920, 1080)`: sigue `\pos(960,86)`, ahora con `\fad(0,300)` (actualizar el test existente de la línea 83);
  - zonas con título: `titulo["y"][0] == 442`.
- [ ] **Step 2:** Ver que fallan.
- [ ] **Step 3:** Implementar. Revisar que los tests de `videopipeline/edicion` y de `shorts` que dependan de la franja del título siguen en verde y actualizar los valores esperados que cambien.
- [ ] **Step 4:** Suite completa en verde.
- [ ] **Step 5:** Commit `feat: title at 23% on vertical videos, fully visible from the first frame`.

### Task 2: Campos nuevos de cada red en la subida

**Files:**
- Modify: `videopipeline/redes/modelo.py` (`Opciones`, `Publicacion`, constantes), `videopipeline/redes/upload_post.py` (`campos`, `ProveedorUploadPost.publicar`)
- Test: `tests/test_redes_upload_post.py`

**Interfaces:**
- Produces (en `modelo.py`):
  - `PRIVACIDADES_TIKTOK: dict[str, str]` con los cuatro valores y textos de Global Constraints, como `N_()`, en ese orden.
  - `Opciones` gana, al final y con estos valores por defecto:
    - `tiktok_privacidad: str = ""`
    - `tiktok_comentarios: bool = False`
    - `tiktok_duos: bool = False`
    - `tiktok_stitch: bool = False`
    - `tu_marca: bool = False`
    - `contenido_de_marca: bool = False`
    - `idioma: str = ""`
  - `Publicacion` gana `portada: float | None = None` (segundos) y `miniatura: Path | None = None` (JPEG).
- Produces (en `upload_post.py`), en `campos(...)`:
  - **TikTok directo (`PUBLICO`):**
    - `privacy_level` = `opciones.tiktok_privacidad`, ya no `PUBLIC_TO_EVERYONE` fijo;
    - `disable_comment`, `disable_duet` y `disable_stitch` = `"true"` si la casilla correspondiente **no** está marcada;
    - si `tu_marca` o `contenido_de_marca`: `disclose_commercial="true"`, `your_brand` y `branded_content` como `"true"`/`"false"`;
    - si `publicacion.portada` no es None: `cover_timestamp=str(round(portada*1000))`.
  - **TikTok borrador:** igual que hoy, sin ninguno de esos campos.
  - **YouTube:**
    - `selfDeclaredMadeForKids="false"` siempre;
    - `defaultLanguage` y `defaultAudioLanguage` según `opciones.idioma` (Global Constraints);
    - `hasPaidProductPlacement="true"` si `contenido_de_marca`.
  - **Instagram:** `thumb_offset=str(round(portada*1000))` si hay portada.
  - **X:** `x_paid_partnership="true"` si `contenido_de_marca`.
  - Comentario de una línea junto a las marcas de IA explicando por qué van en `false`: TSOTS no genera personas, voces ni escenas realistas.
  - `ProveedorUploadPost.publicar`:
    - en YouTube con `publicacion.miniatura`, añade la parte `files["thumbnail"] = (nombre, archivo abierto, "image/jpeg")` junto a `video`;
    - **TikTok directo sin `tiktok_privacidad`** devuelve `Resultado(ok=False, error=_("Elige quién puede verlo en TikTok"))` **sin hacer la petición**.

- [ ] **Step 1: Tests** (`upload_post.campos` y `publicar` con `http` falso, como los existentes):
  - TikTok directo con privacidad `SELF_ONLY` y casillas sin marcar da `disable_*` todos `"true"` y ningún `disclose_commercial`;
  - con comentarios marcados da `disable_comment == "false"`;
  - con `tu_marca`: `disclose_commercial="true"`, `your_brand="true"` y `branded_content="false"`;
  - con portada 1.5 da `cover_timestamp == "1500"`;
  - TikTok borrador con todo lo anterior no envía `privacy_level`, `disable_*`, `disclose_commercial` ni `cover_timestamp`;
  - YouTube con `idioma="es"` da `es`/`es-ES`, con «en» da `en`/`en-US` y con «auto» o «» no envía ninguno; `selfDeclaredMadeForKids == "false"` siempre; `hasPaidProductPlacement` solo con `contenido_de_marca`;
  - Instagram con portada 2.0 da `thumb_offset == "2000"`;
  - X con `contenido_de_marca` da `x_paid_partnership == "true"`; con solo `tu_marca` no lo envía;
  - `publicar` en YouTube con `miniatura` envía la parte `thumbnail`, y en TikTok no la envía;
  - `publicar` en TikTok directo sin privacidad devuelve `ok=False` con ese error y no llama a `http.post`.
- [ ] **Step 2:** Ver que fallan.
- [ ] **Step 3:** Implementar. Actualizar los tests existentes que esperaban `privacy_level == "PUBLIC_TO_EVERYONE"`.
- [ ] **Step 4:** Suite completa en verde.
- [ ] **Step 5:** Commit `feat: send compliance fields, covers and language to each network`.

### Task 3: Permisos de la cuenta de TikTok

**Files:**
- Modify: `videopipeline/redes/modelo.py`, `videopipeline/redes/proveedor.py`, `videopipeline/redes/upload_post.py`, `tests/redes_falsos.py`
- Test: `tests/test_redes_upload_post.py`, `tests/test_redes_contrato.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class AjustesTikTok: privacidades: tuple[str, ...]; max_segundos: int | None = None; comentarios_off: bool = False; duos_off: bool = False; stitch_off: bool = False` en `modelo.py`.
  - `Proveedor.ajustes_tiktok(self) -> AjustesTikTok` en el protocolo, documentado: solo lanza `ErrorConsulta`.
  - `ProveedorUploadPost.ajustes_tiktok()`:
    - `GET {URL_API}/uploadposts/tiktok/settings?profile=<perfil>` con `_consultar`;
    - lee `privacy_level_options` (solo los cuatro valores conocidos, en el orden de `PRIVACIDADES_TIKTOK`), `max_video_post_duration_sec`, `comment_disabled`, `duet_disabled` y `stitch_disabled`.
  - `_mensaje_http`: una respuesta con `reauth_required` (409, por ejemplo) da el mismo texto de «Reconecta TikTok…» que `tiktok_reconnect_required`.
  - `ProveedorFalso` acepta `ajustes_tiktok: AjustesTikTok | Exception | None` en el constructor (por defecto, las cuatro privacidades y sin límites). Lo devuelve o lo lanza y anota la consulta en `.consultas`.

- [ ] **Step 1: Tests**:
  - respuesta buena (ejemplo del OpenAPI: `["FOLLOWER_OF_CREATOR","MUTUAL_FOLLOW_FRIENDS","SELF_ONLY"]`, 600, `comment_disabled=true`) → `AjustesTikTok` con esos valores y la URL y el parámetro `profile` correctos;
  - un valor desconocido en la lista se ignora;
  - 400 con `tiktok_reconnect_required` → `ErrorConsulta` con «Reconecta TikTok»;
  - 409 con `reauth_required` → el mismo texto;
  - 502 → `ErrorConsulta`;
  - sin red → `ErrorConsulta`;
  - el contrato de `test_redes_contrato.py` incluye `ajustes_tiktok`.
- [ ] **Step 2:** Ver que fallan.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa en verde.
- [ ] **Step 5:** Commit `feat: read the TikTok account's publishing settings`.

### Task 4: Fotograma de portada antes de subir

**Files:**
- Create: `videopipeline/redes/portada_video.py`
- Modify: `app/widgets/dialogo_publicar.py` (`HiloPublicacion.run`)
- Test: `tests/test_redes_portada_video.py`, `tests/test_app_redes.py` (o el test de `HiloPublicacion` que exista)

**Interfaces:**
- Consumes: `Publicacion.portada` y `Publicacion.miniatura` (Task 2); `fotogramas.nitidez` y `fotogramas._leer_cv2` (existentes, solo OpenCV).
- Produces (en `portada_video.py`):
  - `INSTANTES = tuple(x / 2 for x in range(1, 10))`, es decir de 0.5 a 4.5.
  - `elegir(video: Path, duracion: float | None = None, leer=None) -> tuple[float, "np.ndarray"] | None`:
    - el instante más nítido entre los `INSTANTES` menores que la duración (si `duracion` es None, se lee con `steps.duracion_video`);
    - None si no se pudo leer ningún fotograma;
    - nunca lanza: cualquier error devuelve None y queda en el log.
  - `con_portada(publicacion: Publicacion, carpeta: Path) -> Publicacion`:
    - llama a `elegir`;
    - si hay fotograma, escribe `carpeta / "miniatura.jpg"` (JPEG calidad 92) y devuelve `replace(publicacion, portada=segundo, miniatura=ruta)`;
    - si no, devuelve la publicación tal cual.
  - `HiloPublicacion.run`: antes de `publicador.publicar`, en un `tempfile.TemporaryDirectory()` que dura toda la publicación, `self._publicacion = con_portada(self._publicacion, Path(tmp))`.

- [ ] **Step 1: Tests** (usar el fixture `video_vertical` de `conftest.py` y un `leer` falso):
  - con un `leer` que devuelve fotogramas de nitidez creciente, se elige 4.5;
  - con duración 2.0 solo se miran 0.5, 1.0 y 1.5;
  - con duración 0.3 sale None;
  - con un `leer` que siempre devuelve None sale None;
  - con un `leer` que lanza sale None, sin lanzar;
  - `con_portada` con el vídeo real `video_vertical` escribe un JPEG legible y rellena `portada` y `miniatura`;
  - con un vídeo inexistente devuelve la publicación sin cambios;
  - `HiloPublicacion` pasa a `publicador.publicar` una publicación con `portada` rellena (sustituir `publicador.publicar` por un falso que la capture).
- [ ] **Step 2:** Ver que fallan.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suite completa en verde.
- [ ] **Step 5:** Commit `feat: pick a title-visible cover frame before uploading`.

### Task 5: Diálogo de publicar conforme con TikTok y contenido comercial

**Files:**
- Modify: `app/widgets/dialogo_publicar.py`, `app/widgets/dialogo_publicar_shorts.py` (solo si hace falta que la vista previa siga al primer short marcado)
- Create: `tests/test_app_cumplimiento.py`
- Modify: `locale/tsots.pot`, `locale/en/LC_MESSAGES/tsots.po` (`.mo` compilado)

**Interfaces:**
- Consumes:
  - `Proveedor.ajustes_tiktok()` y `AjustesTikTok` (Task 3);
  - los campos nuevos de `Opciones` y `PRIVACIDADES_TIKTOK` (Task 2);
  - `portada_video.elegir` (Task 4);
  - `segundo_plano.en_segundo_plano`;
  - `_estado_plataforma`, `_refrescar_plataformas` y `_refrescar` (existentes).
- Produces (nombres de widgets y métodos que usan los tests):

  **Bloque de TikTok** (`self.grupo_tiktok`, un `QGroupBox` «TikTok»): visible solo con TikTok marcado y modo `PUBLICO`. Contiene:
  - `self.etiqueta_cuenta_tiktok`: «Se publicará en: …», con el texto de `Cuenta.visible`.
  - `self.combo_privacidad_tiktok`:
    - el primer elemento es «Elige quién puede verlo…», con data `""`;
    - luego solo las privacidades de `AjustesTikTok.privacidades`, con los textos de `PRIVACIDADES_TIKTOK`;
    - siempre empieza en el primer elemento y no se guarda en `ajustes`.
  - `self.casilla_comentarios_tiktok`, `self.casilla_duos_tiktok`, `self.casilla_stitch_tiktok`: «Permitir comentarios», «Permitir dúos», «Permitir stitch». Desmarcadas al abrir. Deshabilitadas, con tooltip «Desactivado en tu cuenta de TikTok», si la cuenta lo tiene apagado.
  - `self.etiqueta_consentimiento_tiktok`: el texto de consentimiento con enlaces (`setOpenExternalLinks(True)`):
    - Confirmación de uso de música: `https://www.tiktok.com/legal/page/global/music-usage-confirmation/en`;
    - Política de contenido de marca: `https://www.tiktok.com/legal/page/global/bc-policy/en`.

  **Bloque comercial común** (`self.casilla_comercial`, «Contenido comercial»):
  - `self.casilla_tu_marca` («Tu marca: promocionas algo tuyo») y `self.casilla_de_marca` («Contenido de marca: una marca te paga o te da algo»), habilitadas solo con la principal marcada;
  - `self.etiqueta_comercial`: la etiqueta de TikTok («Se etiquetará como…») y los avisos:
    - TikTok en borrador: «Márcalo en la app de TikTok»;
    - Instagram o Facebook marcados con «Contenido de marca»: «Añade la etiqueta de colaboración pagada desde la app de Instagram o Facebook».

  **Permisos:** `_consultar_ajustes_tiktok()` y el slot `_al_consultar_ajustes_tiktok(resultado)`:
  - se lanzan en segundo plano cuando TikTok queda marcado en modo `PUBLICO` y aún no se han pedido para la cuenta actual;
  - guardan `self._ajustes_tiktok: AjustesTikTok | None` y `self._error_ajustes_tiktok: str`;
  - descartan respuestas viejas, como `_consulta_n`.

  **Bloqueos de TikTok en modo `PUBLICO`** (en `_estado_plataforma`):
  - cargando → «Cargando los permisos de TikTok…»;
  - error → el mensaje del error;
  - privacidad sin elegir → «Elige quién puede verlo en TikTok»;
  - `max_segundos` y `self.duracion > max_segundos` → TikTok deshabilitado con «Este vídeo dura más de lo que tu cuenta de TikTok permite publicar ({limite})» (usar `limites.duracion_legible`).

  **Bloqueo común:** contenido comercial marcado sin ninguna de las dos casillas → el texto de Global Constraints.

  **«Contenido de marca»:** deshabilita el elemento `SELF_ONLY` del combo, con tooltip «El contenido de marca no puede ser privado». Si estaba elegido, vuelve al primer elemento.

  **Vista previa:** `self.vista_portada`, un `QLabel` de unos 90 × 160 px junto al bloque de TikTok, con el fotograma de `portada_video.elegir(self.video)` calculado en segundo plano al abrir. En «Publicar shorts» sigue al primer short marcado.

  **`opciones()`:** rellena los campos nuevos de `Opciones` desde estos widgets; `idioma` desde `self._idioma` (Task 6, `""` por ahora). `_recordar_eleccion` **no** guarda privacidad, casillas ni contenido comercial.

  **Al terminar en TikTok directo:** la fila de TikTok añade «TikTok puede tardar unos minutos en mostrarlo».

- [ ] **Step 1: Tests** (`qtbot`, `ProveedorFalso`, `ajustes` en `tmp_path`, como `tests/test_app_publicar_shorts.py`):
  - `test_tiktok_directo_pide_privacidad`: al marcar `PUBLICO` se consultan los permisos, el combo empieza en «Elige…» y «Publicar» está deshabilitado con «Elige quién puede verlo en TikTok». Al elegir «Solo yo» se habilita.
  - `test_tiktok_combo_solo_privacidades_de_la_cuenta`: con `privacidades=("FOLLOWER_OF_CREATOR", "SELF_ONLY")` hay 3 elementos.
  - `test_tiktok_casillas_desmarcadas_y_deshabilitadas_si_la_cuenta_las_apaga`.
  - `test_tiktok_permisos_con_error_bloquean_directo_pero_no_borrador`.
  - `test_tiktok_duracion_mayor_que_la_cuenta_desmarca`.
  - `test_contenido_de_marca_vacia_solo_yo` y `test_comercial_sin_casillas_bloquea`.
  - `test_textos_de_etiqueta_y_consentimiento`: los cuatro textos exactos de Global Constraints según las casillas.
  - `test_aviso_borrador_y_aviso_instagram`.
  - `test_opciones_lleva_las_elecciones` (`opciones()` refleja privacidad, casillas y comercial).
  - `test_no_se_recuerda_entre_publicaciones`: un diálogo nuevo con los mismos `ajustes` vuelve a «Elige…», casillas desmarcadas y comercial apagado.
  - `test_publicar_shorts_aplica_las_elecciones_a_cada_short`: `ProveedorFalso.llamadas` lleva las mismas `Opciones` de TikTok en cada short y una `Publicacion.portada` en cada uno.
- [ ] **Step 2:** Ver que fallan.
- [ ] **Step 3:** Implementar. Traducciones: `lanzador/traducir.sh` y rellenar los `msgstr` nuevos.
- [ ] **Step 4:** Suite completa en verde.
- [ ] **Step 5:** Commit `feat: TikTok direct-post UX and commercial content disclosure`.

### Task 6: Idioma del vídeo y documentación

**Files:**
- Modify: `app/widgets/dialogo_publicar.py` (`__init__`), `app/widgets/dialogo_publicar_shorts.py`, `app/main.py:644,668`
- Modify: `README.md` (`## Publish to social networks`, l.439-577), `README.es.md` (`## Publicar en redes`, l.441-579), catálogos de traducción
- Test: `tests/test_app_main.py` o `tests/test_app_redes.py`, y `tests/test_app_cumplimiento.py`

**Interfaces:**
- Consumes: `Opciones.idioma` (Task 2).
- Produces:
  - `DialogoPublicar.__init__(…, idioma: str = "", …)` y lo mismo en `DialogoPublicarShorts`; lo guardan en `self._idioma`, que entra en `opciones()`.
  - `app/main.py`, al abrir los diálogos: `idioma` = `ficha.artefactos[TRANSCRIPCION].ajustes.get("idioma")` si la ficha tiene transcripción con idioma; si no, el `idioma_subs` del panel (`panel_opciones` → `valores()["idioma_subs"]`). Se pasa tal cual («es», «en» o «auto»): `campos` ya ignora «auto».

- [ ] **Step 1: Tests**:
  - un diálogo creado con `idioma="en"` da `opciones().idioma == "en"`;
  - en `main`, una ficha con transcripción en «en» abre el diálogo con «en»; sin transcripción usa el valor del panel (sustituir el diálogo por un falso que capture los argumentos, como los tests existentes de `main`).
- [ ] **Step 2:** Ver que fallan.
- [ ] **Step 3:** Implementar.
  - README (ES y EN), un párrafo nuevo en la sección de publicar con:
    - qué declara TSOTS por ti: no es para niños, no está hecho con IA, idioma;
    - qué eliges en cada publicación directa de TikTok: privacidad, comentarios, dúos, stitch y contenido comercial; nada de eso se recuerda;
    - que la música de `~/TSOTS/musica` debe tener licencia para redes (la sintetizada no tiene problema);
    - que la etiqueta de colaboración pagada de Instagram y Facebook se pone en su app;
    - que la miniatura de YouTube necesita un canal verificado;
    - que la portada es el fotograma más nítido de los primeros 5 s, donde se ve el título;
    - que si TikTok no deja publicar en ese momento, el error llega al subir.
  - Traducciones.
- [ ] **Step 4:** Suite completa en verde.
- [ ] **Step 5:** Commit `feat: send the video's language and document what TSOTS declares`.

### Task 7: Prueba real (controlador, con permiso explícito del usuario)

Publicar es una acción externa: **no se hace sin que el usuario lo autorice en el chat**.

- [ ] **Step 1:** Pedir permiso y hacer, con la app del worktree:
  - un short a TikTok en directo con «Solo yo»: portada con título y campos aceptados;
  - un short a YouTube: miniatura aceptada o aviso;
  - un short **programado** desde «Publicar shorts» a Instagram y YouTube: portada y miniatura en una subida programada.
- [ ] **Step 2:** Si YouTube rechaza la miniatura como error de la subida (y no como aviso), o la subida programada pierde el archivo, quitar `thumbnail` en ese caso y documentarlo (supuestos 5.2 del diseño).
