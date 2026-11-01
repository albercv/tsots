"""Ventana Programadas…: lo pendiente en el servicio, en un calendario de mes.

Muestra una etiqueta por vídeo y hora dentro de cada día y deja cancelar
cada publicación. Lo pide al servicio al abrirse y al pulsar Actualizar,
siempre en segundo plano (`segundo_plano`). Al cancelar algo programado
desde la app, olvida su entrada en el registro del vídeo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from videopipeline.i18n import N_, _
from videopipeline.redes import proveedor as proveedores
from videopipeline.redes import registro
from videopipeline.redes.modelo import (
    ETIQUETAS_FACEBOOK,
    ETIQUETAS_INSTAGRAM,
    ETIQUETAS_TIKTOK,
    ORDEN,
    ModoFacebook,
    ModoInstagram,
    ModoTikTok,
    Plataforma,
    Programada,
)

from .. import credenciales, segundo_plano
from .. import cuentas as consulta_cuentas
from ..cuentas import COLOR_AVISO, COLOR_ERROR, COLOR_OK, COLOR_SECUNDARIO
from ..settings import Ajustes
from .dialogo_publicar import zona_local

log = logging.getLogger(__name__)

Fabrica = Callable[[str, str, dict], proveedores.Proveedor]

MESES = (N_("Enero"), N_("Febrero"), N_("Marzo"), N_("Abril"), N_("Mayo"), N_("Junio"),
         N_("Julio"), N_("Agosto"), N_("Septiembre"), N_("Octubre"), N_("Noviembre"),
         N_("Diciembre"))
DIAS = (N_("Lun"), N_("Mar"), N_("Mié"), N_("Jue"), N_("Vie"), N_("Sáb"), N_("Dom"))
# Siglas de cada red en las etiquetas, que son estrechas (marcas: no se
# traducen). El nombre entero sale en el tooltip y en el detalle.
SIGLAS = {Plataforma.TIKTOK: "TT", Plataforma.YOUTUBE: "YT", Plataforma.INSTAGRAM: "IG",
          Plataforma.X: "X", Plataforma.FACEBOOK: "FB"}
# Etiquetas por día antes de resumir el resto en «+N más».
MAX_ETIQUETAS = 3
ESTILO_ETIQUETA = (
    "QPushButton { text-align: left; padding: 1px 4px; border: none;"
    " border-left: 3px solid #f59e0b; background: rgba(245, 158, 11, 0.22); }")


@dataclass
class Grupo:
    """Lo programado de un mismo vídeo a la misma hora: la app sube una vez
    por red, así que un vídeo en tres redes son tres trabajos."""

    fecha: datetime  # en la zona del Mac
    titulo: str
    trabajos: list[Programada] = field(default_factory=list)

    @property
    def plataformas(self) -> list[Plataforma]:
        propias = {p for t in self.trabajos for p in t.plataformas}
        return [p for p in ORDEN if p in propias]

    @property
    def texto(self) -> str:
        """Dos líneas: la hora y las siglas de las redes, que siempre caben, y
        el título, que se recorta si no cabe."""
        redes = " ".join(SIGLAS[p] for p in self.plataformas)
        return f"{self.fecha:%H:%M} · {redes}\n{self.titulo or _('(sin título)')}"

    @property
    def descripcion(self) -> str:
        redes = ", ".join(p.nombre for p in self.plataformas)
        return f"{self.fecha:%H:%M} · {redes} · {self.titulo or _('(sin título)')}"


def agrupar(programadas: list[Programada], zona: tzinfo) -> dict[date, list[Grupo]]:
    """Grupos por día (en la zona del Mac), en orden de hora; dentro de cada
    grupo, los trabajos en el orden de publicación de sus redes."""
    grupos: dict[tuple[datetime, str], Grupo] = {}
    orden = sorted(programadas, key=lambda t: (
        t.fecha, min((ORDEN.index(p) for p in t.plataformas), default=len(ORDEN))))
    for trabajo in orden:
        local = trabajo.fecha.astimezone(zona)
        grupos.setdefault((local, trabajo.titulo), Grupo(local, trabajo.titulo)
                          ).trabajos.append(trabajo)
    por_dia: dict[date, list[Grupo]] = {}
    for grupo in grupos.values():
        por_dia.setdefault(grupo.fecha.date(), []).append(grupo)
    return por_dia


def _modo(plataforma: Plataforma, valor: str) -> str:
    try:
        if plataforma == Plataforma.TIKTOK:
            return _(ETIQUETAS_TIKTOK[ModoTikTok(valor)])
        if plataforma == Plataforma.INSTAGRAM:
            return _(ETIQUETAS_INSTAGRAM[ModoInstagram(valor)])
        if plataforma == Plataforma.FACEBOOK:
            return _(ETIQUETAS_FACEBOOK[ModoFacebook(valor)])
    except ValueError:
        pass
    return ""


def describir_trabajo(trabajo: Programada) -> str:
    """«TikTok · Borrador (lo terminas en la app), YouTube»."""
    partes = []
    for plataforma in ORDEN:
        if plataforma in trabajo.plataformas:
            modo = _modo(plataforma, trabajo.modos.get(plataforma, ""))
            partes.append(f"{plataforma.nombre} · {modo}" if modo else plataforma.nombre)
    return ", ".join(partes)


class CeldaDia(QFrame):
    """Un día del calendario: su número y sus etiquetas."""

    def __init__(self, dia: date, del_mes: bool, hoy: bool, parent=None):
        super().__init__(parent)
        self.dia = dia
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumSize(110, 84)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.caja = QVBoxLayout(self)
        self.caja.setContentsMargins(3, 2, 3, 2)
        self.caja.setSpacing(2)
        numero = QLabel(str(dia.day))
        estilo = "font-weight: bold;"
        if hoy:
            estilo += f" color: {COLOR_OK};"
        elif not del_mes:
            estilo += f" color: {COLOR_SECUNDARIO};"
        numero.setStyleSheet(estilo)
        self.caja.addWidget(numero)
        self.caja.addStretch(1)

    def poner(self, grupos: list[Grupo], al_pulsar: Callable[[list[Grupo]], None]) -> None:
        visibles = grupos if len(grupos) <= MAX_ETIQUETAS + 1 else grupos[:MAX_ETIQUETAS]
        for grupo in visibles:
            self._boton(grupo.texto, lambda g=grupo: al_pulsar([g]), grupo.descripcion)
        if len(visibles) < len(grupos):
            self._boton(_("+{n} más").format(n=len(grupos) - len(visibles)),
                        lambda: al_pulsar(grupos))

    def _boton(self, texto: str, accion: Callable[[], None], ayuda: str = "") -> None:
        boton = QPushButton(texto)
        boton.setFlat(True)
        boton.setStyleSheet(ESTILO_ETIQUETA)
        boton.setToolTip(ayuda or texto)
        boton.setCursor(Qt.CursorShape.PointingHandCursor)
        # Que un título largo no ensanche la columna.
        boton.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        boton.clicked.connect(accion)
        self.caja.insertWidget(self.caja.count() - 1, boton)


class DialogoProgramadas(QDialog):
    def __init__(self, ajustes: Ajustes, llavero=credenciales, fabrica: Fabrica | None = None,
                 zona: tzinfo | None = None, hoy: date | None = None, parent=None):
        super().__init__(parent)
        self.ajustes = ajustes
        self.llavero = llavero
        self.fabrica = fabrica or (lambda nombre, clave, datos: proveedores.crear(
            nombre, clave, datos))
        self.zona = zona or zona_local()
        self.hoy = hoy or datetime.now(self.zona).date()
        self.mes = self.hoy.replace(day=1)
        self._programadas: list[Programada] = []
        self._ocupado = False
        self.celdas: dict[date, CeldaDia] = {}
        self.setWindowTitle(_("Programadas"))
        self.setMinimumSize(860, 700)
        self.resize(1040, 760)

        raiz = QVBoxLayout(self)
        cabecera = QHBoxLayout()
        self.boton_anterior = QPushButton(_("‹ Anterior"))
        self.boton_anterior.clicked.connect(self.anterior)
        self.etiqueta_mes = QLabel()
        self.etiqueta_mes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.etiqueta_mes.setStyleSheet("font-weight: bold; font-size: 15px;")
        self.boton_siguiente = QPushButton(_("Siguiente ›"))
        self.boton_siguiente.clicked.connect(self.siguiente)
        cabecera.addWidget(self.boton_anterior)
        cabecera.addWidget(self.etiqueta_mes, 1)
        cabecera.addWidget(self.boton_siguiente)
        raiz.addLayout(cabecera)

        self.rejilla = QGridLayout()
        self.rejilla.setSpacing(2)
        for columna, dia in enumerate(DIAS):
            nombre = QLabel(_(dia))
            nombre.setAlignment(Qt.AlignmentFlag.AlignCenter)
            nombre.setStyleSheet(f"color: {COLOR_SECUNDARIO};")
            self.rejilla.addWidget(nombre, 0, columna)
            self.rejilla.setColumnStretch(columna, 1)
        raiz.addLayout(self.rejilla, 1)

        self.etiqueta_estado = QLabel()
        self.etiqueta_estado.setWordWrap(True)
        self.etiqueta_estado.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        raiz.addWidget(self.etiqueta_estado)

        pie = QHBoxLayout()
        self.etiqueta_zona = QLabel(_("Hora de tu Mac ({zona})").format(
            zona=getattr(self.zona, "key", None) or str(self.zona)))
        self.etiqueta_zona.setStyleSheet(f"color: {COLOR_SECUNDARIO};")
        self.boton_actualizar = QPushButton(_("Actualizar"))
        self.boton_actualizar.clicked.connect(self.actualizar)
        boton_cerrar = QPushButton(_("Cerrar"))
        boton_cerrar.clicked.connect(self.reject)
        pie.addWidget(self.etiqueta_zona, 1)
        pie.addWidget(self.boton_actualizar)
        pie.addWidget(boton_cerrar)
        raiz.addLayout(pie)

        self._pintar()
        self.actualizar()

    # --- navegación ---

    def anterior(self) -> None:
        self.mes = (self.mes - timedelta(days=1)).replace(day=1)
        self._pintar()

    def siguiente(self) -> None:
        self.mes = (self.mes + timedelta(days=32)).replace(day=1)
        self._pintar()

    def _pintar(self) -> None:
        self.etiqueta_mes.setText(f"{_(MESES[self.mes.month - 1])} {self.mes.year}")
        for celda in self.celdas.values():
            self.rejilla.removeWidget(celda)
            celda.deleteLater()
        self.celdas = {}
        grupos = agrupar(self._programadas, self.zona)
        inicio = self.mes - timedelta(days=self.mes.weekday())  # lunes
        for indice in range(42):  # seis semanas: cabe cualquier mes
            dia = inicio + timedelta(days=indice)
            celda = CeldaDia(dia, dia.month == self.mes.month, dia == self.hoy)
            celda.poner(grupos.get(dia, []), self._abrir)
            self.rejilla.addWidget(celda, 1 + indice // 7, indice % 7)
            self.celdas[dia] = celda

    # --- consulta ---

    def _estado(self, texto: str, color: str = "") -> None:
        self.etiqueta_estado.setText(texto)
        self.etiqueta_estado.setStyleSheet(f"color: {color};" if color else "")

    def _ocupar(self, ocupado: bool) -> None:
        self._ocupado = ocupado
        self.boton_actualizar.setEnabled(not ocupado)

    def actualizar(self) -> None:
        if self._ocupado:
            return
        self._ocupar(True)
        self._estado(_("Consultando…"))
        llavero, fabrica = self.llavero, self.fabrica
        nombre, datos = self.ajustes.proveedor_redes, self.ajustes.ajustes_proveedor()
        segundo_plano.en_segundo_plano(
            lambda: consulta_cuentas.programadas(llavero, fabrica, nombre, datos),
            self._al_consultar, "tsots-programadas")

    def _al_consultar(self, resultado) -> None:
        self._ocupar(False)
        if isinstance(resultado, BaseException):  # `programadas` no lanza; por si acaso
            resultado = (None, type(resultado).__name__)
        lista, error = resultado
        if lista is None:
            self._estado(error, COLOR_ERROR)
            return
        self._programadas = list(lista)
        self.ajustes.podar_programadas({p.referencia for p in lista})
        self._estado(_("{n} publicaciones pendientes.").format(n=len(lista)) if lista
                     else _("No hay nada programado."))
        self._pintar()

    # --- detalle y cancelar ---

    def _abrir(self, grupos: list[Grupo]) -> None:
        self.detalle(grupos).exec()

    def detalle(self, grupos: list[Grupo]) -> QDialog:
        """Ventana con los trabajos de esos grupos y un Cancelar por trabajo."""
        dialogo = QDialog(self)
        dialogo.setWindowTitle(_("Programada"))
        dialogo.setMinimumWidth(420)
        caja = QVBoxLayout(dialogo)
        trabajos: list[Programada] = []
        for grupo in grupos:
            titulo = QLabel(grupo.titulo or _("(sin título)"))
            titulo.setStyleSheet("font-weight: bold;")
            titulo.setWordWrap(True)
            caja.addWidget(titulo)
            caja.addWidget(QLabel(f"{grupo.fecha:%d/%m/%Y %H:%M}"))
            for trabajo in grupo.trabajos:
                fila = QHBoxLayout()
                fila.addWidget(QLabel(describir_trabajo(trabajo)), 1)
                boton = QPushButton(_("Cancelar"))
                boton.setObjectName(f"cancelar_{trabajo.referencia}")
                boton.clicked.connect(
                    lambda _c=False, t=trabajo: (dialogo.accept(), self.cancelar([t])))
                fila.addWidget(boton)
                caja.addLayout(fila)
                trabajos.append(trabajo)
        botones = QHBoxLayout()
        botones.addStretch(1)
        if len(trabajos) > 1:
            todas = QPushButton(_("Cancelar todas"))
            todas.clicked.connect(lambda: (dialogo.accept(), self.cancelar(trabajos)))
            botones.addWidget(todas)
        cerrar = QPushButton(_("Cerrar"))
        cerrar.setDefault(True)
        cerrar.clicked.connect(dialogo.reject)
        botones.addWidget(cerrar)
        caja.addLayout(botones)
        return dialogo

    def cancelar(self, trabajos: list[Programada]) -> None:
        """Pide confirmación y cancela en segundo plano."""
        if self._ocupado or not trabajos:
            return
        lineas = "\n".join(
            "• " + _("{redes}: «{titulo}» el {fecha}").format(
                redes=describir_trabajo(t), titulo=t.titulo or _("(sin título)"),
                fecha=t.fecha.astimezone(self.zona).strftime(_("%d/%m a las %H:%M")))
            for t in trabajos)
        respuesta = QMessageBox.question(
            self, _("Cancelar publicación"),
            _("¿Cancelar estas publicaciones?\n\n{lista}\n\nEl servicio devuelve el "
              "crédito.").format(lista=lineas),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        self._ocupar(True)
        self._estado(_("Cancelando…"))
        llavero, fabrica = self.llavero, self.fabrica
        nombre, datos = self.ajustes.proveedor_redes, self.ajustes.ajustes_proveedor()
        referencias = [t.referencia for t in trabajos]
        segundo_plano.en_segundo_plano(
            lambda: consulta_cuentas.cancelar(llavero, fabrica, nombre, datos, referencias),
            self._al_cancelar, "tsots-cancelar")

    def _al_cancelar(self, resultado) -> None:
        self._ocupar(False)
        if isinstance(resultado, BaseException):  # `cancelar` no lanza; por si acaso
            resultado = ([], type(resultado).__name__)
        canceladas, error = resultado
        for referencia in canceladas:
            log.info("Cancelada la programada %s", referencia)
            video = self.ajustes.olvidar_programada(referencia)
            if video:
                try:
                    registro.olvidar(Path(video), referencia)
                except OSError:
                    # El servicio ya la canceló; solo queda un aviso de más.
                    log.warning("No se pudo limpiar el registro de %s", video, exc_info=True)
        self._programadas = [p for p in self._programadas if p.referencia not in canceladas]
        self._pintar()
        if error:
            self._estado(_("No se pudo cancelar: {motivo}").format(motivo=error), COLOR_ERROR)
        else:
            self._estado(_("Canceladas: {n}.").format(n=len(canceladas)), COLOR_AVISO)
