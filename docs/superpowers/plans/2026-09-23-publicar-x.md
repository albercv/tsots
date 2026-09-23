# Publicar también en X y Facebook — plan de implementación

**Goal:** añadir X y Facebook como cuarta y quinta plataforma del botón
**Publicar…**, con sus límites propios, sin romper el diseño independiente del
proveedor. Orden fijo: TikTok → YouTube → Instagram → X → Facebook.

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
- No se sabe si X y Facebook entran en el plan gratuito: un error del servicio
  se muestra con el tratamiento de errores que ya existe.

## Diseño

| Pieza | Cambio | ¿Conoce Upload-Post? |
|---|---|---|
| `modelo.py` | `Plataforma.X` («X») y `Plataforma.FACEBOOK` («Facebook»), al final de `ORDEN`. `ModoFacebook` (reel / vídeo normal / borrador). `Publicacion.texto_x` (texto propio de X; vacío = el de por defecto). `Opciones.x_premium` y `Opciones.facebook_modo` | No |
| `textos.py` | `longitud_x(texto)`: cuenta como X (URL = 23, pesos 1/2, emoji = 2; aproximación documentada). `texto_x_por_defecto(pub)`: título + hashtags; quita hashtags desde el final y después acorta el título hasta caber en 280. `texto_para(X, pub, x_premium=…)`: el texto de X garantizado ≤ 280 sin Premium. Facebook: descripción = caption + hashtags, título = título | No |
| `limites.py` (nuevo) | Límites de vídeo de X sin Premium (140 s, 512 MB) y `motivo_no_admite_x(duracion, tamano, premium)`: texto claro o `""` | No |
| `upload_post.py` | X: `x_title`, `x_long_text_as_post` (`true` solo con Premium y texto > 280), `made_with_ai=false`. Facebook: `facebook_page_id` desde los ajustes neutros (`pagina_facebook`), `facebook_title`, `facebook_description`, `facebook_media_type` + `video_state` según el modo, `facebook_is_ai_generated=false`. Un POST por plataforma, `async_upload`, sin reintentos de subida, sondeo y análisis tolerante como las demás | Sí |
| `publicador.py` | `modo_de` para X y Facebook | No |
| `app/settings.py` | `x_premium` (por defecto no), `pagina_facebook`, `facebook_modo` (reel). `ajustes_proveedor()` añade `pagina_facebook`. `plataformas_redes`: las listas guardadas sin X/Facebook siguen valiendo (X y Facebook desmarcadas) | No |
| `dialogo_redes.py` | Casilla «Mi cuenta de X tiene Premium», campo «Página de Facebook (ID)» con ayuda genérica para encontrarlo y aviso si no es un número, modo de Facebook por defecto | No |
| `dialogo_publicar.py` | Campo «Texto para X» con contador en vivo (x/280), precargado y regenerado mientras no se edite. X deshabilitada y desmarcada con el motivo si el vídeo pasa de 2:20 o 512 MB sin Premium (duración con `steps.duracion_video` en un hilo aparte, sin bloquear la ventana). Selector de modo de Facebook. Si Facebook está marcada sin ID de página, se explica qué falta y no se publica | No |

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
- Usuarios nuevos: las cinco plataformas marcadas, como hasta ahora. Usuarios
  con una elección guardada: X y Facebook desmarcadas hasta que las marquen.

## Tareas

### Task 1: modelo, textos y límites (tests primero)
- [ ] Orden TikTok → YouTube → Instagram → X → Facebook y nombres.
- [ ] `longitud_x`: texto normal, URL = 23, emoji = 2, CJK = 2.
- [ ] Texto por defecto de X: cabe entero; quita hashtags desde el final;
      acorta el título si ni sin hashtags cabe; nunca pasa de 280.
- [ ] Texto propio de X > 280: recortado sin Premium, entero con Premium.
- [ ] Facebook: texto = caption + hashtags.
- [ ] `motivo_no_admite_x`: duración y tamaño, con y sin Premium, duración desconocida.

### Task 2: Upload-Post y publicador
- [ ] Campos de X (con y sin Premium, texto corto y largo) y de Facebook
      (tres modos, sin ID de página no se envía nada).
- [ ] Resultado de X y Facebook con respuesta síncrona y asíncrona.
- [ ] Contrato y desacoplamiento: X y Facebook en `Plataforma`; cadenas
      nuevas (`x_title`, `facebook_page_id`…) prohibidas fuera del módulo.
- [ ] `modo_de` y registro para X y Facebook.

### Task 3: ajustes y Redes…
- [ ] `x_premium`, `pagina_facebook`, `facebook_modo`: defecto, persistencia,
      valores corruptos; listas guardadas sin X/Facebook.
- [ ] Redes…: casilla Premium, ID de página con aviso, modo de Facebook.

### Task 4: diálogo Publicar
- [ ] Casillas en el orden nuevo; campo de X precargado con contador; se
      regenera hasta que se edita; contador en aviso y Publicar bloqueado si
      pasa de 280 sin Premium.
- [ ] X deshabilitada por duración o tamaño sin Premium, con el motivo;
      habilitada con Premium.
- [ ] Facebook sin ID de página: explicación y Publicar bloqueado.
- [ ] Opciones y publicación que llegan al proveedor.

### Task 5: traducciones, documentación y capturas
- [ ] Cadenas nuevas en inglés.
- [ ] README (es/en): X y Facebook con sus límites; paso 1 de la instalación
      con el enlace directo al ZIP estable de `main` y la última Release
      (Code → Download ZIP da `develop`).
- [ ] `docs/DEVELOPMENT.md`: plataformas, campos y supuestos.
- [ ] Capturas offscreen del diálogo Publicar (X activa y X bloqueada) y de
      Redes…, en claro y oscuro.

### Task 6: prueba real (necesita al usuario)
- [ ] Conectar X y una página de Facebook en Upload-Post.
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
