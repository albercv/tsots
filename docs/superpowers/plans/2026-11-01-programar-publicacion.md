# Programar publicaciones Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Programar una publicación para una fecha y hora desde Publicar… y ver/cancelar lo programado en un calendario de mes.

**Architecture:** `Opciones.programada` viaja hasta `upload_post.campos`, que añade `scheduled_date` + `timezone`. El 202 con `job_id` se convierte en `Resultado(ok=True, programada=…, referencia=job_id)`, que `publicador` no sondea y anota en el registro. El protocolo `Proveedor` gana `programadas()` y `cancelar()`; una ventana nueva los usa en segundo plano.

**Tech Stack:** Python 3.11, PySide6, httpx, pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-11-01-programar-publicacion-design.md`

## Global Constraints

- Tests: `QT_QPA_PLATFORM=offscreen ~/Documents/personalProjects/limpiadorVideo/.venv-clearvoice/bin/python -m pytest -q`. Nunca `-m lenta` ni `-m ""`.
- Código, comentarios y textos de interfaz en español; textos nuevos con `_()`/`N_()` y traducidos en `locale/en/LC_MESSAGES/tsots.po` vía `lanzador/traducir.sh`.
- Commits en inglés, sin atribución a IA.
- Ninguna cadena propia de Upload-Post fuera de `videopipeline/redes/upload_post.py` (`tests/test_redes_contrato.py`).
- Nunca la API key, el perfil ni ids de lugar de TikTok en el registro.
- Fecha programada: mínimo 15 min en el futuro, máximo 365 días.

## Review Focus

1. Mac con una zona sin nombre IANA (tzinfo de desfase fijo) → se envía en UTC con `timezone=UTC`, nunca una hora equivocada. Test en Task 2.
2. Servicio que responde con `request_id` y sin `job_id` al programar → se da por programada sin referencia, nunca «por confirmar» eterno ni sondeo de 15 min. Test en Task 2/3.
3. Cancelar algo que ya no existe (404) → se trata como cancelado, desaparece del calendario. Test en Task 2.
4. Trabajo de la web con redes que la app no conoce (p. ej. `linkedin`) o fecha ilegible → se ignora la red / el trabajo, el calendario no se cae. Test en Task 2.
5. Registro antiguo sin `programada`/`referencia` → se sigue leyendo igual. Test en Task 1.

---

### Task 1: Modelo y registro

**Files:**
- Modify: `videopipeline/redes/modelo.py`, `videopipeline/redes/registro.py`
- Test: `tests/test_redes_registro.py`

**Interfaces:**
- Produces: `Opciones.programada: datetime | None = None`; `Resultado.programada: datetime | None = None`; `@dataclass(frozen=True) class Programada: referencia: str; fecha: datetime; plataformas: tuple[Plataforma, ...]; titulo: str = ""; modos: dict = field(default_factory=dict, compare=False)`; `Entrada.programada: str = ""`, `Entrada.referencia: str = ""`; `registro.anotar(..., programada: datetime | None = None, referencia: str = "")`; `registro.olvidar(video: Path, referencia: str) -> bool`.

- [ ] Tests: `test_programada_y_referencia_ida_y_vuelta` (anotar con programada/referencia, leer devuelve ISO y job_id; el JSON no lleva las claves cuando están vacías), `test_olvidar_quita_solo_esa_referencia` (devuelve True; otra entrada intacta; referencia inexistente → False y fichero igual), `test_registro_antiguo_sin_campos_nuevos`.
- [ ] Run → FAIL. Implement. Run → PASS. Commit `feat: model and record fields for scheduled posts`.

### Task 2: Proveedor Upload-Post y protocolo

**Files:**
- Modify: `videopipeline/redes/proveedor.py`, `videopipeline/redes/upload_post.py`, `tests/redes_falsos.py`
- Test: `tests/test_redes_upload_post.py`, `tests/test_redes_contrato.py`

**Interfaces:**
- Consumes: Task 1 types.
- Produces: `Proveedor.programadas() -> list[Programada]` (lanza `ErrorConsulta`), `Proveedor.cancelar(referencia: str) -> None` (lanza `ErrorConsulta`; 404 = ya cancelada, no lanza). `ProveedorFalso(programadas=[...]|excepción, al_cancelar=None|excepción)` anota `"programadas"` y `f"cancelar:{ref}"` en `consultas`.

- [ ] Tests:
  - `test_programar_envia_fecha_local_y_zona_sin_async` — `Opciones(programada=datetime(2026,11,3,18,0,tzinfo=ZoneInfo("Europe/Madrid")))` → campos `scheduled_date == ["2026-11-03T18:00:00"]`, `timezone == ["Europe/Madrid"]`, sin `async_upload`.
  - `test_programar_con_desfase_fijo_va_en_utc` — tzinfo `timezone(timedelta(hours=1))` → `"2026-11-03T17:00:00"`, `"UTC"`.
  - `test_respuesta_programada_es_ok_con_job_id` — 202 `{"success": true, "job_id": "j1", "scheduled_date": "2026-11-03T17:00:00Z"}` → `ok`, `programada == opciones.programada`, `referencia == "j1"`, sin sondeo.
  - `test_programada_con_solo_request_id_queda_programada_sin_referencia`.
  - `test_lista_de_programadas` — GET `.../uploadposts/schedule` con `profile_username`; trabajos con `platforms` `["tiktok"]`, `["youtube","linkedin"]`, uno con fecha ilegible → 2 `Programada` (UTC aware), `linkedin` ignorada, ilegible descartada; modos de TikTok desde `fields.post_mode` (`MEDIA_UPLOAD`→`borrador`, `DIRECT_POST`→`publico`).
  - `test_cancelar_borra_y_404_cuenta_como_cancelada`; `test_cancelar_error_lanza_error_consulta_sin_clave`.
  - Contrato: añadir `p.programadas` y `lambda: p.cancelar("j")` al bucle de `test_consultas_fallidas_lanzan_error_consulta_sin_la_clave` (los métodos aceptados pasan a ser GET y DELETE).
- [ ] Run → FAIL. Implement (`URL_PROGRAMADAS = f"{URL_API}/uploadposts/schedule"`; `cancelar` usa `DELETE {URL_PROGRAMADAS}/{quote(ref)}` con `ESPERA_CONSULTA`; `_interpretar_subida(plataforma, respuesta, programada=None)`). Run → PASS. Commit `feat: schedule, list and cancel posts in the Upload-Post provider`.

### Task 3: Publicador

**Files:** Modify `videopipeline/redes/publicador.py`. Test `tests/test_redes_publicador.py`.

- [ ] Tests: `test_programada_no_se_sondea_y_se_anota_con_fecha_y_referencia` (falso devuelve `Resultado(T, ok=True, programada=F, referencia="j1")` → sin llamadas `estado`, registro con `programada` y `referencia`, progreso `HECHO`).
- [ ] Implement: `terminar` pasa `programada=resultado.programada, referencia=resultado.referencia if resultado.programada else ""` a `registro.anotar`; `_describir` dice `programada para <iso> (job …)`. Commit `feat: record scheduled results without polling`.

### Task 4: Diálogo Publicar

**Files:** Modify `app/widgets/dialogo_publicar.py`, `app/settings.py`. Test `tests/test_app_redes.py`.

**Interfaces:**
- Produces: `Ajustes.programadas_locales() -> dict[str, str]`, `Ajustes.anotar_programada(referencia: str, video: Path) -> None`, `Ajustes.olvidar_programada(referencia: str) -> str` (devuelve la ruta o ""). `DialogoPublicar.radio_ahora`, `.radio_programar`, `.campo_fecha` (`QDateTimeEdit`), `.programada() -> datetime | None`. `MARGEN_MINIMO = timedelta(minutes=15)`, `MAXIMO = timedelta(days=365)`. `zona_local() -> ZoneInfo` (de `QTimeZone.systemTimeZoneId()`, UTC si falla) en `app/widgets/dialogo_publicar.py`.
- [ ] Tests: botón «Publicar»→«Programar» al marcar; fecha < 15 min o > 365 días desactiva y explica; confirmación «¿Programar para…?»; el falso recibe `opciones.programada` con zona; fila «📅 Programado para el 03/11 18:00»; `ajustes.programadas_locales()` guarda job→vídeo; aviso «TikTok (programado para el 03/11/2026 18:00)».
- [ ] Implement, PASS, commit `feat: schedule from the Publish dialog`.

### Task 5: Ventana Programadas y botón

**Files:** Create `app/widgets/dialogo_programadas.py`. Modify `app/main.py`. Test `tests/test_app_programadas.py`.

**Interfaces:**
- Produces: `agrupar(programadas: list[Programada], zona) -> dict[date, list[Grupo]]` con `Grupo(fecha_local: datetime, titulo: str, trabajos: list[Programada])` agrupando por `(titulo, fecha_local)`; `DialogoProgramadas(ajustes, llavero=credenciales, fabrica=None, zona=None, hoy=None, parent=None)` con `.mes` (date día 1), `.anterior()`, `.siguiente()`, `.actualizar()`, `.celdas: dict[date, CeldaDia]`, `.cancelar(trabajos: list[Programada]) -> None`.
- [ ] Tests: `agrupar` junta TikTok+YouTube mismo título/hora y separa otra hora; la etiqueta sale en el día local (23:30 UTC → día siguiente en Madrid); navegar meses; actualizar consulta en segundo plano y pinta; error de consulta se muestra; cancelar pide confirmación, llama al proveedor, quita la etiqueta y limpia registro + índice; error al cancelar deja la etiqueta; sin clave lo dice; main tiene `boton_programadas`.
- [ ] Implement, PASS, commit `feat: calendar of scheduled posts with cancel`.

### Task 6: Traducciones, documentación, verificación

- [ ] `lanzador/traducir.sh`; traducir los `msgstr ""` nuevos en `locale/en/LC_MESSAGES/tsots.po`; recompilar.
- [ ] `docs/DEVELOPMENT.md` (Publishing: scheduling + calendar), `README.md`/`README.es.md` (Publicar en redes), `docs/TODO.md` (cambiar fecha, resultado tras la hora, cola).
- [ ] Suite completa en verde. Commit `docs: scheduling and its translations`.
