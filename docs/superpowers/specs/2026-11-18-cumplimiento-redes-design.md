# Cumplir las normas de cada red al publicar, y portada con título — diseño

Fecha: 2026-11-18. Estado: pendiente de aprobación (decisiones del usuario incorporadas).

## 1. Intención

El usuario publica sus vídeos desde TSOTS (diálogo «Publicar…» y «Publicar
shorts») en TikTok, Instagram, YouTube, Facebook, X y LinkedIn a través de
Upload-Post. Quiere:

1. **Cumplir** lo que cada red exige a quien publica por API, sobre todo
   TikTok, Instagram y YouTube, y aplicar sus buenas prácticas. Sus palabras:
   «me interesa sobre todo ser compliance».
2. Que **las miniaturas de TikTok muestren el título quemado**. Ahora no sale.

### Por qué no sale el título (comprobado)

- El título se quema arriba, al 8 % del alto (`titulo.MARGEN_SUPERIOR`),
  durante 5 s y con fundido de entrada de 300 ms.
- La cuadrícula del perfil recorta el vídeo 9:16 por el centro. Con 3:4 (lo
  que hace Instagram y probablemente TikTok) quita el 12,5 % de arriba y la
  primera línea del título desaparece. Comprobado sobre el fotograma del
  segundo 1 del short «01 - ¿Juniors o Seniors?». Con 1:1 desaparece entero.
- Por el fundido, el fotograma 0 no tiene título. Es el que suelen usar los
  borradores de TikTok como portada.

## 2. Objetivos, no objetivos y antiobjetivos

**Objetivos**

- El título queda dentro de la zona que sobrevive a un recorte 1:1 **y** 3:4.
- Cada publicación lleva una portada que muestra el título: el fotograma en
  TikTok, una imagen en Instagram y la miniatura en YouTube.
- La publicación directa en TikTok cumple la «Required UX» de su Content
  Posting API.
- Declaraciones obligatorias explícitas: contenido para niños en YouTube y
  contenido comercial o colaboración pagada donde la red lo admita.

**No objetivos**

- Comprobar licencias de la música. Se documenta en el README: la carpeta
  `~/TSOTS/musica` debe contener música con licencia para redes; la
  sintetizada no tiene problema.
- Marcar contenido como generado por IA. TSOTS no genera personas, voces ni
  escenas realistas: la IA limpia el audio y elige rótulos, iconos y B-roll de
  stock. Las marcas de IA siguen en `false`.
- Normas de X y LinkedIn más allá de la colaboración pagada en X: no se han
  podido leer sus páginas oficiales.
- Subtítulos como archivo: ninguna de las redes usadas los admite hoy por
  Upload-Post de forma útil.

**Antiobjetivos** (sería un fracaso aunque funcionara)

- Que TSOTS elija la privacidad de TikTok o marque los permisos por el
  usuario.
- Que una portada que no se pueda calcular o una miniatura que YouTube
  rechace impida publicar.
- Que TSOTS diga que un vídeo no es comercial sin que el usuario lo haya
  visto: el interruptor está a la vista en cada publicación.

## 3. Restricciones

- `videopipeline/redes/upload_post.py` es el único módulo que conoce
  Upload-Post. El resto usa `Proveedor`, `Opciones` y `Publicacion`
  (`redes/modelo.py`).
- La interfaz está en español y se traduce al inglés en
  `locale/en/LC_MESSAGES/tsots.po` con `lanzador/traducir.sh`.
- Los tests no salen a la red: la guarda `sin_red_ni_llavero` de
  `tests/conftest.py`.
- No se leen ni guardan credenciales nuevas. La clave de Upload-Post sigue
  donde está.
- Publicar de verdad es una acción externa. Las pruebas reales las autoriza
  el usuario.

## 4. Enfoques considerados

**Cómo cumplir en TikTok**

1. **Completar la publicación directa (elegido por el usuario).** El diálogo
   muestra lo que pide TikTok, con los permisos de la cuenta que da
   Upload-Post (`GET /api/uploadposts/tiktok/settings`). El borrador sigue
   igual, porque en él la app de TikTok pide todo eso.
2. TikTok solo en borrador: menos código, pero cada vídeo se termina a mano en
   TikTok. Además no está documentado que el borrador respete
   `cover_timestamp`, así que no resolvía la portada. Descartado.

**Dónde va el título** (elección del usuario: 23 %)

- 15 %: sobrevive a 3:4, pero no a 1:1.
- **23 %: sobrevive a 1:1 y a 3:4.** Queda a media altura, más cerca de las
  caras. Elegido.
- Centrado el primer segundo y luego subiendo: portada perfecta, pero tapa a
  la persona al empezar y es más trabajo. Descartado.

## 5. Diseño

### 5.1 Título al 23 % en vertical, sin fundido de entrada

- Vídeo vertical (alto > ancho): el título empieza al **23 %** del alto
  (y = 442 px en 1080×1920). Con dos líneas ocupa hasta unos 695 px; la zona
  1:1 conserva y = 420–1500.
- Horizontal: sigue al 8 %. Allí no hay recorte de cuadrícula.
- Fundido: `\fad(0,300)`. El título está entero desde el fotograma 0 y se
  sigue desvaneciendo al salir. Duración igual: 5 s.
- `videopipeline/edicion/zonas.py` toma la franja del título de la constante
  vertical. El editor con Claude se adapta solo. El constructor comprueba que
  las zonas de `lupa` y `dato` («arriba») y la de contenido siguen teniendo
  sitio, y si una se queda sin hueco, se coloca bajo el título.
- Afecta a vídeos nuevos y reprocesos. Los ya publicados no cambian.
- **Todos los encuadres verticales (decisión del usuario):** el título va al
  23 % también en «cara», «barras» y «difuminado». En esos encuadres la imagen
  empieza más abajo (y = 555 px en «cara», unos 656 px con 16:9), así que el
  título tapa la parte de arriba de la imagen. Se acepta para que el título
  se vea en las miniaturas. No hace falta pasar el encuadre a
  `lineas_titulo` ni a `zonas.calcular`.

### 5.2 Fotograma de portada

- Función nueva, fuera del proveedor, que **solo usa OpenCV**, sin S3FD ni
  torch. La app no carga el detector de caras en su propio proceso, y así no
  puede ponerse a descargar pesos a mitad de una publicación. Decisión mía.
  - Entrada: el vídeo que se publica (también `.editado.mp4`).
  - Mira los instantes 0.5, 1.0, …, 4.5 s, dentro de la duración del vídeo y
    de la ventana del título (0–5 s).
  - Elige el más nítido (`nitidez`, varianza del laplaciano).
  - Devuelve el segundo y una miniatura para la vista previa.
- **Vista previa:** se calcula en segundo plano al abrir el diálogo (en
  «Publicar shorts», al marcar cada short) y se muestra pequeña junto a las
  opciones de TikTok. Así se cumple el «debería mostrar una vista previa» de
  TikTok.
- Uso:
  - **TikTok, publicación directa:** `cover_timestamp` = ese segundo en ms.
    En borrador no se envía.
  - **Instagram:** `thumb_offset` = ese segundo en ms. Es un número, no una
    imagen, así que sobrevive a las publicaciones programadas, que son todas
    las de «Publicar shorts». No hace falta recomprimir nada.
  - **YouTube:** `thumbnail` = JPEG de ese fotograma, escrito en una carpeta
    temporal de la publicación.
  - Facebook, X y LinkedIn: nada.
- Si falla (no se puede leer el vídeo…), se publica sin esos campos y queda en
  el registro. Nunca bloquea la publicación.
- **Supuestos a verificar en la prueba real:**
  - En un canal de YouTube sin verificar, Upload-Post devuelve la miniatura
    rechazada como aviso y no como error de la subida.
  - Una subida programada conserva el archivo `thumbnail`.

  Si alguno falla, la miniatura de YouTube se quita en ese caso y se
  documenta.
- Vídeo sin título quemado (paso «Título» desactivado): se elige igual entre
  0.5 y 4.5 s. Es un buen fotograma aunque no tenga título. Decisión mía.

### 5.3 TikTok: publicación directa conforme

La «Required UX» oficial (developers.tiktok.com/doc/content-sharing-guidelines),
aplicada solo cuando el modo de TikTok es publicación directa (hoy «Público»):

1. **Cuenta:** el diálogo ya muestra la cuenta conectada (nombre y usuario).
   Se mantiene visible junto a las opciones de TikTok.
2. **Permisos de la cuenta:** el proveedor gana un método que lee
   `GET /api/uploadposts/tiktok/settings?profile=<perfil>` y devuelve
   `privacy_level_options`, `max_video_post_duration_sec`,
   `comment_disabled`, `duet_disabled` y `stitch_disabled`. Se pide al
   activar TikTok en modo directo, como ya se hace con las cuentas.
   - Error con `reauth_required` o `tiktok_reconnect_required`: TikTok
     muestra «Reconecta tu cuenta de TikTok en Upload-Post» y el modo directo
     no deja publicar. El borrador sí.
   - Otros errores o sin red: mismo comportamiento, con el motivo.
3. **Quién puede verlo:** un desplegable sin valor inicial («Elige…») con
   solo las opciones de la cuenta:
   - `PUBLIC_TO_EVERYONE` → «Todo el mundo»
   - `FOLLOWER_OF_CREATOR` → «Seguidores»
   - `MUTUAL_FOLLOW_FRIENDS` → «Amigos»
   - `SELF_ONLY` → «Solo yo»

   No se recuerda entre publicaciones. Sin elegir, «Publicar» queda
   desactivado con el motivo en la fila de TikTok.
4. **Permitir comentarios, dúos y stitch:** tres casillas, desmarcadas cada
   vez. Cada una se desactiva (en gris) si la cuenta lo tiene apagado. Se
   envían `disable_comment`, `disable_duet` y `disable_stitch` = no
   marcadas.
5. **Contenido comercial:** ver 5.4. En TikTok se envían
   `disclose_commercial`, `your_brand` y `branded_content`.
   - Etiqueta que se muestra:
     - solo «Tu marca» → «Se etiquetará como "Contenido promocional"»;
     - «Contenido de marca», solo o con «Tu marca» → «Se etiquetará como
       "Colaboración pagada"».
   - Con «Contenido de marca», la opción «Solo yo» se desactiva con el texto
     «El contenido de marca no puede ser privado». Si ya estaba elegida, se
     vacía la elección.
6. **Consentimiento antes de publicar:** texto junto al botón, con enlaces a
   las políticas de TikTok:
   - sin contenido de marca: «Al publicar, aceptas la Confirmación de uso de
     música de TikTok»;
   - con contenido de marca: «Al publicar, aceptas la Política de contenido
     de marca y la Confirmación de uso de música de TikTok».
7. **Duración:** si el vídeo pasa de `max_video_post_duration_sec`, TikTok se
   desmarca con el motivo, como ya hace `limites` con otros límites.
8. **Tiempo de proceso:** al terminar, la fila de TikTok dice que TikTok puede
   tardar unos minutos en mostrarlo. TSOTS ya consulta el estado.
9. Sin marca de agua ni logo añadidos. Ya es así.

En «Publicar shorts» (que hereda de `DialogoPublicar`), las mismas
elecciones valen para todos los shorts marcados del lote, también los
programados.

Programar: los campos nuevos viajan en la misma subida, como los de ahora.
`_modos` sigue distinguiendo borrador y directo por `post_mode`.

### 5.4 Contenido comercial en todas las redes

Un bloque común del vídeo, a la vista en cada publicación:

- Interruptor «Contenido comercial», apagado cada vez y sin recordarse.
- Si se enciende, dos casillas:
  - «Tu marca»: promocionas tu negocio, tu podcast o algo tuyo;
  - «Contenido de marca»: una marca te paga o te da algo.

  Hay que marcar al menos una; si no, «Publicar» se desactiva con «Indica si
  promocionas algo tuyo, de un tercero o ambos».

Qué se envía en cada red:

| Red | «Tu marca» | «Contenido de marca» |
|---|---|---|
| TikTok directo | `disclose_commercial`, `your_brand` | `disclose_commercial`, `branded_content` |
| TikTok borrador | nada; aviso «márcalo en la app de TikTok» | ídem |
| YouTube | nada (no es promoción pagada) | `hasPaidProductPlacement=true` |
| X | nada | `x_paid_partnership=true` |
| Instagram y Facebook | nada | nada por API; aviso «añade la etiqueta de colaboración pagada desde la app» |
| LinkedIn | nada | nada |

Se usan los campos propios de cada red, no el alias `paid_partnership`, para
que lo enviado sea explícito.

### 5.5 Declaraciones fijas

- **YouTube:**
  - `selfDeclaredMadeForKids=false` siempre: los vídeos del usuario no están
    dirigidos a niños. Se documenta en el README.
  - `defaultLanguage` y `defaultAudioLanguage` según el idioma con que se
    **procesó ese vídeo**, si la ficha o la transcripción lo guardan. Si no,
    según `idioma_subs` del panel. «es» → `es`/`es-ES`, «en» → `en`/`en-US`.
    Con «auto», o si no se sabe, no se envían y YouTube lo detecta. Decisión
    mía.
- **TikTok, «no puedes publicar ahora»:** `/tiktok/settings` no da ese dato.
  Se deja al error de la subida, que ya se muestra, y se documenta. Decisión
  mía.
- **Marcas de IA:** siguen en `false` (TikTok `is_aigc`, Instagram
  `is_ai_generated`, YouTube `containsSyntheticMedia`, X `made_with_ai` y
  Facebook `facebook_is_ai_generated`), con un comentario que explica por
  qué.

### 5.6 Documentación

README (ES/EN):

- Qué declara TSOTS por ti (no para niños, sin IA, idioma) y qué eliges en
  cada publicación (privacidad, permisos y contenido comercial en TikTok).
- La música de `~/TSOTS/musica` debe tener licencia para redes.
- La etiqueta de colaboración pagada en Instagram y Facebook se pone en su
  app.
- La miniatura de YouTube necesita un canal verificado.

## 6. Casos y errores

| Caso | Comportamiento |
|---|---|
| Cuenta de TikTok privada (sin «Todo el mundo») | Solo se ofrecen sus opciones. |
| «Contenido de marca» y «Solo yo» | Imposible: «Solo yo» desactivado y elección vaciada. |
| Comentarios apagados en la cuenta | Casilla en gris y `disable_comment=true`. |
| Vídeo más largo que lo que admite la cuenta | TikTok desmarcado con el motivo. |
| Los permisos de TikTok no cargan | Directo bloqueado con el motivo; borrador disponible. |
| Portada imposible | Se publica sin campos de portada; queda en el registro. |
| Miniatura de YouTube rechazada | Aviso en el registro; el vídeo se publica (supuesto 5.2). |
| TikTok en borrador | Sin privacidad, permisos ni contenido comercial; aviso de que se hace en la app. |

## 7. Verificación

- Tests de `campos()` para cada red y combinación: directo o borrador,
  comercial sí/no, tu marca o de marca, idiomas «es», «en» y «auto», con y
  sin portada.
- Test de lectura de `/tiktok/settings`: respuesta buena, 400 de reconectar,
  409 y 5xx.
- Test de la elección de portada con un detector falso: con caras, sin caras,
  vídeo de menos de 5 s y vídeo ilegible.
- Tests del diálogo sin ventana (offscreen):
  - «Publicar» bloqueado sin privacidad;
  - «Solo yo» desactivado con contenido de marca;
  - casillas desmarcadas al abrir;
  - privacidad no recordada;
  - texto de consentimiento según el caso;
  - lo mismo en «Publicar shorts».
- Test del título: posición vertical 23 %, horizontal 8 % y `\fad(0,300)`.
- Zonas del editor con Claude: la franja del título se mueve y los tests de
  zonas siguen en verde.
- **Prueba real, con permiso del usuario:**
  - un short a TikTok en directo con «Solo yo» para ver la portada y los
    campos;
  - uno a YouTube para ver la miniatura;
  - **un short programado** desde «Publicar shorts» a Instagram y YouTube,
    para comprobar la portada y la miniatura en una subida programada
    (supuestos de 5.2).

## 8. Lo que decide el constructor

- Distribución exacta de los controles nuevos en el diálogo.
- Nombres de funciones, clases y campos de `Opciones`.
- Dónde se guarda el JPEG temporal y cuándo se borra.
- Cómo se recomprime el JPEG si pasa de 8 MB.
- Textos en inglés de la traducción.
