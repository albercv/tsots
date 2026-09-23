# Secciones plegables y previsualización fija — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la previsualización esté siempre a la vista. Los grupos de opciones de la columna derecha (Modo, Limpieza de audio, Corte de silencios, Subtítulos, Caption SEO) pasan a ser secciones plegables en acordeón: solo una abierta, Modo abierta al arrancar. Si hace falta scroll, solo se desplazan las secciones; debajo, fija, una zona con pestañas **Previsualización** y **Caption** que siempre existe y conserva su hueco, con un texto de marcador cuando no hay nada que mostrar.

**Architecture:**

```
columna derecha
├── scroll_derecha (QScrollArea, stretch 1)
│   └── PanelOpciones
│       ├── SeccionPlegable "Modo"               ▾ abierta
│       ├── SeccionPlegable "Limpieza de audio"   ▸
│       ├── SeccionPlegable "Corte de silencios"  ▸
│       ├── SeccionPlegable "Subtítulos"          ▸
│       └── SeccionPlegable "Caption SEO"         ▸
└── pestanas (QTabWidget, alto fijo, fuera del scroll)
    ├── "Previsualización" → VistaPrevia
    └── "Caption"          → PanelCaption (marcador si no hay caption)
```

- Widget nuevo `SeccionPlegable` en `app/widgets/seccion_plegable.py`: cabecera `QToolButton` (flecha de despliegue + título, a todo el ancho, checkable) y un `contenido` (`QWidget`) donde cada grupo monta su layout como antes lo hacía en el `QGroupBox`. Su `minimumSizeHint`/`sizeHint` de ancho cuentan el contenido aunque esté plegado, para que el ancho de la columna no salte al abrir una sección.
- `Acordeon` (mismo fichero): agrupa las cabeceras en un `QButtonGroup` exclusivo; abrir una cierra la otra.
- `PanelOpciones` sustituye los `QGroupBox` por secciones. La lógica de habilitados recorre `seccion.contenido`, no la sección entera, para no deshabilitar nunca una cabecera.
- `VentanaPrincipal`: el `QScrollArea` solo contiene el panel de opciones; la vista previa y el caption van a un `QTabWidget` debajo, con alto fijo calculado para que quepan la previsualización a tamaño completo (260 px) y el caption.
- `PanelCaption`: cambio mínimo (otra rama está moviendo el botón **Redes…** fuera de este panel). Deja de ocultarse: un `QStackedLayout` alterna entre el marcador vacío y el contenido, y el alto no cambia. El `QGroupBox` "Caption SEO" pasa a ser un `QWidget` simple porque la pestaña ya pone el título y el marco.

**Decisiones tomadas sin consultar (revisables):**

1. **Pulsar la cabecera de la sección abierta no la pliega.** El acordeón mantiene siempre exactamente una sección abierta. Plegarlo todo no gana nada (la previsualización ya está fija y visible) y dejaría la columna como una lista de títulos sin contenido. Técnicamente es el comportamiento del `QButtonGroup` exclusivo.
2. **Cambio automático de pestaña.** Al seleccionar en la cola un vídeo terminado con caption, o cuando el vídeo seleccionado termina y genera caption, se muestra la pestaña Caption: es el siguiente paso (copiar, publicar). Al seleccionar cualquier otro vídeo, o al tocar las opciones de subtítulos (diseño, posición, tamaño, activar), vuelve a Previsualización para ver el efecto. Los cambios de selección y de opciones son acciones del usuario, así que no le quita la pestaña por sorpresa.
3. **Tamaño inicial de la ventana 960 × 720** (antes 900 × 560), recortado al área útil de la pantalla. Con la zona de pestañas fija, a 560 px de alto casi solo quedaban a la vista las cabeceras de las secciones.

**Tech Stack:** Python 3.11, PySide6 6.11, pytest + pytest-qt. Sin dependencias nuevas.

## Global Constraints

- `test_ventana_cabe_en_pantallas_pequenas` sigue pasando sin tocarlo: `minimumSizeHint()` ≤ 700 × 600 px. La zona de pestañas tiene alto fijo; las secciones hacen scroll.
- No se toca la barra inferior ni se depende de `PanelCaption.boton_redes` (la rama `fix/redes-ajustes-app` lo mueve junto al selector de idioma).
- Se conserva todo: habilitados entre opciones, señales de repintado de la preview, **Publicar…**, `cargar`/`valores` y traducciones. El contenido plegado no afecta a `valores()`.
- Nada de colores fijos nuevos: la cabecera de sección usa la paleta (claro y oscuro).
- Cadenas nuevas con `_()`; `lanzador/traducir.sh` y `locale/en/LC_MESSAGES/tsots.po` sin fuzzy.
- Tests: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m "not lenta" -q` en verde tras cada tarea. Qt siempre offscreen: nunca abrir ventanas en la pantalla del usuario.
- GUI, comentarios y nombres de código en español. Commits en inglés, sin atribución de IA.
- Rama `feature/secciones-plegables` desde `develop`; PR contra `develop`.

## Mapa de ficheros

| Fichero | Cambio |
|---|---|
| `app/widgets/seccion_plegable.py` (crear) | `SeccionPlegable` y `Acordeon` |
| `app/widgets/panel_opciones.py` | Grupos → secciones en acordeón; `secciones`, `seccion_abierta()` |
| `app/widgets/panel_caption.py` | Marcador vacío en vez de ocultarse; sin `QGroupBox` |
| `app/main.py` | Scroll solo con opciones; pestañas fijas debajo; cambio automático de pestaña; tamaño inicial |
| `tests/test_app_widgets.py` | Tests de sección, acordeón, `valores()` con secciones plegadas, marcador del caption |
| `tests/test_app_main.py` | Pestañas fuera del scroll, siempre presentes, cambio automático; tests de caption adaptados (ya no se oculta) |
| `locale/en/LC_MESSAGES/tsots.po` | Pestañas y marcador |
| `README.md`, `README.es.md`, `docs/DEVELOPMENT.md` | Nueva disposición |

## Tareas

### Task 1: `SeccionPlegable` y `Acordeon`

- [ ] Tests en `tests/test_app_widgets.py`:
  - `test_seccion_plegable_abre_y_cierra`: `expandir(True/False)` muestra/oculta el contenido y cambia la flecha.
  - `test_seccion_plegable_ancho_cuenta_contenido_plegado`.
  - `test_acordeon_solo_una_abierta`: abrir otra cierra la anterior; pulsar la abierta la deja abierta.
- [ ] Implementar `app/widgets/seccion_plegable.py`.

### Task 2: secciones en `PanelOpciones`

- [ ] Tests:
  - `test_panel_secciones_en_orden_y_modo_abierto`.
  - `test_panel_clic_en_otra_seccion_cambia_la_abierta` (con `qtbot.mouseClick` en la cabecera).
  - `test_panel_valores_no_dependen_de_la_seccion_abierta`.
  - `test_panel_habilitados_no_tocan_cabeceras` (modo "solo silencios" deshabilita el contenido de audio, no su cabecera).
- [ ] Sustituir los `QGroupBox` por secciones.
- [ ] Commit `feat(gui): collapsible option sections in an accordion`.

### Task 3: pestañas fijas en la ventana

- [ ] Tests en `tests/test_app_main.py`:
  - `test_pestanas_fijas_fuera_del_scroll`: `vista_previa` y `panel_caption` no descienden de `scroll_derecha`; la zona de pestañas queda debajo del scroll.
  - `test_pestanas_siempre_presentes_con_marcador`: dos pestañas, marcadores sin vídeo ni caption, mismo alto con y sin caption.
  - `test_seleccion_cambia_de_pestana_segun_caption`, `test_terminar_con_caption_muestra_pestana_caption`, `test_opciones_subs_vuelven_a_previsualizacion`.
  - Adaptar los tests que miraban `panel_caption.isHidden()`.
- [ ] `PanelCaption` con marcador; ventana con pestañas.
- [ ] Commit `feat(gui): fixed preview and caption tabs below the options`.

### Task 4: traducciones, revisión visual y documentación

- [ ] `lanzador/traducir.sh`, traducir en `tsots.po`, sin fuzzy.
- [ ] Capturas offscreen (`grab()`) a tamaño por defecto y mínimo, paleta clara y oscura, y con caption. Ajustar hasta que se vea nativo.
- [ ] README (es/en): la sección "Cómo funciona" describe las opciones y dónde aparece el caption. `docs/DEVELOPMENT.md`: disposición de la ventana.
- [ ] Commit `docs: collapsible sections and fixed preview tabs`.

## Riesgos

- **Alto mínimo:** la zona fija resta alto a las secciones. A 600 px quedan unas pocas filas visibles y el resto hace scroll; es lo pedido.
- **Ancho de la pestaña Caption:** los cuatro botones de copiar suman ~450 px y ahora cuentan en el mínimo de la ventana (antes el panel estaba oculto al calcularlo). Se mide contra el test de 700 px.
- **Conflicto con `fix/redes-ajustes-app`:** ambos tocan `panel_caption.py` y `tests/test_app_main.py`. Los cambios aquí quedan al principio y al final de `__init__` y en `mostrar`, lejos de la fila de botones de redes.
