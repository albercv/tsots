# Publicar también en X y Facebook — plan de implementación

**Goal:** añadir X y Facebook como cuarta y quinta plataforma del botón
**Publicar…**, con sus límites propios, sin romper el diseño independiente del
proveedor. Orden fijo: TikTok → YouTube → Instagram → X → Facebook. Además,
la app **lee del proveedor** las cuentas conectadas y las páginas de Facebook
en lugar de pedirle al usuario que las escriba.

Parte de `2026-09-23-publicar-redes.md` (mismo paquete `videopipeline/redes/`,
mismas reglas de desacoplamiento).

## Hechos de partida

**X** (límites de la plataforma, no del proveedor):
- Un post admite **280 caracteres** en cuentas normales. X cuenta con pesos:
  cada URL cuenta 23, los caracteres latinos y la puntuación habitual 1, el
  resto (CJK, emoji…) 2. Un texto más largo, Upload-Post lo publica como
  **hilo**, que no queremos.
- Vídeo sin Premium: hasta **140 s (2:20)** y **512 MB**. Con Premium se
  admiten vídeos largos y textos largos en un solo post.

**Facebook:** Meta solo deja publicar en **páginas**, no en perfiles
personales. Hace falta el ID de la página.

**Upload-Post** (documentación consultada el 2026-09-23):
- X: `platform[]=x`, `x_title`, `x_long_text_as_post`, `made_with_ai`
  (también `reply_settings`, `nullcast`, `community_id`, `x_alt_text`,
  `x_subtitles_url` —solo URL pública, se omite— y `x_paid_partnership`, que
  no se usan).
- Facebook: `platform[]=facebook`, `facebook_page_id` (obligatorio),
  `facebook_title` (si falta, `title`), `facebook_description`,
  `facebook_media_type` = `REELS` (defecto) | `STORIES` | `VIDEO`,
  `video_state` = `PUBLISHED` (defecto) | `DRAFT`, `facebook_is_ai_generated`,
  `facebook_no_story`.
- Cuentas: `GET /api/uploadposts/users/{perfil}` → `social_accounts` por
  plataforma (`null`/`""` si no está conectada; si no, `display_name`,
  `handle`, `username`, `social_images`, `reauth_required`, `capabilities`).
- Páginas: `GET /api/uploadposts/facebook/pages?profile=` → lista de
  `{page_id, page_name, profile}` (se aceptan envoltorios).
- No se sabe si X y Facebook entran en el plan gratuito: un error del servicio
  se muestra con el tratamiento de errores que ya existe.

## Diseño

| Pieza | Cambio | ¿Conoce Upload-Post? |
|---|---|---|
| `modelo.py` | `Plataforma.X` («X») y `Plataforma.FACEBOOK` («Facebook»), al final de `ORDEN`. `ModoFacebook` (reel / vídeo normal / borrador). `Publicacion.texto_x` (texto propio de X; vacío = el de por defecto). `Opciones.x_premium` y `Opciones.facebook_modo`. `Cuenta` (nombre, usuario, reconectar, capacidades, Premium si se sabe) y `Pagina` (id, nombre) | No |
| `proveedor.py` | El protocolo suma `cuentas() -> dict[Plataforma, Cuenta \| None]` y `paginas_facebook() -> list[Pagina]`; ambas lanzan `ErrorConsulta` (neutra, legible, sin la clave) | No |
| `textos.py` | `longitud_x(texto)`: cuenta como X (URL = 23, pesos 1/2, emoji = 2; aproximación documentada). `texto_x_por_defecto(pub)`: título + hashtags; quita hashtags desde el final y después acorta el título hasta caber en 280. `texto_para(X, pub, x_premium=…)`: el texto de X garantizado ≤ 280 sin Premium. Facebook: descripción = caption + hashtags, título = título | No |
| `limites.py` (nuevo) | Límites de vídeo de X sin Premium (140 s, 512 MB) y `motivo_no_admite_x(duracion, tamano, premium)`: texto claro o `""` | No |
| `upload_post.py` | Cuentas y páginas: URLs, campos y análisis tolerante (envoltorios, `x`/`twitter`, cuentas `null`/`""`). Premium de X: supuesto, una capacidad que nombra Premium o vídeo/texto largo. X: `x_title`, `x_long_text_as_post` (`true` solo con Premium y texto > 280), `made_with_ai=false`. Facebook: `facebook_page_id` desde los ajustes neutros (`pagina_facebook`), `facebook_title`, `facebook_description`, `facebook_media_type` + `video_state` según el modo, `facebook_is_ai_generated=false`. Un POST por plataforma, `async_upload`, sin reintentos de subida, sondeo y análisis tolerante como las demás | Sí |
| `publicador.py` | `modo_de` para X y Facebook | No |
| `app/settings.py` | `x_premium` (por defecto no), página de Facebook y última consulta de cuentas (por proveedor, ligada al perfil), `facebook_modo` (reel). `ajustes_proveedor()` añade `pagina_facebook`. `plataformas_redes`: las listas guardadas sin X/Facebook siguen valiendo (X y Facebook desmarcadas) | No |
| `app/segundo_plano.py`, `app/cuentas.py` (nuevos) | Tareas cortas en un hilo aparte con aviso en el hilo de la interfaz; consulta de cuentas y páginas común a los dos diálogos | No |
| `dialogo_redes.py` | «Comprobar conexión» (en segundo plano, con la clave recién escrita o la del Llavero): cada plataforma conectada (@usuario), no conectada o «reconecta». Página de Facebook en una lista sacada del servicio (sola si solo hay una); campo manual solo si la lista falla. Casilla «Mi cuenta de X tiene Premium», que se marca sola si el servicio lo indica. Modo de Facebook por defecto | No |
| `dialogo_publicar.py` | Campo «Texto para X» con contador en vivo (x/280), precargado y regenerado mientras no se edite. X deshabilitada y desmarcada con el motivo si el vídeo pasa de 2:20 o 512 MB sin Premium (duración con `steps.duracion_video` en un hilo aparte, sin bloquear la ventana). Selector de modo de Facebook. Si Facebook está marcada sin página, se explica qué falta y no se publica. Al abrirse, consulta las cuentas en segundo plano: las no conectadas, deshabilitadas («No conectada en Upload-Post»); las que hay que reconectar, con aviso; sin conexión, lo último guardado. El registro de la publicación anota las cuentas y de dónde salieron | No |

**Decisiones:**
- El ID de la página de Facebook es un dato de Facebook (no del proveedor) y
  no es secreto: va a `Ajustes` y llega al proveedor en `ajustes_proveedor()`
  como `pagina_facebook`. Solo `upload_post.py` lo llama `facebook_page_id`.
- Borrador de Facebook = reel en `DRAFT` (supuesto a confirmar en la prueba
  real).
- Con Premium no se comprueba ni la duración ni el tamaño (los límites de
  Premium son de horas y GB).
- Si ffprobe no puede leer la duración, X no se bloquea por duración (el
  tamaño sí se comprueba).
- Usuarios nuevos: TikTok, YouTube e Instagram marcadas; X y Facebook se
  activan a mano (pueden no estar en el plan y Facebook necesita página).
  Usuarios con una elección guardada: X y Facebook desmarcadas hasta que las
  marquen. Se recuerda lo que el usuario quiere marcado aunque hoy no se
  pueda (p. ej. X con un vídeo largo).
- La API key también se lee (en segundo plano) para consultar las cuentas al
  abrir Publicar… y al pulsar «Comprobar conexión», no solo al confirmar.

## Tareas

### Task 1: modelo, textos y límites (tests primero)
- [x] Orden TikTok → YouTube → Instagram → X → Facebook y nombres.
- [x] `longitud_x`: texto normal, URL = 23, emoji = 2, CJK = 2.
- [x] Texto por defecto de X: cabe entero; quita hashtags desde el final;
      acorta el título si ni sin hashtags cabe; nunca pasa de 280.
- [x] Texto propio de X > 280: recortado sin Premium, entero con Premium.
- [x] Facebook: texto = caption + hashtags.
- [x] `motivo_no_admite_x`: duración y tamaño, con y sin Premium, duración desconocida.

### Task 2: Upload-Post y publicador
- [x] Campos de X (con y sin Premium, texto corto y largo) y de Facebook
      (tres modos, sin ID de página no se envía nada).
- [x] Resultado de X y Facebook con respuesta síncrona y asíncrona.
- [x] Contrato y desacoplamiento: X y Facebook en `Plataforma`; cadenas
      nuevas (`x_title`, `facebook_page_id`…) prohibidas fuera del módulo.
- [x] `modo_de` y registro para X y Facebook.

### Task 3: ajustes y Redes…
- [x] `x_premium`, `pagina_facebook`, `facebook_modo`: defecto, persistencia,
      valores corruptos; listas guardadas sin X/Facebook.
- [x] Redes…: casilla Premium, ID de página con aviso, modo de Facebook.

### Task 4: diálogo Publicar
- [x] Casillas en el orden nuevo; campo de X precargado con contador; se
      regenera hasta que se edita; contador en aviso y Publicar bloqueado si
      pasa de 280 sin Premium.
- [x] X deshabilitada por duración o tamaño sin Premium, con el motivo;
      habilitada con Premium.
- [x] Facebook sin ID de página: explicación y Publicar bloqueado.
- [x] Opciones y publicación que llegan al proveedor.

### Task 5: traducciones, documentación y capturas
- [x] Cadenas nuevas en inglés.
- [x] README (es/en): X y Facebook con sus límites; paso 1 de la instalación
      con el enlace directo al ZIP estable de `main` y la última Release
      (Code → Download ZIP da `develop`).
- [x] `docs/DEVELOPMENT.md`: plataformas, campos y supuestos.
- [x] Capturas offscreen del diálogo Publicar (X activa y X bloqueada) y de
      Redes…, en claro y oscuro.

### Task 6: prueba real (necesita al usuario)
- [ ] Conectar X y una página de Facebook en Upload-Post.
- [ ] Redes… → Comprobar conexión: ¿salen bien las cinco cuentas, la página
      y (si la hay) la detección de Premium? Revisar en el registro la forma
      real de `social_accounts` y de `capabilities`.
- [ ] ¿Entran X y Facebook en el plan gratuito? Si no, el error debe leerse bien.
- [ ] Publicar un vídeo corto en X (sin Premium) y comprobar que sale un solo
      post, no un hilo.
- [ ] Si la cuenta tiene Premium: marcarlo en Redes… y probar un vídeo largo.
- [ ] Facebook: reel publicado, vídeo normal y borrador (¿el borrador de un
      reel se puede terminar desde Meta Business Suite?).

## Riesgos

- **Cuenta de caracteres de X:** es una aproximación de `twitter-text`
  (pesos por rangos Unicode, URL = 23, emoji = 2). Casos raros (algunos
  símbolos, secuencias de emoji poco comunes) pueden contar distinto; el
  margen de error es de unos pocos caracteres, así que el texto por defecto
  deja la regla estricta y el usuario ve el contador.
- **Premium:** no hay forma de saberlo por la API; lo declara el usuario. Si
  lo marca sin tenerlo, X rechazará el vídeo largo o el texto largo y el
  error se mostrará.
- **Borrador de Facebook** (`REELS` + `DRAFT`): no verificado.
- **Forma de las respuestas de cuentas y páginas:** solo documentada a
  grandes rasgos; el análisis es tolerante y, si falla, la app sigue con lo
  último guardado o con todo habilitado.
