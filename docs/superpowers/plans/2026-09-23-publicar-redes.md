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

**Architecture:**
- `videopipeline/redes.py` (lógica pura + cliente HTTP inyectable): arma los campos de cada plataforma, publica **una plataforma por llamada** en orden TikTok → YouTube → Instagram, y consulta el estado (`GET /api/uploadposts/status?request_id=…`) cuando la subida es asíncrona. Si una plataforma falla, sigue con las demás y lo informa.
- `app/credenciales.py`: guarda y lee la API key en el **Llavero de macOS** con el comando `security` (sin dependencias nuevas). Nunca en QSettings ni en ficheros.
- `app/widgets/dialogo_publicar.py`: textos editables, casillas por plataforma, modo de TikTok y de Instagram, botón Publicar con confirmación, progreso y enlaces resultantes. La subida corre en un hilo (`QThread`) para no bloquear la ventana.
- `app/widgets/dialogo_redes.py`: configuración, con perfil de Upload-Post (`user`) y API key. La clave la escribe el usuario; se guarda directamente en el Llavero.
- Registro `nombre_limpio.publicado.json` junto al vídeo: plataformas, fechas y enlaces. El diálogo avisa si un vídeo ya se publicó en alguna plataforma.

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

### Task 1: `redes.py` — campos por plataforma
- [ ] Tests: `campos_tiktok` en modo borrador y público; `campos_youtube` con título recortado a 100, descripción = caption + hashtags, tags; `campos_instagram` en modo prueba y normal; límite de 2200 caracteres recortando el caption y nunca los hashtags; máximo 30 hashtags en Instagram.
- [ ] Implementar `Publicacion` (dataclass: vídeo, título, caption, hashtags, palabras clave, perfil) y `campos(plataforma, pub, opciones) -> dict`.

### Task 2: `redes.py` — cliente y orden
- [ ] Tests con transporte `httpx.MockTransport`: una llamada por plataforma en orden; cabecera `Authorization: Apikey …`; respuesta síncrona con URL; respuesta asíncrona con `request_id` y sondeo de estado hasta terminar; error 401/429/503 en YouTube no impide Instagram; resultado por plataforma (`ok`, `url`, `error`).
- [ ] Implementar `publicar(pub, plataformas, opciones, clave, cliente=None, al_progresar=None) -> dict[str, Resultado]`, con reintentos solo en 503 y tiempo máximo de sondeo.

### Task 3: registro de publicaciones
- [ ] Tests: escribir y leer `nombre_limpio.publicado.json`; fusionar publicaciones sucesivas; `ya_publicado(video) -> set[str]`.
- [ ] Implementar en `redes.py`.

### Task 4: Llavero
- [ ] Tests con `subprocess.run` falso: guardar usa `security add-generic-password -U -s tsots-upload-post -a api-key -w`; leer usa `find-generic-password -w`; clave ausente devuelve `None`; borrar.
- [ ] Implementar `app/credenciales.py`.

### Task 5: configuración de redes
- [ ] `Ajustes`: `perfil_upload_post`, `youtube_categoria`, modo por defecto de TikTok e Instagram. Tests de persistencia.
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

- **Dependencia de un tercero:** si Upload-Post cambia precios o cierra, se sustituye `redes.py`. Todo lo demás es independiente del servicio.
- **Reel de prueba:** depende de que Instagram mantenga la función para la cuenta. Si la API la rechaza, el diálogo informa y ofrece publicar como reel normal.
- **Plan gratuito:** 10 subidas al mes; no está claro si cuenta por vídeo o por plataforma.

## Estimación

Un día: tareas 1 a 4 (3 h), 5 a 7 (3 h), 8 (1 h), más la prueba real con el usuario.
