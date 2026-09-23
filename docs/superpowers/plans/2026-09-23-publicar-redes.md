# Publicar en TikTok, YouTube e Instagram — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Desde TSOTS, publicar el vídeo terminado en TikTok, YouTube e Instagram, en ese orden, con el título, caption y hashtags que ya genera la app, revisados por el usuario antes de salir.

**Por qué un servicio intermediario (investigación 2026-09-23):**

| Plataforma | API oficial propia | Motivo |
|---|---|---|
| TikTok | No viable | Sin auditoría solo publica en privado; su guía rechaza "a utility tool to help upload contents to the account(s) you or your team manages" |
| YouTube | Tras auditoría | Los vídeos de proyectos sin auditar quedan privados y no se pueden hacer públicos |
| Instagram | Viable | Acceso estándar sin revisión de Meta |

Postiz autoalojado no lo evita: usa apps propias de TikTok y Google, con las mismas auditorías. Se usa **Upload-Post** (`POST https://api.upload-post.com/api/upload`, cabecera `Authorization: Apikey …`), que ya tiene las apps aprobadas.

**Decisiones del usuario:**
1. **Botón Publicar**, nunca automático. El usuario revisa y puede editar título, caption y hashtags.
2. **TikTok:** se elige en cada publicación entre **borrador** (`post_mode=MEDIA_UPLOAD`, se termina en la app) y **público** (`post_mode=DIRECT_POST`, `privacy_level=PUBLIC_TO_EVERYONE`).
3. **YouTube:** Short público (`privacyStatus=public`).
4. **Instagram:** **reel de prueba** que se comparte con los seguidores solo si funciona (`share_mode=TRIAL_REELS_SHARE_TO_FOLLOWERS_IF_LIKED`), para publicar a todos solo lo que tiene tracción. Alternativa en el diálogo: reel normal (`share_mode=CUSTOM`, `share_to_feed=true`).

**Architecture — independiente del proveedor (requisito del usuario):** el proveedor puede cambiar (otro servicio, Postiz, o APIs oficiales propias). Todo lo específico de Upload-Post vive en **un solo módulo**; el resto de la app solo conoce tipos neutros.

Paquete `videopipeline/redes/`:

| Módulo | Responsabilidad | ¿Conoce Upload-Post? |
|---|---|---|
| `modelo.py` | Tipos neutros: `Plataforma` (TIKTOK, YOUTUBE, INSTAGRAM, con `ORDEN`), `Publicacion` (vídeo, título, caption, hashtags, palabras clave), `Opciones` (`tiktok_modo`: borrador/publico; `instagram_modo`: prueba/normal; `youtube_categoria`), `Resultado` (ok, url, error, pendiente) | No |
| `textos.py` | Límites de cada **plataforma** (no del proveedor): título de YouTube ≤ 100, textos ≤ 2200, ≤ 30 hashtags en Instagram; recorta el caption y nunca los hashtags | No |
| `proveedor.py` | `Protocol Proveedor`: `nombre`, `publicar(plataforma, publicacion, opciones, video) -> Resultado`, `estado(ref) -> Resultado`. Registro `PROVEEDORES = {"upload_post": …}` y `crear(nombre, clave, ajustes)` | No |
| `upload_post.py` | **Único** módulo con URLs, campos (`post_mode`, `share_mode`, `privacyStatus`…), cabecera `Apikey` y sondeo de estado de Upload-Post | Sí |
| `publicador.py` | Orquesta: orden TikTok → YouTube → Instagram, sigue si una falla, progreso, espera de pendientes, escribe el registro | No |
| `registro.py` | `nombre_limpio.publicado.json`: plataforma, fecha, url, proveedor | No |

Reglas de desacoplamiento, comprobadas con tests:
- Ningún módulo fuera de `upload_post.py` importa `upload_post` ni contiene cadenas de Upload-Post. Un test recorre `app/` y `videopipeline/` y falla si aparecen `upload-post`, `post_mode` o `share_mode` fuera de ese módulo.
- La GUI y el publicador trabajan contra un `ProveedorFalso` en los tests. Un test de contrato común se ejecuta contra cada proveedor registrado.
- Ajustes guardan el **nombre** del proveedor (`redes/proveedor`, por defecto `upload_post`) y sus datos no secretos (perfil). La clave va al Llavero bajo el servicio `tsots-<proveedor>`.
- Añadir un proveedor = un módulo nuevo + una línea en `PROVEEDORES`.

Resto de la app:
- `app/credenciales.py`: guarda y lee la clave en el **Llavero de macOS** con el comando `security` (sin dependencias nuevas). Nunca en QSettings ni en ficheros.
- `app/widgets/dialogo_publicar.py`: textos editables, casillas por plataforma, modo de TikTok y de Instagram, botón Publicar con confirmación, progreso y enlaces. La subida corre en un `QThread`.
- `app/widgets/dialogo_redes.py`: elegir proveedor (de momento solo Upload-Post), perfil y clave. La clave la escribe el usuario y va directa al Llavero.
- El diálogo Publicar avisa si el vídeo ya se publicó en alguna plataforma, leyendo el registro.

**Tech Stack:** Python 3.11, PySide6 6.11, `httpx` 0.28 (ya en `requirements.txt`, subida multipart en streaming), comando `security` de macOS, pytest + pytest-qt. Sin dependencias nuevas.

## Correspondencia de campos

| Dato de TSOTS | TikTok | YouTube | Instagram |
|---|---|---|---|
| Título (≤ 60) | — | `youtube_title` (≤ 100) | — |
| Caption + hashtags | `tiktok_title` (≤ 2200) | `youtube_description` | `instagram_title` (≤ 2200, ≤ 30 hashtags) |
| Palabras clave | — | `tags` | — |
| Vídeo | `video` (fichero) | `video` | `video`, `media_type=REELS` |

`title` común = título de TSOTS (obligatorio para YouTube). `categoryId` de YouTube por defecto `22` (People & Blogs), configurable. `is_aigc`, `containsSyntheticMedia` e `is_ai_generated` a `false`: el vídeo es real; solo se limpia audio, se cortan silencios y se añaden subtítulos.

## Global Constraints

- Nada se publica sin pulsar Publicar y confirmar. Nunca hay publicación automática.
- La API key solo vive en el Llavero. No aparece en logs, errores, `PipelineConfig`, QSettings ni en el registro `.publicado.json`.
- Orden fijo TikTok → YouTube → Instagram; las no marcadas se saltan. Un fallo en una no cancela las siguientes.
- Los tests nunca llaman a Upload-Post: cliente HTTP falso. Un único test `lenta` opcional, saltado si no hay clave en el Llavero, que publica en TikTok como borrador.
- Tests: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m "not lenta" -q` en verde antes de cada commit.
- Reglas de `CLAUDE.md`: rama `feature/publicar-redes`, PR contra `develop`, sin atribución de IA, GUI y código en español con traducción inglesa.

## Tareas

### Task 1: `modelo.py` y `textos.py` — tipos neutros y límites de plataforma
- [x] Tests: `ORDEN` es TikTok, YouTube, Instagram; título de YouTube recortado a 100; texto = caption + hashtags ≤ 2200 recortando el caption y nunca los hashtags; máximo 30 hashtags en Instagram.
- [x] Implementar los tipos neutros y `texto_para(plataforma, publicacion)`.

### Task 2: `proveedor.py`, `upload_post.py` y `publicador.py`
- [x] Tests de `upload_post.py` con `httpx.MockTransport`: campos por plataforma (TikTok borrador `MEDIA_UPLOAD` / público `DIRECT_POST` + `PUBLIC_TO_EVERYONE`; YouTube `public`, tags, categoría; Instagram `REELS` con `TRIAL_REELS_SHARE_TO_FOLLOWERS_IF_LIKED` o `CUSTOM` + `share_to_feed`); cabecera `Authorization: Apikey …`; respuesta síncrona con URL; respuesta asíncrona con `request_id` y sondeo de estado hasta terminar; error 401/429/503 en YouTube no impide Instagram; resultado por plataforma (`ok`, `url`, `error`).
- [x] Test de contrato común para todo `Proveedor` registrado y test de desacoplamiento (cadenas de Upload-Post solo en su módulo).
- [x] Tests de `publicador.py` con `ProveedorFalso`: orden, fallo que no corta, pendientes que se sondean, progreso.
- [x] Implementar, con reintentos solo en 503 y tiempo máximo de sondeo.

### Task 3: `registro.py`
- [x] Tests: escribir y leer `nombre_limpio.publicado.json` (incluye el nombre del proveedor); fusionar publicaciones sucesivas; `ya_publicado(video) -> set[Plataforma]`.
- [x] Implementar.

### Task 4: Llavero
- [x] Tests con `subprocess.run` falso: guardar usa `security add-generic-password -U -s tsots-<proveedor> -a api-key -w`; leer usa `find-generic-password -w`; clave ausente devuelve `None`; borrar.
- [x] Implementar `app/credenciales.py`.

### Task 5: configuración de redes
- [ ] `Ajustes`: `proveedor_redes` (por defecto `upload_post`), `perfil_redes`, `youtube_categoria`, modo por defecto de TikTok e Instagram. Tests de persistencia.
- [ ] `DialogoRedes`: perfil y API key (campo de contraseña; muestra "guardada" sin revelar la clave). Tests.

### Task 6: diálogo Publicar
- [ ] Tests: textos editables precargados desde el `Caption`; casillas en orden TikTok, YouTube, Instagram; modos por defecto (TikTok según ajustes, Instagram prueba); aviso si ya se publicó; botón deshabilitado sin clave o sin plataformas; confirmación antes de publicar; muestra resultado y enlaces por plataforma con `publicar` falso.
- [ ] Implementar `DialogoPublicar` con la subida en un `QThread`.

### Task 7: cableado en la ventana
- [ ] Botón **Publicar…** en `PanelCaption`, activo cuando el vídeo terminado tiene caption; menú o botón **Redes…** para la configuración. Tests en `tests/test_app_main.py`.

### Task 8: traducciones, documentación y TODO
- [ ] Cadenas nuevas traducidas al inglés.
- [ ] README (es/en): sección "Publicar en redes" con los requisitos: cuenta en Upload-Post, perfiles conectados, Instagram profesional.
- [ ] `docs/DEVELOPMENT.md`: módulo `redes.py`, Llavero y el motivo del servicio intermediario.
- [ ] Quitar la tarea de `docs/TODO.md`.

### Task 9: verificación real (necesita al usuario)
- [ ] El usuario crea la cuenta de Upload-Post, conecta TikTok, YouTube e Instagram y guarda la clave desde **Redes…**.
- [ ] Publicar un vídeo de prueba: TikTok en borrador, YouTube como Short e Instagram como reel de prueba. Comprobar los tres enlaces.
- [ ] Comprobar cuánto descuenta cada subida del plan gratuito (campo `usage` de la respuesta).

## Riesgos

- **Dependencia de un tercero:** si Upload-Post cambia precios o cierra, se añade otro módulo proveedor y se cambia el ajuste. Nada más cambia.
- **Reel de prueba:** depende de que Instagram mantenga la función para la cuenta. Si la API la rechaza, el diálogo informa y ofrece publicar como reel normal.
- **Plan gratuito:** 10 subidas al mes; no está claro si cuenta por vídeo o por plataforma.

## Estimación

Un día: tareas 1 a 4 (3 h), 5 a 7 (3 h), 8 (1 h), más la prueba real con el usuario.
