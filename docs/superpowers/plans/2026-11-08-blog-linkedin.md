# Artículo de blog y post de LinkedIn a partir de un vídeo — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** con la casilla «Blog y LinkedIn», cada vídeo procesado deja:

- un post de LinkedIn listo en «Publicar…», con texto largo, portada 4:5 y 2-3 fotogramas;
- una carpeta en `~/TSOTS/blog/pendientes/`, que un agente launchd convierte con `claude -p` en un **borrador** de evolve2digital, con portada, imágenes y vídeo.

**Architecture:**

- **Cuatro módulos puros nuevos** en `videopipeline/`:
  - `fotogramas.py`: candidatos;
  - `portada.py`: imagen estilo 3 con Pillow;
  - `linkedin.py`: texto con Ollama y ficheros acompañantes;
  - `difusion.py`: lo junta todo y escribe las salidas.
- **En la ficha:** un artefacto `difusion`, sin archivo, y una acción `DIFUSION`, la última del plan. Se hace una vez por vídeo.
- **LinkedIn:** séptima `Plataforma`. Publica fotos con `POST /api/upload_photos`.
- **Blog:**
  - `lanzador/blog/` lleva el script del agente, las instrucciones para Claude y la plantilla del plist;
  - `videopipeline/blog_subida.py` sube la media con el token de `posts_request_upload`.

**Tech Stack:** Python 3.11, PySide6, OpenCV, Pillow 12, httpx, S3FD (ya en el repo), Ollama (`ollama.chat_json`), Upload-Post, Claude Code CLI + MCP `e2d`, launchd, pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-11-08-blog-linkedin-design.md`

## Global Constraints

- **Idioma y commits:** código, comentarios y textos de la GUI en español; commits en inglés, sin atribución a IA (ni `Co-Authored-By` ni «Generated with»).
- **Tests:** `QT_QPA_PLATFORM=offscreen ~/Documents/personalProjects/limpiadorVideo/.venv-clearvoice/bin/python -m pytest -q` desde esta carpeta. Commit solo con la suite en verde.
- **Nunca** `-m ""` ni `-m lenta`: suben a redes con la cuenta real.
- **Ningún test** depende de Ollama, ffmpeg, red, modelos ni Claude.
- **No tocar** `~/Documents/personalProjects/limpiadorVideo` (producción): solo se usa su intérprete.
- **Sin dependencias nuevas.** Pillow 12.3, OpenCV 4.10, numpy y httpx ya están en `requirements.txt`.
- **Nunca hace fallar el vídeo:** cualquier error del paso nuevo es un aviso (`_avisar`).
- **El blog siempre como borrador:** `posts_create` con `published: false`. Ningún script ni instrucción pone `published: true`.
- **Colores E2D:**
  - turquesa `#05b4ba`, turquesa claro `#7ee8eb`;
  - fondo `#050a0f`, pizarra `#293039`;
  - blanco `#ffffff`, gris `#9ca3af`.
- **Tamaños:** portada del blog **1672×941**; portada de LinkedIn **1080×1350**.
- **Portada estilo 3:**
  - cara en el tercio derecho;
  - degradado `#050a0f` desde la izquierda;
  - título corto en mayúsculas, blanco, con la palabra clave en `#05b4ba`, en **Inter Black**;
  - logo E2D pequeño en una esquina **solo en LinkedIn**.
- **Texto de LinkedIn:** 1300-2500 caracteres, gancho en las 2 primeras líneas y 3-5 hashtags al final, sin los de `caption.HASHTAGS_GENERICOS`.
- **Post de LinkedIn:** perfil personal (sin `target_linkedin_page_id`), sin enlace al blog, con fotos en vez del vídeo.
- **Una vez por vídeo:** reprocesar otros pasos no vuelve a generar nada.
- **Fuentes de cada salida:**
  - fotogramas: de la base limpia (`_Pasada.base`);
  - vídeo del blog: el final horizontal, o la base si solo hay vertical.
- **Traducciones** con `lanzador/traducir.sh` y `locale/en/LC_MESSAGES/tsots.po`.
- **Flujo de ramas:** rama `feature/blog-linkedin`, PR contra `develop`, nunca push a `develop` ni a `main`.

## Review Focus

1. **Vídeo sin cara en ningún candidato** (grabación de pantalla): salen candidatos igualmente, ordenados por nitidez, y la portada se hace sin colocar la cara. Test en Task 2 (`test_sin_caras_devuelve_los_mas_nitidos`) y Task 3 (`test_portada_sin_cara`).
2. **Vídeo corto (< 30 s) o menos momentos válidos que 6:** menos candidatos, sin error. Test en Task 2 (`test_video_corto_da_menos_candidatos`).
3. **Título largo** («AUTOMATIZACIONES INTELIGENTES PARA PEQUEÑAS EMPRESAS»): la letra se reduce hasta caber en sus márgenes; nunca se corta una palabra. Test en Task 3 (`test_titulo_largo_cabe`).
4. **Reprocesar un vídeo ya difundido** (cambiar subtítulos): sin `DIFUSION` en el plan, sin carpeta nueva en `pendientes/` y sin tocar el `.linkedin.md`. Test en Task 6 (`test_difusion_una_vez_por_video`).
5. **Ficheros de LinkedIn borrados o sin imágenes al abrir «Publicar…»:** LinkedIn deshabilitado con motivo; nunca se envía un post con 0 fotos. Tests en Task 8 (`test_linkedin_sin_fotos_no_envia`) y Task 9 (`test_linkedin_sin_acompanantes_deshabilitado`).

---

### Task 1 (controlador, con el usuario): comprobaciones reales previas

**Files:**
- Modify: `docs/superpowers/specs/2026-11-08-blog-linkedin-design.md` (sección «Riesgos que hay que comprobar primero»)

**Interfaces:**
- Produces: qué campo de `upload_photos` es el cuerpo visible en LinkedIn y si la CLI ve las herramientas `mcp__e2d__*`. Lo usan las Tasks 8 y 11.

- [ ] **Step 1: Preguntar al usuario.** Hay que pedirle permiso explícito para programar un post de prueba en su LinkedIn, a 7 días vista, y cancelarlo después. Sin su sí, saltar a Step 4.
- [ ] **Step 2: Programar el post de prueba con `curl`.**
  - Llamada: `POST https://api.upload-post.com/api/upload_photos` con:
    - `user`, `platform[]=linkedin`;
    - `title="Prueba A (title)"`, `linkedin_description="Prueba B (description)"`;
    - `scheduled_date` a 7 días;
    - dos `photos[]` (PNG cualesquiera).
  - La clave sale del Llavero con `security find-generic-password` (servicio de `app/credenciales.py`); no se imprime.
  - Esperado: 202 con `job_id`.
- [ ] **Step 3: Ver el post y cancelarlo.**
  - Ver el post programado en `GET /api/uploadposts/schedule?profile_username=<perfil>` y anotar qué texto queda como cuerpo.
  - Cancelarlo con `DELETE /api/uploadposts/schedule/<job_id>`.
  - Si la API no muestra el cuerpo, pedir al usuario que lo mire en la cola de Upload-Post antes de cancelar.
- [ ] **Step 4: Comprobar la CLI.** Pedir al usuario que ejecute `claude mcp list` en su terminal. Esperado: `e2d` conectado. Si sale «needs authentication», el usuario hace `/mcp` dentro de `claude` y se repite.
- [ ] **Step 5: Anotar el resultado** en la sección de riesgos del spec (campo del cuerpo y estado de `e2d`) y hacer commit.

```bash
git add docs/superpowers/specs/2026-11-08-blog-linkedin-design.md
git commit -m "docs: record LinkedIn photo field and e2d CLI checks"
```

Sin respuesta del usuario: las Tasks 8 y 11 usan el valor por defecto, que es enviar el texto solo en `title`. La documentación dice que el comentario reutiliza `title` si falta `linkedin_description`.

---

### Task 2: Fotogramas candidatos

**Files:**
- Create: `videopipeline/fotogramas.py`
- Test: `tests/test_fotogramas.py`

**Interfaces:**
- Consumes: `subtitles.Palabra(texto, inicio, fin)`; `seguimiento._detector_s3fd() -> Detector` (`Detector = Callable[[np.ndarray], np.ndarray]`, filas `[x1, y1, x2, y2, score]`); `steps.duracion_video(Path) -> float`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class Candidato:
      archivo: Path
      segundo: float
      texto: str
      cara: tuple[int, int, int, int] | None  # x1, y1, x2, y2 en píxeles del fotograma
      nitidez: float

  NUM_CANDIDATOS = 6
  def momentos(duracion: float, n: int = NUM_CANDIDATOS) -> list[float]
  def nitidez(imagen_bgr: np.ndarray) -> float
  def cara_completa(cajas: np.ndarray, ancho: int, alto: int) -> tuple[int, int, int, int] | None
  def texto_en(palabras: list[Palabra], segundo: float, radio: float = 8.0) -> str
  def extraer_candidatos(video: Path, palabras: list[Palabra], destino: Path, *,
                         n: int = NUM_CANDIDATOS, detector: Detector | None = None,
                         leer: Callable[[Path, float], np.ndarray | None] | None = None,
                         duracion: float | None = None) -> list[Candidato]
  ```

Reglas que fija este plan:

- **`momentos`:** `n` instantes equiespaciados entre el 5 % y el 95 % de la duración. Si la duración es menor de 30 s, `n = max(1, int(duracion // 5))`.
- **Búsqueda alrededor de cada momento:** se leen 5 fotogramas, en el instante y a ±1 s y ±2 s, recortados a [0, duración].
- **Elección del fotograma de cada momento:** gana el que tenga `cara_completa`; a igualdad, el de mayor `nitidez`.
- **`nitidez`:** varianza del laplaciano (`cv2.Laplacian(gris, cv2.CV_64F).var()`).
- **Descartes:** un momento cuyo mejor fotograma tiene nitidez < `NITIDEZ_MINIMA = 40.0` se descarta, salvo que se descartarían todos. En ese caso se queda el más nítido de cada momento.
- **`cara_completa`:** la caja de mayor área con `score >= 0.8` que:
  - deja un margen de al menos el 2 % del ancho y del alto con cada borde;
  - mide al menos el 12 % del alto del fotograma.
  - Si ninguna cumple, `None`.
- **Ficheros:** se guardan como `destino / f"candidato_{i:02d}.jpg"` (calidad 92), en orden de tiempo.
- **`leer` por defecto:** `cv2.VideoCapture` con `CAP_PROP_POS_MSEC`.
- **`detector` por defecto:** `_detector_s3fd()`, creado una sola vez.

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_momentos_reparte_entre_5_y_95_por_ciento():
    assert momentos(100.0, 6) == pytest.approx([5.0, 23.0, 41.0, 59.0, 77.0, 95.0])

def test_video_corto_da_menos_candidatos(tmp_path):
    lector = lambda video, t: np.full((90, 160, 3), 128, np.uint8)
    cands = extraer_candidatos(Path("v.mp4"), [], tmp_path, detector=lambda f: np.zeros((0, 5)),
                               leer=lector, duracion=12.0)
    assert len(cands) == 2

def test_cara_completa_descarta_cortada_y_pequena():
    cajas = np.array([[0, 10, 50, 80, 0.99],      # toca el borde izquierdo
                      [60, 40, 66, 46, 0.99],     # demasiado pequeña
                      [80, 20, 130, 85, 0.95]])
    assert cara_completa(cajas, 160, 90) == (80, 20, 130, 85)

def test_prefiere_fotograma_con_cara_a_mas_nitido(tmp_path): ...
    # lector: nítido sin cara en t, menos nítido con cara en t+1 → gana t+1

def test_sin_caras_devuelve_los_mas_nitidos(tmp_path): ...
    # detector que nunca encuentra caras → 6 candidatos, todos con cara=None

def test_borrosos_se_descartan_salvo_que_lo_sean_todos(tmp_path): ...

def test_texto_en_junta_palabras_del_entorno():
    palabras = [Palabra("hola", 1.0, 1.5), Palabra("mundo", 9.5, 10.0), Palabra("lejos", 30.0, 30.5)]
    assert texto_en(palabras, 5.0) == "hola mundo"
```

- [ ] **Step 2: Comprobar que fallan.** `... -m pytest tests/test_fotogramas.py -q`. Esperado: `ModuleNotFoundError: videopipeline.fotogramas`.
- [ ] **Step 3: Implementar `videopipeline/fotogramas.py`** con las firmas y reglas de arriba. El texto de `texto_en` son las palabras con `inicio` dentro de `[segundo - radio, segundo + radio]`, unidas por espacios.
- [ ] **Step 4: Comprobar que pasan.** Mismo comando. Esperado: PASS.
- [ ] **Step 5: Commit**

```bash
git add videopipeline/fotogramas.py tests/test_fotogramas.py
git commit -m "feat: pick sharp frame candidates with a full face"
```

---

### Task 3: Portada estilo 3 (Pillow)

**Files:**
- Create: `videopipeline/portada.py`
- Create: `videopipeline/fuentes/Inter-Black.ttf`, `videopipeline/fuentes/OFL-Inter.txt`
  - Origen: release oficial de `rsms/inter`, versión 4.x, fichero estático `Inter-Black.ttf`.
- Create: `videopipeline/recursos/e2d_logo.png`
  - Origen: `https://evolve2digital.com/e2d_logo.webp`, convertido con `sips -s format png`.
- Test: `tests/test_portada.py`

**Interfaces:**
- Consumes: `Candidato.cara` (Task 2).
- Produces:
  ```python
  TAM_BLOG = (1672, 941)
  TAM_LINKEDIN = (1080, 1350)
  TURQUESA, FONDO = "#05b4ba", "#050a0f"
  def palabra_destacada(titulo: str) -> int
  def componer_portada(fotograma: Image.Image, titulo: str, tamano: tuple[int, int], *,
                       cara: tuple[int, int, int, int] | None = None,
                       con_logo: bool = False) -> Image.Image
  ```

Reglas que fija este plan:

- **`palabra_destacada`:** índice de la palabra más larga; a igualdad, la primera.
- **Recorte:**
  - el fotograma se escala hasta cubrir `tamano`;
  - se recorta para que el centro de la cara caiga en el 70 % del ancho, ajustado a los bordes;
  - sin cara, recorte centrado.
- **Degradado:** `FONDO` horizontal, con opacidad 0,92 en x = 0 que baja de forma lineal hasta 0 en el 65 % del ancho. En 4:5 también va de abajo arriba, de 0,92 en y = alto a 0 en el 45 % del alto.
- **Título:**
  - mayúsculas, Inter Black;
  - dentro de una caja del 8 % al 58 % del ancho en 16:9, o del 7 % al 93 % del ancho y la mitad inferior en 4:5;
  - como mucho 3 líneas;
  - la letra empieza en el 13 % del alto y baja de 2 en 2 px hasta que cabe; nunca parte una palabra;
  - interlineado 0,95;
  - la palabra destacada en `TURQUESA` y el resto en blanco.
- **Logo** (`con_logo`): 9 % del ancho, abajo a la derecha, margen del 4 %.

- [ ] **Step 1: Escribir los tests que fallan.** Usan una imagen sintética de 1920×1080 con un rectángulo claro en la caja de la cara. Los helpers `_sintetica(cara=None)`, `_blanca()`, `_negra()`, `_centro_x_de_lo_claro(img)` y `_caja_de_pixeles_blancos_o_turquesa(img)` se definen en el propio fichero de tests, con numpy.

```python
def test_tamanos_exactos():
    img = componer_portada(_sintetica(), "Agentes de IA rentables", TAM_BLOG)
    assert img.size == (1672, 941)
    assert componer_portada(_sintetica(), "Agentes de IA rentables", TAM_LINKEDIN).size == (1080, 1350)

def test_palabra_destacada_es_la_mas_larga():
    assert palabra_destacada("Agentes de IA rentables") == 3

def test_cara_queda_en_el_tercio_derecho():
    img = componer_portada(_sintetica(cara=(1300, 200, 1600, 600)), "Uno dos tres", TAM_BLOG,
                           cara=(1300, 200, 1600, 600))
    assert _centro_x_de_lo_claro(img) / img.width == pytest.approx(0.70, abs=0.05)

def test_lado_izquierdo_oscurecido():
    img = componer_portada(_blanca(), "Uno dos tres", TAM_BLOG)
    assert img.getpixel((5, 470))[0] < 40 and img.getpixel((1660, 470))[0] > 200

def test_titulo_largo_cabe():
    img = componer_portada(_negra(), "Automatizaciones inteligentes para pequeñas empresas", TAM_BLOG)
    x0, _, x1, _ = _caja_de_pixeles_blancos_o_turquesa(img)
    assert x0 >= int(0.08 * 1672) - 2 and x1 <= int(0.58 * 1672) + 2

def test_portada_sin_cara():
    assert componer_portada(_sintetica(), "Uno dos tres", TAM_LINKEDIN, cara=None).size == TAM_LINKEDIN

def test_logo_solo_si_se_pide():
    sin = componer_portada(_negra(), "Uno dos tres", TAM_LINKEDIN)
    con = componer_portada(_negra(), "Uno dos tres", TAM_LINKEDIN, con_logo=True)
    zona = (int(1080 * 0.85), int(1350 * 0.90), 1075, 1345)
    assert sin.crop(zona).getextrema() != con.crop(zona).getextrema()
```

- [ ] **Step 2: Comprobar que fallan.** `... -m pytest tests/test_portada.py -q`. Esperado: `ModuleNotFoundError`.
- [ ] **Step 3: Añadir la fuente, su licencia y el logo; implementar `videopipeline/portada.py`** con las reglas de arriba (ImageDraw, ImageFont.truetype y un degradado con `Image.linear_gradient` o con numpy).
- [ ] **Step 4: Comprobar que pasan.** Esperado: PASS.
- [ ] **Step 5: Commit**

```bash
git add videopipeline/portada.py videopipeline/fuentes/Inter-Black.ttf videopipeline/fuentes/OFL-Inter.txt videopipeline/recursos/e2d_logo.png tests/test_portada.py
git commit -m "feat: compose E2D style cover from a video frame"
```

---

### Task 4: Texto de LinkedIn y ficheros acompañantes

**Files:**
- Create: `videopipeline/linkedin.py`
- Test: `tests/test_linkedin.py`

**Interfaces:**
- Consumes: `ollama.chat_json(modelo, mensajes, esquema) -> dict`; `caption._normalizar_hashtag`, `caption.HASHTAGS_GENERICOS`, `caption.recortar`.
- Produces:
  ```python
  MIN_CARACTERES, MAX_CARACTERES = 1300, 2500
  def construir_mensajes(transcripcion: str, contexto_marca: str, idioma: str) -> list[dict]
  def generar(transcripcion: str, contexto_marca: str, modelo: str,
              cliente=chat_json, idioma: str = "es") -> str    # texto + "\n\n" + hashtags
  def rutas(final: Path) -> tuple[Path, Path]   # (x_limpio.linkedin.md, x_limpio.linkedin/)
  def escribir(texto: str, final: Path) -> None
  def leer(final: Path) -> tuple[str, list[Path]] | None   # None si falta el .md
  ```

Reglas que fija este plan:

- **Prompts:** uno `_SYSTEM_ES` y otro `_SYSTEM_EN`, como en `caption.py`. Piden:
  - post de LinkedIn de 1300-2500 caracteres, tono profesional cercano;
  - las 2 primeras líneas de gancho, párrafos cortos y sin hashtags dentro del texto;
  - `hashtags`: 3-5;
  - no inventar datos;
  - responder solo JSON con el esquema `{"texto": str, "hashtags": [str]}`.
- **Validación:**
  - `texto` con menos de 600 caracteres → `PasoFallido`;
  - con más de `MAX_CARACTERES` → se corta en el último fin de párrafo anterior al límite;
  - hashtags normalizados, sin genéricos, como mucho 5.
- **`leer`:** devuelve las imágenes `*.png` y `*.jpg` de la carpeta en orden de nombre. Excluye la subcarpeta `candidatos/`.

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_generar_une_texto_y_hashtags():
    cliente = lambda m, msgs, esq: {"texto": "Gancho.\n\n" + "x" * 1400, "hashtags": ["#IA", "#viral", "pymes"]}
    texto = generar("transcripción", "", "m", cliente=cliente)
    assert texto.endswith("\n\n#ia #pymes")

def test_texto_corto_falla():
    with pytest.raises(PasoFallido):
        generar("t", "", "m", cliente=lambda *a: {"texto": "corto", "hashtags": []})

def test_texto_largo_se_corta_por_parrafo():
    largo = ("p" * 1200 + "\n\n") * 3
    texto = generar("t", "", "m", cliente=lambda *a: {"texto": largo, "hashtags": []})
    assert len(texto) <= MAX_CARACTERES and texto.endswith("p")

def test_rutas_junto_al_final(tmp_path):
    assert rutas(tmp_path / "x_limpio.mp4") == (tmp_path / "x_limpio.linkedin.md", tmp_path / "x_limpio.linkedin")

def test_leer_devuelve_imagenes_ordenadas_sin_candidatos(tmp_path): ...

def test_leer_sin_md_es_none(tmp_path):
    assert leer(tmp_path / "x_limpio.mp4") is None
```

- [ ] **Step 2: Comprobar que fallan.** Esperado: `ModuleNotFoundError`.
- [ ] **Step 3: Implementar `videopipeline/linkedin.py`.**
- [ ] **Step 4: Comprobar que pasan.** Esperado: PASS.
- [ ] **Step 5: Commit**

```bash
git add videopipeline/linkedin.py tests/test_linkedin.py
git commit -m "feat: generate LinkedIn post text with the local model"
```

---

### Task 5: `difusion.preparar` (junta todo y escribe las salidas)

**Files:**
- Create: `videopipeline/difusion.py`
- Test: `tests/test_difusion.py`

**Interfaces:**
- Consumes: Tasks 2-4; `caption.texto_plano`; `caption.leer_md(Path) -> Caption | None` (título SEO y palabras clave, si existen).
- Produces:
  ```python
  DIR_BLOG = Path.home() / "TSOTS" / "blog"
  NUM_IMAGENES = 3   # fotogramas que acompañan a la portada en LinkedIn
  @dataclass(frozen=True)
  class Resultado:
      linkedin_md: Path
      carpeta_blog: Path
  def preparar(*, nombre: str, base: Path, video_blog: Path, final: Path,
               palabras: list[Palabra], titulo: str, idioma: str, contexto_marca: str,
               modelo: str, dir_blog: Path = DIR_BLOG, cliente=chat_json,
               detector=None, leer=None, hoy: date | None = None) -> Resultado
  ```

Qué escribe:

1. **Candidatos.** `extraer_candidatos(base, palabras, linkedin.rutas(final)[1] / "candidatos")`. Sin candidatos → `PasoFallido`.
2. **Portada.** La hace el candidato con cara de mayor nitidez o, si no hay ninguno con cara, el más nítido.
3. **Carpeta de LinkedIn:**
   - `x_limpio.linkedin/01_portada.png` (TAM_LINKEDIN, `con_logo=True`);
   - `02_…`, `03_…`, `04_…`: copias de los `NUM_IMAGENES` candidatos restantes más repartidos en el tiempo, uno de cada tercio del vídeo si se puede.
   - `linkedin.escribir(texto, final)`.
4. **Carpeta del blog,** escrita en `dir_blog / "pendientes" / f"{hoy:%Y-%m-%d}-{nombre}"` vía una carpeta oculta `.<nombre>.tmp` que se renombra al final, para que launchd no vea nunca una carpeta a medias. Contenido:
   - `video.mp4` (enlace duro si se puede, si no copia);
   - `transcripcion.txt`;
   - `portada.png` (TAM_BLOG, sin logo);
   - `candidatos/`;
   - `meta.json`:
     ```json
     {"idioma": "es", "nombre": "...", "titulo_corto": "...", "titulo_seo": "... | null",
      "palabras_clave": ["..."], "contexto_marca": "...",
      "candidatos": [{"archivo": "candidatos/candidato_01.jpg", "segundo": 12.4, "texto": "..."}]}
     ```
5. **Nombre ocupado:** si la carpeta ya existe en `pendientes/`, `hechos/` o `errores/`, se añade el sufijo `-2`, `-3`…

- [ ] **Step 1: Escribir los tests que fallan.** Usan un lector y un detector falsos, un cliente LLM falso y `tmp_path` como `dir_blog`.

```python
def test_preparar_escribe_linkedin_y_blog(tmp_path): ...
    # asserts: .linkedin.md existe; .linkedin/01_portada.png de 1080x1350 + 3 imágenes;
    # pendientes/2026-11-08-x/{video.mp4,transcripcion.txt,portada.png,meta.json}; portada 1672x941;
    # meta["candidatos"] con 6 entradas y sus segundos

def test_nombre_ocupado_en_hechos_lleva_sufijo(tmp_path): ...

def test_sin_candidatos_falla_sin_dejar_carpeta(tmp_path): ...
    # PasoFallido y no queda nada en pendientes/ (ni la oculta)
```

- [ ] **Step 2: Comprobar que fallan.** Esperado: `ModuleNotFoundError`.
- [ ] **Step 3: Implementar `videopipeline/difusion.py`.**
- [ ] **Step 4: Comprobar que pasan.** Esperado: PASS.
- [ ] **Step 5: Commit**

```bash
git add videopipeline/difusion.py tests/test_difusion.py
git commit -m "feat: prepare LinkedIn sidecars and blog handoff folder"
```

---

### Task 6: Paso `DIFUSION` en config, ficha, planificador y ejecutor

**Files:**
- Modify: `videopipeline/config.py` (campo `difusion: bool = False`, después de `caption_seo`)
- Modify: `videopipeline/ficha.py` (constante `DIFUSION = "difusion"` junto a `TITULO`)
- Modify: `videopipeline/reproceso_plan.py`:
  - `Accion.DIFUSION = "difusion"` como **último** miembro;
  - nueva regla en `planificar` después del paso 6;
  - nuevo error sin final.
- Modify: `videopipeline/reproceso.py`:
  - método `_Pasada.difusion(self, paso)`;
  - `_mover_acompanantes` mueve también `.linkedin.md` y `.linkedin/`.
- Test: `tests/test_reproceso_plan.py`, `tests/test_reproceso.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `difusion.preparar` (Task 5); `titulo.generar_titulo(...) -> str | None`; `pipeline.asegurar_servidor` / `_cerrar_servidor` / `_avisar`.
- Produces:
  - `PipelineConfig.difusion`;
  - `Accion.DIFUSION`;
  - artefacto `ficha.artefactos["difusion"] = Artefacto("hecho", None, {"blog": str(carpeta_blog), "linkedin": str(linkedin_md)})`.

Reglas que fija este plan:

- **Cuándo entra en el plan:** `config.difusion and DIFUSION not in ficha.artefactos` añade `Accion.DIFUSION`, y también `TRANSCRIBIR` si `transcripcion is None`. Se mira la clave, no `_vale`: aunque el usuario borre los ficheros, no se repite.
- **Sin final:** si no hay `ficha.final` y la pasada no crea ninguno, error `'"{nombre}" aún no tiene vídeo procesado: el blog y LinkedIn solo se pueden pedir sobre un vídeo ya procesado'`.
- **`_Pasada.difusion`:**
  - `self._palabras()`; si da `PasoFallido` o está vacío → `_avisar` y salir;
  - idioma: `self.c.idioma_subs` si está en `("es", "en")`; si no, `"es"` (la misma regla que el caption);
  - título corto: el de `TITULO` en la ficha o `generar_titulo(...)`; si da `None`, `self.ficha.nombre`;
  - `final = self.ficha.ruta_final(self.ficha.hay_horizontal())`;
  - `video_blog = final if self.ficha.hay_horizontal() else self.base`;
  - Ollama con `asegurar_servidor()` / `_cerrar_servidor` en `finally`;
  - cualquier excepción → `_avisar(_("Blog y LinkedIn fallaron: {error}. Vídeo guardado igual.{sugerencia}"))` y sin artefacto;
  - si va bien: artefacto y `guardar(self.ficha)`.

- [ ] **Step 1: Escribir los tests que fallan**

```python
# tests/test_reproceso_plan.py  (_panel ya pone las demás casillas a False; añadir difusion=False a `marcas`)
def test_difusion_pide_transcribir_si_falta(tmp_path):
    plan = planificar(_ficha(tmp_path, {}), _panel(difusion=True), Decisiones())
    assert plan.acciones == [A.TRANSCRIBIR, A.DIFUSION]

def test_difusion_va_la_ultima(tmp_path): ...
    # con caption_seo=True y difusion=True sobre ficha con transcripción → [A.CAPTION, A.DIFUSION]

def test_difusion_una_vez_por_video(tmp_path):
    ficha = _ficha(tmp_path, {TRANSCRIPCION: _transcripcion("original"), HORIZONTAL: _horizontal(),
                              DIFUSION: Artefacto("hecho", None, {})})
    plan = planificar(ficha, _panel(subtitulos=True, diseno="caja", difusion=True),
                      Decisiones(rehacer=frozenset({"subtitulos"})))
    assert A.DIFUSION not in plan.acciones

def test_difusion_sin_final_da_error(tmp_path):
    plan = planificar(_ficha(tmp_path, {}, final=None), _panel(difusion=True), Decisiones())
    assert "el blog y LinkedIn" in plan.error

# tests/test_reproceso.py
def test_difusion_guarda_artefacto(...): ...      # monkeypatch reproceso.preparar_difusion → Resultado falso
def test_difusion_falla_sin_tumbar_el_video(...): ...  # preparar lanza → aviso emitido, sin artefacto, ejecutar() devuelve el final
def test_r10_mueve_acompanantes_de_linkedin(...): ...  # .linkedin.md y .linkedin/ siguen al nuevo final
```

- [ ] **Step 2: Comprobar que fallan.** `... -m pytest tests/test_reproceso_plan.py tests/test_reproceso.py -q`. Esperado: FAIL (`AttributeError: DIFUSION`).
- [ ] **Step 3: Implementar.**
  - En `reproceso.py`, importar `from .difusion import preparar as preparar_difusion`, para poder sustituirlo en los tests.
  - Si `test_config.py` lista los campos, añadir `difusion` a esa lista.
- [ ] **Step 4: Comprobar que pasa la suite completa.** Esperado: PASS.
- [ ] **Step 5: Commit**

```bash
git add videopipeline/config.py videopipeline/ficha.py videopipeline/reproceso_plan.py videopipeline/reproceso.py tests/
git commit -m "feat: run blog and LinkedIn preparation once per video"
```

---

### Task 7: Casilla «Blog y LinkedIn» en el panel

**Files:**
- Modify: `app/widgets/panel_opciones.py`:
  - `self.check_difusion` en la sección «Caption SEO», debajo de la fila del caption;
  - `valores()["difusion"]`;
  - restauración en `aplicar_valores`, con valor por defecto `False` y `_como_bool`.
- Modify: `app/widgets/info.py` (o donde viva la ayuda de cada opción; seguir el patrón de `check_caption`)
- Modify: `locale/en/LC_MESSAGES/tsots.po` (vía `lanzador/traducir.sh`)
- Test: `tests/test_app_widgets.py`

Textos que fija este plan:

- **Casilla:** `_("Blog y LinkedIn")`.
- **Tooltip:** `_("Prepara un borrador para el blog de evolve2digital y un post de LinkedIn con portada e imágenes del vídeo. Se hace una vez por vídeo.")`.
- **Traducción al inglés:** «Blog and LinkedIn».

- [ ] **Step 1: Escribir el test que falla:** `test_casilla_difusion_se_guarda_y_restaura`. Marca la casilla, comprueba que `valores()["difusion"] is True`, aplica `{"difusion": "false"}` y comprueba que queda desmarcada.
- [ ] **Step 2: Comprobar que falla.** `... -m pytest tests/test_app_widgets.py -q`. Esperado: FAIL.
- [ ] **Step 3: Implementar y ejecutar `lanzador/traducir.sh`;** completar el `msgstr` en `tsots.po`.
- [ ] **Step 4: Comprobar que pasa la suite completa.** Esperado: PASS.
- [ ] **Step 5: Commit**

```bash
git add app/widgets/ locale/ tests/test_app_widgets.py
git commit -m "feat: add Blog and LinkedIn option to the panel"
```

---

### Task 8: LinkedIn en el modelo de redes y en Upload-Post

**Files:**
- Modify: `videopipeline/redes/modelo.py`:
  - `Plataforma.LINKEDIN = "linkedin"`, al final de `ORDEN`;
  - `NOMBRES[LINKEDIN] = "LinkedIn"`;
  - `Publicacion.fotos: tuple[Path, ...] = ()` y `Publicacion.texto_linkedin: str = ""`.
- Modify: `videopipeline/redes/textos.py` (`MAX_TEXTO[Plataforma.LINKEDIN] = 3000`)
- Modify: `videopipeline/redes/upload_post.py`:
  - `_PLATAFORMAS[LINKEDIN] = "linkedin"`;
  - `URL_FOTOS = f"{URL_API}/upload_photos"`;
  - rama de LinkedIn en `publicar`, que llama a `_publicar_fotos`;
  - campos de LinkedIn en `campos`.
- Test: `tests/test_redes_upload_post.py`, `tests/test_redes_textos.py`, `tests/test_redes_contrato.py`

**Interfaces:**
- Consumes: resultado de la Task 1 (campo del cuerpo).
- Produces: `Publicacion.fotos`, `Publicacion.texto_linkedin` y `Plataforma.LINKEDIN`, que usa la Task 9.

Reglas que fija este plan:

- **Validación en `publicar(LINKEDIN, …)`:**
  - no usa `publicacion.video`;
  - exige `publicacion.fotos` no vacío y todas existentes. Si no, `_error(plataforma, _("No hay imágenes para LinkedIn"))` o `_("No se encuentra la imagen: {nombre}")`.
- **Campos:**
  - `user`, `platform[]=["linkedin"]`;
  - `title = texto_linkedin` recortado a 3000; si la Task 1 dijo otra cosa, el campo que diga;
  - `visibility = "PUBLIC"`;
  - `async_upload` o `scheduled_date` + `timezone`, como hoy;
  - `external_id` derivado de la primera foto.
- **Envío:**
  - `files` es una lista de tuplas `("photos[]", (nombre, fichero, mime))`, con mime `image/png` o `image/jpeg`;
  - la respuesta la interpreta el `_interpretar_subida` de siempre.
- **`cuentas()`:** LinkedIn se reconoce como las demás, vía `_PLATAFORMAS` / `_NOMBRES_RESPUESTA`.

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_linkedin_sube_fotos_a_upload_photos(tmp_path):
    fotos = tuple(_png(tmp_path / f"{i}.png") for i in range(3))
    servidor = Servidor(_ok_sync)
    pub = replace(_pub(tmp_path / "no_existe.mp4"), fotos=fotos, texto_linkedin="Gancho.\n\nCuerpo")
    r = _proveedor(servidor).publicar(Plataforma.LINKEDIN, pub, Opciones())
    assert r.ok
    peticion = servidor.peticiones[0]
    assert str(peticion.url) == "https://api.upload-post.com/api/upload_photos"
    campos = servidor.formularios[0]
    assert campos["platform[]"] == ["linkedin"] and campos["title"] == ["Gancho.\n\nCuerpo"]
    assert campos["visibility"] == ["PUBLIC"] and "target_linkedin_page_id" not in campos
    assert peticion.content.count(b'name="photos[]"') == 3

def test_linkedin_sin_fotos_no_envia(tmp_path):
    servidor = Servidor(_ok_sync)
    r = _proveedor(servidor).publicar(Plataforma.LINKEDIN, _pub(tmp_path / "v.mp4"), Opciones())
    assert not r.ok and servidor.peticiones == []

def test_linkedin_programado_lleva_fecha(tmp_path): ...
def test_cuentas_reconoce_linkedin(): ...
def test_max_texto_linkedin(): assert MAX_TEXTO[Plataforma.LINKEDIN] == 3000
```

- [ ] **Step 2: Comprobar que fallan.** Esperado: FAIL.
- [ ] **Step 3: Implementar.** Revisar los `ORDEN`, `Plataforma` y los diccionarios por plataforma de `registro.py`, `diario.py`, `publicador.py` y `tests/redes_falsos.py`; cualquiera que espere una entrada por plataforma la necesita también para LinkedIn.
- [ ] **Step 4: Comprobar que pasa la suite completa** (`test_redes_contrato.py` cubre que todas las plataformas tengan sus entradas). Esperado: PASS.
- [ ] **Step 5: Commit**

```bash
git add videopipeline/redes/ tests/
git commit -m "feat: publish LinkedIn photo posts through Upload-Post"
```

---

### Task 9: LinkedIn en «Publicar…» y «Redes…»

**Files:**
- Modify: `app/widgets/dialogo_publicar.py`:
  - fila LinkedIn con `QLabel(_("Post con fotos"))`;
  - campo `self.campo_linkedin` (QPlainTextEdit, altura 120, contador de caracteres sobre 3000) debajo de «Texto para X»;
  - tira `self.tira_linkedin`;
  - `publicacion()` rellena `fotos` y `texto_linkedin`;
  - `_estado_plataforma(LINKEDIN)` deshabilita con motivo si `linkedin.leer(self.video)` es `None` o no quedan fotos.
- Create: `app/widgets/tira_imagenes.py`. Es `TiraImagenes(QWidget)`:
  - miniaturas de 96 px de alto, cada una con botón «Quitar»;
  - botón «Añadir…» que abre un `QMenu` con los candidatos de `.linkedin/candidatos/` que no estén ya;
  - acepta arrastrar ficheros `.png` / `.jpg` / `.jpeg`;
  - `fotos() -> tuple[Path, ...]` y señal `cambiada`.
- Modify: `app/widgets/dialogo_redes.py`, solo si su lista de cuentas no sale ya de `ORDEN`.
- Modify: `locale/en/LC_MESSAGES/tsots.po`
- Test: `tests/test_app_redes.py` (o el fichero de tests de `DialogoPublicar` que ya exista)

Reglas que fija este plan:

- **Las imágenes que se arrastran o se añaden no se copian:** la publicación usa sus rutas tal cual. Tampoco se borra nada del disco al quitar una.
- **El texto de LinkedIn se lee del `.linkedin.md`;** si el usuario lo edita, se usa lo editado. No se guarda de vuelta en esta versión.
- **Sin `.linkedin.md`,** la fila LinkedIn sale deshabilitada con el motivo `_("Este vídeo no tiene post de LinkedIn: activa «Blog y LinkedIn» y procésalo.")`. El campo y la tira quedan ocultos.

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_linkedin_sin_acompanantes_deshabilitado(qtbot, tmp_path): ...
    # vídeo sin .linkedin.md → casilla LinkedIn deshabilitada, motivo visible, campo oculto
def test_linkedin_publicacion_lleva_texto_y_fotos(qtbot, tmp_path): ...
    # con .linkedin.md + 4 imágenes → publicacion().fotos == las 4 en orden; texto_linkedin == contenido
def test_quitar_imagen_la_saca_de_la_publicacion(qtbot, tmp_path): ...
def test_quitar_todas_deshabilita_linkedin(qtbot, tmp_path): ...
def test_anadir_candidato(qtbot, tmp_path): ...
def test_arrastrar_imagen_propia(qtbot, tmp_path): ...  # QDropEvent con QMimeData.setUrls
```

- [ ] **Step 2: Comprobar que fallan.** Esperado: FAIL.
- [ ] **Step 3: Implementar; ejecutar `lanzador/traducir.sh` y traducir los textos nuevos.**
- [ ] **Step 4: Comprobar que pasa la suite completa.** Esperado: PASS.
- [ ] **Step 5: Commit**

```bash
git add app/widgets/ locale/ tests/
git commit -m "feat: LinkedIn text and photo strip in the publish dialog"
```

---

### Task 10: Subida de media al blog (`blog_subida`)

**Files:**
- Create: `videopipeline/blog_subida.py`
- Test: `tests/test_blog_subida.py`

**Interfaces:**
- Produces: este comando, que usan las instrucciones de la Task 11:
  ```
  python -m videopipeline.blog_subida <uploadUrl> --fichero <ruta>=<slug-key> [--fichero …] [--portada <slug-key>] [--alt <slug-key>=<texto> …]
  ```
  ```python
  def subir(upload_url: str, ficheros: list[tuple[Path, str]], *, portada: str | None = None,
            alts: dict[str, str] | None = None, http: httpx.Client | None = None) -> None
  ```

Protocolo (comprobado el 2026-11-08; spec, «Subida de media al blog»):

1. **Origen y token:** salen de `upload_url`; el token es el parámetro `token`.
2. **Cada fichero:**
   - `POST {origen}/api/admin/media/upload`;
   - cabeceras `authorization: Bearer <token>`, `content-type: <mime por extensión>` y `x-media-name: <slug-key>`;
   - cuerpo: los bytes, enviados en streaming (sin cargar el vídeo entero en memoria).
3. **Confirmación:**
   - `POST {origen}/api/admin/media/upload/commit` con JSON `{"files": [{"name", "alt", "caption": ""}], "cover": portada}`;
   - `cover` solo si se pasa.
4. **Errores:**
   - un no-2xx lanza `RuntimeError` con el `error` del JSON de respuesta, o con el código HTTP;
   - el token nunca aparece en mensajes ni en logs.
5. **Validación de las slug-keys:** `^[a-z0-9_]+$`, sin repetidas.
6. **Tiempos de espera:** de escritura según el tamaño, como `upload_post.tiempos`.

- [ ] **Step 1: Escribir los tests que fallan** (`httpx.MockTransport`):

```python
def test_sube_cada_fichero_y_confirma(tmp_path):
    # 2 ficheros → 3 peticiones; 1ª: URL /api/admin/media/upload, Bearer, x-media-name, content-type image/png;
    # última: /upload/commit con {"files":[...], "cover":"portada"}
def test_error_del_servidor_sin_token_en_el_mensaje(tmp_path): ...
def test_slug_key_invalida_no_envia_nada(tmp_path): ...
def test_cli_parsea_ficheros_y_portada(tmp_path, monkeypatch): ...
```

- [ ] **Step 2: Comprobar que fallan.** Esperado: `ModuleNotFoundError`.
- [ ] **Step 3: Implementar `videopipeline/blog_subida.py`** con un `main(argv)` que use argparse.
- [ ] **Step 4: Comprobar que pasan.** Esperado: PASS.
- [ ] **Step 5: Commit**

```bash
git add videopipeline/blog_subida.py tests/test_blog_subida.py
git commit -m "feat: upload blog media with the MCP upload token"
```

---

### Task 11: Agente del blog (launchd + `claude -p`)

**Files:**
- Create: `lanzador/blog/procesar_pendientes.sh`
- Create: `lanzador/blog/instrucciones.md`
- Create: `lanzador/blog/com.tsots.blog.plist.plantilla`
- Modify: `instalar.command`, `desinstalar.command`
- Modify: `docs/DEVELOPMENT.md` (sección corta «Agente del blog»), `docs/TODO.md` (quitar la entrada del blog, que queda hecha)
- Test: `tests/test_blog_agente.py`

**`procesar_pendientes.sh <dir_blog>`:**
- **Bloqueo:** `mkdir "$DIR/.bloqueo"`; si ya existe, sale con 0. Se borra con `trap … EXIT`.
- **Recorrido:** por cada carpeta de `pendientes/` que no empiece por `.`:
  - ejecuta, desde la carpeta:
    ```
    claude -p "$(cat instrucciones.md)" --add-dir "$carpeta" \
      --allowedTools "mcp__e2d__posts_create,mcp__e2d__posts_request_upload,mcp__e2d__posts_validate,mcp__e2d__posts_set_cover,mcp__e2d__posts_list_media,Read,Write,Bash(<python> -m videopipeline.blog_subida:*)"
    ```
  - stdout/stderr van a `claude.log` dentro de la carpeta;
  - `<python>` es el intérprete de la instalación (`.venv-clearvoice/bin/python`), con `PYTHONPATH` en la raíz del repo.
- **Destino de cada carpeta:**
  - si al terminar existe `resultado.json` con `"url"`, la carpeta pasa a `hechos/`;
  - si no, a `errores/`, con `motivo.txt` (las últimas 40 líneas del log).
- **Sin `claude` en PATH** (se busca también en `~/.local/bin` y `/opt/homebrew/bin`): todas a `errores/` con ese motivo.

**`instrucciones.md`** (prompt, en español). Fija:

1. **Lectura:** `meta.json` y `transcripcion.txt`.
2. **Artículo:**
   - en el idioma de `meta.idioma`, con el tono y el formato E2D del spec (sección «Identidad E2D»): `<Lead>`, `##`, `<PullQuote>`, `<Callout>`, «Fuente:» si las hay y `[contact]` al final;
   - sin inventar datos que no estén en la transcripción.
3. **Imágenes del artículo:** elige 2-3 candidatos según su `texto` y los coloca como `[image:fotograma_N]` en la sección que encaja. Pone `[video:video]` después del `<Lead>`.
4. **Creación del borrador:** `posts_create` con `published: false`, `cover: "portada"`, `locale = meta.idioma` y `tags` derivados de las palabras clave.
5. **Subida de la media:** `posts_request_upload(slug, locale)` y después:
   ```
   python -m videopipeline.blog_subida <uploadUrl> --fichero portada.png=portada --fichero video.mp4=video --fichero candidatos/…=fotograma_N … --portada portada
   ```
6. **Comprobación:** `posts_validate`; si no hay errores, `posts_set_cover`.
7. **Resultado:** escribe `resultado.json` `{"slug", "locale", "url"}`. Ante cualquier fallo, no escribe `resultado.json` y explica el motivo en su última línea.
8. **Prohibido**, con esta frase literal: «Nunca uses `published: true`». Tampoco `posts_delete` ni `posts_update_frontmatter`, ni tocar otros posts.

**Plist:**
- `Label com.tsots.blog`;
- `ProgramArguments`: el script y `~/TSOTS/blog`;
- `WatchPaths` `~/TSOTS/blog/pendientes`;
- `StartInterval 3600` como reintento;
- logs en `~/TSOTS/blog/agente.log`.
- `instalar.command` sustituye las rutas, crea `~/TSOTS/blog/{pendientes,hechos,errores}`, copia el plist en `~/Library/LaunchAgents/` y hace `launchctl bootstrap gui/$(id -u)`.
- `desinstalar.command` hace `launchctl bootout` y borra el plist; **no** borra `~/TSOTS/blog`.

- [ ] **Step 1: Escribir los tests que fallan** (`tests/test_blog_agente.py`, con `subprocess` y un `claude` falso en un `PATH` temporal):

```python
def test_carpeta_con_resultado_pasa_a_hechos(tmp_path): ...   # claude falso escribe resultado.json
def test_carpeta_sin_resultado_pasa_a_errores_con_motivo(tmp_path): ...
def test_carpetas_ocultas_se_ignoran(tmp_path): ...
def test_segunda_ejecucion_con_bloqueo_no_hace_nada(tmp_path): ...
def test_instrucciones_prohiben_publicar():
    texto = Path("lanzador/blog/instrucciones.md").read_text()
    assert "`published: false`" in texto
    assert texto.count("published: true") == 1 and "Nunca uses `published: true`" in texto
def test_plist_plantilla_es_valido():
    plistlib.loads(Path("lanzador/blog/com.tsots.blog.plist.plantilla").read_bytes())
```

- [ ] **Step 2: Comprobar que fallan.** Esperado: FAIL.
- [ ] **Step 3: Implementar el script, las instrucciones, la plantilla y los cambios de instalación; actualizar `DEVELOPMENT.md` y `TODO.md`.**
- [ ] **Step 4: Comprobar que pasa la suite completa.** Esperado: PASS.
- [ ] **Step 5: Commit**

```bash
git add lanzador/blog/ instalar.command desinstalar.command docs/ tests/test_blog_agente.py
git commit -m "feat: launchd agent that drafts blog posts with claude -p"
```

---

### Task 12 (controlador, con el usuario): prueba real de punta a punta

- [ ] **Step 1: Procesar un vídeo real** con la app de esta rama (no la de producción), con «Blog y LinkedIn» activado. Esperado:
  - aparecen `<nombre>_limpio.linkedin.md` y `.linkedin/` con 4 imágenes;
  - aparece la carpeta en `~/TSOTS/blog/pendientes/`.
- [ ] **Step 2: Enseñar al usuario las dos portadas** (1672×941 y 1080×1350) y ajustar degradado, tamaños y palabra destacada según lo que diga. Commit de los ajustes con sus tests actualizados.
- [ ] **Step 3: Ejecutar `lanzador/blog/procesar_pendientes.sh ~/TSOTS/blog` a mano.** Esperado: la carpeta en `hechos/` y `resultado.json` con la URL de un **borrador**. Pedir al usuario que lo revise en evolve2digital.
- [ ] **Step 4: Probar LinkedIn de verdad, con permiso explícito del usuario.** En «Publicar…», programar el post a 7 días; comprobarlo en «Programadas…» y cancelarlo, salvo que el usuario quiera dejarlo.
- [ ] **Step 5: Abrir la PR contra `develop`** con descripción: qué cambia, por qué, cómo se verificó y riesgos (calidad del texto local, autenticación de `e2d` en la CLI).
