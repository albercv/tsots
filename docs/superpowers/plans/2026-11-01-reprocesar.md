# Reprocesar un vídeo sin perder trabajo — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** que cada vídeo tenga una ficha que recuerde lo hecho. Así se
pueden relanzar pasos sobre el vídeo ya editado, con avisos, sin perder
caption ni transcripción, sin rehacer lo que ya vale y sin multiplicar
versiones.

**Arquitectura:**
- Tres módulos nuevos en `videopipeline/`:
  - `ficha.py`: datos y disco;
  - `reproceso_plan.py`: lógica pura de qué rehacer;
  - `reproceso.py`: ejecuta el plan con las funciones de `steps.py` y de
    `pipeline.py`.
- `pipeline.run` queda como está, para la CLI.
- La app pasa siempre por la ficha: el worker envía al runner el JSON de
  siempre más una clave `reproceso`, y el runner vuelve a planificar y
  ejecuta.
- En la GUI: la cola muestra los pasos hechos, un diálogo pregunta antes de
  procesar y hay dos acciones nuevas, «Volver a procesar» y «Olvidar este
  vídeo».

**Tecnologías:** Python 3.11, PySide6, ffmpeg y auto-editor (los de hoy),
pytest con pytest-qt.

**Spec:** `docs/superpowers/specs/2026-11-01-reprocesar-design.md`. Sus reglas
R0–R10 y la tabla de casos mandan sobre este plan.

## Restricciones globales

- **Idioma:** código, comentarios e interfaz en español. Commits en inglés,
  sin atribución a IA. Nunca se hace push a `develop` ni a `main`; la PR va
  contra `develop`.
- **Python de pruebas:** `PY=~/Documents/personalProjects/limpiadorVideo/.venv-clearvoice/bin/python`.
  - En la worktree no hay venv: se usa el de producción solo para
    ejecutar.
  - Para los tests lentos, enlazar temporalmente `checkpoints` y
    `clearvoice/models/av_mossformer2_tse/faceDetector/s3fd/sfd_face.pth`
    desde producción, y quitar después solo esos enlaces.
- **Batería:** `QT_QPA_PLATFORM=offscreen $PY -m pytest -q`. Tiene que estar
  verde antes de cada commit.
- **Textos nuevos:** se marcan con `_()`. Se traducen en la tarea 8 con
  `lanzador/traducir.sh` y `locale/en/LC_MESSAGES/tsots.po`.
- **Fichas:** viven en `BASE_DIR / "fichas" / <id>/`.
  - El `<id>` es `uuid4().hex[:12]`.
  - `ficha.json` se escribe de forma atómica: temporal y `replace`.
- **Escritura de salidas:** siempre a un temporal oculto
  (`.{stem}_tmp{suffix}`) y `replace` al final, como hoy.
  - Los movimientos entre carpetas usan `shutil.move`, porque la carpeta de
    salida puede estar en otro disco.
- **Compatibilidad:**
  - El JSON del runner sin la clave `reproceso` sigue ejecutando
    `pipeline.run`.
  - Los ajustes guardados no cambian.
  - La CLI no usa fichas.
- **Degradación:** la de hoy no cambia. Si falla el caption o el vertical
  queda un aviso, el vídeo no falla, y un fallo de subtítulos con otros
  pasos guarda el vídeo sin ellos.

## Review Focus

1. **La carpeta de salida está en otro disco que `fichas/`.** Mover el final
   a la ficha como base (R3) no debe fallar: se copia y se borra. Test en la
   tarea 3.
2. **La pasada se cancela o falla a mitad.** Las salidas anteriores quedan
   intactas, la ficha solo registra los artefactos terminados y la carpeta
   `tmp` se borra. Tests en la tarea 3; la cancelación desde la GUI, en la
   tarea 6.
3. **El usuario edita o mueve fuera de la app el original o una salida.** Ni
   la huella ni el nombre engañan a la app: se avisa, y nunca se sobrescribe
   un archivo ajeno. Test en la tarea 1.
4. **Dos originales distintos con el mismo nombre** (`x.mov` en dos
   carpetas) **y la misma carpeta de salida:** no deben pisarse sus salidas.
   Test en la tarea 1.
5. **Un `ficha.json` dañado o a medio escribir:** se ignora con un aviso y no
   rompe la cola. Test en la tarea 1.

---

## Mapa de archivos

| Archivo | Qué |
|---|---|
| `videopipeline/ficha.py` (nuevo) | `Huella`, `Artefacto`, `Ficha`, cargar y guardar, reconocer un archivo, olvidar, `ocupa`, rutas de salida, temporales |
| `videopipeline/reproceso_plan.py` (nuevo) | Claves, `Consulta`, `Decisiones`, `Plan`, `revisar()`, `planificar()`. Sin E/S, salvo comprobar si existen archivos |
| `videopipeline/reproceso.py` (nuevo) | `ejecutar(ficha, plan, on_progress) -> Path` |
| `videopipeline/subtitles.py` | `leer_srt()`, para importar `.srt` de vídeos antiguos |
| `videopipeline/steps.py` | `a_flac()` |
| `videopipeline/pipeline.py` | `_fase_vertical` acepta un seguimiento ya calculado |
| `videopipeline/config.py` | `validar(exigir_paso_de_video=True)` y `from_datos()` |
| `videopipeline/runner.py` | Clave `reproceso` en el JSON |
| `app/queue_model.py` | `Trabajo.ficha_id`, `resumen`, `ocupa`; volver a poner en espera en vez de duplicar |
| `app/widgets/dialogo_reproceso.py` (nuevo) | El aviso de Procesar |
| `app/widgets/panel_opciones.py` | `hay_pasos()`, que incluye el caption |
| `app/main.py` | Reconocer al añadir, «Volver a procesar», «Olvidar este vídeo», Procesar con consultas, caption y Publicar desde la ficha |
| `desinstalar.command`, `README*.md`, `docs/DEVELOPMENT.md`, `locale/` | Tarea 8 |

---

### Tarea 1: la ficha (`videopipeline/ficha.py`)

**Archivos:**
- Crear: `videopipeline/ficha.py`, `tests/test_ficha.py`
- Modificar: `videopipeline/subtitles.py`, para añadir `leer_srt`

**Interfaces que produce:**

```python
DIR_FICHAS: Path                      # BASE_DIR / "fichas"; los tests lo monkeypatchean
SUFIJOS_SALIDA = ("_limpio", "_vertical")
# Claves de artefacto:
AUDIO, BASE, TRANSCRIPCION, HORIZONTAL, CAPTION, SEGUIMIENTO, VERTICAL = (
    "audio", "base", "transcripcion", "horizontal", "caption", "seguimiento", "vertical")

@dataclass(frozen=True)
class Huella:
    ruta: Path; tamano: int; mtime_ns: int
    @classmethod
    def de(cls, ruta: Path) -> "Huella"          # ruta.resolve() + stat
    def coincide(self, ruta: Path) -> bool       # misma ruta resuelta, tamaño y mtime_ns

@dataclass
class Artefacto:
    clave: str
    archivo: str | None = None   # nombre dentro de la carpeta de la ficha; None = vive fuera
    ajustes: dict = field(default_factory=dict)   # con qué se hizo (R6, R8)
    linea_tiempo: str = ""       # para AUDIO, BASE y TRANSCRIPCION

@dataclass
class Ficha:
    id: str
    nombre: str
    carpeta_salida: Path
    original: Huella | None = None
    final: Huella | None = None       # horizontal o, sin horizontal, el vertical único
    vertical: Huella | None = None    # vertical que acompaña al horizontal
    legado: bool = False
    subs_quemados_sin_base: bool = False
    desactualizado: set[str] = field(default_factory=set)   # {"vertical"}
    artefactos: dict[str, Artefacto] = field(default_factory=dict)
    @property
    def carpeta(self) -> Path                     # DIR_FICHAS / id
    def ruta(self, archivo: str) -> Path          # carpeta / archivo
    def pasos_hechos(self) -> list[str]           # subconjunto ordenado de PASOS
    def hay_horizontal(self) -> bool             # hay HORIZONTAL, o es legado cuyo final no acaba en _vertical
    def ruta_final(self, horizontal: bool) -> Path   # final.ruta si existe y es de ese tipo; si no, <carpeta_salida>/<nombre>_limpio.mp4 o _vertical.mp4
    def ruta_vertical(self) -> Path               # <carpeta_salida>/<nombre>_limpio_vertical.mp4

PASOS = ("audio", "silencios", "subtitulos", "caption", "vertical")

def guardar(ficha: Ficha) -> None
def cargar(id: str) -> Ficha | None               # None si falta o está dañado
def todas() -> list[Ficha]                        # ignora las dañadas
def reconocer(ruta: Path, carpeta_salida: Path | None) -> tuple[Ficha, str]  # (ficha, aviso o "")
def olvidar(ficha: Ficha) -> None                 # rmtree(carpeta); no toca salidas
def ocupa(ficha: Ficha) -> int                    # bytes de la carpeta
def limpiar_temporales(ficha: Ficha) -> None      # carpeta/"tmp" y los .{stem}_tmp / _subs_tmp de sus salidas
# en subtitles.py:
def leer_srt(ruta: Path) -> list[Palabra]         # [] si no se puede leer
```

**Cómo se derivan los pasos hechos** (`pasos_hechos`):

| Paso | Hecho si… |
|---|---|
| audio | `BASE.ajustes["audio"]` existe |
| silencios | `BASE.ajustes["silencios"]` existe |
| subtitulos | `HORIZONTAL.ajustes["subtitulos"]` existe, o la ficha tiene `VERTICAL` con `ajustes["subtitulos"]` y no tiene horizontal |
| caption | hay `CAPTION` |
| vertical | hay `VERTICAL` |

**Reglas de `reconocer`** (spec, «Casos» y «Ficha y almacenamiento»):

1. **La ruta coincide con la huella** del original, del final o del vertical
   de una ficha: se devuelve esa ficha y aviso `""`.
2. **La ruta coincide pero la huella no** (se editó fuera de la app):
   - se olvida la ficha vieja y se crea otra con las reglas 3 y 4;
   - el aviso dice «"x" ha cambiado fuera de la app: se empieza una ficha
     nueva».
   - *Ruling* (la spec pide una ficha nueva, pero no dice qué pasa con la
     vieja): así nunca hay dos fichas con las mismas salidas.
3. **Nombre con sufijo de salida** (`stem` que acaba en `_limpio` o
   `_vertical`) **sin ficha:**
   - es una ficha de legado: `nombre` = stem sin un sufijo final, `final` =
     la huella del propio archivo y `legado=True`;
   - `.md` con su nombre al lado: se guarda como `caption.md` y entra como
     `CAPTION` (clave `"importado"`);
   - `.srt` al lado: `leer_srt` lo convierte en `transcripcion.json`
     (`TRANSCRIPCION`, `linea_tiempo="legado"`) y `subs_quemados_sin_base=True`.
4. **Nombre normal sin ficha:** ficha nueva con ese original.
   - `carpeta_salida`: la que se pasa, o la carpeta del original si es
     `None`.
   - **Si la salida que le tocaría** (`<carpeta>/<nombre>_limpio.mp4`) **es el
     final de una ficha de legado sin original:** se adopta en esa ficha
     (`original` = huella, `legado=False`) en vez de crear otra.
   - **Si esa salida es de otra ficha con original:** se renombra a
     `"<nombre> (2)"`, `(3)`… hasta que no choque (Review Focus 4).

**Pasos:**

- [ ] **Paso 1: tests que fallen** en `tests/test_ficha.py`, con `DIR_FICHAS`
  monkeypatcheado a `tmp_path / "fichas"`:
  - `test_guardar_y_cargar_ida_y_vuelta`: los campos y artefactos son iguales
    tras `guardar` + `cargar`.
  - `test_cargar_ficha_danada_devuelve_none` y
    `test_todas_ignora_las_danadas`: un `ficha.json` con `"{"`.
  - `test_reconocer_original_nuevo_crea_ficha`: `nombre == "charla"` y
    `carpeta_salida` es la pasada. Con `None`, la carpeta del vídeo.
  - `test_reconocer_mismo_original_devuelve_la_misma_ficha`: segunda llamada,
    mismo `id`.
  - `test_reconocer_una_salida_devuelve_su_ficha`: con `ficha.final` guardado
    para `charla_limpio.mp4`.
  - `test_archivo_editado_fuera_crea_ficha_nueva_y_avisa`: misma ruta, otro
    tamaño. `id` distinto, aviso no vacío, la carpeta vieja ya no existe.
  - `test_legado_limpio_limpio_es_su_propio_final`: `x_limpio_limpio.mp4`.
    `nombre == "x_limpio"`, `final.ruta` es el archivo, `legado`.
  - `test_legado_importa_md_y_srt`: con `x_limpio.md` (`escribir_md`) y
    `x_limpio.srt`. Hay `CAPTION` y `TRANSCRIPCION` y
    `subs_quemados_sin_base is True`.
  - `test_original_adopta_ficha_de_legado`: primero `salida/x_limpio.mp4`,
    después `orig/x.mov` con `carpeta_salida=salida`. Mismo `id`, `original`
    puesto, `legado is False`.
  - `test_mismo_nombre_otra_carpeta_no_pisa_salidas`: `a/x.mov` y `b/x.mov`
    con la misma salida. El segundo se llama `"x (2)"` y
    `ruta_final(True).name == "x (2)_limpio.mp4"`.
  - `test_pasos_hechos_segun_artefactos`: parametrizado con la tabla de
    arriba.
  - `test_olvidar_borra_la_carpeta_y_no_las_salidas`.
  - `test_cambiar_carpeta_no_mueve_fichas_existentes`: reconocer de nuevo
    con otra `carpeta_salida` conserva la de la ficha (rutas fijas).
  - `test_leer_srt_reparte_palabras_en_el_bloque`: un bloque de 0 a 1 s con
    «hola mundo» da 2 `Palabra`, la segunda empieza en 0.5.
- [ ] **Paso 2:** `QT_QPA_PLATFORM=offscreen $PY -m pytest -q tests/test_ficha.py`.
  Esperado: FAIL con `ModuleNotFoundError: videopipeline.ficha`.
- [ ] **Paso 3: implementar** `ficha.py` y `leer_srt`.
  - JSON: `Path` y `set` se serializan como `str` y `list`.
  - Fechas con `st_mtime_ns`.
- [ ] **Paso 4:** la misma orden. Esperado: PASS. Después, la batería completa
  en verde.
- [ ] **Paso 5: commit** `feat: add per-video record that remembers what was done`.

---

### Tarea 2: el planificador (`videopipeline/reproceso_plan.py`)

**Archivos:**
- Crear: `videopipeline/reproceso_plan.py`, `tests/test_reproceso_plan.py`
- Modificar: `videopipeline/config.py`, para añadir
  `validar(self, exigir_paso_de_video: bool = True)` y
  `from_datos(cls, datos: dict)`. `from_json` pasa a usar `from_datos`.

**Usa:** de la tarea 1, `Ficha`, `Artefacto`, las constantes de artefacto y
`PASOS`.

**Interfaces que produce:**

```python
def clave(*partes) -> str          # sha256 de json.dumps(partes, sort_keys=True, default=str)[:16]
def ajustes_audio(c: PipelineConfig) -> dict       # {"tarea", "modelo"}
def ajustes_silencios(c) -> dict                    # {"margen", "umbral", "silencios", "velocidad"}
def ajustes_subtitulos(c) -> dict                   # {"diseno", "posicion", "tamano", "idioma", "modelo_whisper"}
def ajustes_transcripcion(c) -> dict                # {"idioma", "modelo_whisper", "glosario": clave(c.glosario)}
def ajustes_vertical(c) -> dict                     # {"encuadre"}
def ajustes_caption(c) -> dict                      # {"modelo_caption"}

class Accion(str, Enum):
    LIMPIAR_AUDIO_ORIGINAL = "limpiar_audio_original"   # audio del original entero → AUDIO(linea "original")
    LIMPIAR_AUDIO_BASE = "limpiar_audio_base"           # audio de la base recortada → AUDIO(linea de la base)
    PONER_AUDIO = "poner_audio"                         # remux sin recodificar → BASE
    CORTAR = "cortar"                                   # auto-editor → BASE
    TRANSCRIBIR = "transcribir"                         # → TRANSCRIPCION(linea de la base nueva)
    QUEMAR = "quemar"                                   # base + subs → final (guarda la base aparte, R3)
    ESCRIBIR_FINAL = "escribir_final"                   # base sin subs → final
    CAPTION = "caption"
    SEGUIMIENTO = "seguimiento"
    VERTICAL = "vertical"
    RENOMBRAR_VERTICAL = "renombrar_vertical"           # R10 sin recodificar
    RETIRAR_VERTICAL_UNICO = "retirar_vertical_unico"   # R10 tras regenerar

@dataclass(frozen=True)
class Consulta:
    paso: str          # uno de PASOS
    tipo: str          # "hecho" | "otros_ajustes" | "cambia_base" | "bloqueado"
    texto: str         # traducido, listo para el diálogo
    cambios: tuple[str, ...] = ()

@dataclass(frozen=True)
class Decisiones:
    rehacer: frozenset[str] = frozenset()
    regenerar_vertical: bool = False

@dataclass
class Plan:
    acciones: list[Accion]
    config: PipelineConfig     # efectiva: ajustes del panel para lo pedido; R8 para lo implícito
    avisos: list[str]          # bloqueos aplicados (legado)
    error: str = ""            # no se puede ejecutar (falta el original, caption sin vídeo)
    marcar_desactualizado: bool = False
    @property
    def vacio(self) -> bool    # sin acciones y sin error

def revisar(ficha: Ficha, config: PipelineConfig) -> list[Consulta]
def planificar(ficha: Ficha, config: PipelineConfig, decisiones: Decisiones) -> Plan
```

**Algoritmo de `planificar`**. Las reglas de la spec no lo determinan del
todo, así que se fija aquí. `F` es la ficha, `P` la petición y `D` las
decisiones.

1. **Estado objetivo.** Para cada paso `p` de base (audio, silencios) y
   también para subtítulos:
   - `objetivo[p]` = ajustes del panel si `P` marca `p` y (`F` no lo tiene
     o `p ∈ D.rehacer`);
   - si no, = lo de `F` (R1).
   - Subtítulos bloqueados por legado (`F.subs_quemados_sin_base`): no
     cambian y se añade un aviso.
2. **¿Cambia la base?** Sí si `objetivo` difiere de `F` en audio o silencios,
   o si audio o silencios están en `D.rehacer` y marcados. Si cambia:
   1. **Sin recorte en el objetivo:**
      - con audio: `LIMPIAR_AUDIO_ORIGINAL`, salvo que valga un `AUDIO` con
        `linea_tiempo == "original"` y la misma clave; luego `PONER_AUDIO`;
      - sin audio: base = original (no hay acción, pero tiene que existir el
        original).
   2. **Recorte sin cambiar, añadiendo audio** (caso 8): `LIMPIAR_AUDIO_BASE`
      y `PONER_AUDIO`. La línea de tiempo no cambia.
   3. **En otro caso:** si el objetivo lleva audio y no hay un `AUDIO` válido
      con línea `"original"` (R9), `LIMPIAR_AUDIO_ORIGINAL`; luego `CORTAR`.
   - **Lo que necesita el original** (`LIMPIAR_AUDIO_ORIGINAL`, `PONER_AUDIO`
     sobre el original, `CORTAR`) **y no existe** (`not F.original.coincide`):
     `error` = «No encuentro el original de "x": {ruta}».
   - **Legado:** el «original» es el propio final. *Ruling:* el ejecutor lo
     mueve a la ficha como `original<ext>` antes de sobrescribirlo, para
     poder rehacer después.
3. **Línea de tiempo nueva:**
   - `"original"` sin recorte;
   - `clave(objetivo audio si recortó sobre audio limpio, objetivo silencios)`
     con recorte;
   - igual que antes en el caso 8.
4. **Transcripción.** `TRANSCRIBIR` si hacen falta subtítulos (en el
   horizontal o en el vertical que se va a generar) y no hay
   `TRANSCRIPCION` con la línea nueva y la clave de `ajustes_transcripcion`,
   o si `"subtitulos" ∈ D.rehacer`.
   - *Ruling* R8: lo implícito usa `idioma` y `modelo_whisper` de la ficha y
     el glosario actual.
   - Un cambio de glosario no invalida una transcripción por sí solo (R6 lo
     pregunta).
5. **Horizontal:**
   - `QUEMAR` si `objetivo[subtitulos]` y (cambió la base, se transcribió o
     cambian los ajustes de subtítulos);
   - `ESCRIBIR_FINAL` si cambió la base y no hay subtítulos.
6. **Caption:** `CAPTION` si `P.caption_seo` y (no hay `CAPTION` o
   `"caption" ∈ D.rehacer`). Antes va `TRANSCRIBIR` si no existe ninguna
   transcripción y no hay ya otra planificada (R5).
   - Si no hay final ni se va a crear: `error` = «"x" aún no tiene vídeo
     procesado: el caption solo se puede pedir sobre un vídeo ya
     procesado».
7. **Vertical:**
   - **Se genera** (`VERTICAL`) si `P.paso_vertical` y (no hay vertical o
     `"vertical" ∈ D.rehacer`), o si hay vertical, quedaría desactualizado
     (cambió la base o la transcripción, o los ajustes de subtítulos que
     usa) y `D.regenerar_vertical`.
   - **Si quedaría desactualizado y no se regenera:**
     `marcar_desactualizado = True`.
   - `SEGUIMIENTO` antes de `VERTICAL` si el encuadre es `"cara"` y no hay
     `SEGUIMIENTO` con la clave de la base nueva.
8. **R10.** La ficha solo tenía vertical único y el plan crea un
   horizontal:
   - si el vertical no queda desactualizado: `RENOMBRAR_VERTICAL`;
   - si sí: `VERTICAL` y `RETIRAR_VERTICAL_UNICO`, sin preguntar, porque el
     vertical viejo deja de existir.
9. **Orden:** audio y corte → `TRANSCRIBIR` → `QUEMAR` o `ESCRIBIR_FINAL` →
   `CAPTION` → `SEGUIMIENTO` → `VERTICAL` → `RENOMBRAR_VERTICAL` o
   `RETIRAR_VERTICAL_UNICO`.

**`revisar`**. Por cada paso que `P` marca:
- **Ya hecho con los mismos ajustes:** `tipo="hecho"`, con el texto «"x" ya
  tiene {paso}. ¿Rehacerlo?» y, si es un paso de base y la ficha tiene
  subtítulos o vertical, «Rehacerlo volverá a transcribir y quemar los
  subtítulos; el caption se mantiene».
- **Ya hecho con otros ajustes:** `tipo="otros_ajustes"` y `cambios` del tipo
  `"diseno: reels_bold → caja"`.
- **De base, aún no hecho, en una ficha con subtítulos o vertical:**
  `tipo="cambia_base"`, solo informativo, con el texto de la spec.
- **Legado bloqueado:** `tipo="bloqueado"` para subtitulos, y para vertical
  si `P.subtitulos`.

**Pasos:**

- [ ] **Paso 1: tests que fallen.** `tests/test_reproceso_plan.py` construye
  fichas en memoria (sin disco: el original apunta a un archivo de
  `tmp_path` que existe). Incluye:
  - un test parametrizado `test_casos_de_la_spec` con una fila por caso de la
    tabla de la spec, que compara `plan.acciones` con la lista esperada:

    | Caso | Acciones esperadas |
    |---|---|
    | Añadir caption, con transcripción de otra línea de tiempo (R5) | `[CAPTION]` |
    | Añadir caption, sin transcripción | `[TRANSCRIBIR, CAPTION]` |
    | Rehacer el caption | `[CAPTION]` |
    | Añadir subtítulos | `[TRANSCRIBIR, QUEMAR]` |
    | Cambiar el estilo (`rehacer={"subtitulos"}` solo con diseño distinto y misma transcripción) | `[QUEMAR]` |
    | Rehacer los subtítulos | `[TRANSCRIBIR, QUEMAR]` |
    | Añadir silencios a audio + subtítulos | `[CORTAR, TRANSCRIBIR, QUEMAR]`, sin `LIMPIAR_*` |
    | Rehacer silencios con audio limpiado sobre la base (R9) | `[LIMPIAR_AUDIO_ORIGINAL, CORTAR, TRANSCRIBIR, QUEMAR]` |
    | Añadir audio a un vídeo ya recortado con subtítulos | `[LIMPIAR_AUDIO_BASE, PONER_AUDIO, QUEMAR]` |
    | Rehacer audio con recorte | `[LIMPIAR_AUDIO_ORIGINAL, CORTAR, TRANSCRIBIR, QUEMAR]` |
    | Añadir vertical central | `[VERTICAL]` |
    | Cambiar encuadre a cara (rehacer) | `[SEGUIMIENTO, VERTICAL]` |
    | Pasos ya hechos, mismos ajustes, sin rehacer | `[]` (`plan.vacio`) |

  - `test_cambiar_estilo_no_retranscribe` (cubierta por la tabla, pero con
    nombre propio).
  - `test_caption_se_mantiene_al_recortar`: no hay `CAPTION` en las acciones.
  - `test_vertical_desactualizado_sin_regenerar_se_marca` y
    `test_vertical_desactualizado_se_regenera_si_se_pide`.
  - `test_vertical_unico_gana_horizontal_se_renombra` (R10 sin recodificar)
    y `test_vertical_unico_desactualizado_se_regenera_y_retira`.
  - `test_falta_original_da_error` y `test_caption_sin_final_da_error`.
  - `test_legado_con_subs_bloquea_subtitulos`: `Consulta(tipo="bloqueado")`,
    plan sin `QUEMAR` y con aviso.
  - `test_legado_permite_recortar`: `CORTAR` con el final como fuente.
  - `test_revisar_hecho_y_otros_ajustes`: un `cambios` contiene
    `"diseno: reels_bold → caja"`.
  - `test_implicito_usa_ajustes_de_la_ficha` (R8): recortar en una ficha con
    `diseno="caja"` con el panel en `reels_bold` da `plan.config.diseno ==
    "caja"` y `plan.config.glosario` igual al del panel.
  - `test_artefacto_sin_archivo_se_rehace`: con `AUDIO` registrado pero sin
    `audio_limpio.flac`, añadir silencios planifica `LIMPIAR_AUDIO_ORIGINAL`.
  - `test_validar_permite_solo_caption` en `tests/test_config.py`.
- [ ] **Paso 2:** `$PY -m pytest -q tests/test_reproceso_plan.py tests/test_config.py`.
  Esperado: FAIL, porque el módulo no existe.
- [ ] **Paso 3: implementar** con el algoritmo de arriba.
- [ ] **Paso 4:** la misma orden. Esperado: PASS. Después, la batería
  completa.
- [ ] **Paso 5: commit** `feat: plan which steps to redo from what a video already has`.

---

### Tarea 3: el ejecutor (`videopipeline/reproceso.py`)

**Archivos:**
- Crear: `videopipeline/reproceso.py`, `tests/test_reproceso.py`
- Modificar:
  - `videopipeline/steps.py`: añadir
    `a_flac(wav: Path, flac: Path) -> None` (`ffmpeg -c:a flac`) y su
    `cmd_a_flac`;
  - `videopipeline/pipeline.py`: `_fase_vertical` acepta
    `seguimiento: tuple[int | None, Path] | None = None`. Si se pasa, no
    llama a `preparar_seguimiento`. `pipeline.run` no cambia.

**Usa:** de la tarea 1, `Ficha`, `guardar`, `limpiar_temporales` y
`Huella.de`; de la tarea 2, `Plan`, `Accion` y las funciones de ajustes y
`clave`.

**Interfaz que produce:**

```python
def ejecutar(ficha: Ficha, plan: Plan, on_progress: Progreso | None = None) -> Path
# Devuelve la salida principal (ficha.final.ruta). Lanza PasoFallido si falla
# un paso no degradable. Emite {"step", "total", "label", "percent"}: un paso
# por acción.
```

**Qué hace cada acción.** Trabajo en `ficha.carpeta / "tmp"`, que se vacía al
empezar y se borra en `finally`.

| Acción | Qué hace |
|---|---|
| `LIMPIAR_AUDIO_*` | `extraer_audio` → `limpiar_audio` → `a_flac` a `audio_limpio.flac` |
| `PONER_AUDIO` | `remux(fuente, flac, tmp/base.mp4)` |
| `CORTAR` | Entrada: `remux(original, flac, intermedio=True)` si hay audio, o `rellenar_huecos_audio(original)` si no. Luego `cortar_silencios` a `tmp/base.mp4`, con los ajustes de `plan.config` |
| `TRANSCRIBIR` | Sobre la base actual, como `pipeline._transcribir_subs` (incluido `wav_continuo` cuando la base es el original) → `transcripcion.json` |
| `QUEMAR` | `generar_ass` + `quemar_subtitulos` sobre la base, a `.{stem}_subs_tmp`, y `replace` al final. Escribe el `.srt` junto al final (`agrupar` + `generar_srt`). R3: guarda la base aparte |
| `ESCRIBIR_FINAL` | `shutil.move` de la base al final, por un temporal |
| `CAPTION` | Palabras de `transcripcion.json` → `generar_caption` → `caption.md` en la ficha y `.md` junto al final. Degradación como `pipeline._fase_caption` |
| `SEGUIMIENTO` | `preparar_seguimiento(base, …, ficha.ruta("cara.cmd"))`. Guarda `x_inicial` en `ajustes` |
| `VERTICAL` | `pipeline._fase_vertical(..., seguimiento=(x, cara.cmd))` al destino que toque |
| `RENOMBRAR_VERTICAL` / `RETIRAR_VERTICAL_UNICO` | R10. Mueve el `.md` y el `.srt` junto al nuevo final y solo borra rutas cuya huella está en la ficha |

**Al terminar cada acción:**
- se registra su `Artefacto` (clave, archivo, ajustes, linea) y las huellas
  nuevas de `final` y `vertical`;
- se hace `guardar(ficha)`.

**Si `plan.marcar_desactualizado`:** se añade `"vertical"` a
`ficha.desactualizado`. Al regenerar el vertical, se quita.

**R3 en `QUEMAR`:**
- si el final actual no tenía subtítulos y no hay un `BASE.archivo`, se
  mueve con `shutil.move` a `ficha.ruta("base.mp4")` antes de sustituirlo;
- con `ESCRIBIR_FINAL`, `BASE.archivo = None`, porque el final es la base.

**Legado (*ruling* de la tarea 2):** antes de la primera acción que
sobrescriba el final de una ficha de legado, ese archivo se mueve a
`ficha.ruta("original" + suffix)` y pasa a ser su `original`.

**Pasos:**

- [ ] **Paso 1: tests que fallen** en `tests/test_reproceso.py`. Reutilizan
  los falsos de `tests/test_pipeline.py` (`entorno`, `entorno_subs`,
  `entorno_caption`) moviéndolos a `tests/falsos_pipeline.py`, importado
  desde los dos archivos. Además, monkeypatchean `reproceso.a_flac` y
  `ficha.DIR_FICHAS`. Incluye:
  - `test_anadir_caption_no_codifica_video`: las llamadas no contienen
    `quemar`, `cortar` ni `remux`; el final no cambia de bytes; existen
    `caption.md` y el `.md` junto al final.
  - `test_anadir_silencios_reutiliza_audio_limpio`: no hay `limpiar:` en las
    llamadas; sí `cortar:`, `transcribir:` y `quemar`.
  - `test_rehacer_subtitulos_mantiene_caption`: `caption.md` igual byte a
    byte.
  - `test_quemar_guarda_la_base_aparte`: tras `QUEMAR` sobre un final sin
    subtítulos, existe `base.mp4` en la ficha con los bytes del final
    anterior.
  - `test_sin_subtitulos_no_duplica_base`: tras `ESCRIBIR_FINAL`,
    `BASE.archivo is None` y no hay `base.mp4`.
  - `test_fallo_a_mitad_conserva_salidas_y_ficha` (Review Focus 2):
    `quemar_subtitulos` revienta sin degradar (solo subtítulos). El final
    tiene los bytes de antes, `TRANSCRIPCION` está registrada, `HORIZONTAL`
    no ha cambiado y no existe `tmp/`.
  - `test_mover_entre_discos` (Review Focus 1): `os.rename` monkeypatcheado
    para lanzar `OSError(errno.EXDEV, …)`; la base acaba en la ficha y el
    final se sustituye.
  - `test_legado_mueve_el_archivo_a_la_ficha_antes_de_sobrescribir`.
  - `test_r10_renombra_vertical_y_mueve_md_srt`.
  - `test_vertical_con_seguimiento_guardado_no_detecta_otra_vez`:
    `preparar_seguimiento` no se llama si hay `SEGUIMIENTO` válido.
  - `test_desactualizado_se_marca_y_se_limpia_al_regenerar`.
  - `test_reprocesar_sin_caption_conserva_md` (R1): recortar sin marcar
    Caption deja el `.md` y `caption.md` intactos.
  - `test_cambiar_estilo_quema_sobre_la_base` (R2): el segundo `QUEMAR`
    recibe `base.mp4` como fuente, nunca el final con subtítulos.
  - En `tests/test_pipeline.py`, los tests de vertical existentes siguen
    verdes con el `seguimiento` opcional.
- [ ] **Paso 2:** `$PY -m pytest -q tests/test_reproceso.py tests/test_pipeline.py`.
  Esperado: FAIL, porque el módulo no existe.
- [ ] **Paso 3: implementar.**
- [ ] **Paso 4:** la misma orden. Esperado: PASS. Después, la batería
  completa.
- [ ] **Paso 5: commit** `feat: run a reprocessing plan reusing what the record keeps`.

---

### Tarea 4: el runner con clave `reproceso`

**Archivos:** modificar `videopipeline/runner.py` y `tests/test_runner.py`.

**Usa:** `PipelineConfig.from_datos` y `ficha.cargar`, y
`reproceso_plan.planificar` con `Decisiones`, y `reproceso.ejecutar`.

**Protocolo:**
- El JSON puede llevar, además de los campos de `PipelineConfig`,
  `"reproceso": {"ficha": "<id>", "rehacer": [...], "regenerar_vertical": bool}`.
- **Con esa clave:** `cargar` → `planificar` → `ejecutar`, y se valida con
  `config.validar(exigir_paso_de_video=False)`.
  - Si la ficha no existe o el plan tiene `error`, se falla con
    `PasoFallido(plan.error)`.
  - Si el plan está vacío, se emite `done` con la salida actual sin
    ejecutar nada.
- **Sin la clave:** igual que hoy.
- **`done`:** lleva `salida` = `ficha.final.ruta`, `salida_vertical` = la
  ruta del vertical si se escribió en esta ejecución (la regla de mtime de
  hoy) y `"ficha": id`.

**Pasos:**

- [ ] **Paso 1: tests que fallen:**
  - `test_runner_sin_reproceso_igual_que_hoy`, adaptando uno existente;
  - `test_runner_con_reproceso_planifica_y_ejecuta`: con `planificar` y
    `ejecutar` monkeypatcheados, comprueba los argumentos y el `done` con
    `"ficha"`;
  - `test_runner_plan_con_error_falla_con_su_texto`;
  - `test_runner_plan_vacio_termina_sin_ejecutar`.
- [ ] **Paso 2:** `$PY -m pytest -q tests/test_runner.py`. Esperado: FAIL.
- [ ] **Paso 3: implementar.**
- [ ] **Paso 4:** PASS y la batería completa.
- [ ] **Paso 5: commit** `feat: runner executes reprocessing plans`.

---

### Tarea 5: la cola

**Archivos:** modificar `app/queue_model.py` y `tests/test_app_queue.py`.

**Interfaces que produce:**

```python
@dataclass
class Trabajo:   # campos nuevos
    ficha_id: str | None = None
    resumen: str = ""          # "✓ audio · silencios · subtítulos · caption" (+ " · vertical desactualizado")
    ocupa: int = 0             # bytes de la ficha

class ModeloCola:
    def anadir(self, entradas: list[tuple[Path, str | None]]) -> list[int]
    # (ruta, ficha_id). Si ya hay una fila con ese ficha_id: si está HECHO, ERROR
    # o CANCELADO vuelve a ESPERA (limpia error, aviso y percent); si está en ESPERA
    # o PROCESANDO no se toca. Devuelve las filas nuevas o reactivadas.
    def volver_a_espera(self, filas: list[int]) -> None   # solo HECHO, ERROR o CANCELADO
    def fila_de_ficha(self, ficha_id: str) -> int | None
def resumen_de(ficha: Ficha) -> str
```

**Qué se ve en la fila:**
- se añade `resumen` cuando no está vacío;
- con `ocupa > 0`, el tamaño en MB redondeado (`"· 312 MB"`).

Las llamadas que hoy pasan `list[Path]` se adaptan en la tarea 6. Los
tests existentes de `tests/test_app_queue.py` que llaman a `anadir`
se adaptan en esta tarea, pasando `(ruta, None)`.

**Pasos:**

- [ ] **Paso 1: tests que fallen:**
  - `test_anadir_misma_ficha_reactiva_en_vez_de_duplicar`;
  - `test_anadir_misma_ficha_en_espera_no_cambia`;
  - `test_volver_a_espera_solo_terminados`;
  - `test_fila_muestra_resumen_y_tamano`;
  - `test_resumen_de_ficha` (incluye «vertical desactualizado»).
- [ ] **Paso 2:** `$PY -m pytest -q tests/test_app_queue.py`. Esperado: FAIL.
- [ ] **Paso 3: implementar.**
- [ ] **Paso 4:** PASS y la batería completa.
- [ ] **Paso 5: commit** `feat: queue rows show what each video already has`.

---

### Tarea 6: ventana principal (añadir, volver a procesar, olvidar, caption y Publicar)

**Archivos:** modificar `app/main.py` y `tests/test_app_main.py`.

**Usa:** `ficha.reconocer`, `cargar`, `olvidar`, `ocupa` y
`limpiar_temporales`; de la tarea 5, `ModeloCola.anadir`,
`volver_a_espera` y `resumen_de`.

**Qué cambia:**
- **`anadir_videos`:** llama a `reconocer(ruta, self.ajustes.carpeta_salida)`
  por cada ruta con audio. Los avisos no vacíos se muestran juntos en un
  `QMessageBox.information`. Rellena `resumen` y `ocupa`.
- **Botones nuevos bajo la cola:**
  - `self.boton_reprocesar` «Volver a procesar», que llama a
    `volver_a_espera` con la selección;
  - `self.boton_olvidar` «Olvidar este vídeo», que pide confirmación con
    `QMessageBox.question`, por defecto No. Su texto: «Se borrarán los datos
    guardados para rehacer pasos de "x" ({MB} MB). Los vídeos y su caption
    no se tocan.». Luego llama a `olvidar` y vacía `ficha_id`, `resumen` y
    `ocupa` de la fila.
  - Los dos se deshabilitan mientras se procesa, como Quitar.
- **`_caption_de(trabajo)`:**
  - lee `ficha.ruta("caption.md")` si la fila tiene ficha con `CAPTION`;
  - si falta el `.md` junto al final, lo vuelve a escribir;
  - deja de exigir `HECHO`: basta con que la ficha tenga final y caption, y
    la fila no esté en `PROCESANDO`. Publicar usa el final de la ficha.
- **`_al_terminar_trabajo`:** con `ok`, recarga la ficha y actualiza
  `salida`, `salida_vertical`, `resumen` y `ocupa`.
- **`_limpiar_temporal` (al cancelar):** usa `limpiar_temporales(ficha)` si la
  fila tiene ficha, y la lógica de hoy si no.

**Pasos:**

- [ ] **Paso 1: tests que fallen:**
  - `test_anadir_dos_veces_el_mismo_video_no_duplica`;
  - `test_anadir_salida_reconoce_su_ficha`;
  - `test_volver_a_procesar_pone_en_espera`;
  - `test_olvidar_borra_datos_tras_confirmar` y
    `test_olvidar_cancelado_no_borra`;
  - `test_publicar_disponible_con_caption_en_la_ficha`: una fila en ESPERA
    cuya ficha tiene final y `CAPTION`, sin `.md` junto al final. Se muestra
    el caption y se vuelve a escribir el `.md`;
  - `test_cancelar_limpia_temporales_de_la_ficha`.
- [ ] **Paso 2:** `$PY -m pytest -q tests/test_app_main.py`. Esperado: FAIL.
- [ ] **Paso 3: implementar.**
- [ ] **Paso 4:** PASS y la batería completa.
- [ ] **Paso 5: commit** `feat: recognise videos, reprocess and forget from the queue`.

---

### Tarea 7: Procesar con avisos y «solo caption»

**Archivos:**
- Crear: `app/widgets/dialogo_reproceso.py`, con sus tests en
  `tests/test_app_widgets.py`
- Modificar: `app/main.py`, `app/widgets/panel_opciones.py` y
  `tests/test_app_main.py`

**Interfaces que produce:**

```python
class DialogoReproceso(QDialog):
    def __init__(self, consultas: dict[str, tuple[str, list[Consulta]]], hay_vertical: set[str], parent=None)
    # clave: ficha_id → (nombre visible, consultas). hay_vertical: fichas con vertical que podría quedar desactualizado.
    def decisiones(self) -> dict[str, Decisiones]
# Función del mismo módulo; main la importa por nombre y los tests
# monkeypatchean `app.main.preguntar_reproceso`:
def preguntar_reproceso(padre, consultas, hay_vertical) -> dict[str, Decisiones] | None   # None = cancelar
# panel_opciones:
def hay_pasos(self) -> bool    # algún paso marcado, caption incluido
```

**El diálogo:**
- un bloque por vídeo;
- por cada consulta `hecho` u `otros_ajustes`, una casilla «Rehacer» que
  empieza desmarcada (Mantener por defecto, R6). En `otros_ajustes` se
  enseñan los `cambios`;
- `cambia_base` y `bloqueado` son etiquetas;
- casilla «Regenerar también el vertical» por vídeo de `hay_vertical`,
  desmarcada;
- casilla «Aplicar a todos los vídeos», que copia las marcas del primer
  vídeo a los demás en los pasos que coinciden;
- botones Procesar y Cancelar.

**`procesar()`:**
1. Para cada fila pendiente con ficha: `revisar`.
2. Si hay consultas, `preguntar_reproceso`. Con `None` no se hace nada.
3. Para cada fila: `planificar`.
   - **Con `error`:** la fila pasa a ERROR con ese texto y no se lanza.
   - **Vacío:** vuelve a HECHO y se acumula en «Nada que hacer en: x, y».
     Se avisa con un `information`.
4. El JSON es `{**config, "reproceso": {"ficha", "rehacer", "regenerar_vertical"}}`.

**`_refrescar_boton`:** usa `hay_pasos()` y actualiza el tooltip: «Marca al
menos un paso».

**Pasos:**

- [ ] **Paso 1: tests que fallen:**
  - `test_dialogo_mantener_por_defecto`;
  - `test_dialogo_rehacer_marca_decision`;
  - `test_dialogo_aplicar_a_todos`;
  - `test_procesar_pregunta_si_ya_tiene_pasos`, con `preguntar_reproceso`
    monkeypatcheado;
  - `test_procesar_cancelado_no_lanza`;
  - `test_procesar_plan_vacio_avisa_y_no_lanza`;
  - `test_procesar_solo_caption_sin_final_marca_error`;
  - `test_procesar_json_lleva_reproceso`;
  - `test_boton_procesar_con_solo_caption_habilitado`.
- [ ] **Paso 2:** `$PY -m pytest -q tests/test_app_main.py tests/test_app_widgets.py`.
  Esperado: FAIL.
- [ ] **Paso 3: implementar.**
- [ ] **Paso 4:** PASS y la batería completa.
- [ ] **Paso 5: commit** `feat: ask before redoing steps a video already has`.

---

### Tarea 8: traducciones, desinstalador y documentación

**Archivos:**
- `locale/en/LC_MESSAGES/tsots.po`, con `lanzador/traducir.sh`;
- `desinstalar.command`: añadir `fichas` al `rm -rf` y a su comentario;
- `README.es.md` y `README.md`: sección «Volver a procesar un vídeo» (qué
  guarda la ficha, avisos, Olvidar, vídeos antiguos);
- `docs/DEVELOPMENT.md`: sección «### Fichas y reproceso» (artefactos y
  claves, R0–R10 en una tabla corta, protocolo `reproceso` del runner,
  dónde viven las fichas).

**Pasos:**

- [ ] **Paso 1:** `lanzador/traducir.sh`, traducir los `msgid` nuevos y
  fuzzy, y comprobar con `msgattrib --untranslated --only-fuzzy` que no
  queda ninguno.
- [ ] **Paso 2:** test `test_desinstalar_borra_fichas` en
  `tests/test_cli_compat.py`, que lee el script y comprueba `fichas` en la
  línea del `rm -rf`. Verlo fallar y añadirlo.
- [ ] **Paso 3:** documentación.
- [ ] **Paso 4:** la batería completa, con los lentos (enlaces temporales).
- [ ] **Paso 5: commit** `docs: explain reprocessing; translate and uninstall records`.

---

## Verificación final y entrega

- [ ] **Prueba a mano en la app de la rama:** arrancarla con el Python de
  producción desde la worktree. Con un clip corto, recorrer los casos:
  - original sin silencios;
  - añadir silencios (avisa, conserva el caption, rehace subtítulos);
  - solo caption;
  - cambiar el estilo de los subtítulos;
  - añadir vertical;
  - volver a procesar sin arrastrar;
  - olvidar;
  - arrastrar un `x_limpio.mp4` antiguo.

  Comprobar que en la carpeta de salida no aparece ningún `_limpio_limpio`.
- [ ] **Revisión final de la rama** y PR contra `develop`: en español, sin
  atribución, con qué, por qué, cómo se verificó y qué debe saber el revisor.
- [ ] **Despliegue** (tras la release a `main`): `git pull` en producción,
  reiniciar la app y borrar una sola vez el contenido de
  `limpiadorVideo/audio_procesado/`. El usuario ya lo aprobó en el diseño.
