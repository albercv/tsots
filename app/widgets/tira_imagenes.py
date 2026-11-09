"""Tira con las fotos de un post: miniaturas con «Quitar», «Añadir…» con los
fotogramas candidatos y arrastrar imágenes propias.

Las rutas se usan tal cual: nada se copia al añadir ni se borra al quitar.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from videopipeline.i18n import _

EXTENSIONES = {".png", ".jpg", ".jpeg"}
ALTO = 96  # de cada miniatura
ESPACIO = 4  # entre la miniatura y su «Quitar»


class TiraImagenes(QWidget):
    cambiada = Signal()

    def __init__(self, fotos, candidatos: Path, parent=None):
        super().__init__(parent)
        self._fotos: list[Path] = list(fotos)
        self._candidatos = candidatos
        self.setAcceptDrops(True)
        cuerpo = QWidget()
        self._fila = QHBoxLayout(cuerpo)
        self._fila.setContentsMargins(0, 0, 0, 0)
        # Sin esto el desplazable estrecha las miniaturas en vez de desplazarse.
        self._fila.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._fila.addStretch(1)
        self.boton_anadir = QPushButton(_("Añadir…"))
        self.boton_anadir.setToolTip(_(
            "Añade otro fotograma del vídeo u otra imagen. También puedes arrastrar "
            "imágenes aquí."))
        self.boton_anadir.setMenu(QMenu(self.boton_anadir))
        self.boton_anadir.menu().aboutToShow.connect(self._rellenar_menu)
        # Muchas fotos no ensanchan el diálogo: la tira se desplaza.
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QFrame.Shape.NoFrame)
        desplazable.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        desplazable.setWidget(cuerpo)
        desplazable.setFixedHeight(
            ALTO + ESPACIO + self.boton_anadir.sizeHint().height()
            + desplazable.horizontalScrollBar().sizeHint().height())
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.addWidget(desplazable, 1)
        raiz.addWidget(self.boton_anadir, 0, Qt.AlignmentFlag.AlignTop)
        self._pintar()

    def fotos(self) -> tuple[Path, ...]:
        return tuple(self._fotos)

    def candidatos(self) -> list[Path]:
        """Los fotogramas de `candidatos/` que aún no están. Las fotos que
        prepara `difusion` son copias `NN_<candidato>`: cuentan como ese."""
        nombres = [p.name for p in self._fotos]
        return [c for c in sorted(self._candidatos.glob("*"))
                if c.suffix.lower() in EXTENSIONES and c not in self._fotos
                and not any(n.endswith("_" + c.name) for n in nombres)]

    def anadir(self, rutas) -> None:
        nuevas = [r for r in dict.fromkeys(rutas) if r not in self._fotos]
        if nuevas:
            self._fotos += nuevas
            self._pintar()
            self.cambiada.emit()

    def quitar(self, ruta: Path) -> None:
        self._fotos.remove(ruta)
        self._pintar()
        self.cambiada.emit()

    def _pintar(self) -> None:
        while self._fila.count() > 1:  # el último es el relleno del final
            miniatura = self._fila.takeAt(0).widget()
            miniatura.hide()
            miniatura.deleteLater()  # puede ser su «Quitar» el que llama
        for i, ruta in enumerate(self._fotos):
            self._fila.insertWidget(i, self._miniatura(ruta))

    def _miniatura(self, ruta: Path) -> QWidget:
        caja = QWidget()
        capa = QVBoxLayout(caja)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(ESPACIO)
        imagen = QLabel()
        imagen.setFixedHeight(ALTO)
        imagen.setToolTip(str(ruta))
        pixmap = QPixmap(str(ruta))
        if pixmap.isNull():
            imagen.setText(ruta.name)
        else:
            pixmap = pixmap.scaledToHeight(ALTO, Qt.TransformationMode.SmoothTransformation)
            imagen.setPixmap(pixmap)
            imagen.setFixedSize(pixmap.size())  # que la tira no la estreche
        quitar = QPushButton(_("Quitar"))
        quitar.clicked.connect(lambda: self.quitar(ruta))
        capa.addWidget(imagen)
        capa.addWidget(quitar)
        return caja

    def _rellenar_menu(self) -> None:
        menu = self.boton_anadir.menu()
        menu.clear()
        for ruta in self.candidatos():
            menu.addAction(QIcon(str(ruta)), ruta.name,
                           lambda _marcada=False, r=ruta: self.anadir([r]))
        menu.addSeparator()
        menu.addAction(_("Otra imagen…"), self._elegir)

    def _elegir(self) -> None:
        patron = _("Imágenes ({extensiones})").format(
            extensiones=" ".join(f"*{e}" for e in sorted(EXTENSIONES)))
        rutas, _filtro = QFileDialog.getOpenFileNames(self, _("Elegir imágenes"), "", patron)
        self.anadir([Path(r) for r in rutas])

    @staticmethod
    def _imagenes(mime: QMimeData) -> list[Path]:
        return [Path(url.toLocalFile()) for url in mime.urls()
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in EXTENSIONES]

    def dragEnterEvent(self, evento) -> None:
        if self._imagenes(evento.mimeData()):
            evento.acceptProposedAction()

    def dropEvent(self, evento) -> None:
        self.anadir(self._imagenes(evento.mimeData()))
        evento.acceptProposedAction()
