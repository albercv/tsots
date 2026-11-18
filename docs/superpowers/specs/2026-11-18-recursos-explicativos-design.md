# Recursos explicativos para «Editar con Claude»: señalar en pantalla, B-roll, iconos y datos

Fecha: 2026-11-18 · Estado: aprobado
Repo: `~/Documents/personalProjects/limpiadorVideo` (TSOTS), sobre v1.12.0.
Se apoya en el diseño `docs/superpowers/specs/2026-11-17-edicion-shorts-design.md`
(agente, `plan.json`, zonas, render) y en `2026-11-17-editar-video-suelto-design.md`.

## 1. Intención

Hoy Haiku solo pone texto (rótulos, contadores, título), emojis, golpes,
transiciones y zooms. El usuario quiere que la edición **acompañe a la
explicación**, como un vídeo explicativo profesional:

- que **señale en la pantalla** lo que se está diciendo cuando sale escrito
  (sus vídeos son a menudo demos de producto, como `odin_17_11`);
- que meta **B-roll** (clips de recurso) cuando se habla de algo concreto que no
  se ve;
- que los estilos formal y académico tengan **iconos y datos animados** en vez de
  solo texto.

Todo **gratis**: sin servicios de pago, solo con lo que corre en el Mac y una
clave gratuita de Pexels.

Y Haiku tiene que **elegir el mejor recurso** en cada momento, entre los de
antes y los nuevos.

## 2. Objetivos, no objetivos, anti-objetivos

**Objetivos**
- **Señalar** (`señalar`): círculo, flecha o subrayado sobre un texto que sale en
  pantalla mientras se dice. Sigue al texto aunque la imagen se mueva (vídeo
  grabado con el móvil apuntando al monitor).
- **Lupa** (`lupa`): una ventana con la zona de ese texto ampliada, unida con un
  trazo a su sitio. Sustituye al zoom de cámara, imposible en vídeos a pantalla
  completa (los subtítulos van quemados).
- **B-roll** (`broll`): Haiku escribe qué buscar; el render descarga un clip de
  Pexels y lo pone 2,5 s. Según el contenido (decisión del usuario, opción C):
  - **tapa** toda la imagen por encima de los subtítulos si en ese momento no
    hay texto en pantalla (sale la persona hablando);
  - **ventana** (tarjeta arriba) si en pantalla hay texto que importa (demo).
- **Icono** (`icono`): un icono vectorial de un catálogo fijo, animado como hoy
  los emojis.
- **Dato** (`dato`): un número grande que cuenta hasta su valor con una etiqueta
  debajo; si es un porcentaje, además una barra que se llena.
- **Elegir el mejor recurso**: tabla de decisión en la skill, contexto con los
  hechos que la alimentan (qué hay en pantalla, qué números se dicen, qué
  iconos existen, si hay B-roll) y sugerencias del validador.

**No objetivos (v1)**
- Imágenes o vídeo generados por IA, 3D, recortar a la persona («texto detrás»),
  motion tracking de objetos que no sean texto, motor gráfico aparte (Manim,
  Motion Canvas, Remotion).
- Otros bancos de stock (Pixabay…): solo Pexels.
- Que Haiku vea los clips antes de elegirlos: los ve en `verificacion.png`.
- Gráficas con varias series o ejes: solo número + barra de porcentaje.

**Anti-objetivos**
- Tapar los subtítulos quemados o el título (antes de `titulo.hasta`).
- Tapar una demo con B-roll a pantalla completa.
- Inventar cifras: un `dato` solo con un número que se dice en el vídeo.
- Que un fallo de Pexels, de red o del OCR haga fallar la edición: ese recurso
  se omite y el resto sigue.
- Guardar o mostrar la clave de Pexels en ficheros del trabajo, logs o el plan.
- Cualquier servicio de pago.

## 3. Hechos del código en los que se apoya

- `video.mp4` del trabajo es el short o el final **ya terminado**: lleva quemados
  los subtítulos (si se pidieron) y el título (los primeros `titulo.hasta` s).
  Por eso el OCR los vería y hay que enmascararlos; con `zonas.subtitulos =
  None` no hay subtítulos quemados y no se enmascara esa banda.
- Haiku solo lee `contexto.md` (estilo, zonas, caption, frases y palabras con
  tiempo) que escribe `preparar.py`; ve la imagen solo al final, en
  `verificacion.png` (`verificar.py`, un fotograma en `t + 0.4` de cada momento).
- `plan.py`: `TIPOS`, `Momento` (campos fijos), `DURACION` por tipo, `validar`
  (palabra anclada al transcript con tolerancia 0.4 s, nada antes de
  `titulo.hasta` salvo zoom/golpe, densidad máxima del estilo, solapes en la
  «zona superior» entre `_VISUALES`, con excepciones para emoji lateral).
- `renderizar.py`: `derivar` (pura) convierte momentos en `Pieza`s y `EventoSfx`;
  cada pieza se dibuja con PIL a fotogramas RGBA 1080×1920 y `rotulos.render_slot`
  la guarda como ProRes 4444; `componer.componer` las superpone con
  `overlay=enable=between(t,…)`. El compositor no cambia: B-roll y lupa también
  serán overlays a pantalla completa con alfa.
- Emojis: `cy=330`, centrados o laterales (`cx=950`) si coinciden con un rótulo.
  Contadores en `cy=360`.
- `zonas.calcular`: `contenido`, `subtitulos [y0, y1]` (o `None`), `titulo
  {y, hasta}`, `franja_zoom`, `graficos_hasta`. En encuadre `central` no hay
  franja de zoom.
- Estilos en `lanzador/edicion/estilos/*.json`: `tipos`, `densidad_max`, `sfx`
  (un efecto solo suena si el estilo lo tiene), `paleta`.
- Claves: `app/credenciales.py` guarda en el Llavero con el comando `security`
  (servicio por proveedor, cuenta `api-key`); se leen sin diálogo desde
  cualquier proceso del usuario con `security find-generic-password … -w`.
- El agente solo ejecuta `./tsots preparar|validar_plan|renderizar|verificar`;
  esos pasos son Python normal y pueden usar la red.
- Ya hay: OpenCV (`cv2`), `httpx`, `requests`, PIL, numpy. No hay `pyobjc`.

## 4. Diseño

### 4.1 Leer la pantalla (OCR) en `preparar`

- Muestrea `video.mp4` a **2 fps** y pasa cada fotograma por el OCR de Apple
  (Vision, `VNRecognizeTextRequest`, idiomas es y en). Dependencia nueva:
  `pyobjc-framework-Vision` (y `-Quartz` si hace falta), en `requirements.txt`.
- **Enmascara antes de leer** la banda de subtítulos (`zonas.subtitulos`) y la
  del título mientras dura (`zonas.titulo`): si no, los subtítulos quemados
  saldrían como «texto en pantalla» de todo lo que se dice.
- Guarda `pantalla.json` en el trabajo: por muestra, `t` y una lista de
  `{texto, caja [x,y,w,h] en 1080×1920, confianza}`.
- Calcula y guarda también los **intervalos con texto en pantalla**: tramos en
  los que el área de texto detectado supera un umbral (lo usa el render para
  decidir tapa o ventana).
- En `contexto.md`, nueva sección `## En pantalla`: solo las **coincidencias**
  entre lo que se dice y lo que se ve. Cada línea: intervalo, el texto visible y
  la palabra dicha (p. ej. `41.80-45.00 «Revisión» (dicha en 42.10)`). Así el
  contexto no se llena de todo el texto de la demo.
- Si el OCR no está disponible o falla: `## En pantalla` dice «no disponible»,
  `señalar` y `lupa` no se ofrecen y el B-roll siempre va en modo tapa. Nunca
  falla `preparar` por esto.

### 4.2 Nuevos tipos en `plan.json`

```json
{"t": 42.10, "palabra": "revisión", "tipo": "señalar", "pantalla": "Revisión", "forma": "circulo"}
{"t": 45.02, "palabra": "fichas",   "tipo": "lupa",    "pantalla": "Revisión de fichas"}
{"t": 66.96, "palabra": "seguros",  "tipo": "broll",   "buscar": "insurance contract signing"}
{"t": 54.66, "palabra": "documentos","tipo": "icono",  "icono": "documento"}
{"t": 30.20, "palabra": "años",     "tipo": "dato",    "valor": 10, "texto": "AÑOS DE CASOS"}
```

- `Momento` gana los campos `pantalla`, `forma`, `buscar`, `icono`, `valor`,
  `unidad` (opcional, `"%"`).
- Duraciones: `señalar` 2.0 s, `lupa` 2.6 s, `broll` 2.5 s, `icono` 1.6 s,
  `dato` 2.4 s.
- Todos cuentan para la densidad del estilo. `broll`: como mucho uno cada 15 s
  (`ceil(duración / 15)`).
- Todos los estilos admiten los cinco tipos nuevos (se añaden a `tipos` de los
  tres JSON). Los emojis siguen solo en divertido.

### 4.3 Validación

- `señalar` y `lupa`: `pantalla` debe coincidir (normalizado como `palabra`) con
  un texto de `pantalla.json` visible en `t` (±0.5 s); `forma` ∈ `circulo`,
  `flecha`, `subrayado` (por defecto `circulo`). Error con las coincidencias
  disponibles si no.
- `broll`: `buscar` de 2 a 6 palabras, letras latinas; solo si hay clave de
  Pexels (lo dice el contexto). Máximo por vídeo como arriba.
- `icono`: nombre del catálogo (el error lista los parecidos).
- `dato`: `valor` (número) debe aparecer dicho cerca de `t` (±1.5 s), en cifras
  o en palabras sencillas en español (cero a cien, mil); `texto` como un
  contador (≤ 22 caracteres). Si se dice «por ciento» o «%», `unidad: "%"`.
- Solapes en la zona superior: `lupa` y `dato` ocupan la zona superior como un
  rótulo; `icono` se comporta como emoji (puede ir lateral junto a un rótulo);
  `señalar` va sobre el contenido y no puede coincidir con una `lupa` del mismo
  texto.
- `broll`, **en los dos modos**, no puede coincidir en el tiempo con ningún otro
  momento visual (rótulos, contadores, emojis e iconos laterales incluidos,
  `señalar`, `lupa`, `dato`, final); sí con una `transicion`. *(Decisión mía:
  regla única, sin depender del modo.)*
- `señalar` y `lupa` no pueden coincidir con un zoom (`zoom` del plan ni los
  zooms lentos automáticos de entrada y de los últimos 3 s cuando hay franja):
  el zoom mueve la imagen y la caja leída por OCR dejaría de estar en su sitio.
  *(Decisión mía.)*
- El modo del B-roll (tapa o ventana) lo decide una única función compartida
  por validador y render, a partir de `pantalla.json`: **ventana si alguna
  muestra dentro de `[t, t+2.5]` tiene texto en pantalla**, tapa si ninguna.
  Determinista. *(Decisión mía.)*
- **Sugerencias** (no bloquean): `validar_plan` imprime `OK` y, debajo, líneas
  `Sugerencia: …`, p. ej. «el momento 4 (etiqueta) dice “REVISIÓN” mientras
  “Revisión” sale en pantalla: mejor `señalar`». La skill pide aplicarlas una
  vez si tienen sentido.

### 4.4 Render

- **`señalar`**: para cada fotograma del intervalo, la caja del texto: OCR en el
  render sobre los fotogramas del tramo (o cada 2 y se interpola), suavizada
  para que no tiemble. Se dibuja con el color de acento: círculo que se traza,
  flecha que entra o subrayado que se extiende. Si se pierde el texto, se
  desvanece.
- **`lupa`**: recorta de los fotogramas de `video.mp4` la zona del texto (con
  margen), la amplía ×2 y la pinta en una tarjeta con borde redondeado y sombra,
  en la mitad vertical opuesta al texto y siempre por encima de
  `graficos_hasta`; un trazo une la tarjeta con la caja original.
- **`broll`**: `GET https://api.pexels.com/videos/search` (`orientation=portrait`,
  la clave en la cabecera `Authorization`). Elige de forma determinista el primer
  resultado con al menos 2.5 s que no se haya usado ya en el vídeo, el fichero
  de menos de 1920 px de alto más grande, y lo descarga al trabajo. Sin sonido.
  - **Tapa** si `[t, t+2.5]` no cae en un intervalo con texto en pantalla:
    cubre de y=0 hasta el borde superior de los subtítulos (o la pantalla
    entera si no hay subtítulos), recortado para llenar y con un zoom lento.
  - **Ventana** si cae: tarjeta de unos 900 px de ancho con esquinas redondeadas
    en la zona superior.
  - Entrada y salida con un fundido corto o el barrido de la transición del
    estilo.
  - Guarda en `broll.json` del trabajo el autor y la URL de cada clip usado
    (crédito). Sin clave, sin red o sin resultados: se omite ese momento y se
    anota en el log.
  - Caché por búsqueda en `<trabajo>/broll/` (fuera de `tmp/`, que se borra en
    cada render): volver a renderizar tras corregir el plan reutiliza el mismo
    clip sin descargarlo otra vez. *(Decisión mía.)*
- **`icono`**: glifo de una fuente de iconos libre (Material Symbols, Apache 2.0)
  incluida en el repo, en una insignia redonda del color de acento; entrada con
  rebote como los emojis; misma posición que los emojis (centrada o lateral).
- **`dato`**: número grande en la zona superior que cuenta de 0 a `valor`
  (ease-out, 0.8 s), etiqueta en una píldora debajo; con `%`, barra que se llena
  hasta el valor. Colores de la paleta del estilo.
- Sonidos: cada tipo nuevo usa un efecto que ya existe (`pop`, `tap`, `tick`,
  `whoosh_*`); solo suena si el estilo lo tiene, como hoy.
- Todo sigue siendo un overlay RGBA 1080×1920 → `render_slot` → compositor sin
  cambios.

### 4.5 Clave de Pexels

- Botón «Pexels…» en el panel de shorts, junto al estilo de «Editar con Claude»,
  que abre un diálogo para pegar, comprobar (una búsqueda de prueba) y borrar la
  clave, con enlace a la página para pedirla gratis. Se guarda en el Llavero
  como las de redes (proveedor `pexels`).
- El motor la lee con `security find-generic-password` (sin importar `app/`) en
  el momento de descargar; nunca la escribe en el trabajo.
- `preparar` pone en el contexto «B-roll: disponible» solo si existe la clave.
- El agente (`claude -p` lanzado por `procesar_pendientes.sh`) no activa el
  sandbox de Claude Code, así que `./tsots renderizar` debería poder usar la red
  y el Llavero. **El plan empieza comprobándolo de verdad** (una búsqueda de
  Pexels y una lectura de la clave desde un trabajo lanzado por el agente)
  antes de construir encima. *(Decisión mía.)*
- El nombre de servicio en el Llavero debe ser exactamente el que da
  `app/credenciales.servicio("pexels")`; el lector del motor usa la misma
  cadena (un test lo compara).

### 4.6 La skill: elegir el mejor recurso

`SKILL.md` (y el formato de `plan.json`) añaden los tipos nuevos y una **tabla
de decisión**, en este orden de preferencia para cada momento:

1. Lo dicho **sale en pantalla** (`## En pantalla`) → `señalar`; si es pequeño o
   es lo más importante del tramo → `lupa`.
2. Se dice un **número** relevante → `dato`.
3. Se nombra algo **concreto que no se ve** (un objeto, un lugar, una acción) →
   `broll` (si está disponible), con búsqueda en inglés, concreta y visual.
4. Un **concepto** abstracto con icono en el catálogo → `icono`.
5. Una **frase clave** → `etiqueta`; una enumeración → `contador`.
6. Solo divertido: un chiste o imagen dicha → `emoji`, `golpe`, `error`.

Más reglas: variedad (no tres momentos seguidos del mismo tipo), los cupos por
tipo, y leer las `Sugerencia:` del validador.

`contexto.md` añade `## En pantalla`, `## Números dichos` (t, valor, palabra),
`## Iconos` (catálogo) y en `## Estilo` si hay B-roll.

### 4.7 Pruebas

- OCR: la función que lee un fotograma se sustituye en los tests; `pantalla.json`,
  máscara de subtítulos/título, coincidencias y sección del contexto con datos
  fijos. Una prueba real (marcada, se salta sin `pyobjc`) sobre un fotograma con
  texto.
- Validación de cada tipo nuevo (casos buenos y malos), sugerencias y solapes.
- Render: cada pieza nueva produce fotogramas con alfa donde toca y nunca pinta
  sobre la banda de subtítulos; B-roll con la API de Pexels simulada (sin red en
  los tests) en modo tapa y ventana, y omitido sin clave o con error.
- Clave: guardar/borrar con el Llavero simulado; nunca aparece en ficheros del
  trabajo.
- Prueba real: `odin_17_11` (demo grabada con el móvil) y un short del
  Episodio 20 (cara, podcast), con Haiku; revisar `verificacion.png`.

## 5. Enfoques

1. **Ampliar el motor actual** (elegido por el usuario): PIL + ffmpeg + OpenCV
   como los rótulos; OCR de Apple con `pyobjc`; iconos con una fuente de iconos;
   Pexels con `httpx`. Un solo camino de render, una dependencia nueva pequeña.
2. Motor gráfico aparte (Manim / Motion Canvas) para iconos y datos: más
   vistoso, pero dependencias pesadas, dos caminos de render y más lento.
3. Sin dependencias nuevas (tesseract con español): lee mal pantallas grabadas
   con el móvil, justo el caso principal.

## 6. Decisiones del usuario

- Los tres recursos (señalar/lupa con OCR, B-roll de Pexels, iconos y datos),
  sin pagar nada.
- B-roll **según contenido** (C): tapa si no hay texto en pantalla, ventana si lo
  hay.
- La skill elige el mejor recurso entre los de antes y los nuevos.
- Enfoque 1.

## 7. Decisiones mías (revisables)

- La lupa sustituye al zoom guiado (los subtítulos quemados impiden el zoom de
  cámara en pantalla completa).
- OCR a 2 fps, solo coincidencias dicho/visto en el contexto.
- Búsquedas de B-roll en inglés; solo Pexels; máximo uno cada 15 s; 2.5 s.
- Iconos y datos en los tres estilos; emojis solo en divertido.
- `dato` solo con números dichos; barra solo con porcentajes.
- Duraciones de cada tipo (4.2) y sugerencias del validador sin bloquear.
- Créditos de B-roll en `broll.json`, sin ponerlos en el vídeo.
- El B-roll no coincide con ningún otro momento visual, en ningún modo.
- `señalar` y `lupa` no coinciden con zooms (manuales ni automáticos).
- Modo del B-roll con una función compartida: ventana si hay texto en pantalla
  en cualquier punto de sus 2,5 s.
- Caché de B-roll por búsqueda dentro del trabajo.
- Comprobar al principio que el agente llega a la red y al Llavero.

## 8. Para el constructor

- Muestreo y rendimiento del OCR (nivel `fast` o `accurate`, escala), umbral de
  «texto en pantalla» y cómo seguir la caja en el render (OCR por fotograma,
  cada 2 con interpolación u OpenCV).
- Catálogo de iconos (unos 40 nombres en español → glifo) y qué fichero de
  fuente incluir (la variante estática más ligera de Material Symbols).
- Animaciones exactas de cada pieza y sus efectos de sonido.
- Dónde va el lector de la clave en el motor y el texto del diálogo de Pexels.
- Cómo instalar `pyobjc` para quien actualice (README y aviso si falta).
