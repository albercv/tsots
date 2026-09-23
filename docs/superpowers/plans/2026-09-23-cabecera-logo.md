# Cabecera con el logo de la app — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar el logo de la app en la ventana principal: una cabecera arriba con el logo, el nombre "The Silence of the Shorts" y un lema corto, y la zona de soltar vídeos y la cola debajo.

**Architecture:** Widget nuevo `Cabecera` en `app/widgets/cabecera.py`, añadido como primera fila del layout raíz de `VentanaPrincipal`, a todo el ancho y por encima de las dos columnas (zona de soltar + cola a la izquierda, opciones a la derecha). El nombre y el lema son texto de Qt, no parte de la imagen: se ven nítidos, siguen la paleta (modo claro y oscuro) y el lema se traduce.

**Decisión tomada sin consultar (revisable):** la imagen de la cabecera es la marca de la oveja (`app/recursos/icon_512.png`, el mismo PNG del icono de la ventana), no `docs/img/logo.png` completo. `logo.png` es RGB sin alfa, con fondo casi blanco y el nombre en tinta oscura: en modo oscuro quedaría un rectángulo blanco o el texto sería invisible. `icon_512.png` ya tiene fondo transparente, lo genera `lanzador/generar_icono.py` a partir del mismo arte y se resuelve igual dentro del `.app` (el lanzador del bundle ejecuta `python -m app` desde el proyecto, así que `Path(__file__)` apunta a `app/recursos/` en ambos casos). El lema es el del logo: "Edit quieter. Create louder." (en español, "Edita en silencio. Crea a lo grande.").

**Tech Stack:** Python 3.11, PySide6 6.11, pytest + pytest-qt. Sin dependencias nuevas.

## Global Constraints

- `test_ventana_cabe_en_pantallas_pequenas` sigue pasando sin tocarlo: `minimumSizeHint()` ≤ 700 × 600 px. Antes de este cambio el mínimo es 567 × 317; la cabecera añade unos 60 px de alto.
- Nada de colores fijos: textos con roles de la paleta (`WindowText`, `PlaceholderText`) y separador derivado de `WindowText` con alfa, así funciona en claro y oscuro y al cambiar de modo en caliente.
- Logo nítido en Retina: se escala desde el PNG de 512 px a `lado × devicePixelRatio` con `SmoothTransformation` y se marca el `devicePixelRatio` del pixmap. Se recalcula al cambiar de pantalla (`QEvent.DevicePixelRatioChange`).
- Si falta el PNG, la cabecera no falla: oculta el logo y muestra el nombre y el lema.
- Cadenas nuevas con `_()`; `lanzador/traducir.sh` y `locale/en/LC_MESSAGES/tsots.po` sin fuzzy.
- Tests: `QT_QPA_PLATFORM=offscreen .venv-clearvoice/bin/python -m pytest -m "not lenta" -q` en verde tras cada tarea.
- GUI, comentarios y nombres de código en español. Commits en inglés, sin atribución de IA.
- Rama `feature/cabecera-logo` desde `develop`; PR contra `develop`.

## Mapa de ficheros

| Fichero | Cambio |
|---|---|
| `app/widgets/cabecera.py` (crear) | `Cabecera` (logo, título, lema, separador) y `pixmap_logo(imagen, lado, dpr)` |
| `app/main.py` | Cabecera como primera fila del layout raíz, con `RUTA_ICONO` |
| `tests/test_app_widgets.py` | Tests de `Cabecera` y `pixmap_logo` |
| `tests/test_app_main.py` | La cabecera queda encima de la zona de soltar, la cola y el panel |
| `locale/en/LC_MESSAGES/tsots.po` | Traducción del lema y del nombre accesible del logo |
| `docs/TODO.md` | Quitar "Header with the app logo" |

## Tareas

### Task 1: widget `Cabecera`

- [x] Tests en `tests/test_app_widgets.py`:
  - `test_cabecera_carga_logo`: pixmap no nulo, logo visible, tamaño lógico `LADO_LOGO`.
  - `test_pixmap_logo_escala_con_dpr`: con `dpr=2` el pixmap mide `2 × lado` píxeles y tiene `devicePixelRatio() == 2`.
  - `test_cabecera_muestra_nombre_y_lema`.
  - `test_cabecera_sin_logo_no_falla`: ruta inexistente → logo oculto, título visible, `grab()` no nulo.
  - `test_cabecera_sigue_la_paleta`: con una paleta oscura (texto blanco), el título se pinta claro; sin hojas de estilo en la cabecera.
  - `test_cabecera_lema_traducible`: con un catálogo `en` mínimo, el lema sale en inglés.
- [x] Implementar `app/widgets/cabecera.py`.
- [x] Commit `feat(gui): header widget with the app logo, name and tagline`.

### Task 2: cabecera en la ventana principal

- [x] Test en `tests/test_app_main.py`: `test_cabecera_encima_de_zona_drop_y_cola` (la parte inferior de la cabecera queda por encima de la zona de soltar, la cola y el panel derecho; ocupa el ancho de las dos columnas).
- [x] Añadir la cabecera en `VentanaPrincipal` antes de `fila_superior`.
- [x] Commit `feat(gui): show the header above the drop zone and the queue`.

### Task 3: traducciones, revisión visual y documentación

- [x] `lanzador/traducir.sh`, traducir en `tsots.po`, sin fuzzy.
- [x] Capturas offscreen de la ventana en paleta clara y oscura, y al tamaño mínimo. Ajustar márgenes y tamaños hasta que se vea bien.
- [x] README: solo si describe la disposición de la ventana (dice "la zona de la izquierda", que sigue siendo cierto: sin cambios).
- [x] Quitar el punto de `docs/TODO.md`.
- [x] Commit `docs: header plan results; remove it from TODO`.

## Riesgos

- **Altura mínima:** la cabecera resta alto útil a la cola en pantallas pequeñas. Se mantiene compacta (logo de 40 px, cabecera de 50 px) y se comprueba el mínimo con el test existente.
- **`PlaceholderText` en temas antiguos:** en algunos estilos puede tener poco contraste. En macOS es el gris secundario del sistema.

## Resultado (2026-09-23)

Implementado en `feature/cabecera-logo`.

- Cabecera de 50 px lógicos: marca de la oveja de 40 px, "The Silence of the Shorts" en negrita (1,45 × la fuente del sistema), el lema en el gris secundario de la paleta y un separador fino.
- El icono lleva un 10 % de margen transparente (el que deja `generar_icono.py`); la cabecera lo recorta para que el cuadrado ocupe los 40 px y quede alineado con el borde de la zona de soltar.
- Mínimo de la ventana con el estilo nativo de macOS (Retina, dpr 2): 645 × 415 (antes ~645 × 365). Con la plataforma `offscreen` de los tests: 567 × 377.
- Capturas revisadas con la plataforma `cocoa` en claro y oscuro (`styleHints().setColorScheme`), a 900 × 560, al tamaño mínimo y en inglés.
