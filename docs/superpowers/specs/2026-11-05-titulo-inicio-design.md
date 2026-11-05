# Título al inicio del vídeo — diseño

Estado: borrador para aprobar (2026-11-05).

## Qué y por qué

Los primeros segundos deciden si alguien sigue viendo un vídeo en redes. El usuario quiere que cada vídeo empiece con un título grande y llamativo: 3-5 palabras clave que resuman de qué va. Hoy lo haría a mano en otro editor. La app ya transcribe el vídeo y genera un caption con un modelo local, así que tiene todo lo necesario para escribir el título y quemarlo sola.

**Es un éxito si** al procesar un vídeo, sin tocar nada más, sale con un título legible, bien colocado y con sentido durante sus 5 primeros segundos, en todas sus salidas.

## Decidido con el usuario

- **Duración:** 5 segundos al principio del vídeo.
- **Texto:** 3-5 palabras clave que resumen el vídeo. Lo genera la app sola, sin pedir confirmación.
- **Tipografía y estilo:**
  - Titan One (Google Fonts, licencia OFL);
  - relleno blanco y borde negro que rodea toda la letra;
  - contorno dorado (amarillo-dorado) por fuera del borde negro, algo desplazado hacia abajo a la derecha para que haga de sombra.

  Es la opción 4 de las maquetas que vio el usuario.
- **Posición:** arriba, centrado, con aire por encima.
  - Con encuadres a pantalla completa (recorte central, horizontal, vídeo que ya era vertical), el título va encima de la imagen y puede pisar la parte alta de la cabeza.
  - Las maquetas que eligió el usuario eran justo ese caso (fotograma vertical a pantalla completa), así que se acepta.
  - No se detectan caras para esquivarlas.
- **Dónde va:** en todos los vídeos que salen: el horizontal, el vertical y los shorts. Cada short lleva su propio título; ver el diseño de shorts.
- **Control:** una casilla en la sección «Subtítulos» del panel para ponerlo o no.

## Decisiones mías (el usuario puede corregirlas)

- **Mayúsculas:** como en las maquetas.
- **Entrada y salida:** fundido corto de unos 0,3 s al entrar y al salir. No se habló de animación; algo suave evita un corte brusco.
- **Tamaño:**
  - alrededor del 7 % de la altura en horizontal y del 5,5 % en vertical;
  - como mucho el 90 % del ancho, en 1 o 2 líneas;
  - si no cabe, se reduce la letra, como ya hace `_fs_ajustado` con los subtítulos.
- **Margen superior:** alrededor del 8 % de la altura. En el vertical «Seguir la cara (4:3)» de la PR #25 cae sobre la franja difuminada de arriba, y eso está bien.
- **Casilla por defecto:** activada. Se guarda con el resto de ajustes del panel.
- **Generación del título:**
  - se pide al mismo modelo del caption (`modelo_caption`, con `ollama.chat_json`) a partir de la transcripción, siempre en una llamada propia y antes de quemar;
  - no se junta con la del caption, que hoy va después de quemar; así no hay que reordenar el pipeline;
  - va en el idioma de los subtítulos.
- **Sin subtítulos:** si el título está activo pero los subtítulos no, se transcribe igualmente (hace falta para el título) y se quema solo el título.
  - **Coste aceptado:** un trabajo de «solo audio» o «solo silencios» con la casilla activada pasa a transcribir y a recodificar el vídeo. Quien no lo quiera, desmarca la casilla.
- **Ficha y reproceso:** el título no es un paso nuevo del reproceso.
  - Se guarda en la ficha y entra en la clave del artefacto quemado, junto con la casilla.
  - **Se genera** cuando falta: casilla recién activada, vídeo nuevo o transcripción nueva, por ejemplo al rehacer los subtítulos porque «no me gustan».
  - **Cambiar la casilla** rehace las salidas quemadas sin volver a transcribir, igual que hoy un cambio de estilo de subtítulos.
  - **Rehacer el caption** no toca el título.
- **Si falla el modelo** (Ollama apagado, error o respuesta vacía), el vídeo sale sin título, con un aviso en la fila, y no falla el procesado. Mismo criterio que el caption.

## Cómo se pinta

- **Capas ASS.** Se añade al mismo archivo `.ass` que ya se quema en el paso de subtítulos, con su propio estilo y dos capas:
  - **capa 0:** el texto en dorado, con un borde dorado grueso y desplazado unos píxeles abajo a la derecha;
  - **capa 1:** el texto en blanco, con borde negro.
- **La fuente:**
  - el archivo `TitanOne-Regular.ttf` va dentro del repo, junto a su licencia OFL;
  - se pasa a libass con `fontsdir` en el filtro `ass` para no depender de que esté instalada en el sistema;
  - **Hay que descargarla** de `github.com/google/fonts`, `ofl/titanone`; pesa unos 60 KB. El usuario lo aprueba al aprobar este diseño.
- **Un solo paso de codificación.** El horizontal y el vertical ya queman subtítulos con ASS: el título va en ese mismo paso, sin codificar el vídeo otra vez.

## Qué no entra

- Editar el título a mano antes de quemarlo. Se puede añadir después.
- Varias tipografías o colores a elegir.
- Animaciones más allá del fundido.
- Títulos en mitad del vídeo o en capítulos.

## Lo que haría que fallara aunque funcione

- Un título que no dice nada, como «Vídeo interesante hoy». El prompt debe pedir palabras clave concretas del contenido.
- Un título cortado por los lados o pegado al borde de arriba.
- Un título que tapa los ojos o la boca. Que pise el pelo en un encuadre a pantalla completa sí se acepta.
- Que sin Ollama deje de procesarse el vídeo.

## Lo que queda para el constructor

- Prompt exacto, campo del JSON y validación de 3-5 palabras (recortar si sobran, descartar si faltan).
- Valores finos de tamaño, márgenes, grosores y desplazamiento, ajustados con un fotograma real.
- Cómo encaja en `reproceso_plan.py` (reglas y claves) y en `pipeline.run`.
- Traducciones de los textos nuevos, con `lanzador/traducir.sh`.

## Relación con otras ramas

- **PR #25 (`fix/zoom-cara`).** Toca `vertical.py`. El título va en el ASS, no en el filtro de encuadre, así que no deberían chocar. Si #25 se mergea antes, se rebasa.
- **Shorts (`feature/shorts`).** Quema el título de cada short con dos funciones públicas de esta rama, que son su contrato:
  - **`generar_titulo(transcripcion: str, idioma: str, modelo: str) -> str | None`:** el texto de 3-5 palabras, o `None` si falla. Shorts lo llama con el tramo de transcripción de cada short.
  - **`lineas_titulo(texto: str, resolucion: tuple[int, int], inicio: float = 0.0, duracion: float = 5.0) -> tuple[list[str], list[str]]`:** los estilos y los eventos ASS del título, para añadirlos a cualquier `.ass`.

  Los nombres exactos los puede ajustar el constructor, pero los dos usos deben quedar cubiertos.
