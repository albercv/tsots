"""Tareas cortas fuera del hilo de la interfaz (ffprobe, consultas al servicio).

`en_segundo_plano(funcion, al_terminar)` ejecuta `funcion()` en un hilo de
Python y llama a `al_terminar(resultado)` en el hilo de la interfaz. Si
`funcion` lanza, `al_terminar` recibe la excepción.

La tarea no cuelga de ningún widget: vive en `_VIVAS` hasta que termina, así
que cerrar o destruir el diálogo que la pidió no rompe nada (Qt desconecta
sola la señal de un receptor destruido).
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

_VIVAS: set["Tarea"] = set()


class Tarea(QObject):
    terminada = Signal(object)  # resultado o excepción

    def __init__(self, funcion: Callable[[], Any], nombre: str = "tsots-tarea"):
        super().__init__()  # sin padre: ver el docstring del módulo
        self._funcion = funcion
        self._nombre = nombre

    def iniciar(self) -> None:
        _VIVAS.add(self)
        # Se conecta después que el receptor: se suelta cuando ya se avisó.
        self.terminada.connect(self._soltar)
        threading.Thread(target=self._correr, name=self._nombre, daemon=True).start()

    def _correr(self) -> None:
        try:
            resultado = self._funcion()
        except Exception as e:  # la recibe `al_terminar`
            resultado = e
        self._funcion = None
        self.terminada.emit(resultado)

    def _soltar(self, _resultado: Any) -> None:
        # Fuera de la entrega de la propia señal, para no destruir el objeto
        # mientras Qt aún lo usa.
        QTimer.singleShot(0, lambda: _VIVAS.discard(self))


def en_segundo_plano(funcion: Callable[[], Any], al_terminar: Callable[[Any], None],
                     nombre: str = "tsots-tarea") -> Tarea:
    tarea = Tarea(funcion, nombre)
    tarea.terminada.connect(al_terminar)
    tarea.iniciar()
    return tarea


def vivas() -> int:
    return len(_VIVAS)
