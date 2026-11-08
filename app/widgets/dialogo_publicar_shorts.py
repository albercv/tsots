"""Publicar en lote los shorts de un vídeo largo, cada uno con su fecha.

Es el diálogo de publicar de un vídeo (`DialogoPublicar`) con la lista de
shorts en lugar de los textos y de la fila «Cuándo»: las plataformas, sus
modos, la ubicación, la clave, el aviso de duplicados, el hilo de subida y su
progreso son los mismos. Los shorts se envían uno detrás de otro; el texto de
cada uno viene de su `.md` y cada uno lleva su `Opciones.programada`.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from videopipeline.caption import Caption
from videopipeline.i18n import _
from videopipeline.redes import limites, registro
from videopipeline.redes.modelo import ORDEN, Plataforma, Resultado
from videopipeline.shorts import Corto

from .. import segundo_plano
from ..cuentas import COLOR_AVISO, COLOR_ERROR, COLOR_OK, COLOR_SECUNDARIO
from .dialogo_publicar import DialogoPublicar, HiloPublicacion, fecha_local, log
from .selector_ubicacion import describir_ubicacion

FILAS_VISIBLES = 6  # a partir de aquí, la lista se desplaza


@dataclass(eq=False)
class Fila:
    corto: Corto
    casilla: QCheckBox
    campo: QDateTimeEdit
    estado: QLabel
    enviado: bool = False  # su `estado` muestra el resultado de un envío


class DialogoPublicarShorts(DialogoPublicar):
    def __init__(self, cortos: list[Corto], ajustes, *args, **kwargs):
        # Antes de `super().__init__`: el constructor base ya llama a `_refrescar`.
        self._cortos = list(cortos)
        self.filas: list[Fila] = []
        self._duraciones: dict[Path, float] | None = None  # `None`: aún midiendo
        self._enlote = False
        self._cola: list[tuple[Fila, list[Plataforma], datetime]] = []
        self._prefijo = ""
        self._proveedor_lote = None
        self._resultados_lote: dict[Fila, dict[Plataforma, Resultado]] = {}
        primero = next((c for c in self._cortos if c.caption), self._cortos[0])
        super().__init__(primero.mp4, primero.caption or Caption("", "", [], []),
                         ajustes, *args, **kwargs)
        self.setWindowTitle(_("Publicar shorts"))
        self.setMinimumWidth(880)
        self.cabecera.setText(self._cortos[0].mp4.parent.name)
        # Lo que el diálogo de un vídeo pide aquí lo pone cada short.
        for widget in (self.grupo_textos, self.aviso_publicado, self.etiqueta_cuando,
                       self.radio_ahora, self.radio_programar, self.campo_fecha,
                       self.aviso_fecha, self.boton_ubicacion):
            widget.hide()
        # LinkedIn no: su post y sus fotos son del vídeo largo, no de los shorts.
        self._linkedin = None
        for widget in (self.casillas[Plataforma.LINKEDIN], self.modos[Plataforma.LINKEDIN],
                       self.estados[Plataforma.LINKEDIN]):
            widget.hide()
        self.layout().insertWidget(1, self._crear_lista())
        self._refrescar()

    # --- la lista ---

    def _crear_lista(self) -> QGroupBox:
        grupo = QGroupBox(_("Shorts: elige cuáles y cuándo"))
        cuerpo = QWidget()
        rejilla = QGridLayout(cuerpo)
        rejilla.setColumnStretch(0, 2)
        rejilla.setColumnStretch(3, 3)
        for i, corto in enumerate(self._cortos):
            casilla = QCheckBox(corto.titulo)
            casilla.setToolTip(corto.mp4.name)
            campo = self._nuevo_campo_fecha(self._fecha_inicial + timedelta(days=i))
            estado = QLabel()
            estado.setWordWrap(True)
            estado.setOpenExternalLinks(True)
            fila = Fila(corto, casilla, campo, estado)
            if corto.caption is None:
                casilla.setEnabled(False)
                campo.setEnabled(False)
                estado.setText(html.escape(_(
                    "sin caption: vuelve a crear los shorts con «Título, caption y "
                    "hashtags» activado")))
                estado.setStyleSheet(f"color: {COLOR_SECUNDARIO};")
            else:
                casilla.setChecked(True)
            casilla.toggled.connect(self._refrescar)
            campo.dateTimeChanged.connect(self._refrescar)
            rejilla.addWidget(casilla, i, 0)
            rejilla.addWidget(QLabel(limites.duracion_legible(corto.duracion)), i, 1)
            rejilla.addWidget(campo, i, 2)
            rejilla.addWidget(estado, i, 3)
            self.filas.append(fila)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QFrame.Shape.NoFrame)
        desplazable.setWidget(cuerpo)
        # Una fila con el motivo en dos o tres líneas mide unos 48 px.
        desplazable.setMinimumHeight(48 * min(len(self._cortos), FILAS_VISIBLES) + 8)
        QVBoxLayout(grupo).addWidget(desplazable)
        return grupo

    # --- duración (X) ---

    def _medir_video(self) -> None:
        """Mide todos los shorts de una vez; la base mediría solo el primero."""
        self.duracion = 0.0  # lo de X se mira short a short (`_plataformas_de`)
        medir, mp4s = self._medir, [c.mp4 for c in self._cortos]
        segundo_plano.en_segundo_plano(
            lambda: [float(medir(m) or 0.0) for m in mp4s],
            lambda r: self._al_medir_todos(mp4s, r), "tsots-ffprobe")

    def _al_medir_todos(self, mp4s: list[Path], resultado) -> None:
        # Una duración ilegible no bloquea, como en el diálogo de un vídeo.
        self._duraciones = dict(zip(mp4s, resultado if isinstance(resultado, list)
                                    else [0.0] * len(mp4s)))
        self._refrescar()

    def _plataformas_de(self, fila: Fila) -> tuple[list[Plataforma], str]:
        """Las plataformas marcadas que admite este short, y por qué se quita X."""
        plataformas, motivo = self.plataformas(), ""
        if Plataforma.X in plataformas:
            try:
                tamano = fila.corto.mp4.stat().st_size
            except OSError:
                tamano = None
            motivo = limites.motivo_no_admite_x(
                (self._duraciones or {}).get(fila.corto.mp4), tamano,
                self.ajustes.x_premium)
            if motivo:
                plataformas.remove(Plataforma.X)
        return plataformas, motivo

    # --- estado ---

    @property
    def publicando(self) -> bool:
        return self._hilo is not None or self._enlote

    def _elegidas(self) -> list[Fila]:
        return [f for f in self.filas if f.casilla.isChecked()]

    def _nota(self, fila: Fila) -> tuple[str, str, bool]:
        """(texto, color, bloquea) de un short marcado."""
        plataformas, motivo_x = self._plataformas_de(fila)
        partes: list[tuple[str, bool]] = []
        motivo_fecha = self._motivo_de(self._fecha_de(fila.campo))
        if motivo_fecha:
            partes.append((motivo_fecha, True))
        if motivo_x:
            partes.append((motivo_x if plataformas else motivo_x + " " + _(
                "No queda ninguna plataforma para este short."), not plataformas))
        previas = [p.nombre for p in ORDEN if p in registro.ultimas(fila.corto.mp4)
                   and p in plataformas]
        if previas:
            partes.append((_("⚠ ya se publicó o programó en: {lista}").format(
                lista=", ".join(previas)), False))
        return (" · ".join(t for t, _b in partes), COLOR_AVISO if partes else "",
                any(b for _t, b in partes))

    def _refrescar(self, *args) -> None:
        bloqueos = self._refrescar_plataformas()
        listo, _motivo = self._listo()
        bloqueado = False
        for fila in self.filas:
            if fila.corto.caption is None:
                continue
            fila.casilla.setEnabled(not self.publicando)
            fila.campo.setEnabled(fila.casilla.isChecked() and not self.publicando)
            if self.publicando or (fila.enviado and not fila.casilla.isChecked()):
                continue  # muestra el progreso o el resultado, no el estado previo
            fila.enviado = False
            texto, color, bloquea = (self._nota(fila) if fila.casilla.isChecked()
                                     else ("", "", False))
            fila.estado.setText(html.escape(texto))
            fila.estado.setToolTip("")
            fila.estado.setStyleSheet(f"color: {color};" if color else "")
            bloqueado = bloqueado or bloquea
        elegidas = self._elegidas()
        self.boton_publicar.setText(_("Programar {n} shorts").format(n=len(elegidas)))
        self.boton_publicar.setEnabled(
            listo and not self.publicando and bool(elegidas) and bool(self.plataformas())
            and not bloqueos and not bloqueado and self._duraciones is not None)

    def _refrescar_aviso(self) -> None:
        """Los duplicados se avisan short a short (`_nota`)."""

    def _poner_estado(self, texto: str, color: str = "") -> None:
        super()._poner_estado(f"{self._prefijo}: {texto}" if self._prefijo and texto
                              else texto, color)

    # --- confirmar y enviar ---

    def _envios(self) -> list[tuple[Fila, list[Plataforma], datetime]]:
        return [(f, self._plataformas_de(f)[0], self._fecha_de(f.campo))
                for f in self._elegidas()]

    def _confirmar(self) -> bool:
        formato = _("%d/%m/%Y %H:%M")
        elegidas = set(self.plataformas())
        lineas, previas = [], []
        for fila, plataformas, fecha in self._envios():
            lineas.append("• " + _("{titulo}: {fecha} en {lista}").format(
                titulo=fila.corto.titulo, fecha=fecha_local(fecha, self._zona, formato),
                lista=", ".join(p.nombre for p in plataformas)))
            ultimas = {p for p in registro.ultimas(fila.corto.mp4) if p in plataformas}
            if ultimas:
                previas.append(_("«{titulo}» ya estaba en {lista}").format(
                    titulo=fila.corto.titulo,
                    lista=", ".join(p.nombre for p in ORDEN if p in ultimas)))
        texto = _("Se programarán {n} shorts:\n\n{lista}\n\n{resumen}").format(
            n=len(lineas), lista="\n".join(lineas), resumen=self._resumen())
        if set(self.ubicacion().plataformas()) & elegidas:
            texto += "\n\n" + _("Ubicación: {ubicacion}").format(
                ubicacion=describir_ubicacion(self.ubicacion(), elegidas))
        if previas:
            texto += "\n\n" + _("⚠ Ya publicado o programado antes:") + "\n" + "\n".join(
                "• " + p for p in previas) + "\n" + _("Si sigues, saldrán repetidos.")
        texto += "\n\n" + _("¿Programarlos?")
        return QMessageBox.question(
            self, _("Publicar shorts"), texto,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes

    def publicar(self) -> None:
        if self.publicando:
            return
        self._refrescar()  # una hora elegida pudo quedarse corta mientras tanto
        if not self.boton_publicar.isEnabled():
            _listo, motivo = self._listo()
            self._poner_estado(motivo or _(
                "Marca al menos un short y una plataforma."), COLOR_AVISO)
            return
        nombre = self.ajustes.proveedor_redes
        plataformas = self.plataformas()
        opciones = replace(self.opciones(),
                           ubicacion=self._ubicacion_propia or self._guardada())
        envios = self._envios()
        self._en_curso, self._opciones_en_curso = plataformas, opciones
        self._poner_estado(_("Esperando confirmación…"))
        if not self._confirmar():
            self._terminar_sin_enviar(_("Publicación cancelada: no se ha enviado nada."),
                                      COLOR_AVISO, marcar=False)
            return
        motivo = next((m for _f, _p, fecha in envios if (m := self._motivo_de(fecha))), "")
        if motivo:  # la confirmación pudo quedarse abierta un rato
            self._terminar_sin_enviar(motivo, COLOR_AVISO, marcar=False)
            return
        self._cerrar_diario()
        self._abrir_diario(self._cortos[0].mp4.parent, opciones)  # antes de leer la clave
        self._registrar_inicio_lote(envios, opciones)
        proveedor = self._abrir_servicio(nombre)
        if proveedor is None:
            return
        self._recordar_eleccion(opciones)
        self._proveedor_lote, self._opciones_lote, self._nombre_lote = (
            proveedor, opciones, nombre)
        self._cola = list(envios)
        self._total = len(envios)
        self._resultados_lote = {}
        self._enlote = True
        self._bloquear(True)
        self._siguiente()

    def _registrar_inicio_lote(self, envios, opciones) -> None:
        log.info("Inicio de la publicación de %d shorts de %s", len(envios),
                 self._cortos[0].mp4.parent)
        log.info("Plataformas y modos: %s", ", ".join(
            f"{p.nombre} [{self._modo_visible(p, opciones)}]" for p in self.plataformas()))
        for fila, plataformas, fecha in envios:
            log.info("Short %s · %s · %s", fila.corto.mp4.name, fecha.isoformat(),
                     ", ".join(p.nombre for p in plataformas))

    def _cargar_corto(self, corto: Corto) -> None:
        """Pone en los campos del diálogo base los textos de este short."""
        self.video = corto.mp4
        self.campo_titulo.setText(corto.caption.titulo)
        self.campo_caption.setPlainText(corto.caption.caption)
        self.campo_hashtags.setText(corto.caption.hashtags_texto)
        self._palabras_clave = tuple(corto.caption.palabras_clave)
        self._rellenar_x()

    def _siguiente(self) -> None:
        fila, plataformas, fecha = self._cola.pop(0)
        self._fila_actual = fila
        self._cargar_corto(fila.corto)
        opciones = replace(self._opciones_lote, programada=fecha)
        self._reiniciar(plataformas, opciones)
        self._prefijo = _("Short {n} de {total}").format(
            n=self._total - len(self._cola), total=self._total)
        fila.estado.setText(html.escape(_("Subiendo…")))
        fila.estado.setStyleSheet("")
        self._poner_estado(_("Programando: {lista}…").format(
            lista=", ".join(p.nombre for p in plataformas)))
        log.info("%s: %s", self._prefijo, fila.corto.mp4.name)
        # El registro se cierra con el último hilo: cerrarlo con el de un short
        # intermedio lo quitaría a los siguientes (ver `_soltar`).
        self._hilo = HiloPublicacion(
            self._proveedor_lote, self.publicacion(), opciones, plataformas,
            self._nombre_lote, None if self._cola else self._diario, self._ahora)
        self._hilo.progreso.connect(self._al_progresar)
        self._hilo.terminado.connect(self._al_terminar)
        self._hilo.start()

    def _al_terminar(self, resultados: dict) -> None:
        self._hilo = None  # lo suelta `_soltar` cuando acaba del todo
        fila = self._fila_actual
        self.resultados = {
            p: resultados.get(p) or Resultado(p, ok=False, error=_("No se llegó a enviar."))
            for p in self._en_curso}
        self._resultados_lote[fila] = self.resultados
        buenos = sum(1 for r in self.resultados.values() if r.ok)
        color = (COLOR_OK if buenos == len(self.resultados)
                 else COLOR_AVISO if buenos else COLOR_ERROR)
        fila.estado.setText(" · ".join(
            f"{html.escape(p.nombre)}: {self._texto_resultado(p, r)[0]}"
            for p, r in self.resultados.items()))
        fila.estado.setToolTip("\n".join(r.error for r in self.resultados.values()
                                         if r.error))
        fila.estado.setStyleSheet(f"color: {color};")
        fila.enviado = True
        log.info("%s: %s", fila.corto.mp4.name, "; ".join(
            f"{p.nombre} " + ("OK" if r.ok else "pendiente" if r.pendiente
                              else "error: " + r.error)
            for p, r in self.resultados.items()))
        if self._cola:
            self._siguiente()
        else:
            self._al_terminar_lote()

    def _al_terminar_lote(self) -> None:
        self._enlote = False
        self._prefijo = ""
        self._proveedor_lote = None  # suelta la clave que guarda el proveedor
        rondas = list(self._resultados_lote.items())
        completos = sum(1 for _f, rs in rondas if all(r.ok for r in rs.values()))
        hay_pendientes = any(r.pendiente for _f, rs in rondas for r in rs.values())
        for fila, rs in rondas:
            # Lo que salió, o pudo salir, no se vuelve a marcar: evita duplicados.
            if any(r.ok or r.pendiente for r in rs.values()):
                fila.casilla.blockSignals(True)
                fila.casilla.setChecked(False)
                fila.casilla.blockSignals(False)
        self._con_resultado.clear()  # las plataformas vuelven a mostrar su cuenta
        if completos == 0 and not hay_pendientes:
            texto, color = _("Falló en todos"), COLOR_ERROR
        else:
            texto = _("Programados {ok} de {total} shorts").format(
                ok=completos, total=len(rondas))
            color = COLOR_OK if completos == len(rondas) else COLOR_AVISO
        self._poner_estado(texto, color)
        log.info("Resumen: %s", texto)
        log.info("Fin")
        self._cerrar_diario()
        self._bloquear(False)
        self.publicacion_terminada.emit({f.corto.mp4: rs for f, rs in rondas})
