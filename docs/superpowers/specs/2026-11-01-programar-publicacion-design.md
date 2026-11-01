# Programar publicaciones — diseño

Fecha: 2026-11-01. Estado: aprobado por el usuario (modo autónomo). Base: `develop`
(`6cebe7a`).

Las reglas marcadas *(decisión mía)* no las ha pedido el usuario: son
propuestas del diseño que puede corregir.

## Intención

Hoy **Publicar…** solo sube al momento. Cuando el usuario quiere que un
vídeo salga más tarde, se lo envía al móvil y lo programa a mano en la app de
TikTok, YouTube o la que toque, una por una. Quiere hacerlo desde TSOTS:

- En el diálogo Publicar, elegir entre **publicar ya** o **programar** para
  una fecha y hora.
- Poder **cancelar** lo programado desde la app, viéndolo en un
  **calendario** de mes con los títulos dentro de cada día (como Google
  Calendar; opción B de los bocetos).

## Objetivos

1. Programar desde el diálogo Publicar, con una sola fecha y hora para todas
   las redes marcadas.
2. Que, una vez programado, la app pueda cerrarse o el Mac apagarse: lo
   publica Upload-Post a esa hora.
3. Una ventana **Programadas…** con un calendario de mes que muestra lo
   pendiente en Upload-Post y deja cancelarlo, red a red o todo el vídeo.
4. Que el aviso de «ya publicado» del diálogo Publicar sepa que un vídeo está
   programado, y lo olvide si se cancela desde el calendario.

## Fuera de alcance

- **Cambiar la fecha** de algo ya programado (el usuario se conforma con
  cancelar y volver a programar). La API lo permite (`PATCH`): queda para
  más adelante.
- La **cola de huecos** de Upload-Post (`add_to_queue`): siempre elige fecha
  y hora el usuario.
- Saber **cómo acabó** una publicación programada (enlace, error) después de
  su hora. Se mira en la red o en Upload-Post. El registro local se queda
  con «programado para…».
- Programar desde el calendario (pulsar un día para programar algo nuevo).
- Programación nativa de cada red (`youtube_publish_at` y similares).

## Lo que no debe pasar

- Que un vídeo programado se publique dos veces por un reintento: la subida
  sigue sin repetirse nunca sola, igual que hoy.
- Que cancelar algo deje el vídeo sin cancelar sin decirlo: si Upload-Post
  falla, el error se ve y la entrada sigue en el calendario.
- Mostrar o registrar datos privados de la cuenta (ids de lugar de TikTok,
  la API key, el perfil), igual que hoy.

## API de Upload-Post (docs leídas el 2026-11-01)

- `POST /api/upload` admite `scheduled_date` (ISO 8601, futura, como mucho a
  365 días) y `timezone` (IANA; si se da, la fecha se interpreta en esa
  zona). Responde 202 `{"success": true, "job_id": …, "scheduled_date": …}`.
  Programar reserva un crédito por red; cancelar antes de la hora lo
  devuelve.
- El vídeo se queda guardado con el trabajo programado (el detalle trae
  `media_urls`; cancelar dice «assets deleted»). Por eso la app no tiene que
  seguir abierta. Esto se deduce de la documentación, que no lo dice con
  esas palabras.
- `GET /api/uploadposts/schedule?profile_username=<perfil>` →
  `{"scheduled_posts": [...]}`. Cada trabajo trae `job_id`, `scheduled_date`
  (UTC), `platforms` (lista), `title`, `caption`, `fields` (los campos con
  que se subió), `external_id`, `original_timezone`. Solo lista lo pendiente.
  Admite `from`/`to`; sin `limit` devuelve todo.
- `DELETE /api/uploadposts/schedule/<job_id>` → `{"success": true,
  "credits_refunded": n}`; 404 `{"error": "Job not found"}` si ya no existe.
- `GET /api/uploadposts/status?job_id=` da `status: "pending"` mientras no
  ha corrido. No se usa en esta versión.
- No documentado: qué pasa al combinar `async_upload=true` con
  `scheduled_date`. Ver «Riesgos».

## Cómo se ve

### Diálogo Publicar

Una fila nueva bajo «Ubicación»:

```
Cuándo:  (•) Ahora   ( ) Programar  [ 03/11/2026  18:00 ▾]
```

- **Ahora** es lo de siempre y es la opción por defecto al abrir.
- **Programar** activa un selector de fecha y hora (`QDateTimeEdit` con el
  calendario desplegable) en la hora del Mac. El botón «Publicar» pasa a
  llamarse **«Programar»**.
- Valor inicial del selector: la siguiente hora en punto que quede al menos
  a una hora vista *(decisión mía)*.
- Límites: al menos **15 minutos** en el futuro y como mucho a **365 días**
  *(decisión mía: subir el vídeo a cada red lleva tiempo, y Upload-Post
  rechaza una fecha que ya pasó)*. Fuera de rango, el botón se desactiva y
  la línea de estado dice por qué.
- La confirmación cambia de «¿Publicar ahora?» a «¿Programar para el martes
  3 de noviembre a las 18:00?», con el mismo resumen de redes y modos.
- Durante la subida, cada red muestra lo de hoy («Subiendo…»). Al acabar,
  una red programada con éxito muestra **«📅 Programado para el 03/11
  18:00»** en verde. No hay sondeo de estado: no hay nada que esperar.
- Los modos de cada red se respetan tal cual *(decisión mía)*: un TikTok en
  borrador programado llega a los borradores a esa hora.
- Al terminar, las redes programadas se desmarcan como hoy las publicadas,
  para no programarlas dos veces sin querer.

### Aviso de «ya publicado»

El aviso amarillo de arriba y la confirmación ya leen el registro local.
Una entrada programada se describe como «TikTok (programado para el 03/11
18:00)» en lugar de con la fecha de publicación. Cuenta igual que una
publicada para avisar de que saldría repetido.

### Ventana «Programadas…»

- Botón **«Programadas…»** en la barra inferior de la ventana principal,
  junto a «Redes…», con tooltip «Lo que tienes programado en el servicio».
- Ventana con un **calendario de mes**: cabecera con «‹ Anterior», el mes y
  el año, y «Siguiente ›». Abre en el mes actual. Semanas de lunes a
  domingo; los días de otros meses, atenuados; hoy, resaltado.
- Dentro de cada día, una **etiqueta por vídeo y hora**: «18:00 Título ·
  TikTok, YouTube». Los trabajos con el mismo título y la misma hora se
  juntan en una etiqueta *(decisión mía: TSOTS sube una vez por red, así que
  un vídeo programado en tres redes son tres trabajos)*. Si no caben, el día
  muestra «+N más» y al pulsarlo se ven todas.
- Las horas se muestran en la zona horaria del Mac; al pie, «Hora de tu Mac
  (Europe/Madrid)».
- Al **pulsar una etiqueta**, un detalle con título, fecha y hora, y una
  fila por trabajo con sus redes, su modo si se sabe (por `fields`, p. ej.
  «TikTok · Borrador») y un botón **Cancelar**. Si hay más de un trabajo,
  también **«Cancelar todas»**.
- Cancelar siempre pide confirmación: «¿Cancelar la publicación de «Título»
  en TikTok el 03/11 a las 18:00? Upload-Post devuelve el crédito.».
- Salen también los trabajos programados desde la web de Upload-Post o desde
  otra app con el mismo perfil, y se cancelan igual. Un trabajo con varias
  redes se cancela entero (es un solo trabajo en el servicio).
- La lista se pide a Upload-Post **en segundo plano** al abrir la ventana y
  al pulsar **«Actualizar»**. Mientras tanto, «Consultando…». Si falla, se
  muestra el motivo y el calendario se queda vacío o con lo último que se
  leyó en esa ventana.
- Sin API key o sin perfil, el mismo mensaje que el diálogo Publicar
  («Falta la API key del servicio: guárdala en Redes…»).
- Tras cancelar, la entrada desaparece del calendario. Si la cancelación
  falla, el motivo se ve y la entrada se queda.

## Cómo encaja en el código

Se mantienen las capas de hoy: `upload_post` es el único que conoce el
servicio, `publicador` y la app solo ven el protocolo `Proveedor`.

- **`modelo.py`**
  - `Opciones.programada: datetime | None = None`, con zona horaria
    (`tzinfo` = la del Mac). `None` = publicar ya.
  - `Resultado.programada: datetime | None = None`: la red quedó programada
    para esa fecha; `referencia` lleva el `job_id`. Va con `ok=True`.
  - `Programada` (dataclass congelada): `referencia` (job_id), `fecha`
    (datetime con zona), `plataformas: tuple[Plataforma, ...]`, `titulo`, y
    `modos: dict[Plataforma, str]` si el servicio los da. Las redes que la
    app no conoce se ignoran.
- **`proveedor.py`**: el protocolo gana `programadas() -> list[Programada]`
  (lanza `ErrorConsulta`) y `cancelar(referencia) -> None` (lanza
  `ErrorConsulta`; un 404 cuenta como ya cancelada y no lanza).
- **`upload_post.py`**
  - `campos(...)`: con `opciones.programada`, añade `scheduled_date`
    (fecha local sin desfase, `YYYY-MM-DDTHH:MM:SS`) y `timezone` (nombre
    IANA de la zona de la fecha), y no pide `async_upload`.
  - `_interpretar_subida`: un 2xx con `job_id` y `scheduled_date` y sin
    `results` → `Resultado(ok=True, programada=<fecha>, referencia=job_id)`.
  - `programadas()` y `cancelar()` sobre los endpoints de arriba, con el
    mismo trato de errores y de registro que las demás consultas (la clave
    nunca al registro).
- **`publicador.py`**: un resultado con `programada` termina al momento, sin
  sondeo. Se anota en el registro con su fecha programada y su `job_id`.
- **`registro.py`**: `Entrada` gana `programada: str = ""` (ISO) y
  `referencia: str = ""` (solo se escriben si hay valor, como
  `sin_confirmar`). Nueva función `olvidar(video, referencia)` que quita la
  entrada con ese `job_id` (escritura atómica, como `anotar`).
- **Índice de programadas** *(decisión mía)*: para que cancelar desde el
  calendario pueda limpiar el registro del vídeo, la app guarda en sus
  ajustes (`QSettings`) un mapa `job_id → ruta del vídeo` al programar. Al
  cancelar: si el `job_id` está en el mapa, `registro.olvidar` sobre ese
  vídeo y se borra del mapa. Las entradas cuya fecha ya pasó se pueden
  purgar al abrir el calendario. Sin entrada en el mapa (programado desde la
  web), no hay registro que limpiar.
- **`app/widgets/dialogo_publicar.py`**: la fila «Cuándo», el texto del
  botón, los límites de fecha, la confirmación y el texto «📅 Programado
  para…».
- **`app/widgets/dialogo_programadas.py`** (nuevo): la ventana del
  calendario. Lee la API key del Llavero y consulta en segundo plano con
  `segundo_plano`, como `app/cuentas.py`.
- **`app/main.py`**: el botón «Programadas…» en la barra inferior.
- **Traducciones**: textos nuevos en español, traducidos con
  `lanzador/traducir.sh` y `locale/en/LC_MESSAGES/tsots.po`.
- **Documentación**: `docs/DEVELOPMENT.md` (diálogo Publicar y ventana
  nueva) y el README si describe Publicar.

## Pruebas

TDD, con el proveedor falso de `tests/redes_falsos.py` y respuestas HTTP
falsas como las de `tests/test_redes_upload_post.py`:

- `campos` con y sin `programada` (fecha local y `timezone`).
- Interpretar el 202 de programación; el 404 al cancelar; la lista de
  programadas con redes desconocidas, fechas UTC y varias redes por trabajo.
- `publicador` no sondea un resultado programado y lo anota con su fecha y
  `job_id`.
- `registro`: leer y escribir `programada`/`referencia`; `olvidar`; los
  ficheros antiguos siguen leyéndose.
- Diálogo Publicar: el botón cambia de texto, los límites de fecha lo
  desactivan, la fila muestra «Programado para…», el aviso describe lo
  programado.
- Calendario: agrupa por título y hora, pone cada etiqueta en su día en la
  zona del Mac, cancelar llama al proveedor y limpia el registro vía el
  índice, un fallo al cancelar deja la entrada.

Nunca se ejecuta `-m lenta` ni `-m ""`: `tests/test_redes_real.py` publica de
verdad.

## Riesgos y comprobación real

- **`async_upload` con `scheduled_date`** no está documentado: al programar,
  la subida **no** pide `async_upload` *(decisión mía)*, para recibir el
  `job_id` en la misma respuesta (el 202 documentado). Si aun así el servicio
  responde solo con un `request_id` aceptado, la red se da por programada sin
  referencia: sale en el calendario y se cancela desde ahí, pero el registro
  del vídeo no se limpia solo. Queda anotado en el registro de la publicación.
- **Prueba real** (solo con permiso explícito del usuario y su cuenta):
  programar un vídeo corto en una red para dentro de varios días, verlo en
  el calendario y cancelarlo. No llega a publicarse nada y el crédito vuelve.
  Sirve para confirmar la forma real de la respuesta.
