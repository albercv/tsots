# Shorts por temas — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que «Crear shorts» elija temas completos de todo el vídeo (los mejores momentos, de 60 a 179 s y lo más largos posible), como mucho uno cada 10 minutos.

**Architecture:** Todo vive en `videopipeline/shorts.py`. La selección pasa a tener cuatro pasos:
1. El modelo del caption segmenta en temas con ventanas encadenadas de unos 10 min.
2. El código arma candidatos (temas y tramos de temas) y el modelo saca fragmentos de los temas de más de 179 s.
3. `tev1` puntúa, sin cambios.
4. Se elige con reparto por tramos de 10 min.

`crear` y una entrada nueva de «solo selección» comparten `seleccionar`.

**Tech Stack:** Python 3, Ollama (`chat_json`, `systemone`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-shorts-por-temas-design.md`

## Global Constraints

- Código, comentarios, interfaz y prompts en español. Las cadenas de interfaz van con `_()` y se traducen al inglés en `locale/en/LC_MESSAGES/tsots.po` (ejecutar `lanzador/traducir.sh` y rellenar los `msgstr`).
- Commits en inglés, **sin atribución de IA** (sin `Co-Authored-By` ni «Generated with»).
- Tests: `QT_QPA_PLATFORM=offscreen ~/Documents/personalProjects/limpiadorVideo/.venv-clearvoice/bin/python -m pytest -q`. Ruido conocido en worktrees: `tests/test_pipeline.py::test_solo_vertical_cara_con_subs`.
- Los tests no tocan la red ni Ollama: se sustituyen `shorts.chat_json` y `shorts.systemone` (ver `_chat_falso` en `tests/test_shorts.py`).
- Sin dependencias ni modelos nuevos. Siguen `config.modelo_caption` (por defecto `qwen3.5:9b`), `JUEZ = "tev1:0.8b"` y `num_ctx` 16384.
- Valores del diseño:
  - duración de un short: `DURACION_MIN = 60.0`, `DURACION_MAX = 179.0`;
  - ventana y tramo: 10 min;
  - como mucho 3 fragmentos por llamada;
  - empate de interés: 0.3;
  - tope: 0 si el vídeo dura menos de 180 s; si no, `max(1, duración // 600)`;
  - `shorts.json` pasa a `"version": 2`;
  - descarte nuevo: `"tema_corto"`;
  - `Candidato.origen`: `"tema"`, `"tramo"` o `"fragmento"`.
- **Nunca** se ejecuta «Crear shorts» sobre el Episodio 20 (ficha `c77cb35e0467`): borraría sus 15 shorts editados y publicados. Para probar se usa la entrada de solo selección (Task 6).

## Review Focus

1. El modelo devuelve inicios de tema fuera de la ventana, repetidos, decrecientes o no enteros. Se ignoran y la segmentación sigue avanzando (Task 2).
2. Un tema más largo que la ventana (ningún inicio nuevo en ella) no atasca el bucle y el tema continúa (Task 2).
3. Un vídeo que es un solo tema enorme (más de 10 min) se parte en subventanas y cada llamada pide 3 fragmentos como mucho (Task 4).
4. Todos los temas son cortos y sueltos: ningún candidato. `crear` da el aviso de siempre, «Ningún trozo… no se ha creado ninguno», sin romper (Task 6).
5. La segmentación falla dos veces seguidas: `PasoFallido` con detalle, y el modelo se descarga igualmente (Task 6).

---

### Task 1: Tope de shorts y modelo cargado entre llamadas

**Files:**
- Modify: `videopipeline/shorts.py` (`maximo_shorts`)
- Modify: `videopipeline/ollama.py` (`chat_json`, nueva `descargar`)
- Test: `tests/test_shorts.py`, `tests/test_ollama.py`

**Interfaces:**
- Produces:
  - `maximo_shorts(duracion: float) -> int`;
  - `chat_json(..., keep_alive: int | str = 0)`, que manda el valor tal cual en `"keep_alive"`;
  - `descargar(modelo: str, url: str = URL) -> None`, que hace `POST /api/generate` con `{"model": modelo, "keep_alive": 0}` y se traga cualquier error, porque descargar es higiene y no debe romper nada;
  - constante `KEEP_ALIVE_SHORTS = "5m"` en `shorts.py`.

- [ ] **Step 1: Tests**

```python
def test_maximo_shorts():
    assert [shorts.maximo_shorts(d) for d in (179, 180, 599, 1199, 1800, 7860)] == [0, 1, 1, 1, 3, 13]

def test_chat_json_pasa_keep_alive(...):  # mismo patrón de captura que los tests actuales de chat_json
    # sin keep_alive → cuerpo["keep_alive"] == 0 ; con keep_alive="5m" → "5m"

def test_descargar_pide_keep_alive_cero_y_no_lanza(...):
    # captura el POST: ruta "/api/generate", cuerpo {"model": "m", "keep_alive": 0}
    # si _post_json lanza PasoFallido, descargar no lanza
```

- [ ] **Step 2:** Ejecutar y ver que fallan.
- [ ] **Step 3:** Implementar. Actualizar en `test_shorts.py` cualquier otra aserción que dependa del tope antiguo (duración // 180).
- [ ] **Step 4:** `pytest tests/test_shorts.py tests/test_ollama.py -q` en verde.
- [ ] **Step 5:** Commit `feat: one short per 10 minutes and keep the model loaded between calls`.

### Task 2: Paso 1, segmentación en temas

**Files:**
- Modify: `videopipeline/shorts.py`
- Test: `tests/test_shorts.py`

**Interfaces:**
- Consumes: `chat_json(..., temperatura=..., keep_alive=KEEP_ALIVE_SHORTS)` (Task 1).
- Produces:
  - `@dataclass class Tema: frase_inicio: int; frase_fin: int; titulo: str; sigue_al_anterior: bool; inicio: float = 0.0; fin: float = 0.0`. Las frases son globales, de 1 a n, ambas incluidas. Los segundos son los de las frases, sin margen.
  - `MINUTOS_VENTANA = 10`
  - `TEMPERATURA_TEMAS = 0.2`
  - `ESQUEMA_TEMAS = {"temas": [{"frase_inicio": int, "titulo": str, "sigue_al_anterior": bool}]}` como JSON Schema con los tres campos obligatorios.
  - `ventana(frases: list[Frase], desde: int) -> int`: `hasta` exclusivo (índices desde 0) con las frases que acaban como mucho `MINUTOS_VENTANA` minutos después de que empiece `frases[desde]`. Siempre al menos una frase.
  - `construir_mensajes_temas(frases, desde, hasta) -> list[dict]`: el mismo formato de línea que `construir_mensajes` (`[i] 123s-130s: texto`, numeración global). Instrucciones `_SYSTEM_TEMAS`:
    - devolver los temas que **empiezan** en el texto, con su primera frase, un título de 3 a 5 palabras en el idioma de la transcripción y `sigue_al_anterior`;
    - un tema es un asunto que se puede contar entero;
    - `sigue_al_anterior` es verdadero si es otro punto de la misma conversación y falso si cambia de asunto;
    - responder solo JSON.
  - `validar_temas(datos, desde: int, hasta: int) -> list[tuple[int, str, bool]]`:
    - `PasoFallido` (con `detalle`) si `datos` no es un dict con lista `temas`;
    - ignora entradas que no son dict, con `frase_inicio` no entero (usar `_entero`) o fuera de `[desde + 1, hasta]`;
    - el título se limpia como en `validar`; `sigue_al_anterior` que no sea bool cuenta como `False`;
    - devuelve los inicios en orden creciente y sin repetir (gana la primera aparición).
  - `segmentar(frases: list[Frase], modelo: str, on_percent=None) -> list[Tema]`.

`segmentar`. Es un algoritmo que la firma no determina, así que va aquí:

```python
inicios: dict[int, tuple[str, bool]] = {}   # frase global -> (titulo, sigue)
desde = 0
while desde < len(frases):
    hasta = ventana(frases, desde)
    nuevos = <pedir y validar_temas; si PasoFallido, reintentar una vez; el segundo fallo se propaga>
    for ini, titulo, sigue in nuevos:
        inicios[ini] = (titulo, sigue)          # la ventana posterior manda
    on_percent(100 * hasta / len(frases))
    if hasta == len(frases):
        break
    ultimo = max((i for i in inicios if i <= hasta), default=desde + 1)
    # El último tema puede seguir: se vuelve a mirar desde su inicio, salvo que
    # empiece en la primera frase de esta ventana (tema más largo que la ventana).
    desde = ultimo - 1 if ultimo - 1 > desde else hasta
inicios.setdefault(1, ("", False))
# Temas en orden: cada uno acaba en la frase anterior al siguiente inicio o en la
# última frase. El primer tema siempre tiene sigue_al_anterior=False. inicio y fin
# se rellenan desde frases[...].inicio y .fin.
```

Sin frases: `[]` sin llamar al modelo.

- [ ] **Step 1: Tests** (con `_frases_de` y `_chat_falso`):
  - `test_ventana_diez_minutos`: con `_frases_de(120, 10)` (20 min), `ventana(frases, 0) == 60` y `ventana(frases, 119) == 120`.
  - `test_validar_temas_filtra_y_ordena`: entradas fuera de rango, repetidas, desordenadas, `"7"` en texto y `sigue_al_anterior="sí"`. Resultado esperado: crecientes, únicas, sigue `False`.
  - `test_validar_temas_sin_lista_falla`: `PasoFallido`.
  - `test_segmentar_una_ventana`: 30 frases de 10 s, respuesta con inicios 1, 10 y 20. Salen 3 temas `(1-9, 10-19, 20-30)` con `inicio`/`fin` en segundos y el primero con `sigue_al_anterior=False`.
  - `test_segmentar_encadena_desde_el_ultimo_tema`: 120 frases de 10 s, primera respuesta con inicios 1, 30 y 50. La segunda llamada empieza en la frase 50: su primera línea es `[50]`. Las mismas instrucciones van en `llamadas[1]["mensajes"]`.
  - `test_segmentar_tema_mas_largo_que_la_ventana_no_se_atasca`: respuestas sin inicios nuevos (solo el 1, o vacías). Termina, con `len(llamadas) == 2` para 120 frases, y deja un único tema.
  - `test_segmentar_reintenta_una_vez`: la primera respuesta es basura y la segunda vale, así que funciona. Dos respuestas basura → `PasoFallido`.
  - `test_segmentar_temperatura_y_keep_alive`: cada llamada lleva `temperatura=TEMPERATURA_TEMAS` y `keep_alive=KEEP_ALIVE_SHORTS`.
- [ ] **Step 2:** Ver que fallan.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `pytest tests/test_shorts.py -q` en verde.
- [ ] **Step 5:** Commit `feat: split long videos into topics for shorts`.

### Task 3: Paso 2, candidatos de temas y tramos

**Files:**
- Modify: `videopipeline/shorts.py`
- Test: `tests/test_shorts.py`

**Interfaces:**
- Consumes: `Tema` (Task 2) y `validar(datos, frases, duracion)` (existente: calcula el corte con margen y marca `duracion` y `repetido`).
- Produces:
  - `Candidato.origen: str = ""`, un campo nuevo al final de la dataclass.
  - `bloques(temas: list[Tema]) -> list[list[Tema]]`: agrupa temas consecutivos mientras el siguiente tenga `sigue_al_anterior`.
  - `candidatos_de_temas(temas, frases, duracion) -> tuple[list[Candidato], list[Tema]]`. Devuelve `(candidatos, temas_largos)`:
    - **«tema»:** cada tema de 60 a 179 s.
    - **«tramo»:** dentro de cada bloque, desde cada tema `i`, el tramo `i..j` más largo con `j > i` que dure entre 60 y 179 s (`frases[fin].fin - frases[ini].inicio`). Como mucho uno por tema de inicio.
    - **`temas_largos`:** los temas de más de 179 s.
    - **`tema_corto`:** cada tema de menos de 60 s que no queda dentro de ningún tramo sale como `Candidato` con `descarte="tema_corto"`, sin `inicio`/`fin`.
  - Los candidatos «tema» y «tramo» se construyen pasando `{"candidatos": [...]}` por `validar`, para reutilizar el corte y el control de repetidos. Título: el del primer tema. `motivo`: `""`.

- [ ] **Step 1: Tests**:
  - `test_bloques_agrupa_por_sigue`.
  - `test_candidatos_tema_entero_en_rango`: un tema de 120 s da un candidato `origen="tema"` con el corte de `validar`.
  - `test_candidatos_tramo_mas_largo_que_cabe`: un bloque de cinco temas de 40 s da tramos `1-4`, `2-5`, `3-5` y `4-5` (160, 160, 120 y 80 s). El tramo `5..` no existe, porque necesita `j > i`. Ningún tema sale solo, porque 40 < 60. Ninguno es `tema_corto`, porque todos están en algún tramo.
  - `test_candidatos_tramo_no_cruza_bloques`: temas de 40 s con `sigue_al_anterior=False` dan solo `tema_corto` y ningún tramo.
  - `test_candidatos_tema_largo_va_a_fragmentos`: un tema de 400 s sale en `temas_largos`, no como candidato.
  - `test_candidatos_limite_179_y_60_valen`.
- [ ] **Step 2:** Ver que fallan.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** En verde.
- [ ] **Step 5:** Commit `feat: shorts candidates from whole topics and topic runs`.

### Task 4: Paso 2.3, fragmentos de temas largos

**Files:**
- Modify: `videopipeline/shorts.py`
- Test: `tests/test_shorts.py`

**Interfaces:**
- Consumes: `ventana` (Task 2), `validar`, `ESQUEMA_CANDIDATOS` (existente), `KEEP_ALIVE_SHORTS` (Task 1).
- Produces:
  - `MAX_FRAGMENTOS_LLAMADA = 3`
  - `construir_mensajes_fragmentos(frases, desde, hasta, k, cero: float) -> list[dict]`: numeración global y segundos **relativos a `cero`**, el inicio del tema (`[i] 0s-7s: …`). Instrucciones `_SYSTEM_FRAGMENTOS`:
    - hasta `k` fragmentos autocontenidos de 60 a 179 s, que no se solapen;
    - los más largos posibles sin dejar la idea a medias, con gancho al empezar y cierre al acabar;
    - mismos campos que hoy (`frase_inicio`, `frase_fin`, `titulo`, `motivo`);
    - solo JSON.
  - `fragmentos(tema: Tema, frases, duracion, modelo, on_percent=None) -> list[Candidato]`:
    - subventanas del tema con `ventana`, sin pasar de `tema.frase_fin`;
    - en cada subventana, `k = min(MAX_FRAGMENTOS_LLAMADA, max(1, int(dura_sub // 180)))`;
    - una llamada y `validar`;
    - un candidato que se sale del tema → `descarte="fuera_de_rango"`;
    - **una sola corrección** para los que quedan con `descarte="duracion"`: otra llamada con un mensaje de usuario añadido, «El fragmento {ini}-{fin} dura {s} s: ajústalo para que dure entre 60 y 179 s sin dejar la idea a medias», pidiendo `k=1`;
    - si la corrección vale, sustituye al original, que no se guarda; si no, queda el original con su descarte;
    - todos con `origen="fragmento"`.

- [ ] **Step 1: Tests**:
  - `test_fragmentos_segundos_relativos_al_tema`: la primera línea de un tema que empieza a 600 s es `[61] 0s-10s: …`.
  - `test_fragmentos_k_por_subventana`: un tema de 25 min da 3 llamadas, y ninguna pide más de 3. Comprobarlo en el system: `"hasta 3"` o el `k` formateado.
  - `test_fragmentos_fuera_del_tema_se_descarta`.
  - `test_fragmentos_corrige_una_vez`: un candidato de 214 s y una corrección válida dan un único candidato válido. Si la corrección también es inválida, sale el original con `descarte="duracion"` y no hay una tercera llamada.
- [ ] **Step 2:** Ver que fallan.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** En verde.
- [ ] **Step 5:** Commit `feat: best self-contained clips from long topics`.

### Task 5: Paso 4, elegir con reparto

**Files:**
- Modify: `videopipeline/shorts.py` (`elegir`)
- Test: `tests/test_shorts.py` (adaptar los `test_elegir_*` existentes a la firma nueva)

**Interfaces:**
- Produces: `elegir(candidatos: list[Candidato], maximo: int, duracion: float) -> list[Candidato]`, `MINUTOS_TRAMO = 10` y `EMPATE_INTERES = 0.3`.

Algoritmo (los umbrales y los códigos `flojo`, `no_se_entiende_solo`, `solapa` y `sobra` son los de hoy):

```python
pasan = <vivos que superan UMBRAL_INTERES y UMBRAL_INDEPENDIENTE>, ordenados por (-interes, -independiente, inicio)
def colocar(c, elegidos) -> bool:
    choques = [e for e in elegidos if se_solapan(c, e)]      # comparten alguna frase
    if not choques: elegidos.append(c); return True
    e = choques[0]
    if len(choques) == 1 and e.interes - c.interes <= EMPATE_INTERES and dur(c) > dur(e):
        elegidos[elegidos.index(e)] = c; e.descarte = "solapa"; return True   # gana el más largo
    c.descarte = "solapa"; return False
# 1.ª vuelta: el primero de cada tramo int(c.inicio // (MINUTOS_TRAMO*60)) que se pueda colocar
# (un tramo ya cubierto no coloca más en esta vuelta). Si salen más de `maximo`, se quedan los
# `maximo` mejores por el orden de `pasan`; los demás → "sobra".
# 2.ª vuelta: el resto de `pasan` aún sin descarte, en orden, con colocar(), hasta `maximo`; los que no caben → "sobra".
# Devolver los elegidos en el orden de `pasan` (de mejor a peor).
```

- [ ] **Step 1: Tests**:
  - Los `test_elegir_*` existentes, con `duracion` y las mismas expectativas cuando todo cae en un tramo.
  - `test_elegir_reparte_por_tramos`: 4 candidatos buenos en el minuto 2 y 1 flojo pero que pasa en el minuto 35, con `maximo=2`. Salen el mejor del minuto 2 y el del minuto 35.
  - `test_elegir_primera_vuelta_recorta_a_maximo`.
  - `test_elegir_empate_gana_el_mas_largo`: se solapan A (interés 3.0, 70 s) y B (interés 2.8, 170 s), y gana B. Con B en 2.6, gana A.
  - `test_elegir_segunda_vuelta_rellena`: con `maximo=3` y solo dos tramos con candidatos, la segunda vuelta añade el tercero.
- [ ] **Step 2:** Ver que fallan.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** En verde.
- [ ] **Step 5:** Commit `feat: spread shorts across the video and prefer complete clips`.

### Task 6: Integración, registro v2 y solo selección

**Files:**
- Modify: `videopipeline/shorts.py`:
  - `crear`;
  - borrar `partes`, `buscar_candidatos`, `construir_mensajes`, `_SYSTEM_CANDIDATOS`, `MINUTOS_PARTE` y `MINUTOS_SOLAPE` si ya no se usan, junto con sus tests.
- Create: `videopipeline/shorts_prueba.py`, entrada `python -m videopipeline.shorts_prueba`.
- Modify: `README.md`, `README.es.md` (párrafo de **Shorts**), `locale/tsots.pot`, `locale/en/LC_MESSAGES/tsots.po`.
- Test: `tests/test_shorts.py`, `tests/test_shorts_prueba.py`.

**Interfaces:**
- Consumes: todo lo anterior y `puntuar` (sin cambios).
- Produces:
  - `@dataclass class Seleccion: temas: list[Tema]; candidatos: list[Candidato]; elegidos: list[Candidato]; juez: str`.
  - `seleccionar(frases, duracion, modelo, on_aviso, avance_temas=None, avance_momentos=None, avance_notas=None) -> Seleccion`:
    1. `segmentar`;
    2. `candidatos_de_temas`;
    3. `fragmentos` de cada tema largo;
    4. marcar como `repetido` los rangos iguales;
    5. `puntuar`;
    6. `elegir(…, maximo_shorts(duracion), duracion)`.

    Todo dentro de `try/finally` con `descargar(modelo)`.
  - `crear`:
    - paso 1 con la etiqueta «Buscando temas», que pasa a «Buscando los mejores momentos» durante los fragmentos;
    - paso 2, «Puntuando los trozos»;
    - mismo `total` que hoy.
  - `shorts.json`: `"version": 2` y `"temas": [asdict(t) for t in temas]`. Los candidatos llevan `origen` gracias a `asdict`.
  - `listar` y `_anteriores` siguen leyendo un `shorts.json` de versión 1.
  - `shorts_prueba.main(argv) -> int`:
    - argumentos: `ficha_id`, `salida.json` y `--modelo`, que por defecto es `PipelineConfig().modelo_caption`;
    - carga la ficha (`ficha.cargar`) y las palabras de `ficha.ruta("transcripcion.json")`;
    - `duracion` = `duracion_video` de la base, como en `crear`. Si no se puede, el fin de la última palabra;
    - `asegurar_servidor()`, `seleccionar` y escribe en `salida.json` lo mismo que `shorts.json`, más `"segundos"` (lo que tardó la selección);
    - imprime una línea por elegido: minuto de inicio, duración, origen, nota y título;
    - **no escribe nada** en la carpeta de la ficha ni en la de shorts;
    - error claro y código 1 si la ficha no existe o no está transcrita.

- [ ] **Step 1: Tests**:
  - `test_seleccionar_flujo_completo` con `chat_json` y `systemone` falsos: temas, candidatos de los tres orígenes, notas, elegidos repartidos y `descargar` llamado (sustituir `shorts.descargar`).
  - `test_seleccionar_descarga_aunque_falle`: la segmentación falla dos veces → `PasoFallido` y `descargar` llamado.
  - `test_seleccionar_todos_cortos_sin_candidatos`: `elegidos == []`.
  - Adaptar el test actual de `crear` que escribe `shorts.json`: `version == 2`, `temas` presente y `origen` en los candidatos.
  - `test_listar_lee_shorts_json_v1`.
  - `test_shorts_prueba_no_escribe_en_la_ficha`: ficha falsa en `tmp_path`. El JSON de salida existe y la carpeta de la ficha no cambia (comparar listados antes y después).
  - `test_shorts_prueba_ficha_inexistente_devuelve_1`.
- [ ] **Step 2:** Ver que fallan.
- [ ] **Step 3:** Implementar.
  - README: «uno cada 10 minutos como mucho, temas completos de todo el vídeo», y la orden de prueba `python -m videopipeline.shorts_prueba <ficha> <salida.json>`.
  - Traducciones: `lanzador/traducir.sh` y rellenar los `msgstr` nuevos.
- [ ] **Step 4:** Suite completa en verde.
- [ ] **Step 5:** Commit `feat: topic-based shorts selection with a selection-only dry run`.

### Task 7: Prueba real (controlador, sin publicar ni cortar)

- [ ] **Step 1:** Ejecutar en el worktree, en segundo plano porque tarda minutos:
  `~/Documents/personalProjects/limpiadorVideo/.venv-clearvoice/bin/python -m videopipeline.shorts_prueba c77cb35e0467 <scratchpad>/ep20_temas.json`
- [ ] **Step 2:** Medir el tiempo de la selección actual sin cortar. Script en el scratchpad que importe `shorts` del checkout de `develop` (`PYTHONPATH=~/Documents/personalProjects/limpiadorVideo`, que está en la v1.12.0 con el algoritmo antiguo) y ejecute `buscar_candidatos` + `puntuar` + `elegir` sobre las mismas frases.
- [ ] **Step 3:** Comparar con el `shorts.json` actual del Episodio 20 (16 shorts, 5 entre los minutos 84 y 93). Criterios:
  - elegidos repartidos, como mucho 13;
  - mayoría por encima de 120 s;
  - sin descarte masivo por duración;
  - tiempo de selección como mucho el doble.

  Anotar las cifras para el PR.
