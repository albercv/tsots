# Editar con Claude un vídeo que ya es un short

Fecha: 2026-11-17 · Estado: aprobado
Repo: `~/Documents/personalProjects/limpiadorVideo` (TSOTS), sobre v1.10.0.
Se apoya en el diseño `docs/superpowers/specs/2026-11-17-edicion-shorts-design.md`
(secciones 5, 9, 10 y 11): agente, `plan.json`, zonas, estado en la cola y música.

## 1. Intención

Hoy «Editar con Claude» solo edita los shorts que TSOTS saca de un vídeo largo.
El usuario también procesa vídeos que ya son un short (verticales, ~1–3 min,
p. ej. `~/Downloads/odin_17_11.MOV`, 1080×1920, 3:22) y quiere editarlos con
Claude igual: rótulos, contadores, emojis, transiciones, sonidos y música,
sin sacarles shorts.

## 2. Objetivos, no objetivos, anti-objetivos

**Objetivos**
- **A. Botón.** El botón «Editar shorts ya creados» pasa a ser **«Editar con
  Claude…»**:
  - el vídeo elegido tiene shorts → edita sus shorts (como hoy);
  - no tiene shorts y su final es vertical 1080×1920 → edita **el propio
    vídeo final**;
  - tiene las dos cosas → pregunta cuál («Los N shorts» / «El vídeo»);
  - ninguna → aviso explicando que hace falta un final vertical 1080×1920 o
    shorts.
- **C. Automático al procesar.** Con la casilla «Editar con Claude» marcada,
  cada vídeo que se procesa en ese lote y cuyo final sale vertical
  1080×1920 se encola para editarse al terminar su procesado. El agente
  arranca al acabar la cola (como hoy).
- **Publicar.** «Publicar…» del vídeo sube `<final>.editado.mp4` si existe y
  es más reciente que el final.
- **Barra.** El avance aparece bajo la fila de ese vídeo, sin mezclarse con
  otros vídeos que salgan a la misma carpeta.

**No objetivos (v1)**
- Editar el `…_limpio_vertical.mp4` que acompaña a un final horizontal
  («Publicar…» no lo sube).
- Verticales que no sean exactamente 1080×1920 (el motor pinta a 1080×1920).
- Estilo distinto por vídeo, publicación automática.

**Anti-objetivos**
- Tocar o borrar el final limpio.
- Encolar al pulsar «Crear shorts» o al reprocesar solo otras cosas: el
  automático (C) solo vale para vídeos procesados en ese lote con la casilla
  marcada.
- Publicar un editado viejo de un final que se ha vuelto a generar.
- Duplicar trabajos por doble clic o por procesar dos veces seguidas.

## 3. Hechos del código en los que se apoya

- `ficha.final` (`Huella`: `ruta`, `tamano`, `mtime_ns`) es lo que sube
  «Publicar…» (`app/main.py::_video_de` → `DialogoPublicar(video, …)`).
  Con una fuente vertical, el final (`<nombre>_limpio.mp4`) ya es vertical,
  con subtítulos y título quemados según la configuración.
- La ficha guarda con qué se quemó: `artefactos[HORIZONTAL].ajustes =
  {"subtitulos": {diseno, posicion, tamano, idioma, …}, "titulo": <texto>}`
  (`reproceso.py:359-364`, `419`); `"subtitulos"` falta si no se quemaron.
- Transcripción, base y final comparten línea de tiempo (sin desfase); el
  título dura 5 s desde 0 (`titulo.DURACION`).
- `edicion.encolar(carpeta, episodio, stems, tramos, estilo, zonas, idioma,
  encuadre, dir_edicion)` crea `pendientes/<episodio> - <stem>/` con
  `trabajo.json` (`origen`, `destino = <stem>.editado.mp4`, …).
- `estado.leer` agrupa por `Path(origen).parent`, y la ventana lo casa con la
  carpeta de shorts de cada fila.

## 4. Diseño

### 4.1 Encolar un vídeo suelto

Nueva función en `videopipeline/shorts.py` (junto a `editar_existentes`, que
ya tiene a mano `_Pasada`, `_transcrita` y `_encolar_edicion`):

`editar_video(ficha, config, opciones) -> int`
- `final = ficha.final.ruta`; si falta, o `resolucion_video(final) !=
  (1080, 1920)` → `PasoFallido` con el motivo.
- Transcripción: como en `editar_existentes` (`_Pasada` + `_transcrita` +
  `_palabras()`); sin transcripción → `PasoFallido`. Palabras: todas (no un
  tramo).
- Zonas con los ajustes **guardados en la ficha**, no los del panel. Hay dos
  clases de final vertical:
  - **Final del paso horizontal sobre una fuente ya vertical** (`ficha.final`
    ≠ `ficha.ruta_final(False)`): ajustes de `artefactos[HORIZONTAL]`;
    encuadre `"central"` y resolución de la fuente `(1080, 1920)` → el final
    ocupa todo el cuadro, sin franja de zoom.
  - **Vertical único** (`ficha.final == ficha.ruta_final(False)`, es decir
    `<nombre>_vertical.mp4`, `reproceso.py:502-505`): ajustes de
    `artefactos[VERTICAL]` (`{"vertical": {"encuadre"}, "subtitulos"?,
    "titulo"?}`); encuadre el guardado y resolución de la fuente la de
    `_Pasada.base` (como hacen los shorts), así que con `difuminado` o `cara`
    sí puede haber franja de zoom.
  - En los dos: `subtitulos = "subtitulos" in ajustes` y, si están, su
    `diseno`, `posicion`→`posicion_subs`, `tamano`→`tamano_subs`;
    `con_titulo = bool(ajustes.get("titulo"))`.
- Si ya hay un trabajo pendiente para ese final → devuelve 0 (no duplica).
- Sin límite de duración: el motor no tiene tope (un 3:22 vale); el límite es
  el de 1200 s por trabajo del agente.
- `caption.md` es opcional para el agente; si existe `<final>.md` (la app lo
  restaura desde la ficha) se copia como en los shorts.
- Encola un trabajo: `carpeta = final.parent`, `stems = [final.stem]`,
  `episodio = ficha.nombre`, y **`grupo = str(final)`** (4.2). Devuelve 1.

### 4.2 Agrupar por tanda, no por carpeta

- `encolar(..., grupo: str | None = None)` escribe `"grupo"` en
  `trabajo.json`: los shorts, la carpeta de shorts (como hoy, explícito); un
  vídeo suelto, la ruta de su final.
- `estado.leer` agrupa por `Path(trabajo["grupo"])` si existe y, si no
  (trabajos anteriores), por `Path(origen).parent`.
- `MainWindow._refrescar_edicion` busca para cada fila primero su final
  (`ficha.final.ruta`) y luego su carpeta de shorts; muestra el primero que
  tenga estado.

### 4.3 Botón «Editar con Claude…» (A)

- `panel_opciones`: texto `_("Editar con Claude…")`, tooltip nuevo que cubre
  los dos casos; misma señal `editar_shorts` (renombrar a `editar_con_claude`).
- Activo si: hay `claude`, no se procesa, y la fila elegida tiene shorts **o**
  un `ficha.final` (la comprobación de 1080×1920 se hace al pulsar, para no
  lanzar ffprobe en cada cambio de selección).
- Al pulsar (`MainWindow._editar_con_claude`):
  1. Opciones: shorts si `_carpeta_shorts_de(trabajo)`; vídeo si
     `ficha.final` existe y es 1080×1920.
  2. Ninguna → aviso. Una → confirmación como hoy (con el número de shorts o
     el nombre del vídeo, el estilo y que cada uno es una ejecución de Claude).
     Dos → un `QMessageBox` con botones «Los N shorts», «El vídeo» y
     «Cancelar».
  3. Llama a `shorts.editar_existentes` o `shorts.editar_video`, lanza el
     agente, refresca la barra y avisa de lo encolado (o de que ya estaba).

### 4.4 Automático al procesar (C)

- En `MainWindow.procesar`, si la casilla «Editar con Claude» está marcada (y
  hay `claude`), se guardan las filas de ese lote en `self._editar_al_terminar`.
- En `_al_terminar_trabajo(fila, ok, …)`: si `ok` y la fila está en ese
  conjunto → `shorts.editar_video(ficha, config, opciones)` en `try`; si no
  aplica (final no vertical 1080×1920) no hace nada; si falla por otra causa,
  el motivo va al aviso de la fila. Se quita la fila del conjunto.
- **No repite sin motivo:** no se encola si el lote no hizo nada en ese vídeo
  (la rama `plan.vacio` de `procesar`, que llama a `_al_terminar_trabajo` sin
  procesar) ni si ya existe un `<final>.editado.mp4` más reciente que el
  final. Para volver a editar a propósito está el botón (A).
- Si en el mismo lote también se crean shorts del vídeo («Crear shorts al
  procesar»), se editan las dos cosas: cada casilla hace lo que dice.
- «Crear shorts» y reprocesos lanzados desde otros botones no tocan ese
  conjunto.
- La casilla y su tooltip pasan a decir que edita los shorts al crearlos **y
  los vídeos verticales al procesarlos**.

### 4.5 Publicar el editado

- Solo en `MainWindow._publicar`: antes de abrir `DialogoPublicar`, si existe
  `<final>.editado.mp4` con mtime ≥ el del final, se sube ese. `_video_de` y
  el panel de caption no cambian. El caption y el registro siguen siendo los del final
  (`registro.ruta` ya pasa `X.editado.mp4` a `X.publicado.json` si `X.mp4`
  está al lado).
- `DialogoPublicar` muestra «(editado)» junto al nombre del vídeo cuando la
  ruta acaba en `.editado.mp4`.

### 4.6 Volver a procesar

- Cuando `reproceso` escribe un final nuevo (las asignaciones a
  `ficha.final`, `reproceso.py:418` y la del vertical único ~`503-505`), borra
  `<stem>.editado.mp4` y `.editado.mp4.tmp` de ese final.
- Un trabajo pendiente de un final que cambió ya acaba en `errores/` sin llamar
  a Claude (comprobación previa del agente). Su tanda deja de mostrarse en la
  barra cuando se encola otra para ese final (la tanda se mide desde el
  pendiente más viejo) o pasadas 6 h.

### 4.7 Pruebas

- `editar_video`: encola un trabajo con todas las palabras, `grupo` = final,
  zonas sin franja y con subtítulos de los ajustes guardados; final no
  1080×1920 → `PasoFallido`; sin transcripción → `PasoFallido`; doble llamada
  → 0.
- `encolar` con y sin `grupo`; `estado.leer` agrupa por `grupo` y, sin él, por
  carpeta; dos vídeos en la misma carpeta no se mezclan.
- Ventana: el botón se activa con shorts o con final; elige solo, pregunta con
  los dos, avisa con ninguno; C encola solo las filas procesadas con la
  casilla, no las de «Crear shorts»; la barra casa con el final de la fila.
- `_publicar` prefiere el editado más reciente; «(editado)» en el diálogo.
- `reproceso`: escribir un final borra su `.editado.mp4`.
- Prueba real: `odin_17_11` con Claude Haiku → `odin_17_11_limpio.editado.mp4`.

## 5. Decisiones del usuario

- Enfoque **A + C**: un botón contextual y la casilla también para los
  vídeos verticales al procesarlos.

## 6. Decisiones mías (revisables)

- Zonas con los ajustes guardados en la ficha, no los del panel.
- Solo finales 1080×1920; el `_limpio_vertical` de un horizontal queda fuera.
- La función vive en `shorts.py` para reutilizar sus piezas privadas.
- La comprobación de resolución, al pulsar y no al cambiar de fila.
- `grupo` en `trabajo.json` para no mezclar vídeos de una misma carpeta.
- C solo para filas del lote lanzado con «Procesar» en las que de verdad se
  procesó algo, y nunca si ya hay un editado al día.
- Con «Crear shorts al procesar» también marcado, C edita el vídeo y los
  shorts.
- La sustitución por el editado al publicar, solo en `_publicar`.

## 7. Para el constructor

- Texto exacto de diálogos y tooltips (en español, con traducción al inglés).
- Cómo obtener la configuración del vídeo en `_al_terminar_trabajo` (la del
  lote guardada al lanzar o `_config_de` en ese momento).
- Dónde exactamente borrar el editado al escribir un final nuevo.
