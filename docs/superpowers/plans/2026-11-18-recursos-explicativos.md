# Recursos explicativos (señalar, lupa, B-roll, iconos, datos) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que Haiku pueda señalar texto de la pantalla (círculo/flecha/subrayado y lupa), meter B-roll gratuito de Pexels (tapa o ventana según el contenido), iconos vectoriales y datos animados, y elija el mejor recurso entre los de antes y los nuevos.

**Architecture:**
- `preparar` lee la pantalla con el OCR de Apple y escribe `pantalla.json`, más secciones nuevas en `contexto.md` (en pantalla, números dichos, iconos, B-roll).
- `plan.py` valida cinco tipos nuevos; `validar_plan` imprime además sugerencias que no bloquean.
- `renderizar` dibuja cada pieza nueva como un overlay RGBA 1080×1920 más, con los módulos nuevos `pantalla`, `graficos`, `broll` y `callouts`. El compositor no cambia.
- Un diálogo guarda la clave de Pexels en el Llavero, y `SKILL.md` añade la tabla de decisión.

**Tech Stack:** Python 3 (`.venv-clearvoice`), PIL, numpy, OpenCV, ffmpeg-full, `httpx`, `pyobjc-framework-Vision` (nuevo), PySide6, pytest/pytest-qt.

**Spec:** `docs/superpowers/specs/2026-11-18-recursos-explicativos-design.md` (base: `2026-11-17-edicion-shorts-design.md`).

## Global Constraints

- **Worktree y rama.** Repo `~/Documents/personalProjects/limpiadorVideo`; worktree `~/Documents/personalProjects/tsots-recursos`, rama `feature/recursos-explicativos` desde `origin/develop`, sin upstream. Nunca push a `develop`/`main`.
- **Commits** en inglés, **sin atribución de IA** (regla del `CLAUDE.md` del repo).
- **Idioma.** Código, comentarios y GUI en español; textos nuevos con `_()`, traducidos en `locale/en/LC_MESSAGES/tsots.po` con `lanzador/traducir.sh`.
- **Tests.** `PY=~/Documents/personalProjects/limpiadorVideo/.venv-clearvoice/bin/python; QT_QPA_PLATFORM=offscreen $PY -m pytest -q`. En el worktree puede fallar `tests/test_pipeline.py::test_solo_vertical_cara_con_subs` (modelo de caras): es ruido conocido.
- **Aislamiento.** Ningún test usa la red, el Llavero real ni `~/TSOTS` (protecciones de `tests/conftest.py`; se añade una para la red de Pexels).
- **Descargas: permiso del usuario antes de cada una.** Hay que decirle nombre, origen y tamaño:
  - `pyobjc-framework-Vision` (y sus dependencias) de PyPI, que se instala en `.venv-clearvoice` y va en `requirements.txt`;
  - la fuente estática `MaterialSymbolsOutlined` (Apache 2.0) de `github.com/google/material-design-icons`, que se guarda en `lanzador/edicion/recursos/`.
- **Ids de tipo en ASCII**, como `titulo` o `transicion`: `senalar`, `lupa`, `broll`, `icono`, `dato`. Formas: `circulo`, `flecha`, `subrayado`.
- **Duraciones (s):** `senalar` 2.0 · `lupa` 2.6 · `broll` 2.5 · `icono` 1.6 · `dato` 2.4.
- **B-roll:** como mucho `ceil(duración/15)` por vídeo. Búsqueda de 2 a 6 palabras en letras latinas (inglés).
- **Nada tapa los subtítulos** (`zonas.subtitulos`) **ni el título** antes de `zonas.titulo.hasta`.
- **El render nunca falla por el OCR, Pexels o la red:** la pieza afectada se omite y se anota en el log.
- **La clave de Pexels nunca se escribe** en ficheros del trabajo, logs, errores ni el plan.
  - Llavero: servicio `tsots-pexels` (= `app.credenciales.servicio("pexels")`), cuenta `api-key`.
- Overlays RGBA 1080×1920 → `rotulos.render_slot` → `componer.componer` **sin cambios**.

## Review Focus

1. **Texto que se mueve o se pierde** (monitor grabado con el móvil, mano delante): el círculo o la lupa no saltan a otro sitio, se desvanecen. → Task 5.
2. **Vídeo sin texto en pantalla** (podcast a cámara): no hay coincidencias, `senalar`/`lupa` se rechazan con un motivo claro y el B-roll siempre va en modo tapa. → Tasks 2, 7.
3. **Pexels falla de cualquier forma** (sin resultados verticales, clip corto, 401, 429, timeout): el render termina y ese B-roll no sale. → Task 4.
4. **Números dichos de varias formas** («diez», «10», «1.000», «3,5», «20 por ciento», «20%»). → Task 3.
5. **Equipo sin `pyobjc`** (otro usuario que actualiza): `preparar` sigue y solo se apagan `senalar`/`lupa`. → Tasks 2, 6.

---

### Task 1: Worktree y comprobación de red y Llavero desde el agente (controlador)

**Files:** ninguno del producto. Resultado en el ledger.

- [ ] **Step 1: Worktree.**

  ```bash
  git -C ~/Documents/personalProjects/limpiadorVideo fetch origin
  git -C ~/Documents/personalProjects/limpiadorVideo worktree add ../tsots-recursos -b feature/recursos-explicativos origin/develop
  git -C ../tsots-recursos branch --unset-upstream
  ```

  Copia spec y plan a `docs/superpowers/specs|plans/`.
- [ ] **Step 2: Permiso de descargas.** Pide permiso al usuario para las dos descargas de Global Constraints (nombre, origen, tamaño). Con el sí: instala `pyobjc-framework-Vision` en `.venv-clearvoice` y descarga la fuente.
- [ ] **Step 3: Prueba con el agente.**
  - En una carpeta del scratchpad, un script `./sonda` que:
    - haga `GET https://api.pexels.com/videos/search?query=test` sin clave (se espera **401**, lo que prueba que hay red);
    - ejecute `security find-generic-password -s tsots-pexels -a api-key` (se espera código **0 o 44**, lo que prueba que el Llavero es accesible).
  - Lánzalo con `claude -p --model claude-haiku-5-5 --allowedTools "Bash(./sonda:*)" --setting-sources project,local "Ejecuta ./sonda y copia su salida"` desde esa carpeta.
  - Anota el resultado. Si falla, para y avisa al usuario: es requisito del B-roll.

### Task 2: Leer la pantalla (`pantalla.py`)

**Files:**
- Create: `videopipeline/edicion/texto.py`, `videopipeline/edicion/pantalla.py`, `tests/test_edicion_pantalla.py`
- Modify: `videopipeline/edicion/plan.py` (`_norm` pasa a `texto.normalizar`), `requirements.txt`, `tests/conftest.py`

**Interfaces:**
- Produces:
  - `texto.normalizar(s: str) -> str`: el actual `plan._norm`.
  - `@dataclass(frozen=True) Deteccion(texto: str, caja: tuple[int, int, int, int], confianza: float)`: la caja es x, y, w, h en 1080×1920.
  - `@dataclass(frozen=True) Muestra(t: float, detecciones: tuple[Deteccion, ...])`.
  - `@dataclass(frozen=True) Coincidencia(t0: float, t1: float, visible: str, palabra: str, t_palabra: float)`.
  - Constantes: `FPS_MUESTREO = 2`, `UMBRAL_AREA` (fracción del área sin máscara cubierta por texto).
  - `ocr_disponible() -> bool`.
  - `leer_fotograma(imagen: Image.Image) -> list[Deteccion]`: Vision, idiomas es y en; los tests lo sustituyen.
  - `enmascarar(imagen, zonas: dict, t: float) -> Image.Image`.
  - `analizar(video: Path, zonas: dict, destino: Path) -> list[Muestra]`: escribe `pantalla.json`.
  - `cargar(ruta: Path) -> list[Muestra]`: `[]` si no existe o está mal.
  - `hay_texto(muestras, t0, t1) -> bool`.
  - `modo_broll(muestras, t: float, dur: float = 2.5) -> str`: `"ventana"` si `hay_texto(t, t + dur)`, si no `"tapa"`.
  - `buscar(muestras, texto: str, t: float, margen: float = 0.5) -> Deteccion | None`.
  - `coincidencias(muestras, palabras: list[Palabra]) -> list[Coincidencia]`.

- [ ] **Step 1: Tests** (sustituye `pantalla.leer_fotograma` y la extracción de fotogramas por fakes):
  - **Máscara de subtítulos y título:** `test_enmascara_subtitulos_y_titulo`. Con `zonas.subtitulos=[1269,1440]` y `titulo.hasta=5.0`, `enmascarar` deja negra la banda de subtítulos siempre y la del título solo con `t < 5.0`; con `subtitulos=None` no toca esa banda.
  - **Análisis de un vídeo:**
    - `test_analizar_escribe_pantalla_json`: muestras cada 0.5 s y `cargar` las devuelve iguales.
    - `test_cargar_sin_fichero_es_lista_vacia`.
  - **Texto en pantalla y modo del B-roll:**
    - `test_hay_texto_y_modo_broll`: texto solo entre 10 y 12 s → `modo_broll(m, 9.0) == "ventana"` (solapa) y `modo_broll(m, 20.0) == "tapa"`.
    - Un texto diminuto por debajo de `UMBRAL_AREA` no cuenta.
  - **Buscar un texto visible:** `test_buscar_normaliza`. «Revisión» se encuentra con `"revision"` en `t` ±0.5 s y no a 2 s de distancia.
  - **Coincidencias entre lo dicho y lo visto:**
    - `test_coincidencias_dicho_y_visto`: la palabra dicha «documentos» en 41.9 y la línea «Documentos de la empresa» visible entre 41.5 y 45.0 dan una `Coincidencia`.
    - Una palabra dicha sin texto visible no da ninguna.
  - **Review Focus 2 · sin texto en pantalla:** `test_video_sin_texto_no_da_coincidencias`.
  - **Review Focus 5 · sin `pyobjc`:** `test_sin_pyobjc_ocr_no_disponible`. Simulando el `ImportError`, `ocr_disponible()` es `False` y no lanza.
  - **Prueba real del OCR:** `test_ocr_real_lee_texto`, que se salta sin `pyobjc`. Un PNG generado con PIL con «Documentos» → `leer_fotograma` lo devuelve.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implementa.** Muestrea con ffmpeg (`fps=2`, escala 1080×1920) y añade `pyobjc-framework-Vision==<versión instalada>` a `requirements.txt`. `plan.py` importa `normalizar`; sin otros cambios.
- [ ] **Step 4: Run → PASS** (`tests/test_edicion_pantalla.py tests/test_edicion_plan.py`).
- [ ] **Step 5: Commit** `feat: read on-screen text for Claude edits`.

### Task 3: Iconos, datos y números dichos (`graficos.py`, `numeros.py`)

**Files:**
- Create: `videopipeline/edicion/graficos.py`, `videopipeline/edicion/numeros.py`, `lanzador/edicion/recursos/` (fuente de la Task 1 + `LICENCIA.txt`), `tests/test_edicion_graficos.py`

**Interfaces:**
- Produces:
  - `ICONOS: dict[str, str]`: unos 40 nombres en español → glifo (`documento`, `carpeta`, `busqueda`, `candado`, `seguridad`, `euro`, `grafica`, `reloj`, `calendario`, `usuario`, `equipo`, `idea`, `check`, `alerta`, `mensaje`, `correo`, `nube`, `ia`, `codigo`, `casa`, `edificio`, `contrato`, `firma`, `dinero`, `tiempo`, `objetivo`, `cohete`, `ajustes`…).
  - `icono_disponible(nombre: str) -> bool`.
  - `parecidos(nombre: str, n: int = 5) -> list[str]` (difflib).
  - `frames_icono(nombre, dur, cx, cy, tam, paleta, fps)`: insignia redonda del color de acento con el glifo y entrada con rebote, como `emojis.frames_emoji`.
  - `frames_dato(valor: float, texto: str, unidad: str | None, dur, paleta, fps)`: número grande que cuenta de 0 a `valor` (ease-out, 0.8 s) en `cy≈330`, píldora con `texto` debajo y, con `"%"`, una barra que se llena hasta `valor`. Los decimales se pintan con coma.
  - `numeros.valor_de(palabra: str) -> float | None`.
  - `numeros.numeros_dichos(palabras: list[Palabra]) -> list[tuple[float, float, str, bool]]`: `(t, valor, palabra, es_porcentaje)`.

- [ ] **Step 1: Tests.**
  - **Catálogo de iconos:** `test_catalogo_iconos_se_dibuja`. Todos los `ICONOS` dan un glifo no vacío con la fuente.
  - **Animación del icono:** `test_frames_icono_alfa_y_duracion`.
    - Nº de fotogramas = `round(dur*fps)`.
    - Primer fotograma casi transparente.
    - A mitad, píxeles opacos del color de acento.
    - Nada por debajo de y=900.
  - **Animación del dato:** `test_frames_dato_cuenta_y_barra`. Con `valor=10` el último fotograma muestra «10»; se comprueba que cambia entre fotogramas y que con `unidad="%"` hay barra (píxeles de acento en su franja).
  - **Review Focus 4 · formas de los números:** `test_valor_de_formas`.
    - Cifras: «10»→10, «1.000»→1000, «3,5»→3.5, «20%»→20.
    - Palabras: «diez»→10, «cien»→100, «mil»→1000.
    - No números: «hola»→None.
  - **Porcentajes:** `test_numeros_dichos_porcentaje`. «veinte por ciento» → `(t, 20, "veinte", True)`.
  - **Nombres parecidos:** `test_parecidos`. `parecidos("documentos")` incluye `"documento"`.
- [ ] **Step 2: Run → FAIL.** **Step 3: Implementa.** **Step 4: Run → PASS** (`tests/test_edicion_graficos.py`).
- [ ] **Step 5: Commit** `feat: animated icons and spoken-number data cards`.

### Task 4: B-roll de Pexels (`broll.py`)

**Files:**
- Create: `videopipeline/edicion/broll.py`, `tests/test_edicion_broll.py`
- Modify: `tests/conftest.py` (protección: `broll.httpx` sin red y `broll.leer_clave` → `None` por defecto)

**Interfaces:**
- Consumes: `pantalla.modo_broll` (Task 2), solo en tests de integración del modo.
- Produces:
  - Constantes: `SERVICIO = "tsots-pexels"`, `CUENTA = "api-key"`, `DURACION = 2.5`.
  - `leer_clave() -> str | None`: `security find-generic-password -s … -a … -w`.
  - `hay_clave() -> bool`: sin `-w`.
  - `probar_clave(clave: str) -> bool`: una búsqueda.
  - `@dataclass(frozen=True) Clip(archivo: Path, autor: str, url: str, id: int)`.
  - `obtener(buscar: str, usados: set[int], carpeta: Path, clave: str | None = None) -> Clip | None`. Búsqueda `orientation=portrait`; primer vídeo de ≥ `DURACION` s cuyo `id` no esté en `usados`, con el fichero de mayor alto ≤ 1920. Caché por búsqueda en `carpeta` (`<slug>.json` + `<id>.mp4`). Cualquier error → `None`, y un log sin la clave.
  - `frames_broll(clip: Path, modo: str, dur: float, zonas: dict, paleta, fps)`:
    - `"tapa"`: cubre `[0, 0, 1080, zonas.subtitulos[0]]`, o la pantalla entera si no hay subtítulos, recortando para llenar y con un zoom lento.
    - `"ventana"`: tarjeta de ~860 px de ancho con esquinas redondeadas y sombra en la zona superior.
    - En los dos, un fundido de 0.2 s al entrar y al salir.

- [ ] **Step 1: Tests** (`httpx.MockTransport` o sustituyendo `httpx.get`; un clip de prueba generado con ffmpeg `testsrc2`):
  - **Elección del clip:**
    - `test_obtener_elige_vertical_largo_no_usado`: descarta los de 1.5 s y los usados; elige el fichero ≤1920 de alto.
    - `test_obtener_usa_cache`: la segunda llamada no hace petición.
  - **Review Focus 3 · fallos de Pexels:** `test_obtener_falla_suave`. Sin resultados, solo clips cortos, 401, 429 y timeout → `None`, sin excepción.
  - **La clave nunca sale:** `test_clave_no_sale_en_logs`. Con clave `"SECRETA123"` y un 401, el texto del log y los ficheros de `carpeta` no contienen `SECRETA123`.
  - **Llavero:**
    - `test_leer_clave_usa_security`: argumentos exactos, código 44 → `None`.
    - `test_servicio_coincide_con_app`: `SERVICIO == app.credenciales.servicio("pexels")`.
  - **Modos de dibujo:**
    - `test_frames_tapa_respeta_subtitulos`: con `subtitulos=[1269,1440]`, alfa 0 en y ≥ 1269; con `subtitulos=None`, cubre hasta 1920.
    - `test_frames_ventana_en_zona_superior`.
- [ ] **Step 2: Run → FAIL.** **Step 3: Implementa.** **Step 4: Run → PASS** (`tests/test_edicion_broll.py tests/test_credenciales.py`).
- [ ] **Step 5: Commit** `feat: fetch and draw free Pexels B-roll`.

### Task 5: Señalar y lupa (`callouts.py`)

**Files:**
- Create: `videopipeline/edicion/callouts.py`, `tests/test_edicion_callouts.py`

**Interfaces:**
- Consumes: `pantalla.Deteccion`, `pantalla.leer_fotograma`, `pantalla.enmascarar`, `texto.normalizar` (Task 2).
- Produces:
  - `seguir(video: Path, texto: str, t: float, dur: float, fps: int, inicial: Deteccion, zonas: dict) -> list[tuple[int, int, int, int] | None]`: una caja por fotograma del tramo; OCR cada 2 fotogramas con interpolación y media móvil. Si la caja salta más de un 25 % del ancho entre lecturas, o deja de verse, es `None` desde ahí.
  - `frames_senalar(cajas, forma: str, paleta, fps)`:
    - `circulo`: elipse que se traza en 0.3 s;
    - `flecha`: flecha que entra hasta el borde de la caja;
    - `subrayado`: línea que se extiende bajo la caja.
    - Grosor de ~8 px en color de acento. Se desvanece en 0.2 s desde el primer `None`.
  - `frames_lupa(video: Path, cajas, t: float, dur: float, zonas: dict, paleta, fps)`:
    - recorte de la caja con un margen del 30 %, ampliado ×2 (como mucho 900 px de ancho);
    - tarjeta con borde de acento y sombra en la mitad vertical opuesta a la caja, siempre por encima de `graficos_hasta` y por debajo de `titulo.y[1]`;
    - un trazo une la tarjeta con la caja;
    - mismo desvanecido.

- [ ] **Step 1: Tests** (vídeo sintético: ffmpeg `color` + `drawtext` «Revisión» desplazándose 3 px por fotograma; `leer_fotograma` simulado a partir de la posición conocida):
  - **Seguir el texto:** `test_seguir_texto_que_se_mueve`. Las cajas avanzan ~3 px/fotograma y el error es menor de 10 px.
  - **Review Focus 1 · texto que salta o se pierde:** `test_seguir_salto_o_perdida_da_none`. Si la detección salta a la otra punta, o desaparece, la caja queda en `None` desde ahí, sin saltar.
  - **Señalar:** `test_frames_senalar_formas_y_fundido`.
    - Las tres formas pintan acento cerca de la caja.
    - Tras el primer `None`, la opacidad baja hasta 0.
  - **Lupa:** `test_frames_lupa_no_tapa_subtitulos`.
    - La tarjeta está en la mitad opuesta.
    - Hay alfa 0 en la banda de subtítulos.
    - La tarjeta contiene píxeles del recorte ampliado.
- [ ] **Step 2: Run → FAIL.** **Step 3: Implementa.** **Step 4: Run → PASS** (`tests/test_edicion_callouts.py`).
- [ ] **Step 5: Commit** `feat: on-screen callouts and magnifier that follow text`.

### Task 6: Contexto para Haiku (`preparar.py`)

**Files:**
- Modify: `videopipeline/edicion/preparar.py`
- Test: `tests/test_edicion_trabajo.py`

**Interfaces:**
- Consumes: `pantalla.ocr_disponible/analizar/cargar/coincidencias` (Task 2), `graficos.ICONOS` y `numeros.numeros_dichos` (Task 3), `broll.hay_clave` (Task 4).
- Produces: `pantalla.json` en el trabajo (si hay OCR y aún no existe) y `contexto.md` con:
  - en `## Estilo`:
    - `- lectura de pantalla: sí|no`;
    - `- B-roll: disponible|no disponible (falta la clave de Pexels)`.
  - `## En pantalla`: una línea por `Coincidencia`, `41.50-45.00 «Documentos de la empresa» (dicha «documentos» en 41.90)`. Sin coincidencias pone `- ninguna`; sin OCR, `- no disponible`.
  - `## Números dichos`: `30.20 10 «diez»` (y ` %` si es porcentaje), o `- ninguno`.
  - `## Iconos`: los nombres del catálogo separados por comas.

- [ ] **Step 1: Tests** (OCR simulado):
  - **Contexto con todas las secciones:** `test_contexto_con_pantalla_numeros_iconos_y_broll`.
  - **Sin OCR:** `test_contexto_sin_ocr`. Con `ocr_disponible=False`: «lectura de pantalla: no» y `## En pantalla` dice «no disponible», sin fallar.
  - **Sin clave de Pexels:** `test_contexto_sin_clave_pexels`.
  - **Caché del análisis:** `test_preparar_no_repite_ocr`. Si `pantalla.json` existe, no se vuelve a analizar.
- [ ] **Step 2: Run → FAIL.** **Step 3: Implementa.** **Step 4: Run → PASS** (`tests/test_edicion_trabajo.py`).
- [ ] **Step 5: Commit** `feat: tell Haiku what is on screen, numbers, icons and B-roll`.

### Task 7: Plan y validación de los tipos nuevos

**Files:**
- Modify:
  - `videopipeline/edicion/plan.py`;
  - `videopipeline/edicion/validar_plan.py`;
  - `lanzador/edicion/estilos/{divertido,formal,academico}.json`: añadir a `tipos` los cinco nuevos.
- Test: `tests/test_edicion_plan.py`, `tests/test_edicion_estilos.py`

**Interfaces:**
- Consumes: `pantalla` (Task 2), `graficos.icono_disponible/parecidos` y `numeros.numeros_dichos` (Task 3), `broll.hay_clave` y `broll.DURACION` (Task 4).
- Produces:
  - **Tipos y campos:** `TIPOS` con `senalar`, `lupa`, `broll`, `icono`, `dato`, y `DURACION` con sus valores. `Momento` gana `pantalla`, `forma`, `buscar`, `icono`, `valor`, `unidad`, y `leer` comprueba sus tipos JSON.
  - **Validación:** `validar(plan, palabras, zonas, estilo, duracion, pantalla: list[Muestra] = (), broll_disponible: bool = False) -> tuple[Plan, list[str]]`. Sin las dos últimas, se comporta como hoy.
  - **Sugerencias:** `sugerencias(plan: Plan, pantalla: list[Muestra]) -> list[str]`, cada una empezando por «Sugerencia: ».
  - **CLI:** `validar_plan` carga `pantalla.json` y `broll.hay_clave()`. Si no hay errores, imprime `OK` y debajo las sugerencias; el código de salida es 0.

- [ ] **Step 1: Tests:**
  - **Señalar y lupa:**
    - `test_senalar_y_lupa_validos`: `pantalla` visible en t ±0.5; `forma` por defecto `circulo`.
    - `test_senalar_texto_no_visible`: el error lista las coincidencias disponibles.
    - `test_senalar_sin_ocr`: con `pantalla=()`, el error es «este vídeo no tiene lectura de pantalla; quita el momento» (Review Focus 2).
    - `test_forma_invalida`.
  - **B-roll:**
    - `test_broll_requiere_clave_y_busqueda`: sin clave, error; 1 o 7 palabras, error; con caracteres no latinos, error.
    - `test_broll_maximo_por_duracion`: en 30 s, como mucho 2.
    - `test_broll_no_coincide_con_nada_visual`: con etiqueta, emoji lateral, icono, senalar, lupa, dato y final → error; con transicion → OK.
  - **Icono:** `test_icono_desconocido_sugiere_parecidos`.
  - **Dato:**
    - `test_dato_valor_dicho`: «10» dicho en ±1.5 s → OK; «12» no dicho → error.
    - `test_dato_porcentaje`: `unidad: "%"` solo si se dijo en porcentaje.
    - Texto de más de 22 caracteres → error.
  - **Solapes y zooms:**
    - `test_lupa_y_dato_ocupan_zona_superior`: solapan con etiqueta → error.
    - `test_icono_lateral_como_emoji`: icono + etiqueta → OK.
    - `test_senalar_no_coincide_con_zoom`: con `franja_zoom` y un zoom del plan → error; en los últimos 3 s con `zoom_lento > 0` → error; sin franja → OK.
  - **Sugerencias:**
    - `test_sugerencia_etiqueta_en_pantalla`: una etiqueta «REVISIÓN» mientras «Revisión» es visible → `Sugerencia:` que propone `senalar`, y `validar_plan` imprime `OK` + sugerencia con exit 0.
    - `test_sugerencia_variedad`: tres momentos seguidos del mismo tipo → sugerencia.
  - **Estilos:**
    - `test_estilos_admiten_tipos_nuevos`.
    - La densidad cuenta los nuevos.
- [ ] **Step 2: Run → FAIL.** **Step 3: Implementa.** **Step 4: Run → PASS** (`tests/test_edicion_plan.py tests/test_edicion_estilos.py tests/test_edicion_trabajo.py`).
- [ ] **Step 5: Commit** `feat: validate callouts, B-roll, icons and data in edit plans`.

### Task 8: Render de los tipos nuevos

**Files:**
- Modify: `videopipeline/edicion/renderizar.py`
- Test: `tests/test_edicion_renderizar.py`

**Interfaces:**
- Consumes: Tasks 2–5 y los tipos de la Task 7.
- Produces:
  - **`derivar`:** `derivar(plan, zonas, estilo, duracion, pantalla: list[Muestra] = ()) -> Specs`, que sigue siendo pura. Piezas nuevas:
    - `senalar`: `{pantalla, forma, caja}`;
    - `lupa`: `{pantalla, caja}`;
    - `broll`: `{buscar, modo}`, con `modo` de `pantalla.modo_broll`;
    - `icono`: `{icono, cx, cy, tam}`, colocado como los emojis (lateral si coincide con etiqueta o contador);
    - `dato`: `{valor, texto, unidad}`.
  - **Sonidos:** `SFX_NUEVOS = {"senalar": ("tap", "tick", "pop"), "lupa": ("whoosh_b", "tick", "pop"), "broll": ("whoosh_g", "whoosh_b", "pluck"), "icono": ("pop", "tick", "tap"), "dato": ("tick2", "tick", "pluck")}`. Suena el primero que tenga el estilo.
  - **`_render_pieza`:** `_render_pieza(p, estilo, fps, destino, ctx: RenderCtx) -> Path | None`, con `None` cuando la pieza se omite. `RenderCtx(video, zonas, carpeta_broll, usados: set[int], creditos: list[dict])`.
  - **`renderizar`:**
    - carga `pantalla.json`;
    - usa `<trabajo>/broll/` como caché;
    - escribe `broll.json` con los créditos (`autor`, `url`, `buscar`, `t`);
    - deja fuera las piezas `None`.

- [ ] **Step 1: Tests** (OCR y Pexels simulados):
  - **Derivar:**
    - `test_derivar_tipos_nuevos`: clase, parámetros y tiempos de cada pieza.
    - El modo del B-roll sale de `pantalla`.
    - El icono va lateral si coincide con una etiqueta.
  - **Sonidos:** `test_sfx_nuevos_segun_estilo`. En formal, el `senalar` suena `tick`; en un estilo sin ninguno de la lista, nada.
  - **Render completo:**
    - `test_renderizar_con_broll_y_creditos`: `video_vertical` con un `broll` → `salida.mp4` y `broll.json` con autor y url.
    - `test_renderizar_omite_broll_si_pexels_falla`: `obtener` devuelve `None` → el render termina sin esa pieza (Review Focus 3).
  - **Muestra visual:** `test_renderizar_icono_y_dato`, con una muestra de color en `t + 0.5` sobre la zona superior.
- [ ] **Step 2: Run → FAIL.** **Step 3: Implementa.** **Step 4: Run → PASS** (`tests/test_edicion_renderizar.py tests/test_edicion_componer.py`).
- [ ] **Step 5: Commit** `feat: render callouts, magnifier, B-roll, icons and data`.

### Task 9: Clave de Pexels en la app

**Files:**
- Create: `app/widgets/dialogo_pexels.py`
- Modify: `app/widgets/panel_opciones.py` (botón «Pexels…» en la fila del estilo de «Editar con Claude»), `app/main.py` (conexión), `locale/en/LC_MESSAGES/tsots.po`
- Test: `tests/test_app_widgets.py`

**Interfaces:**
- Consumes: `app.credenciales.guardar/borrar/hay_clave` (proveedor `"pexels"`), `broll.probar_clave` (Task 4).
- Produces: `DialogoPexels(QDialog)`.
  - Campo de clave oculto, con botones «Comprobar y guardar» y «Borrar».
  - Estado: «Guardada» o «Sin clave».
  - Enlace a `https://www.pexels.com/api/`.
  - Texto: la clave es gratis, se guarda en el Llavero y sirve para el B-roll de «Editar con Claude».
  - `PanelOpciones.boton_pexels` y la señal `configurar_pexels`.

- [ ] **Step 1: Tests:**
  - **Guardar:** `test_dialogo_pexels_guarda_si_la_prueba_va_bien`. Con `probar_clave` → True, guarda; con → False, avisa y no guarda.
  - **Borrar:** `test_dialogo_pexels_borra`.
  - **La clave no se deja ver:** `test_dialogo_pexels_no_muestra_la_clave`. Tras guardar, el campo queda vacío y el estado no la contiene.
  - **Botón del panel:** `test_boton_pexels_en_panel`. Está activo con Claude disponible y emite la señal.
- [ ] **Step 2: Run → FAIL.** **Step 3: Implementa** y traduce. **Step 4: Run → PASS** (`tests/test_app_widgets.py tests/test_app_main.py`).
- [ ] **Step 5: Commit** `feat: Pexels key dialog for Claude B-roll`.

### Task 10: La skill elige el mejor recurso; docs

**Files:**
- Modify:
  - `lanzador/edicion/SKILL.md`;
  - `README.md` y `README.es.md` (sección de editar con Claude: recursos nuevos, clave de Pexels, `pyobjc`, créditos en `broll.json`);
  - `docs/superpowers/specs/2026-11-17-edicion-shorts-design.md` (sección 13 → spec nuevo).
- Test: `tests/test_edicion_agente.py`

- [ ] **Step 1: Tests:**
  - **Contenido de la skill:** `test_skill_tiene_tabla_de_decision`. `SKILL.md` contiene:
    - los cinco ids nuevos;
    - las secciones de contexto que cita (`## En pantalla`, `## Números dichos`, `## Iconos`);
    - la palabra `Sugerencia`.
  - **El formato no se queda atrás:** `test_skill_formato_valida`. Cada ejemplo JSON del bloque de formato se lee con `plan.leer`, y sus tipos están en `plan.TIPOS`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Escribe:**
  - **Formato:** ejemplos de los tipos nuevos en el bloque de `plan.json` y una fila por tipo en la tabla «cuándo usarlo».
  - **`## Elegir el recurso`:** el orden de preferencia del spec 4.6, los cupos (B-roll ≤ 1 cada 15 s), la variedad (no 3 seguidos del mismo tipo), «búsquedas de B-roll en inglés, concretas y visuales» y «`dato` solo con números de `## Números dichos`».
  - **Paso 3:** «si imprime `OK` seguido de `Sugerencia:`, aplica las que tengan sentido y vuelve a validar una vez».
  - **Paso 5:** en `verificacion.png` revisa también que la flecha o la lupa señalen el texto correcto y que el B-roll tenga que ver con lo que se dice.
  - **Docs:** README ES/EN y sección 13 del diseño.
- [ ] **Step 4: Run → PASS**, suite completa.
- [ ] **Step 5: Commit** `docs: teach the edit agent to pick the best visual`.

### Task 11: Prueba real y PR (controlador)

- [ ] **Step 1: Clave de Pexels.** El usuario la crea gratis en pexels.com/api y la pega en el diálogo nuevo (lanzando la app desde el worktree). La clave nunca pasa por el chat.
- [ ] **Step 2: Prueba real con Haiku** (agente del worktree con `TSOTS_EDICION_PYTHON` del venv principal):
  - `odin_17_11`: demo grabada con el móvil;
  - un short del Episodio 20: cara, podcast.
  - En cada uno se revisa `verificacion.png`:
    - las flechas o lupas sobre el texto correcto;
    - B-roll en tapa (cara) o ventana (demo);
    - nada sobre subtítulos ni título;
    - iconos y datos visibles.
- [ ] **Step 3: Suite completa → PASS.** Push y PR a `develop`, con el permiso del usuario.
