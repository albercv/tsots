# Shorts a partir de un vídeo largo — diseño

Estado: borrador para aprobar (2026-11-05).

## Qué y por qué

El usuario graba vídeos largos (de 5 a 60 minutos) y quiere sacar de cada uno varios shorts para redes sin editarlos a mano. Cada short debe ser un trozo con sentido propio, entre 1:00 y 2:59, en vertical y con título. Hoy la app procesa el vídeo entero, pero no sabe elegir trozos.

**Es un éxito si** con un clic en un vídeo ya procesado salen, en una carpeta propia, los mejores trozos ordenados de mejor a peor y listos para subir. Lo flojo no sale.

## Decidido con el usuario

- **Duración:** cada short dura entre 1:00 y 2:59.
- **Cuántos:** como mucho, los minutos del vídeo divididos entre 3, redondeando hacia abajo (30 min → hasta 10). No tienen por qué salir todos: solo los buenos.
- **Quién elige:** el LLM local (Ollama) elige los trozos a partir de la transcripción.
- **Quién puntúa:** un modelo de decisión tipo Jev (`tev1:0.8b`, ya instalado en Ollama) puntúa cada candidato. Se ordenan de mejor a peor y los flojos se descartan.
- **Formato:** siempre vertical y con título propio, con el estilo del diseño de título (Titan One).
- **Subtítulos:** no hay que transcribir otra vez; ver «Subtítulos» más abajo.
- **Dónde se lanza:** desde su propia sección «Shorts» en la app.
- **Carpeta:** todo lo de los shorts de un vídeo va a una carpeta con el nombre del vídeo. Solo los shorts: las salidas normales siguen donde están.

## Prueba hecha (2026-11-05)

- **Ruta.** `tev1:0.8b` responde en `POST /v1/systemone` del servidor de Ollama (0.40.14). Esa ruta no está documentada.
- **Formato:**
  ```json
  {"model": "tev1:0.8b", "state": "<texto del trozo>",
   "questions": {
     "independiente": {"type": "choice", "instructions": "…",
                       "criteria": {"si": "…", "no": "…"}},
     "interes": {"type": "score", "instructions": "…",
                 "criteria": ["Aburrido…", "Flojo", "Correcto", "Interesante", "Muy enganchante…"]}}}
  ```
  - **Respuesta:** `answers.<pregunta>` con `choice` y `probabilities` en las de elección, o `score` (de 0 a niveles-1) y `probabilities` en las de puntuación.
  - **Errores útiles:** `type` admite `choice`, `noul` o `score`; `score` pide de 2 a 10 niveles; hay de 1 a 64 preguntas.
- **Resultado** sobre 5 trozos de 75 s de un vídeo real (`4steps`):
  - unos 0,2 s por trozo;
  - idéntico en dos pasadas;
  - notas de interés entre 1,66 y 2,70.

## Cómo funciona

1. **Entrada.** Los shorts se cortan de la versión sin subtítulos del vídeo procesado y usan su transcripción (`transcripcion.json` de la ficha).
   - **Qué se corta:** la `base.mp4` de la ficha si existe. Si no, el final (`_limpio.mp4`) siempre que no lleve subtítulos quemados. Si la base se hizo con otros ajustes del panel, se usa tal cual.
   - **Vídeo sin procesar o sin transcripción:** primero se procesa de forma normal con los ajustes del panel, publicando sus salidas como siempre (`planificar` y `ejecutar`), y forzando la transcripción.
   - **Fichas antiguas** con subtítulos quemados y sin base (`subs_quemados_sin_base`): no hay de dónde cortar. Sale un error claro que pide volver a procesarlo.
2. **Máximo.** `max = minutos de lo que se corta // 3`, ya sin silencios. Si sale 0, la sección avisa de que el vídeo es demasiado corto para shorts.
3. **Candidatos con gemma4.** La transcripción se trocea en frases numeradas con sus tiempos y se pide al modelo del caption (`modelo_caption`, con `ollama.chat_json`) hasta `2 × max` candidatos. Cada uno lleva:
   - frase inicial y final;
   - título de 3-5 palabras;
   - una línea de por qué.

   Al modelo se le piden números de frase, no segundos sueltos.
4. **Validación por código:**
   - descarta lo que dure menos de 60 s o más de 179 s;
   - descarta números de frase fuera de rango.

   Los cortes caen siempre en el límite de una frase. Los solapes se resuelven después de puntuar.
5. **Puntuación con `tev1`.** Se puntúa cada candidato válido con dos preguntas: «¿se entiende solo?», que es de elección, e «interés como short», que es de puntuación de 5 niveles. Se ordenan por interés.
   - **Pasan** los que tienen interés de al menos 2 («Correcto») y al menos un 50 % de probabilidad de «se entiende solo».
   - **Solapes:** recorriendo de mejor a peor, se descarta todo lo que se solape con uno ya elegido.
   - **Se quedan** como mucho `max`.
   - **Umbrales:** son constantes del módulo, para afinarlas con vídeos reales.
6. **Generación de cada short:**
   - corte de la base;
   - vertical con el encuadre del panel, normalmente «Seguir la cara (4:3)»;
   - subtítulos;
   - título de 5 s al inicio;
   - caption.

## Subtítulos

- **Por qué no se recorta la versión con subtítulos.** Los subtítulos del horizontal están maquetados para horizontal y sus líneas miden hasta unos 1.800 px. Al recortar a vertical se cortarían por los lados.
- **Qué se hace en su lugar:**
  - cada short sale de la base sin subtítulos;
  - los subtítulos se generan con la transcripción que ya existe, con los tiempos desplazados al inicio del trozo y maquetados para vertical, como hace hoy el paso vertical;
  - no se vuelve a transcribir.
- **Control:** casilla «Subtítulos» en la sección Shorts, activada por defecto, con el mismo estilo de subtítulos del panel.

## La sección Shorts

Es una sección plegable más del panel, como las de hoy (`SeccionPlegable`), con:

- **Opciones:**
  - casilla «Subtítulos»;
  - **selector de encuadre propio**, con las mismas opciones que el de la sección vertical y «Seguir la cara» por defecto. Es propio porque el de la sección vertical se desactiva cuando el paso vertical no está marcado.
- **Lanzarlo con el procesado:** casilla «Crear shorts al procesar», que añade los shorts al final de un procesado normal. Así se pueden sumar al pipeline, como pidió el usuario.
- **Lanzarlo aparte:** botón «Crear shorts», activo con un vídeo de la cola seleccionado y desactivado mientras la cola procesa, igual que los demás botones. Se ejecuta como un trabajo más de la cola, en segundo plano y con su progreso en la fila: buscando trozos, puntuando, short 3 de 7…

## Salida

- **Carpeta:** `<carpeta de salida>/<nombre del vídeo>/`, con:
  - `01 - <Título>.mp4`, `02 - <Título>.mp4`… de mejor a peor;
  - por cada short, su `.md` de caption y su `.srt`;
  - `shorts.json`: los candidatos con tiempos, notas, motivo, cuáles salieron y por qué se descartaron los demás.
- **Volver a crear shorts del mismo vídeo:**
  - **Qué se borra:** solo los archivos que escribió la app, que son los que lista el `shorts.json` anterior. Nunca se borra nada más de esa carpeta.
  - **Cuándo:** los shorts nuevos se generan en una subcarpeta temporal y solo al terminar bien sustituyen a los anteriores. Si falla o se cancela, los anteriores siguen ahí.
  - **Aviso:** con el botón, la app pregunta antes de lanzar. Con «Crear shorts al procesar» reemplaza sin preguntar, porque el usuario ya lo pidió al marcar la casilla.

## Decisiones mías (el usuario puede corregirlas)

- **Umbrales y orden:** los del paso 5.
- **Candidatos:** se piden `2 × max` para que haya donde elegir.
- **Caption:** cada short lleva su caption, con el mismo generador y sobre su trozo de transcripción, si el caption SEO está activo. Así se puede publicar.
- **Nombres:** los de los archivos y el `shorts.json`.
- **Encuadre:** el del panel.
- **Lanzamiento:** las dos formas, botón y casilla.
- **Juez.** Es `tev1:0.8b`, fijado como constante del módulo y sin control en la interfaz por ahora.
  - **Si falta `tev1`** (el modelo no está, la ruta no responde o la versión de Ollama es vieja), juzga el modelo del caption (`modelo_caption`, gemma4 en la máquina del usuario) con los mismos criterios, por chat y a temperatura 0. Para eso `ollama.chat_json` admite fijar la temperatura (hoy es 0,7). Se avisa en la fila.
  - Si tampoco responde el modelo del caption, no hay shorts y sale un aviso claro.
- **Transcripciones largas:** se trocean en partes de unos 20 minutos con solape, y los candidatos se juntan.

## Qué no entra

- Publicar los shorts desde la app: el diálogo de publicar sigue siendo por vídeo y se ve después.
- Ver o editar la lista de candidatos antes de generar.
- Shorts de vídeos que la app no puede procesar.
- La lista de procesados del TODO.

## Lo que haría que fallara aunque funcione

- Shorts que empiezan o acaban a mitad de frase.
- Shorts que no se entienden sin el resto del vídeo.
- Que salgan muchos shorts flojos solo por llegar al máximo.
- Que una prueba de shorts bloquee la cola durante mucho tiempo sin mostrar progreso.
- Que falle el procesado normal de un vídeo por culpa de los shorts.

## Lo que queda para el constructor

- Prompt exacto y esquema JSON de candidatos, y textos de las preguntas a `tev1`.
- Troceo de la transcripción en frases a partir de `transcripcion.json`, con palabras y tiempos.
- Cómo encaja el trabajo de shorts en `runner.py` y `EjecutorCola`, y su progreso.
- Si los shorts y su `shorts.json` se registran en la ficha.
- Traducciones con `lanzador/traducir.sh`.

## Dependencias con otras ramas

- **Título (`feature/titulo-inicio`).** El título de cada short usa el contrato que define el diseño del título:
  - `generar_titulo(transcripcion, idioma, modelo)`, llamado con el tramo del short;
  - `lineas_titulo(texto, resolucion, inicio, duracion)`, para añadir el título al `.ass` del short.

  Las dos ramas avanzan a la vez. Esta deja para el final la tarea de quemar el título y la hace cuando la del título esté en `develop`, rebasando. Hasta entonces el título de cada short es el que propone gemma4 junto con el trozo, y solo se guarda en `shorts.json` y en el nombre del archivo.
- **PR #25 (`fix/zoom-cara`).** Los shorts usan el vertical. Si #25 se mergea antes, se rebasa para tener la ventana 4:3.
