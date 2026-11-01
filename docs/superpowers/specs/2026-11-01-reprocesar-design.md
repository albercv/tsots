# Reprocesar un vídeo sin perder trabajo — diseño

Fecha: 2026-11-01. Estado: pendiente de aprobación del usuario. Base: `develop`
(`f5a6cf9`).

Las reglas marcadas *(decisión mía)* no las ha pedido el usuario: son
propuestas del diseño que puede corregir.

## Intención

Hoy cada pasada por el pipeline trata el vídeo como nuevo. El usuario lo vivió
así: procesó un vídeo sin el recorte de silencios. Para añadirlo arrastró el
`_limpio`, pero perdió el caption y tuvo que regenerarlo. Luego vio que le
faltaban subtítulos y volvió a pasar esa segunda versión, esta vez sin
caption, pensando copiarlo y pegarlo. No pudo, y la tercera versión ni
siquiera ofrecía Publicar. Acabó con cuatro versiones del mismo vídeo
(`x_limpio`, `x_limpio_limpio`…) ocupando espacio, y con el trabajo manual de
arrastrar el vídeo cada vez.

Lo que quiere:

- Relanzar pasos sobre el vídeo ya editado.
- Que la app avise cuando un paso ya está hecho («ya tiene subtítulos»), sin
  impedir rehacerlo si no le gusta el resultado.
- No perder nunca la información que ya existe del vídeo.

Sus reglas, con sus palabras:

- Si se reprocesa un paso que afecta a la imagen o a los tiempos, por ejemplo
  recortar silencios en un vídeo que ya tiene subtítulos, se hace desde la
  versión sin subtítulos. Por eso hay que guardar una **versión base** desde
  la que rehacer.
- Si solo se quiere el caption de un vídeo, no hace falta volver a versiones
  previas.
- No se rehace ningún proceso que ya exista de antes. El diseño debe analizar
  los casos y fijar reglas que ahorren CPU, GPU, tiempo y disco.

## Objetivos

1. **Una ficha por vídeo.** Da igual si se arrastra el original o una salida
   (`_limpio`, `_vertical`): la app reconoce que es el mismo vídeo.
2. **La cola muestra qué pasos tiene ya cada vídeo.**
3. **Avisa al marcar un paso que ya está hecho.** El usuario elige rehacerlo o
   mantener lo que hay.
4. **Las salidas no se multiplican.** Siempre son las mismas y se sobrescriben:
   `<nombre>_limpio.mp4`, `<nombre>_limpio_vertical.mp4` (o
   `<nombre>_vertical.mp4` si solo hay vertical), `.md` y `.srt`. `<nombre>`
   es siempre el del original. Se acaba el `_limpio_limpio`.
5. **La ficha guarda lo que cuesta rehacer:** el audio limpio, la base sin
   subtítulos (cuando hace falta), la transcripción, el caption, el
   seguimiento de la cara y los ajustes con que se hizo cada cosa.
6. **No se recalcula nada válido.** Cada resultado se reutiliza mientras no
   cambie aquello de lo que depende (ver «Reglas»).
7. **Publicar está disponible siempre que haya vídeo final y caption.** Además
   se permite «solo caption» sobre un vídeo ya procesado.
8. **Se guarda lo mínimo.** Los temporales se borran al terminar cada pasada.

## No objetivos (v1)

- **Editar el texto del caption en la app.** Sigue siendo de solo lectura y se
  copia con los botones de hoy.
- **Deshacer**, o guardar versiones anteriores del vídeo final. El usuario
  aceptó sobrescribir.
- **Reajustar los tiempos de una transcripción después de recortar.** Se
  vuelve a transcribir.
- **Fichas que sobrevivan a mover o renombrar los vídeos fuera de la app.** Se
  reconocen por ruta, tamaño y fecha.
- **La CLI** (`limpiarVideo.py`, `limpiarAudio.py`). Sigue igual y no usa
  fichas *(decisión mía)*.
- **Borrar las versiones duplicadas que ya existen** (`x_limpio_limpio`…).
  Las borra el usuario.

## Antiobjetivos

- Perder el caption o la transcripción al reprocesar. Hoy pasa: desmarcar
  Caption borra el `.md` de la salida.
- Volver a ejecutar la limpieza de audio (MossFormer2), Whisper, el LLM del
  caption o el seguimiento de la cara si existe un resultado válido.
- Apilar: subtítulos quemados encima de otros, recortar silencios dos veces,
  limpiar un audio ya limpio sin que el usuario lo pida.
- Crear un archivo de vídeo nuevo en cada pasada.
- Modificar el archivo original del usuario.

## Conceptos

- **Original:** el archivo que el usuario arrastró la primera vez. No se toca
  nunca.
- **Línea de tiempo:** qué trozos del original quedan en el vídeo. Es la del
  original si no se han recortado silencios. Limpiar el audio no la cambia;
  recortar silencios sí.
- **Base:** el vídeo con el audio limpio y/o los silencios recortados, sin
  subtítulos. Si no hay paso de audio ni de silencios, la base es el original.
- **Artefactos:** lo que la ficha guarda o apunta, cada uno con la «clave» de
  lo que lo determina. Si la clave coincide, el artefacto vale.

| Artefacto | Qué es | Su clave (de qué depende) | Coste de rehacer |
|---|---|---|---|
| Audio limpio | Pista de audio limpia, en FLAC *(decisión mía)* | Original + línea de tiempo del audio del que sale + tarea + modelo | Alto (MossFormer2) |
| Base | Vídeo sin subtítulos | Original + audio limpio (si hay) + ajustes de silencios (si hay) | Medio: auto-editor recodifica; con solo audio es una copia sin recodificar |
| Transcripción | Palabras con tiempos y bloques; el `.srt` sale de aquí | Línea de tiempo de la base + modelo de Whisper + idioma + glosario | Medio (Whisper) |
| Horizontal final | Base con los subtítulos quemados, o la base tal cual | Base + transcripción + diseño de subtítulos | Una codificación |
| Caption | Título, caption y hashtags | Texto de la transcripción + modelo LLM + contexto de marca + glosario | Medio (LLM) |
| Seguimiento de cara | Encuadre a lo largo del tiempo | Base | Medio (S3FD en CPU) |
| Vertical | 9:16 | Base + encuadre + seguimiento (si es «cara») + transcripción y diseño (si hay subtítulos) | Una codificación |

## Reglas

**R0 (general).**

- Un artefacto se reutiliza si su clave coincide.
- Si no coincide o falta, se rehace desde el ancestro válido más cercano,
  nunca desde más atrás.
- «Rehacer» invalida ese artefacto y todo lo que depende de él, pero nada de
  aquello de lo que él depende.

**R1. Un paso desmarcado conserva lo que hay.** Desmarcar Caption o Subtítulos
no borra el caption ni los subtítulos existentes. Cambia lo de hoy.

**R2. Los subtítulos nunca se queman sobre un vídeo que ya los tiene.** Se
queman siempre sobre la base.

**R3. La base solo se guarda aparte si el final lleva subtítulos.** Sin
subtítulos, el final es la base y no se duplica.

**R4. El caption depende del texto, no de los tiempos.** Recortar silencios o
rehacer los subtítulos no lo toca. Solo cambia si se pide rehacerlo, o si no
existe y se marca Caption.

**R5. Para el caption vale cualquier transcripción del vídeo, de cualquier
línea de tiempo.** Si no hay ninguna, se transcribe solo el audio del final,
sin codificar vídeo.

**R6. Cambiar de ajustes un paso ya hecho cuenta como «ya hecho, con otros
ajustes».** La app pregunta antes de rehacerlo y por defecto propone mantener
*(decisión mía)*: los ajustes del panel son globales y pueden haberse cambiado
pensando en otro vídeo.

**R7. Salidas que se quedan desactualizadas.** Si cambia algo de lo que
depende el vertical (la base, la transcripción o el diseño de subtítulos) y
el vertical existe, el aviso propone regenerarlo también. Si el usuario no
quiere, la ficha lo marca como desactualizado y la cola lo muestra
*(decisión mía)*.

**R8. Ajustes en lo que se rehace sin pedirlo.** Al volver a transcribir y
quemar tras un recorte, o al regenerar el vertical por R7, se usan los
ajustes guardados en la ficha para ese vídeo: diseño de subtítulos, idioma,
modelo de Whisper y encuadre. El glosario y el contexto de marca, en cambio,
se toman actuales, porque son diccionarios del usuario que solo mejoran
*(decisión mía)*.

**R9. El audio limpio va ligado a su línea de tiempo.** Si se limpió el audio
de una base ya recortada y después se recorta de nuevo con otros ajustes, ese
audio no cubre el original entero. En ese caso, y solo en ese, se vuelve a
limpiar el audio del original completo *(decisión mía)*.

**R10. La app sustituye sus propias salidas en vez de dejarlas duplicadas.**
Si un vídeo que solo tenía vertical (`x_vertical.mp4`) gana un horizontal,
las salidas pasan a ser `x_limpio.mp4` y `x_limpio_vertical.mp4`. Entonces
`x_vertical.mp4` se borra después de escribir las nuevas, y el `.md` y el
`.srt` se mueven junto al nuevo final. Solo se borran archivos que la ficha
registra como salidas de la app *(decisión mía)*.

### Casos

| Petición | Se reutiliza | Se hace | Desde | Codificaciones de vídeo |
|---|---|---|---|---|
| Añadir caption | Transcripción, si hay alguna (R5) | Transcribir el audio del final si no la hay; LLM | El final | 0 |
| Rehacer el caption | Transcripción | LLM | — | 0 |
| Añadir subtítulos | Base; transcripción si su línea de tiempo vale | Transcribir si hace falta; quemar | Base | 1 |
| Cambiar el estilo de los subtítulos | Base y transcripción | Quemar | Base | 1 |
| Rehacer los subtítulos («no me gustan») | Base | Transcribir y quemar. El caption se mantiene (R4) | Base | 1 |
| Añadir el recorte de silencios a un vídeo con audio limpio y subtítulos | Audio limpio; caption | Pasar al original el audio limpio sin recodificar → auto-editor → base nueva → transcribir (la línea de tiempo cambia) → quemar. Vertical: R7 | Original + audio limpio | 2 |
| Rehacer el recorte con otros ajustes | Igual que el anterior | Igual que el anterior | Original + audio limpio | 2 |
| Añadir la limpieza de audio a un vídeo ya recortado | Recorte, transcripción y caption | Limpiar el audio de la base recortada (más corto que el original), cambiarlo sin recodificar y quemar si hay subtítulos. Se mantienen los cortes ya aceptados en vez de recortar de nuevo *(decisión mía)*; ver R9 | Base | 0, o 1 si hay subtítulos |
| Rehacer la limpieza de audio (p. ej. otro modelo) | Caption | Desde el audio del original: limpiar → recortar de nuevo si había recorte → transcribir → quemar | Original | Según los pasos |
| Añadir el vertical | Base, transcripción y seguimiento | Convertir | Base | 1 |
| Cambiar el encuadre del vertical | Base, transcripción y seguimiento (si es «cara») | Convertir | Base | 1 |
| Marcar pasos ya hechos con los mismos ajustes | Todo | Nada, salvo que elija «Rehacer» | — | 0 |
| Arrastrar otra vez el original o una salida | La ficha entera | Se reconoce; no se crea un trabajo «nuevo» | — | 0 |

**Vídeos procesados antes de esta función** (sin ficha) *(decisión mía)*:

- **Original no reconocido con nombre normal** (`x.mov`): se crea una ficha
  con él como original, como con cualquier vídeo nuevo.
- **Salida antigua** (`x_limpio.mp4`, `x_vertical.mp4`, `x_limpio_limpio.mp4`…):
  - **Nombre de la ficha:** el del archivo sin un sufijo final `_limpio` o
    `_vertical`. `x_limpio_limpio` queda en `x_limpio`.
  - **El archivo** pasa a ser el final de la ficha y se sobrescribe a sí
    mismo. Nunca se escribe en otra versión antigua.
  - **Original:** se desconoce.
  - **Caption y transcripción:** si junto al archivo hay un `.md` y un `.srt`
    con su nombre, se importan como caption y como transcripción de su línea
    de tiempo.
- **Si después se arrastra el original verdadero** y su salida calculada
  (`x_limpio.mp4`) es el final de una ficha sin original, el original se
  adopta en esa ficha en vez de crear otra. Nunca hay dos fichas con la misma
  salida.
- **Pasos hechos:** no se conocen, así que no se marca ninguno con ✓.
- **Subtítulos ya quemados:** si existe el `.srt`, el vídeo probablemente los
  lleva y no hay base sin ellos. Entonces:
  - Subtítulos y vertical con subtítulos se bloquean, con un aviso: «Arrastra
    el original para rehacerlos».
  - Lo demás se permite. Recortar silencios corta la imagen y los
    subtítulos quemados a la vez, así que siguen sincronizados.

## Panel, cola y avisos

- **Las casillas del panel** siguen significando «hacer en esta pasada».
- **Volver a procesar sin arrastrar** *(decisión mía)*: una fila terminada
  vuelve a «en espera» de dos formas:
  - con la acción «Volver a procesar» sobre las filas seleccionadas;
  - arrastrando otra vez su vídeo o cualquiera de sus salidas.

  En ningún caso se duplica la fila.
- **Cada fila de la cola** muestra los pasos que ya tiene el vídeo, por
  ejemplo «✓ audio · silencios · subtítulos · caption», y los resultados
  desactualizados (R7).
- **Al pulsar Procesar**, y antes de empezar, la app revisa cada vídeo:
  - **Paso marcado y ya hecho con los mismos ajustes:** «"x" ya tiene
    subtítulos. ¿Rehacerlos?». Botones Rehacer y Mantener; Mantener es el
    botón por defecto. Incluye «aplicar a todos los vídeos».
  - **Paso marcado y ya hecho con otros ajustes:** el aviso dice qué cambia,
    por ejemplo «estilo X → Y». Rehacer aplica la regla mínima: aquí, solo
    volver a quemar.
  - **Paso que cambia la base:** el aviso explica qué más se rehará y qué se
    conserva. Por ejemplo: «Recortar silencios cambia los tiempos: se
    volverán a transcribir y quemar los subtítulos. El caption se mantiene».
    Ofrece regenerar el vertical (R7).
  - **Si al final no queda nada que hacer**, lo dice y no lanza el proceso.
- **«Solo caption»** se admite si el vídeo ya tiene un final. Hoy hace falta
  al menos un paso de vídeo.
- **Publicar** funciona con cualquier fila cuya ficha tenga final y caption.

## Ficha y almacenamiento *(decisión mía)*

- **Una carpeta por vídeo** en `fichas/<id>/`, junto a la carpeta
  `audio_procesado/` de hoy. Contiene:
  - `ficha.json`: original, salidas, claves, ajustes, pasos hechos y huellas
    (ruta, tamaño y fecha) de los archivos que reconoce;
  - el audio limpio en FLAC;
  - la base, solo con R3;
  - la transcripción en JSON (palabras con tiempos);
  - una copia del caption;
  - el seguimiento de la cara.
- **El `.md` y el `.srt` siguen junto al final, como hoy.** Publicar lee el
  `.md`; la copia de la ficha es la fuente de verdad y vuelve a escribir el
  `.md` si falta.
- **Reconocimiento:** un archivo arrastrado pertenece a una ficha si su ruta
  real es la del original o la de una salida, y su tamaño y su fecha
  coinciden con los guardados.
  - Si coincide la ruta pero no la huella (el archivo se editó fuera de la
    app), se avisa y se crea una ficha nueva.
- **Las salidas se escriben primero en un temporal y se sustituyen al final**,
  como hoy. La ficha se actualiza solo con lo que terminó bien.
- **Rutas de salida fijas:** quedan guardadas en la ficha. Si después se
  cambia la carpeta de salida, la nueva solo se aplica a los vídeos nuevos;
  los ya fichados siguen escribiendo en su sitio *(decisión mía)*.
- **`desinstalar.command`** borra también `fichas/`, igual que hoy borra
  `audio_procesado/`.

## Errores

- **Falta el original** (movido o borrado) **y un caso lo necesita** (rehacer
  audio o recorte): se avisa con la ruta y ese vídeo no se procesa. No se
  toca nada.
- **Falta o está dañado un archivo de la ficha:** ese artefacto se trata como
  inválido y se rehace desde sus ancestros (R0). Si no es posible, se avisa.
- **Fallo a mitad de la pasada:** las salidas anteriores y la ficha quedan
  como estaban, salvo los artefactos que se completaron. Las reglas de
  degradación de hoy no cambian: un caption fallido no hace fallar el vídeo,
  etc.
- **El mismo vídeo dos veces en la cola:** no se añade una segunda fila; se
  vuelve a poner en espera la que existe.

## Espacio

- **Por vídeo queda:** el final, el vertical si se pidió, la base solo si el
  final lleva subtítulos, el audio limpio en FLAC y unos JSON pequeños.
- **Temporales** (`_original.wav`, los `.mov` intermedios, los `.ass`): se
  borran al terminar cada pasada, haya ido bien o mal.
- **Los datos de una ficha se guardan hasta que el usuario los olvida**
  (decisión del usuario):
  - Cada fila de la cola muestra cuánto ocupan sus datos.
  - La acción «Olvidar este vídeo» borra la carpeta de su ficha (base, audio
    limpio, transcripción, seguimiento y copia del caption). No toca las
    salidas ni su `.md` y `.srt`.
  - Si después se arrastra una de esas salidas, cuenta como vídeo procesado
    antes de esta función (ver «Casos»).
- **`audio_procesado/` en producción** (4 GB de restos que no se reutilizan):
  se borra una sola vez al desplegar esta función (decisión del usuario). La
  versión nueva no deja restos ahí.

## Restricciones

- Código, comentarios e interfaz en español. Textos nuevos traducidos con
  `lanzador/traducir.sh` y `locale/en/LC_MESSAGES/tsots.po`.
- Tests antes de cada commit:
  `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -q`.
- Los ajustes guardados siguen siendo compatibles, y la versión anterior de la
  app sigue arrancando con lo que guarde esta.
- El JSON que el worker pasa al runner sigue aceptando el formato de hoy.
- Las reglas de degradación de los pasos (audio, silencios, subtítulos,
  caption, vertical) no cambian.

## Lo que queda al constructor

- El esquema de `ficha.json`, cómo se calcula el `<id>` y si hace falta un
  índice de rutas.
- Cómo se calculan las claves: por ejemplo, un hash de los ajustes que
  influyen en cada artefacto.
- La disposición del aviso de Procesar.
- Cómo se reparte el trabajo entre el pipeline, el runner y el worker, siempre
  que el pipeline siga pudiendo ejecutarse sin la GUI.
