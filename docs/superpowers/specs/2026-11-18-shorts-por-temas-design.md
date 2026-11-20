# Shorts por temas: los mejores momentos, completos y repartidos — diseño

Fecha: 2026-11-18. Estado: pendiente de aprobación.

## 1. Intención

«Crear shorts» corta clips de 60 a 179 s de un vídeo largo (un podcast de 2 h,
por ejemplo). El usuario observa que, en los vídeos largos de verdad, los
shorts salen casi siempre de la misma zona o de zonas muy cercanas, y que
secciones enteras se quedan fuera.

Lo que quiere, con sus palabras: «encontrar de verdad los highlights del vídeo
y sacar vídeos lo más completos posible por debajo de esos 179 segundos». Le
gusta que un tema se explique entero; en 3 minutos da tiempo. **Rellenar un
trozo corto con frases de alrededor para llegar a 60 s no le vale**, porque
saldrían temas cortados.

### Cómo funciona hoy (`videopipeline/shorts.py`)

1. La transcripción se trocea en frases numeradas (`trocear_frases`).
2. `partes` divide el vídeo en partes de 20 min que se solapan 3.
3. Para cada parte, el modelo del caption (`qwen3.5:9b` por defecto; `num_ctx`
   16384) propone unos `2 × maximo × dura / duración` trozos como rangos de
   frases (`buscar_candidatos`).
4. `validar` descarta los rangos que no duran 60–179 s y los repetidos.
5. `tev1` puntúa cada trozo por separado (`puntuar`).
6. `elegir` ordena por interés y toma los mejores que no se solapan, hasta
   `maximo_shorts` = duración // 180.

### Por qué fallaba (hipótesis apoyada en `shorts.json` del Episodio 20, 2 h 11 min)

- **72 de 95 propuestas se descartaron por duración.** El modelo propone
  rangos de 3 a 10 frases y no calcula los segundos. Esas propuestas estaban
  repartidas por todo el vídeo, así que el modelo sí lo «ve» entero. Solo
  sobreviven las zonas donde acertó la duración por casualidad.
- **`elegir` no reparte.** 5 de los 16 shorts salieron entre los minutos 84 y
  93, y ninguno entre el 8 y el 35.
- Se piden unos 13 trozos por llamada sobre 20 min de texto: demasiado para un
  modelo de 9B.

## 2. Objetivos, no objetivos y antiobjetivos

**Objetivos**

- Cada short es un tema completo: empieza donde empieza el tema y acaba donde
  acaba, o es el fragmento autocontenido más completo de un tema más largo.
- La duración apunta a lo más largo posible por debajo de 179 s. Nunca baja de
  60 s.
- Los shorts salen de todo el vídeo: cada zona aporta su mejor tema si llega a
  la nota mínima.

**No objetivos**

- Cambiar el corte del vídeo, el encuadre, los subtítulos, los títulos, la
  publicación o la edición con Claude. Solo cambia qué trozos se eligen.
- Modelos nuevos. Se usan los que ya están: el del caption y `tev1`.

**Antiobjetivos**

- Alargar un trozo corto con frases de otro tema para llegar a 60 s.
- Dejar una zona sin shorts porque otra zona puntúe mejor, si esa zona tiene
  un tema que pasa la nota.
- Que la creación de shorts tarde tanto que deje de ser práctica. Orientativo:
  la **selección** (pasos 1–4) no tarda más del doble que ahora en un vídeo de
  2 h. El tiempo de cortar cada short no cambia por short; el total depende de
  cuántos salgan (ver «Pendiente del usuario» en 4.4).

## 3. Enfoques considerados

1. **Primero los temas y luego los mejores momentos (elegido por el
   usuario).** El modelo solo marca dónde empieza cada tema. Las duraciones
   las calcula el código, y el modelo solo elige fragmentos dentro de temas
   largos, viendo los segundos.
2. Mejorar el actual con segundos acumulados y una segunda pasada que corrija:
   sigue dependiendo de que el modelo cuente bien y no garantiza temas
   completos.
3. Cortar los temas con embeddings: hace falta un modelo nuevo y falla en
   conversaciones que saltan de tema.

## 4. Diseño

### 4.1 Paso 1: temas (segmentación)

- Ventanas de unos **10 min** de frases, recorridas en orden.
- Cada llamada recibe las frases con su número global y sus segundos, igual
  que hoy (`[i] 123s-130s: texto`). Devuelve la lista de temas que **empiezan**
  en la ventana:
  - `frase_inicio`: número global;
  - `titulo`: de 3 a 5 palabras, en el idioma de la transcripción;
  - `sigue_al_anterior`: verdadero si es otro punto de la misma conversación
    que el tema anterior, falso si cambia de asunto.
- Un tema va desde su `frase_inicio` hasta la frase anterior al siguiente tema.
- **Ventanas encadenadas por temas:** el último tema de una ventana puede
  estar a medias, así que la ventana siguiente empieza en la primera frase de
  ese tema. Con eso no hay solapes fijos ni temas partidos por el límite.
  - Para no atascarse: si el último tema empieza en la primera frase de la
    ventana (un tema de más de 10 min), la ventana siguiente empieza donde
    acabó esta y el tema continúa.
- La primera frase del vídeo siempre empieza un tema.
- Validación:
  - números fuera de la ventana o no crecientes se ignoran;
  - una ventana sin temas válidos cuenta como un único tema;
  - una respuesta inválida se reintenta una vez y, si vuelve a fallar, falla
    como hoy (`PasoFallido` con detalle).
- Temperatura baja, por ejemplo 0.2: es clasificar, no crear.

### 4.2 Paso 2: candidatos a partir de los temas

Las duraciones las calcula el código desde los tiempos de las frases.

1. **Bloques:** se agrupan los temas consecutivos unidos por
   `sigue_al_anterior`. Un bloque es una conversación entera.
2. **Candidatos completos:** cada tema y cada tramo de temas consecutivos de
   un mismo bloque que dure entre 60 y 179 s es candidato. Se prefieren los
   tramos que empiezan en un tema y acaban en el final de otro, sin cortes a
   mitad de tema.
3. **Temas de más de 179 s** (solo temas sueltos; los bloques no reciben
   esta llamada, sus tramos ya salen en el punto 2): una llamada al modelo con
   las frases de ese tema, cada una con su segundo **desde el inicio del
   tema**, pidiendo **hasta k** fragmentos autocontenidos de 60 a 179 s. La
   instrucción pide los más largos que mantengan la idea completa, con gancho
   al empezar y cierre al acabar. Devuelve `frase_inicio`, `frase_fin`,
   `titulo` y `motivo`.
   - **k** = duración del tema // 180, al menos 1 y **como mucho 3 por
     llamada**.
   - **Temas de más de 10 min:** se parten en subventanas de unos 10 min por
     límites de frase, con una llamada por subventana. Así ninguna llamada
     pasa de unos 5 k tokens ni pide más de 3 fragmentos. Decisión mía.
   - Validación como `validar`.
   - Si un fragmento no cuadra, se pide **una** corrección diciéndole cuánto
     dura («dura 214 s: acórtalo a 179 como mucho sin dejar la idea a
     medias»). Si sigue sin cuadrar, se descarta con su código.
4. Temas de menos de 60 s que no forman tramo con sus vecinos: no son
   candidatos. Descarte nuevo: `"tema_corto"`.

### 4.3 Paso 3: notas (sin cambios)

`puntuar` con `tev1` y, si falla, con el modelo del caption, igual que hoy.
Mismos umbrales: `UMBRAL_INTERES` 2.0 y `UMBRAL_INDEPENDIENTE` 0.5.

### 4.4 Paso 4: elegir con reparto

- Se divide el vídeo en **tramos de unos 10 min**.
- **Primera vuelta:** el mejor candidato que pase la nota en cada tramo (el
  tramo de un candidato es el de su inicio), sin solapes.
- **Segunda vuelta:** se completa con los mejores que queden, sin solapes,
  hasta `maximo`.
- Entre candidatos que se solapan gana más nota de interés. Si la diferencia
  es de 0.3 puntos o menos, gana **el más largo**, que es el más completo. Es
  una decisión mía, ajustable.
- Los elegidos se siguen devolviendo de mejor a peor (la numeración de los
  archivos no cambia de criterio).
- **Cuántos como máximo (decisión del usuario): uno cada 10 minutos.**
  - `maximo_shorts` pasa a 0 si el vídeo dura menos de 180 s, como hoy, y si
    no a `max(1, duración // 600)`. En 2 h 11 min salen 13; en 25 min, 2.
    Antes era duración // 180: 43 en 2 h 11 min. El redondeo es decisión mía.
  - Con ese tope, la primera vuelta puede dar más elegidos que `maximo` (un
    vídeo de 2 h 11 min tiene 14 tramos). En ese caso se quedan los `maximo`
    mejores. La segunda vuelta solo rellena si algún tramo se quedó sin
    candidato.
  - Las pruebas que usan `maximo_shorts` se actualizan.

### 4.5 Registro y compatibilidad

- `shorts.json` pasa a `"version": 2`:
  - añade `"temas"`: inicio, fin, título y `sigue_al_anterior` de cada tema;
  - los candidatos guardan de dónde salen (`"origen"`: `"tema"`, `"tramo"` o
    `"fragmento"`).
- `listar` y `_anteriores` siguen leyendo `candidatos` y `archivos` igual. Los
  `shorts.json` de versión 1 siguen valiendo.
- Progreso: «Buscando temas» (paso 1), «Buscando los mejores momentos»
  (paso 2), «Puntuando los trozos» (paso 3). Mismo número total de pasos
  visibles, con el porcentaje dentro de cada uno.

### 4.6 Rendimiento

- Hoy `chat_json` descarga el modelo después de cada llamada
  (`keep_alive: 0`). Con unas 13 ventanas más las llamadas de temas largos en
  un vídeo de 2 h, recargar el modelo cada vez sería lento. Durante la
  búsqueda de shorts el modelo se mantiene cargado (por ejemplo, un
  `keep_alive` de unos minutos pasado como parámetro). La última llamada lo
  descarga, para no retener la memoria antes del siguiente vídeo de la cola,
  que es por lo que existe `keep_alive: 0`.
- Ventanas de 10 min: unos 4–5 k tokens. Cabe de sobra en `num_ctx` 16384.

## 5. Casos

| Caso | Comportamiento |
|---|---|
| Vídeo de menos de 10 min | Una sola ventana. |
| Vídeo sin frases | Ningún candidato, como hoy. |
| Tema de 15 min | Paso 2.3 con k = 5. |
| Conversación con temas de 30–50 s encadenados | Tramos de temas del mismo bloque de 60–179 s. |
| Tema suelto de 40 s | `tema_corto`, no sale. |
| El modelo devuelve temas desordenados o repetidos | Se ignoran los inválidos; la ventana avanza. |
| Ningún candidato pasa la nota | Mismo aviso que hoy: no se crea ningún short. |

## 6. Verificación

- Tests puros con un `chat_json` falso:
  - segmentación y encadenado de ventanas, incluido el tema de más de 10 min
    que no atasca;
  - bloques y tramos;
  - temas largos con k fragmentos y la corrección;
  - `tema_corto`;
  - reparto en dos vueltas y desempate por duración;
  - `shorts.json` v2 y lectura de v1.
- **Solo selección, sin cortar nada:** una entrada nueva (función y orden de
  línea de comandos) que ejecuta los pasos 1–4 sobre una ficha y escribe el
  resultado en un JSON aparte, sin tocar la carpeta de shorts. Es
  imprescindible para probar sin destruir trabajo: «Crear shorts» borra los
  shorts anteriores, y la carpeta del Episodio 20 tiene 15 shorts editados con
  Claude y registros de publicación.
- Prueba real con esa entrada, en local, sobre el Episodio 20, comparando con
  su `shorts.json` actual (16 shorts, 5 entre los minutos 84 y 93). Para el
  tiempo del algoritmo actual se ejecuta su selección en una copia de
  `develop`, también sin cortar. Se comprueba:
  - shorts repartidos por todo el vídeo;
  - mayoría por encima de 120 s;
  - ningún descarte masivo por duración;
  - tiempo total.

## 7. Lo que decide el constructor

- Redacción exacta de las instrucciones al modelo (en español, como las
  actuales).
- Tamaño exacto de ventana y tramo (unos 10 min) y temperatura del paso 1.
- Cómo se generan los tramos de temas sin explotar combinaciones. Por
  ejemplo, desde cada inicio de tema, el tramo más largo que quepa en 179 s.
- Nombres de funciones y la forma del parámetro de `keep_alive`.

## 8. Cambio (2026-11-20): de 1 a 3 shorts por tramo

A petición del usuario, cada tramo de 10 minutos aporta **de 1 a 3** shorts en lugar de uno solo.

- `MAX_POR_TRAMO = 3`. El tope global (`maximo_shorts`) es 3 × el número de tramos, contando el último aunque esté incompleto. Así nunca recorta lo que corresponde a un tramo.
- La primera vuelta no cambia: el mejor de cada tramo. La segunda rellena por nota hasta 3 por tramo. Un cambio por «gana el más largo» en la segunda vuelta no puede pasar de 3 en el tramo del nuevo ni dejar sin short el tramo del sustituido.
- Los umbrales de nota no cambian. Un tramo sin ningún tema que pase la nota se queda sin short: no se meten shorts flojos para llegar a 1.
- En el Episodio 20 (reproducción de la elección con los candidatos guardados) salen 29 shorts en lugar de 13, con 1 a 3 en cada tramo completo. Solo la cola de 2 minutos, que no tiene candidatos, se queda sin short.
