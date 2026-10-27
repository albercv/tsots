# Pasos combinables y conversión a vertical — diseño

Fecha: 2026-10-27. Estado: aprobado por el usuario. Base: rama
`fix/sync-audio-caption-ligero` (PR #15); se rebasa sobre `develop` cuando
la #15 se integre.

## Intención

El usuario publica vídeos horizontales en YouTube y quiere sacar del mismo
material versiones verticales para Reels y TikTok. Además, los tres modos
fijos de hoy (`completo`, `solo_audio`, `solo_silencios`) se quedan cortos:
quiere combinar libremente los pasos (p. ej. recortar silencios y convertir a
vertical, sin limpiar audio).

Esta función ya se construyó y probó sobre una copia antigua de la app
(repo `ClearerVoice-Studio`, rama `claude/video-horizontal-vertical-dc028d`,
commit `258bdb6`, carpeta `clearvoice/`). Su diseño y su código sirven de
referencia: `videopipeline/vertical.py`, `videopipeline/seguimiento.py` y sus
tests son autocontenidos y se portan casi tal cual; la integración (pipeline,
runner, GUI) se rehace sobre la tsots actual.

## Objetivos

1. **Pasos combinables.** Los modos se sustituyen por casillas
   independientes, una por paso, cada una en su sección del panel:
   - Mejorar audio (sección Audio)
   - Recortar silencios (sección Silencios)
   - Añadir subtítulos (sección Subtítulos, ya existe)
   - Título, caption y hashtags (sección Caption, ya existe)
   - Convertir a vertical 9:16 (sección nueva Vertical)
2. **"Pipeline completo" = marcar todo** (decisión del usuario): una casilla
   que marca los cinco pasos, subtítulos y caption incluidos. Cada paso sigue
   siendo desmarcable en su sección.
3. **Conversión a vertical** 9:16, salida 1080x1920, con cuatro encuadres:
   recorte central (`central`, **por defecto**, decisión del usuario), fondo
   difuminado (`difuminado`), barras negras (`barras`) y seguir la cara
   (`cara`, detector S3FD del repo).
4. **Dos salidas cuando procede** (decisión del usuario): si vertical va con
   otro paso de procesado horizontal, salen el horizontal limpio (YouTube) y
   el vertical derivado de él, limpiando el audio una sola vez.

## No objetivos (v1)

- Extraer clips cortos del vídeo largo.
- Desplazar el recorte a mano o con keyframes; detección de hablante activo.
- Otras proporciones (4:5, 1:1). Reels y TikTok usan el mismo 9:16.
- Vista previa del encuadre vertical.
- Elegir en el diálogo Publicar entre el horizontal y el vertical: se publica
  la salida principal (ver "Salidas"). *(decisión mía)*
- Flags nuevos en `limpiarVideo.py` / `limpiarAudio.py`: su CLI no cambia.
- Caption como único paso, sin ningún paso de vídeo: no se permite en v1.
  *(decisión mía)*

## Antiobjetivos

- Que el vertical empeore, retrase o haga perder la salida horizontal.
- Codificar el vertical dos veces cuando hay subtítulos.
- Seguimiento de cara tembloroso o con barridos a través de cambios de plano.
- Que la GUI importe torch/cv2/S3FD.
- Romper ajustes guardados de versiones anteriores, o que una versión
  anterior deje de arrancar por ajustes guardados por esta (comparten
  `QSettings("albercv", "LimpiadorVideo")`).
- Romper la CLI o los tests existentes.

## Configuración (`PipelineConfig`)

- Desaparece `modo` como campo. Campos nuevos: `paso_audio: bool = True`,
  `paso_silencios: bool = True`, `paso_vertical: bool = False`,
  `encuadre: str = "central"`, `ENCUADRES = ("central", "difuminado",
  "barras", "cara")`. `subtitulos` y `caption_seo` siguen como están.
- Compatibilidad: un `modo` presente en un JSON de runner o en ajustes
  guardados se traduce (`completo` → audio+silencios, `solo_audio` → audio,
  `solo_silencios` → silencios) y no se conserva.
- `validar()`: `encuadre` válido y al menos un paso de vídeo marcado
  (audio, silencios, subtítulos o vertical); si no, `ValueError` con mensaje
  claro.
- Los valores por defecto reproducen el `completo` de hoy, así que
  `limpiarVideo.py` sigue haciendo lo mismo.

## Salidas *(regla: decisión mía sobre lo acordado)*

- **Horizontal**: existe si hay algún paso de procesado horizontal (audio,
  silencios) o si no hay vertical. Nombre `<nombre>_limpio.mp4`, con la regla
  de carpeta/archivo actual de `ruta_salida_final()`.
- **Vertical**: existe si `paso_vertical`. Si también hay horizontal:
  `<nombre>_limpio_vertical.mp4` junto a él (o `X_vertical.mp4` si la salida
  es un archivo explícito `X.mp4`). Si solo hay vertical:
  `<nombre>_vertical.mp4`.
- Subtítulos y caption se aplican a las salidas que existan; no crean una
  salida horizontal por sí solos cuando hay vertical. Ej.: vertical +
  subtítulos → solo `<nombre>_vertical.mp4` con subtítulos.
- **Salida principal** (la que abre la cola con doble clic, la que usa el
  caption y la que se publica): el horizontal si existe; si no, el vertical.
- Publicación atómica (tmp + replace) como hoy. El horizontal se publica
  antes de empezar el vertical.

## Orden del pipeline

1. Audio (si se pide): extraer → ClearVoice → remux.
2. Silencios (si se pide): auto-editor sobre lo anterior o sobre el original.
3. Sin audio ni silencios, la base horizontal es el original (sin recodificar).
4. Subtítulos (si se piden): transcribir **una vez** sobre la base
   (`_transcribir` actual, con glosario); quemar en el horizontal si existe.
5. Caption (si se pide): igual que hoy, sobre la salida principal; reutiliza
   las palabras de la transcripción si las hay.
6. Publicar el horizontal.
7. Vertical (si se pide): desde la base **sin subtítulos**; con subtítulos,
   `.ass` propio a 1080x1920 y filtro + `ass=` en una sola pasada.

Progreso: el total se calcula con los pasos pedidos. Etiquetas nuevas
`"Detectando caras"` y `"Convirtiendo a vertical"`, ambas con %.

## Errores *(decisión mía)*

- Vertical junto a una salida horizontal: si el vertical falla, el
  horizontal queda publicado, aviso `"Versión vertical falló: …"` y el
  trabajo termina OK.
- Vertical como única salida: su fallo es el error del trabajo.
- Si el único paso de vídeo pedido es subtítulos y el quemado falla, el
  trabajo falla (no hay otra salida que publicar).
- `cara` sin ninguna cara detectada, o sin poder cargar/descargar el
  detector → recorte central + aviso.
- Entrada ya vertical (alto ≥ ancho·16/9) → se reescala a 1080x1920 con
  barras + aviso; cuadradas y 4:5 se recortan normalmente.
- Cancelar durante el vertical: el horizontal publicado se conserva; los
  temporales del vertical se borran.

## Seguir la cara

Como en la referencia: muestreo a 2 fps a 480 px de ancho en CPU (medido más
rápido que MPS en este Mac: 85 frente a 129 ms/fotograma), cara de mayor
área, mediana móvil, zona muerta + suavizado, salto directo en cambios de
plano sin interpolar, recorte siempre dentro del fotograma, inicio sin cara
de más de 2 s → centro, `crop@v` movido con `sendcmd`, una sola codificación.
`stderr` de ffmpeg a fichero temporal y ffmpeg matado si falla el detector.

**Pesos del detector:** `sfd_face.pth` no está en tsots (`*.pth` ignorado).
La autodescarga de `S3FD` no funciona: llama a `gdown --id`, opción que ya
no existe en el `gdown==6.1.0` fijado, e ignora el error. `videopipeline`
descarga los pesos por su cuenta antes de crear `S3FD`, con la API de Python
de `gdown` (mismo id de Drive `1KafnHz7ccT-3IyddBsL5yi2xGtxAKypt`, misma
ruta que espera `S3FD`, ~90 MB, escritura atómica) y con la etiqueta
"Descargando detector de caras". Si la descarga falla → central + aviso.

## Codificación

1080x1920, `format=yuv420p`, `setsar=1`, `libx264 -crf 18 -preset medium`,
`+faststart`. Tasa de fotogramas entera con `fps_objetivo()` de la PR #15
(TikTok recodifica los vídeos de tasa variable del iPhone). Audio copiado si
la fuente ya está procesada y cabe en MP4; si la fuente es el original sin
procesar, o el audio no cabe en MP4 (p. ej. PCM), AAC 192k con
`FILTRO_HUECOS_AUDIO` (rellena los huecos del audio del iPhone). El quemado
de subtítulos sobre el original sin procesar aplica lo mismo. Fondo difuminado: desenfoque a 270x480 y reescalado (a
tamaño completo es ~5x más lento). Auxiliares (`subs_vertical.ass`,
`cara.cmd`) en `audio_procesado/<nombre>/`, referenciados por nombre con
`cwd` en esa carpeta.

## Runner, worker y cola

- Evento final: `{"done": true, "salida": <principal>, "salida_vertical":
  <ruta|null>}`; `salida_vertical` solo cuando hay dos salidas y el vertical
  se escribió en esta ejecución.
- Señal nueva `salida_vertical(fila, ruta)`; la fila muestra "+ vertical" y
  la ruta en el tooltip. `trabajo_terminado` no cambia.
- La cola conoce las salidas al terminar el trabajo (evento `done`), también
  el horizontal aunque se publique antes. Con "Seguir la cara" en un vídeo
  largo, el horizontal está en disco minutos antes de que la fila lo
  muestre; si se cancela durante el vertical, la fila queda "cancelado"
  aunque el horizontal exista. Aceptado en v1. *(decisión mía)*
- `_limpiar_temporal` borra los temporales de todos los destinos posibles.

## Panel

- La sección "Modo" desaparece. Encima de las secciones, una casilla
  **"Pipeline completo"** de tres estados: marcada si están los cinco pasos,
  parcial si algunos, vacía si ninguno; al pulsarla marca todos, o los
  desmarca todos si ya estaban todos. *(forma: decisión mía)*
- Cada sección lleva la casilla de su paso como primera fila de su contenido
  (como Subtítulos hoy); sus controles solo se habilitan con el paso marcado.
  Como el acordeón deja abierta una sola sección, el título de cada cabecera
  muestra si su paso está activo (p. ej. "✓ Audio"), sin convertir la
  cabecera en casilla. *(decisión mía)*
- Sección nueva "Vertical": casilla "Convertir a vertical (9:16)" y selector
  de encuadre; con "Seguir la cara", nota "Más lento: analiza el vídeo".
- Por defecto: audio y silencios marcados; subtítulos, caption y vertical
  desmarcados.
- Persistencia: se guardan y restauran los pasos y el encuadre, **excepto**
  `paso_vertical`, que arranca siempre desmarcado (es un paso ocasional).
  Se sigue escribiendo `panel/modo` con el equivalente más cercano para que
  las versiones anteriores arranquen *(decisión mía)*.
- Sin ningún paso de vídeo marcado, Procesar se deshabilita con un tooltip
  que explica por qué.
- Todos los textos nuevos con `_()` / `N_()` y traducidos en
  `locale/en/LC_MESSAGES/tsots.po` vía `lanzador/traducir.sh`.

## Restricciones

- Reglas de `CLAUDE.md` y `docs/DEVELOPMENT.md`: rama desde `develop`, PR
  contra `develop`, commits en inglés sin atribución a IA, tests en verde
  antes de cada commit; código, comentarios y GUI en español.
- La GUI no importa torch/cv2; S3FD se importa perezosamente en el runner.
- La rama `fix/sync-audio-caption-ligero` (sin integrar) también toca el
  pipeline: habrá conflictos al integrar la segunda de las dos.

## Lo que queda al constructor

- Cómo reestructurar `run()` para los pasos combinables.
- Nombres internos de helpers y el reparto en commits.
- Redacción exacta de etiquetas, avisos y tooltips (y su traducción).
