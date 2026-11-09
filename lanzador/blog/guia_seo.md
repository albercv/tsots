# Guía SEO y de redacción

Reglas para que el artículo posicione en Google y lo citen los buscadores con
IA (AI Overviews, ChatGPT, Perplexity) sin dejar de sonar a Alberto. Si una
regla choca con «no inventes», gana «no inventes».

## 1. Palabra clave

- **Principal:** la consulta de 2 a 5 palabras que escribiría en Google el
  dueño de una pyme para encontrar este tema, en el idioma del artículo
  (ejemplo: «coste de usar claude», no «inferencia excesiva en LLMs»). Sale
  del tema central de la transcripción, no de un detalle.
- **Secundarias:** 3 a 5 variantes y términos relacionados (sinónimos, la
  pregunta que la acompaña, el nombre de la herramienta…).
- La principal va en:
  - el `title`, lo más al principio posible;
  - la primera frase del `<Lead>`;
  - al menos un `##`;
  - la `description`;
  - el texto alternativo de al menos una imagen.
- En el resto del texto, con naturalidad: entre 0,5 % y 2 % de las palabras.
  Las secundarias y los sinónimos van en los `##` y el cuerpo. Nunca la
  repitas a la fuerza.

## 2. Título y descripción

- `title`: de 50 a 60 caracteres, nunca más de 60. La palabra clave delante,
  sin el nombre de la marca. Concreto y verdadero: una cifra, el resultado o
  la pregunta que responde; nada de clickbait. El slug sale del título, así
  que cuanto más corto y claro, mejor.
- `description`: de 130 a 155 caracteres, en voz activa. Amplía el título con
  lo que se aprende y acaba invitando a leer. Sin comillas.

## 3. Estructura que citan Google y las IA

- El `<Lead>` responde directamente, en 40-60 palabras, la pregunta que hay
  detrás de la palabra clave. Es el párrafo que Google puede sacar como
  respuesta destacada.
- Cada `##`:
  - en forma de pregunta cuando encaje («¿Cuánto cuesta…?», «¿Por qué…?»);
  - empieza con la respuesta en la primera o las dos primeras frases, y
    luego la explica;
  - se entiende solo, sin leer el resto: nombra el tema en vez de «esto» o
    «lo anterior».
- Párrafos de 2 a 4 frases; frases de unas 15-20 palabras de media.
- Pasos en lista numerada, comparaciones en tabla, y solo si el vídeo los da.
- **Preguntas frecuentes:** antes de la línea de fuentes y de `[contact]`, una
  sección `## Preguntas frecuentes` (`## Frequently asked questions` en inglés,
  `## Domande frequenti` en italiano) con 3 a 5 preguntas `### ¿…?` y
  respuestas de 40 a 80 palabras. Solo preguntas que el vídeo responde; si no
  da para 3, no pongas la sección.
- Extensión: la que pida el tema. Google no premia las palabras, sino cubrir
  bien la pregunta; un vídeo corto da un artículo corto. No rellenes.

## 4. Enlaces internos

- Antes de escribir, busca con `mcp__claude_ai_E2D_-_Blog__posts_search`
  (en el `locale` del artículo) con la palabra clave y 1 o 2 secundarias.
- Elige 2 o 3 posts que de verdad amplíen algo del artículo.
- La búsqueda también devuelve borradores, que dan 404. Antes de enlazar uno,
  comprueba su `url` con `WebFetch`; si no carga, descártalo.
- Enlaza en el cuerpo con Markdown `[texto](url)`. El texto describe el
  destino («cómo calcular el coste por tarea»), nunca «aquí» o «este
  artículo».
- Si ninguno encaja, no pongas enlaces.

## 5. Texto alternativo de las imágenes

- Uno por imagen, de 125 caracteres como mucho: describe lo que se ve y
  para qué sirve en el artículo, sin «imagen de» ni «foto de».
- Al menos uno lleva la palabra clave, si encaja de forma natural.
- La portada: el título del artículo.
- Sin comillas simples ('): van entre comillas simples en la orden de subida.

## 6. Confianza (experiencia y autoridad)

- En primera persona, con la experiencia propia que cuenta el vídeo («lo he
  probado», «en mis proyectos»).
- Las cifras y las fuentes, solo las que se dicen en el vídeo y siempre con
  su fuente.
- Nada de datos, casos, clientes o estudios que no estén en la
  transcripción.

## 7. Redacción

- Empieza por el problema o el dato, no por el contexto general.
- Sin muletillas de texto hecho por IA: «en el mundo actual», «en la era
  digital», «es importante destacar», «cabe destacar», «sumérgete»,
  «desbloquea», «potencia», «revoluciona», «en resumen», «en conclusión»,
  «no es solo X, es Y».
- Sin la raya (—) como conector: usa punto, coma o dos puntos.
- No lo agrupes todo de tres en tres por costumbre: tantos elementos como
  haya.
- No cierres con una moraleja vacía; cierra con lo que el lector puede hacer.
- Verbos activos y ejemplos concretos del vídeo en lugar de abstracciones.

## 8. Antes de crear el borrador, comprueba

- La palabra clave está en el título, el `<Lead>`, un `##`, la descripción y
  un texto alternativo.
- El título tiene 60 caracteres o menos y la descripción, entre 130 y 155.
- Cada enlace interno se ha comprobado con `WebFetch`.
- No hay ninguna cifra, nombre ni fuente que no esté en la transcripción.
