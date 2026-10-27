from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from videopipeline.i18n import _
from videopipeline.redes import proveedor as proveedores
from videopipeline.redes.limites import MAX_DURACION_X, MAX_TAMANO_X, duracion_legible
from videopipeline.redes.modelo import (
    CATEGORIAS_YOUTUBE,
    ETIQUETAS_FACEBOOK,
    ETIQUETAS_INSTAGRAM,
    ETIQUETAS_TIKTOK,
    ORDEN,
    Cuenta,
    ModoFacebook,
    ModoInstagram,
    ModoTikTok,
    Pagina,
    Plataforma,
)
from videopipeline.redes.textos import MAX_TEXTO_X

from .. import credenciales, segundo_plano
from .. import cuentas as consulta_cuentas
from ..cuentas import COLOR_AVISO, COLOR_ERROR, COLOR_OK, COLOR_SECUNDARIO
from ..settings import Ajustes

Fabrica = Callable[[str, str, dict], proveedores.Proveedor]


class DialogoRedes(QDialog):
    """Servicio de publicación, perfil, API key (al Llavero), cuentas
    conectadas, página de Facebook y modos por defecto.

    La clave se escribe aquí y va directa al Llavero: el diálogo nunca la
    muestra ni la lee de vuelta; solo comprueba si existe. «Comprobar
    conexión» pregunta al servicio qué cuentas hay conectadas, en segundo
    plano, con la clave recién escrita o la del Llavero.
    """

    def __init__(self, ajustes: Ajustes, llavero=credenciales, fabrica: Fabrica | None = None,
                 parent=None):
        super().__init__(parent)
        self.ajustes = ajustes
        self.llavero = llavero
        self.fabrica = fabrica or (lambda nombre, clave, datos: proveedores.crear(
            nombre, clave, datos))
        self._consulta_n = 0
        # Última comprobación buena: (perfil con que se hizo, cuentas). Se
        # guarda al pulsar Guardar.
        self._comprobadas: tuple[str, dict[Plataforma, Cuenta | None]] | None = None
        self._paginas: dict[str, Pagina] = {}
        self.setWindowTitle(_("Redes sociales"))
        self.setMinimumWidth(600)
        raiz = QVBoxLayout(self)

        ayuda = QLabel(_(
            "TSOTS publica a través de un servicio que ya tiene permiso de "
            "TikTok, YouTube, Instagram, X y Facebook. Crea una cuenta en el "
            "servicio, conecta allí tus redes y pega aquí su API key: se guarda "
            "en el Llavero de macOS, nunca en la app."))
        ayuda.setWordWrap(True)
        raiz.addWidget(ayuda)

        grupo_cuenta = QGroupBox(_("Cuenta"))
        formulario = QFormLayout(grupo_cuenta)
        formulario.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.combo_proveedor = QComboBox()
        for nombre in proveedores.PROVEEDORES:
            self.combo_proveedor.addItem(proveedores.nombre_visible(nombre), nombre)
        self.combo_proveedor.setCurrentIndex(
            max(0, self.combo_proveedor.findData(ajustes.proveedor_redes)))
        formulario.addRow(_("Servicio:"), self.combo_proveedor)

        self.campo_perfil = QLineEdit()
        self.campo_perfil.setPlaceholderText(_("Nombre del perfil en el servicio"))
        self.campo_perfil.setToolTip(_(
            "El perfil del servicio donde conectaste tus redes."))
        formulario.addRow(_("Perfil:"), self.campo_perfil)
        # Qué es el perfil lo explica cada proveedor (texto propio del servicio).
        self.ayuda_perfil = QLabel()
        self.ayuda_perfil.setWordWrap(True)
        self.ayuda_perfil.setStyleSheet(f"color: {COLOR_SECUNDARIO};")
        formulario.addRow("", self.ayuda_perfil)
        self.aviso_perfil = QLabel(_(
            "⚠ Eso parece un email. El perfil no es el email de tu cuenta: es el "
            "nombre del perfil dentro del servicio."))
        self.aviso_perfil.setWordWrap(True)
        self.aviso_perfil.setStyleSheet(f"color: {COLOR_AVISO};")
        self.aviso_perfil.hide()
        formulario.addRow("", self.aviso_perfil)
        self.campo_perfil.textChanged.connect(self._refrescar_perfil)

        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo_clave.setPlaceholderText(_("Pega la API key para guardarla"))
        formulario.addRow(_("API key:"), self.campo_clave)

        fila_estado = QHBoxLayout()
        self.etiqueta_clave = QLabel()
        self.boton_olvidar = QPushButton(_("Olvidar clave"))
        self.boton_olvidar.clicked.connect(self._olvidar_clave)
        fila_estado.addWidget(self.etiqueta_clave, 1)
        fila_estado.addWidget(self.boton_olvidar)
        formulario.addRow("", fila_estado)
        raiz.addWidget(grupo_cuenta)

        grupo_cuentas = QGroupBox(_("Cuentas conectadas"))
        caja_cuentas = QVBoxLayout(grupo_cuentas)
        rejilla = QGridLayout()
        rejilla.setColumnStretch(1, 1)
        rejilla.setVerticalSpacing(2)
        self.etiquetas_cuentas: dict[Plataforma, QLabel] = {}
        for fila, plataforma in enumerate(ORDEN):
            rejilla.addWidget(QLabel(plataforma.nombre), fila, 0)
            etiqueta = QLabel()
            etiqueta.setWordWrap(True)
            self.etiquetas_cuentas[plataforma] = etiqueta
            rejilla.addWidget(etiqueta, fila, 1)
        caja_cuentas.addLayout(rejilla)
        fila_consulta = QHBoxLayout()
        self.etiqueta_consulta = QLabel()
        self.etiqueta_consulta.setWordWrap(True)
        self.boton_comprobar = QPushButton(_("Comprobar conexión"))
        self.boton_comprobar.setToolTip(_(
            "Pregunta al servicio qué cuentas tienes conectadas y tus páginas de Facebook"))
        self.boton_comprobar.clicked.connect(self._comprobar)
        fila_consulta.addWidget(self.etiqueta_consulta, 1)
        fila_consulta.addWidget(self.boton_comprobar)
        caja_cuentas.addLayout(fila_consulta)
        raiz.addWidget(grupo_cuentas)


        grupo_defecto = QGroupBox(_("Al publicar"))
        formulario_defecto = QFormLayout(grupo_defecto)
        formulario_defecto.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.combo_tiktok = QComboBox()
        for modo in ModoTikTok:
            self.combo_tiktok.addItem(_(ETIQUETAS_TIKTOK[modo]), modo.value)
        self.combo_tiktok.setCurrentIndex(
            self.combo_tiktok.findData(ajustes.tiktok_modo.value))
        formulario_defecto.addRow("TikTok:", self.combo_tiktok)
        self.combo_categoria = QComboBox()
        for codigo, nombre in CATEGORIAS_YOUTUBE.items():
            self.combo_categoria.addItem(_(nombre), codigo)
        indice = self.combo_categoria.findData(ajustes.youtube_categoria)
        if indice < 0:  # categoría guardada que no está en la lista
            self.combo_categoria.addItem(ajustes.youtube_categoria, ajustes.youtube_categoria)
            indice = self.combo_categoria.count() - 1
        self.combo_categoria.setCurrentIndex(indice)
        formulario_defecto.addRow(_("Categoría de YouTube:"), self.combo_categoria)
        self.combo_instagram = QComboBox()
        for modo in ModoInstagram:
            self.combo_instagram.addItem(_(ETIQUETAS_INSTAGRAM[modo]), modo.value)
        self.combo_instagram.setCurrentIndex(
            self.combo_instagram.findData(ajustes.instagram_modo.value))
        formulario_defecto.addRow("Instagram:", self.combo_instagram)
        self.combo_facebook = QComboBox()
        for modo in ModoFacebook:
            self.combo_facebook.addItem(_(ETIQUETAS_FACEBOOK[modo]), modo.value)
        self.combo_facebook.setCurrentIndex(
            self.combo_facebook.findData(ajustes.facebook_modo.value))
        self.casilla_x_premium = QCheckBox(_("Mi cuenta de X tiene Premium"))
        self.casilla_x_premium.setChecked(ajustes.x_premium)
        self.casilla_x_premium.setToolTip(_(
            "Con Premium, TSOTS deja pasar vídeos más largos y textos largos en un "
            "solo post."))
        self.nota_x_premium = QLabel()
        self.nota_x_premium.setStyleSheet(f"color: {COLOR_OK};")
        self.nota_x_premium.hide()
        fila_x = QHBoxLayout()
        fila_x.addWidget(self.casilla_x_premium)
        fila_x.addWidget(self.nota_x_premium, 1)
        formulario_defecto.addRow("X:", fila_x)
        self.ayuda_x = QLabel(_(
            "Sin Premium: vídeos de hasta {duracion} y {tamano} MB, posts de {caracteres} "
            "caracteres.").format(
            duracion=duracion_legible(MAX_DURACION_X), tamano=MAX_TAMANO_X // (1024 * 1024),
            caracteres=MAX_TEXTO_X))
        self.ayuda_x.setWordWrap(True)
        self.ayuda_x.setStyleSheet(f"color: {COLOR_SECUNDARIO};")
        formulario_defecto.addRow("", self.ayuda_x)
        formulario_defecto.addRow("Facebook:", self.combo_facebook)
        self.combo_pagina = QComboBox()
        self.combo_pagina.setToolTip(_(
            "Página de Facebook en la que se publica. La lista sale de las páginas "
            "conectadas en el servicio: pulsa «Comprobar conexión» para verla."))
        formulario_defecto.addRow(_("Página de Facebook:"), self.combo_pagina)
        self.campo_pagina_manual = QLineEdit()
        self.campo_pagina_manual.setPlaceholderText(_("ID de la página (un número)"))
        self.campo_pagina_manual.textChanged.connect(self._refrescar_pagina_manual)
        self.campo_pagina_manual.hide()
        formulario_defecto.addRow("", self.campo_pagina_manual)
        self.aviso_pagina = QLabel()
        self.aviso_pagina.setWordWrap(True)
        self.aviso_pagina.setStyleSheet(f"color: {COLOR_AVISO};")
        self.aviso_pagina.hide()
        formulario_defecto.addRow("", self.aviso_pagina)
        self.ayuda_pagina = QLabel(_(
            "Meta solo deja publicar en páginas, no en perfiles personales."))
        self.ayuda_pagina.setWordWrap(True)
        self.ayuda_pagina.setStyleSheet(f"color: {COLOR_SECUNDARIO};")
        formulario_defecto.addRow("", self.ayuda_pagina)
        raiz.addWidget(grupo_defecto)

        botones = QDialogButtonBox()
        self.boton_guardar = botones.addButton(_("Guardar"),
                                               QDialogButtonBox.ButtonRole.AcceptRole)
        self.boton_guardar.setDefault(True)
        botones.addButton(_("Cancelar"), QDialogButtonBox.ButtonRole.RejectRole)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        raiz.addWidget(botones)

        self.combo_proveedor.currentIndexChanged.connect(self._al_cambiar_proveedor)
        self._al_cambiar_proveedor()

    @property
    def proveedor(self) -> str:
        return str(self.combo_proveedor.currentData())

    def _al_cambiar_proveedor(self, *args) -> None:
        usa_perfil = proveedores.usa_perfil(self.proveedor)
        self.campo_perfil.setEnabled(usa_perfil)
        self.campo_perfil.setText(self.ajustes.perfil_de(self.proveedor))
        ayuda = proveedores.ayuda_perfil(self.proveedor) if usa_perfil else ""
        self.ayuda_perfil.setText(ayuda)
        self.ayuda_perfil.setVisible(bool(ayuda))
        self._refrescar_perfil()
        self.campo_clave.clear()
        self._refrescar_clave()
        self._consulta_n += 1  # una consulta en marcha de otro servicio ya no vale
        self._comprobadas = None
        self.boton_comprobar.setEnabled(True)
        self.campo_pagina_manual.clear()
        self.campo_pagina_manual.hide()
        self.aviso_pagina.hide()
        pagina = self.ajustes.pagina_facebook_de(self.proveedor)
        self._poner_paginas([pagina] if pagina else [], pagina.id if pagina else "")
        guardadas = (self.ajustes.cuentas_guardadas()
                     if self.proveedor == self.ajustes.proveedor_redes else None)
        if guardadas is not None:
            self._mostrar_cuentas(guardadas.cuentas)
            try:
                fecha = datetime.fromisoformat(guardadas.fecha).strftime("%d/%m/%Y %H:%M")
            except ValueError:
                fecha = guardadas.fecha
            self._poner_consulta(_("Última comprobación: {fecha}").format(fecha=fecha))
        else:
            self._mostrar_cuentas({})
            self._poner_consulta(_(
                "Sin comprobar. Pulsa «Comprobar conexión» para ver qué cuentas "
                "tienes conectadas."))

    # --- cuentas conectadas y página de Facebook ---

    def _poner_consulta(self, texto: str, color: str = COLOR_SECUNDARIO) -> None:
        self.etiqueta_consulta.setText(texto)
        self.etiqueta_consulta.setStyleSheet(f"color: {color};" if color else "")

    def _mostrar_cuentas(self, cuentas: dict[Plataforma, Cuenta | None]) -> None:
        servicio = proveedores.nombre_visible(self.proveedor)
        for plataforma, etiqueta in self.etiquetas_cuentas.items():
            if plataforma not in cuentas:
                etiqueta.setText("—")
                etiqueta.setStyleSheet(f"color: {COLOR_SECUNDARIO};")
                continue
            cuenta = cuentas[plataforma]
            texto, color = consulta_cuentas.describir(plataforma, cuenta, servicio)
            if cuenta is not None and not cuenta.reconectar:
                texto, color = "✓ " + texto, COLOR_OK
            etiqueta.setText(texto)
            etiqueta.setStyleSheet(f"color: {color};")

    def _poner_paginas(self, paginas: list[Pagina], elegida: str) -> None:
        """Rellena la lista de páginas. Se elige `elegida` si está, o la
        única que haya."""
        self._paginas = {p.id: p for p in paginas}
        self.combo_pagina.clear()
        self.combo_pagina.addItem(_("(sin elegir)"), "")
        for pagina in paginas:
            self.combo_pagina.addItem(pagina.visible, pagina.id)
        if elegida and elegida not in self._paginas:
            elegida = ""
        if not elegida and len(paginas) == 1:
            elegida = paginas[0].id
        self.combo_pagina.setCurrentIndex(max(0, self.combo_pagina.findData(elegida)))

    def _refrescar_pagina_manual(self, *args) -> None:
        texto = self.campo_pagina_manual.text().strip()
        if texto and not texto.isdigit():
            self.aviso_pagina.setText(_("⚠ El ID de una página solo tiene números."))
            self.aviso_pagina.show()

    def pagina_elegida(self) -> Pagina | None:
        manual = self.campo_pagina_manual.text().strip()
        if not self.campo_pagina_manual.isHidden() and manual:
            return Pagina(manual)
        return self._paginas.get(str(self.combo_pagina.currentData() or ""))

    def _comprobar(self) -> None:
        self._consulta_n += 1
        numero = self._consulta_n
        nombre = self.proveedor
        perfil = self.campo_perfil.text().strip()
        if proveedores.usa_perfil(nombre) and not perfil:
            self._poner_consulta(_("Escribe el perfil del servicio para comprobarlo."),
                                 COLOR_AVISO)
            return
        clave = self.campo_clave.text().strip() or None
        llavero, fabrica = self.llavero, self.fabrica
        datos = {"perfil": perfil, "pagina_facebook": ""}

        def trabajo():
            return numero, perfil, consulta_cuentas.consultar(
                llavero, fabrica, nombre, datos, clave=clave, paginas=None)

        self.boton_comprobar.setEnabled(False)
        self._poner_consulta(_("Comprobando…"))
        segundo_plano.en_segundo_plano(trabajo, self._al_comprobar, "tsots-cuentas")

    def _al_comprobar(self, resultado) -> None:
        if isinstance(resultado, BaseException):  # `consultar` no lanza; por si acaso
            resultado = (self._consulta_n, "", consulta_cuentas.Consulta(
                error=type(resultado).__name__))
        numero, perfil, consulta = resultado
        if numero != self._consulta_n:
            return
        self.boton_comprobar.setEnabled(True)
        if consulta.cuentas is None:
            self._poner_consulta(consulta.error, COLOR_ERROR)
            return
        self._comprobadas = (perfil, consulta.cuentas)
        self._mostrar_cuentas(consulta.cuentas)
        self._poner_consulta(_("Comprobado ahora."), COLOR_OK)
        cuenta_x = consulta.cuentas.get(Plataforma.X)
        if cuenta_x is not None and cuenta_x.premium:
            self.casilla_x_premium.setChecked(True)
            self.nota_x_premium.setText(_("(detectado en tu cuenta)"))
            self.nota_x_premium.show()
        servicio = proveedores.nombre_visible(self.proveedor)
        self.campo_pagina_manual.hide()
        self.aviso_pagina.hide()
        if consulta.paginas is not None:
            actual = str(self.combo_pagina.currentData() or "")
            self._poner_paginas(consulta.paginas, actual)
            if not consulta.paginas:
                self.aviso_pagina.setText(_(
                    "No hay páginas de Facebook conectadas en {servicio}.").format(
                    servicio=servicio))
                self.aviso_pagina.show()
        elif consulta.error_paginas:
            self.aviso_pagina.setText(_(
                "No se pudo leer la lista de páginas ({motivo}). Escribe el ID de la página "
                "a mano: lo encontrarás en la información de la página de Facebook "
                "(transparencia de la página) o en la configuración de Meta Business "
                "Suite.").format(motivo=consulta.error_paginas))
            self.aviso_pagina.show()
            self.campo_pagina_manual.show()
        elif consulta.cuentas.get(Plataforma.FACEBOOK) is None:
            self.aviso_pagina.setText(_("Facebook no está conectada en {servicio}.").format(
                servicio=servicio))
            self.aviso_pagina.show()

    def _refrescar_perfil(self, *args) -> None:
        self.aviso_perfil.setVisible(
            self.campo_perfil.isEnabled() and proveedores.parece_email(self.campo_perfil.text()))

    def _refrescar_clave(self) -> None:
        guardada = self.llavero.hay_clave(self.proveedor)
        if guardada:
            self.etiqueta_clave.setText(_("✓ Guardada en el Llavero"))
            self.etiqueta_clave.setStyleSheet(f"color: {COLOR_OK};")
        else:
            self.etiqueta_clave.setText(_("Sin clave guardada"))
            self.etiqueta_clave.setStyleSheet(f"color: {COLOR_AVISO};")
        self.boton_olvidar.setEnabled(guardada)

    def _olvidar_clave(self) -> None:
        try:
            self.llavero.borrar(self.proveedor)
        except credenciales.ErrorLlavero as e:
            QMessageBox.warning(self, _("Llavero"), str(e))
        self._refrescar_clave()

    def accept(self) -> None:
        clave = self.campo_clave.text().strip()
        if clave:
            try:
                self.llavero.guardar(self.proveedor, clave)
            except credenciales.ErrorLlavero as e:
                QMessageBox.warning(self, _("Llavero"), str(e))
                return
            finally:
                self.campo_clave.clear()
        self.ajustes.proveedor_redes = self.proveedor
        self.ajustes.guardar_perfil(self.proveedor, self.campo_perfil.text())
        self.ajustes.tiktok_modo = ModoTikTok(self.combo_tiktok.currentData())
        self.ajustes.instagram_modo = ModoInstagram(self.combo_instagram.currentData())
        self.ajustes.youtube_categoria = str(self.combo_categoria.currentData())
        self.ajustes.x_premium = self.casilla_x_premium.isChecked()
        self.ajustes.facebook_modo = ModoFacebook(self.combo_facebook.currentData())
        self.ajustes.guardar_pagina_facebook(self.proveedor, self.pagina_elegida())
        if self._comprobadas is not None and self._comprobadas[0] == self.ajustes.perfil_redes:
            self.ajustes.guardar_cuentas(self._comprobadas[1])
        super().accept()
