# Artículo de blog y post de LinkedIn a partir de un vídeo — diseño

Estado: borrador para aprobar (2026-11-08).

## Qué y por qué

El usuario graba vídeos para Evolve2Digital (E2D) y ya los limpia, subtitula y publica en redes con la app. Quiere aprovechar cada vídeo dos veces más, sin escribir a mano:

1. **Un artículo para el blog de evolve2digital.com**, insertado a través del MCP del blog.
2. **Un post largo de LinkedIn** en su feed.

Los dos con imágenes sacadas del propio vídeo y con aspecto corporativo de E2D.

**Es un éxito si** después de procesar un vídeo con la opción activada:

- Aparece en el blog un **borrador** listo para revisar, con portada, 2-3 imágenes dentro del texto y el vídeo.
- En «Publicar…» está LinkedIn con su texto y sus imágenes, para enviarlo o programarlo como las demás redes.

## Decidido con el usuario

- **LinkedIn es un post largo en el feed**, no un artículo nativo de LinkedIn. LinkedIn no ofrece API pública para sus artículos.
- **La cuenta de LinkedIn ya está conectada en Upload-Post.**
- **Blog y LinkedIn llevan imágenes**, sacadas del vídeo:
  - una **portada con título**;
  - **2-3 fotogramas** de momentos clave dentro del artículo;
  - el usuario **puede cambiarlas**.
- **Nada de imágenes generadas con IA.**
- **Estilo de la portada: el «estilo 3» de sus portadas actuales.** Es tipo miniatura de YouTube: la cara del usuario a un lado y un título enorme en mayúsculas al otro. Referencia: la portada de `automatizaciones-para-empresas-con-ia-dos-casos-reales`. **Se genera en local.**
- **El blog sigue el diseño acordado en `docs/TODO.md`** («Blog post from the video…»):
  - tsots deja una carpeta en `pendientes/`;
  - un agente launchd lanza `claude -p` sobre ella;
  - Claude crea el post como **borrador** con el MCP.

## Identidad E2D (sacada de evolve2digital.com el 2026-11-08)

- **Logo:** `https://evolve2digital.com/e2d_logo.webp`. Insignia redonda con fondo `#293039`, aro `#05b4ba`, texto «EVOLVE 2 DIGITAL» en arco y línea de pulso blanca.
- **Colores:**
  - turquesa `#05b4ba` (principal) y turquesa claro `#7ee8eb`;
  - fondo oscuro `#050a0f` y pizarra `#293039`;
  - blanco y gris de texto `#9ca3af`;
  - acentos de degradado: rosa `#ec4899` y violeta `#8b5cf6`.
- **Fuentes de la web:** Inter (texto) y JetBrains Mono (código). Las dos con licencia OFL.
- **Portadas del blog:**
  - 1672×941 (16:9), ninguna lleva el logo;
  - tres estilos distintos, hechos con IA a juzgar por el aspecto;
  - el estilo 3 usa una sans muy gruesa en mayúsculas, blanco y degradados de color, sobre fondo oscuro.
- **Cuerpo de los artículos (MDX):**
  - `<Lead>` de entradilla;
  - secciones `##` con párrafos cortos, datos y **negritas** en las frases clave;
  - `<PullQuote author="…">` y `<Callout type="info|warning">`;
  - `[image:nombre]` para las imágenes;
  - «Fuente:» al final si hay fuentes, y `[contact]` de cierre.
- **Tono:** directo, escéptico, apoyado en datos, pensado para pymes y a veces en primera persona.

## Cómo funciona

### 1. En tsots, al terminar el vídeo

Nueva opción en el panel (casilla «Blog y LinkedIn»). Igual que el caption, **nunca hace fallar el vídeo**: si falla, avisa y el vídeo se guarda igual.

**Encaje:**

- La app no llama a `pipeline.run`. `app/main.py` manda todo por la ficha: `reproceso_plan.planificar` → `reproceso.ejecutar`.
- Esto es un **paso nuevo de la ficha**, con su clave y su resultado guardados, como `caption`.
- **Se hace una vez por vídeo:**
  - marcar la casilla en un vídeo ya procesado lanza el paso;
  - reprocesar otros pasos (subtítulos, encuadre…) **no** crea otro borrador ni otro post.
- Volver a generarlo queda fuera de esta versión.

1. **Transcripción.** Reutiliza las palabras con tiempos ya transcritas; si no las hay, transcribe (mismo patrón que `_fase_caption`).
2. **Título corto.** Reutiliza el título de 3-5 palabras de `titulo.py` (`pedir_titulo`), o lo pide si el paso de título está apagado.
3. **Fotogramas candidatos.**
   - Unos 6, repartidos por la **versión limpia** que guarda la ficha (`fichas/<id>/base.mp4`). Tiene la misma línea de tiempo y no lleva subtítulos ni título quemados.
   - Cada uno se busca en una ventana de pocos segundos alrededor de su momento.
   - Se descartan:
     - los borrosos (varianza del laplaciano con OpenCV);
     - los que no tienen cara o la tienen cortada (detector S3FD que ya usa `seguimiento.py`).
   - Cada candidato guarda su segundo y el trozo de transcripción de ese momento.
4. **Portada, estilo 3,** con Pillow (ya instalado):
   - un fotograma con la cara del usuario, colocada en el tercio derecho;
   - degradado oscuro (`#050a0f`) desde la izquierda;
   - el título corto en mayúsculas, enorme, en blanco, con la palabra clave en turquesa `#05b4ba`.
   - Dos tamaños: **1672×941** para el blog y **1080×1350** (4:5) para LinkedIn.
5. **Texto de LinkedIn** con el LLM local (Ollama), como el caption.
6. **Carpeta para el blog** (ver «Salida»).

### 2. LinkedIn, en «Publicar…»

- **Nueva plataforma LinkedIn**, con el mismo patrón que las demás (`videopipeline/redes/`, diálogos Publicar y Redes, comprobación de cuenta).
- **Publica fotos, no el vídeo:** `POST /api/upload_photos` con `platform[]=linkedin`. Fotos: la portada 4:5 y los 2-3 fotogramas, todo en un solo post.
- **El texto se puede editar antes de enviar** y se puede programar (`scheduled_date`), como hoy.
- **Imágenes cambiables en el diálogo.** LinkedIn muestra sus imágenes en miniatura. El usuario puede:
  - quitar una;
  - añadir otra de los ~6 candidatos, que se guardan junto al vídeo;
  - arrastrar una imagen propia desde el disco.
  - No hay que buscar un fotograma moviéndose por el vídeo.

### 3. Blog, fuera de la app

Según el TODO:

- **Disparo:** un agente launchd vigila `pendientes/` y, por cada carpeta, lanza `claude -p` con un fichero de instrucciones del repo. Ese fichero recoge el formato y tono E2D de arriba y los pasos.
- **Lo que hace Claude:**
  1. elige 2-3 de los fotogramas candidatos y los coloca en las secciones que encajan;
  2. escribe el artículo;
  3. `posts_create` con **`published: false`**;
  4. `posts_request_upload` y sube portada, fotogramas y vídeo (ver «Subida de media al blog»);
  5. `posts_validate` y `posts_set_cover`.

### Subida de media al blog (comprobado el 2026-11-08)

`posts_request_upload` devuelve `uploadUrl` = `https://evolve2digital.com/admin/media-upload?token=<JWT>`, que caduca en 1 h. El formulario de esa página no hace nada que un script no pueda hacer. Usa el token como Bearer:

1. **Por cada fichero:**
   - `POST /api/admin/media/upload`;
   - cabeceras: `authorization: Bearer <token>`, `content-type: <mime del fichero>` y `x-media-name: <slug-key>`;
   - cuerpo: los bytes del fichero, sin multipart.
2. **Al final:**
   - `POST /api/admin/media/upload/commit`, con la misma cabecera y JSON `{"files": [{"name", "alt", "caption"}], "cover": "<nombre>"}`;
   - `cover` solo si es una imagen.
3. **Datos de referencia:**
   - `GET /api/admin/media/token-info?token=` da el contexto del token;
   - el servidor es nginx propio; ya se subió un `.mov` de 114 MB (`benchmarks-de-ia…/explicacion.mov`).
   - El formulario no pone ningún límite de tamaño.

La subida la hace un script del repo (Python o `curl`) que Claude llama con el token. No se suben los bytes a través de Claude.
- **Al terminar,** la carpeta pasa a `hechos/`, con `resultado.json` y la URL del borrador, o a `errores/` con el motivo.

## Salida

- **Junto al vídeo final,** como el `.md` del caption:
  - `<nombre>.linkedin.md`: texto del post;
  - `<nombre>.linkedin/`: portada 4:5, fotogramas elegidos y `candidatos/`.
- **Para el blog:** `~/TSOTS/blog/pendientes/<fecha>-<nombre>/` con:
  - el vídeo final horizontal tal como se publica, con subtítulos si los lleva; si solo hay salida vertical, la versión limpia de la ficha;
  - `transcripcion.txt`;
  - `portada.png` (1672×941);
  - `candidatos/` con los fotogramas;
  - `meta.json`: idioma, contexto de marca, título corto, título SEO y palabras clave si existen, y por cada candidato su fichero, su segundo y su texto.

## Decisiones mías (el usuario puede corregirlas)

- **LinkedIn lleva imágenes en vez del vídeo.** LinkedIn no deja mezclar vídeo e imágenes en un post.
- **El texto de LinkedIn lo escribe el LLM local, no Claude**, para no depender de Claude fuera del blog.
  - Extensión: 1300-2500 caracteres.
  - Las dos primeras líneas hacen de gancho (es lo que se ve antes de «ver más»).
  - 3-5 hashtags al final; no se usan los de relleno de `caption.py`.
- **Se publica en el perfil personal de LinkedIn**, no en una página de empresa (no se envía `target_linkedin_page_id`).
- **El post de LinkedIn no enlaza al blog.** El artículo nace como borrador y su URL no es pública hasta que el usuario lo publica.
- **El artículo sale solo en el idioma del vídeo** (es/en); sin hermanos i18n.
- **Cambiar imágenes:**
  - en LinkedIn, desde «Publicar…» (quitar, elegir entre candidatos o arrastrar una propia);
  - en el blog, en el propio borrador de evolve2digital, porque el artículo se escribe fuera de la app.
- **Una vez por vídeo.** Ni reprocesar crea borradores duplicados ni se actualiza el borrador existente.
- **Fotogramas de la versión limpia**, para que la portada no lleve subtítulos quemados.
- **Al blog va el vídeo tal como se publica** en las redes.
- **Logo:** en la portada del blog no, como en las actuales. En la de LinkedIn, pequeño en una esquina.
- **Fuente del título de la portada: Inter Black**, en mayúsculas. Es OFL; se añade a `videopipeline/fuentes/` con su licencia.
- **El vídeo se sube al blog,** como en el artículo de benchmarks, que lleva `explicacion.mov`.

## Qué no entra

- Artículos nativos de LinkedIn.
- Imágenes generadas con IA.
- Traducciones del artículo.
- Publicar el artículo: siempre queda como borrador; `published: true` solo con confirmación explícita del usuario.
- Páginas de empresa de LinkedIn.
- Carruseles en PDF.
- Recortar la figura del usuario del fondo (necesitaría una dependencia nueva).

## Lo que haría que fallara aunque funcione

- Un artículo que **inventa datos** que no están en el vídeo.
- Un artículo **publicado sin que el usuario lo revise**.
- Una portada que **parece barata** al lado de las actuales: texto pequeño, cara cortada, fotograma borroso u ojos cerrados.
- Un texto de LinkedIn que **suena a IA genérica** o va lleno de hashtags.
- Que un fallo del blog o de LinkedIn **haga fallar o retrase el vídeo** principal.

## Riesgos que hay que comprobar primero

1. **Subir media al blog desde un script.** Resuelto el 2026-11-08: se puede (ver «Subida de media al blog»). Queda probarlo de verdad sobre un borrador de prueba.
2. **Comprobado el 2026-11-08 (Task 1 del plan):**
   - **Post real de LinkedIn publicado desde el vídeo `claudeTokensWaste`.**
     - Petición: `POST /api/upload_photos` con `user`, `platform[]=linkedin`, `visibility=PUBLIC`, el texto **solo en `title`** y 4 `photos[]` (portada PNG 4:5 y 3 JPG verticales).
     - Respuesta síncrona: HTTP 200 con `results.linkedin.{success, url, post_id}`, el mismo formato que la subida de vídeo.
   - **La CLI ya ve el conector del blog de claude.ai** («claude.ai E2D - Blog», conectado). Sus herramientas son `mcp__claude_ai_E2D_-_Blog__posts_*`; no hace falta autenticar `e2d`.
   - **Los vídeos reales son verticales** (1080×1920, cara muy cercana). La portada no puede escalar «a cubrir» sin cortar la cara. El controlador decidió (R4 en el registro del plan):
     - limitar la escala para que la cara ocupe como mucho el 45 % del alto en 16:9 y el 60 % en 4:5;
     - en 16:9, pegar la foto al borde derecho con el resto en fondo oscuro;
     - en 4:5, centrar la cara y poner el título abajo.
   - **El detector de ojos de OpenCV no detecta los ojos cerrados** (lo marcó como abiertos en un fotograma con los ojos cerrados). Queda sin filtro automático; se cambia la imagen a mano.
3. **Autenticación del MCP en la CLI.**
   - En `claude` el servidor `e2d` aparece pendiente de autenticar; el usuario tiene que hacer `/mcp` una vez.
   - Plan B: una tarea programada de la app de escritorio de Claude, que ya tiene el conector del blog (comprobado el 2026-11-08: ve `posts_create`, `posts_request_upload`…).
4. **Campos de LinkedIn en `upload_photos`** (resuelto en el punto 2: basta con `title`).
   - La documentación no deja claro qué campo es el cuerpo visible: `title`/`linkedin_title` o `linkedin_description`.
   - Tampoco documenta el máximo de fotos ni el límite de texto.
   - Hay que probarlo con un post real programado y luego cancelarlo.

## Lo que queda para el constructor

- **Dónde va la casilla** en el panel y cómo cuenta en `total_pasos`.
- **Prompt y esquema JSON del texto de LinkedIn**, y si comparte llamada con el caption o va aparte.
- **Detalles visuales de la portada:**
  - cómo se elige la palabra en turquesa;
  - cuántas líneas tiene el título y cómo se ajusta;
  - opacidad del degradado.
  - Hay que afinarlo con un fotograma real y enseñárselo al usuario antes de cerrar.
- **Ubicación del agente launchd y del fichero de instrucciones** (por ejemplo `lanzador/blog/`).
- **Cómo se instala el agente** con `instalar.command` y se quita con `desinstalar.command`.
- **Pruebas:**
  - lógica pura con tests: elección de candidatos, composición de la portada sobre una imagen sintética, campos de `upload_photos`;
  - la parte de red y de Claude, con una prueba real descrita en el plan.
