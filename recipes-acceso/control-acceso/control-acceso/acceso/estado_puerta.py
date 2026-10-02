#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acceso/estado_puerta.py
=========================
El estado de la puerta (bloqueada / abierta / anulada) es leido y escrito
por tres hilos distintos: el de IA, el de GPIO (boton de anulacion) y el de
salud. Vive en su PROPIO modulo, con su PROPIO lock, para que quien lo lea
no tenga que adivinar si esta protegido o no: si esta aqui, esta protegido.

Esta separacion es la correccion de la condicion de carrera del prototipo
original, donde el estado global se leia y escribia desde varios hilos sin
ningun lock.
"""

import time
import logging
import threading

from acceso import gpio_ctrl, config

log = logging.getLogger("acceso.puerta")

_lock = threading.RLock()

# --- Estado protegido por _lock. Nadie fuera de este archivo debe tocarlo
#     directamente: siempre a traves de las funciones de abajo.
_estado = "BLOQUEADA"          # BLOQUEADA | ABIERTA | OVERRIDE
_tiempo_apertura = 0.0


def estado_actual() -> str:
    with _lock:
        return _estado


def abrir_puerta():
    """Autoriza el acceso: activa el rele logico y arma el cierre automatico."""
    global _estado, _tiempo_apertura
    with _lock:
        if _estado == "OVERRIDE":
            return  # el hardware manda; el software no interfiere
        if _estado != "ABIERTA":
            _estado = "ABIERTA"
            _tiempo_apertura = time.time()
            gpio_ctrl.set_leds(verde=True, rojo=False)
            log.info("Rele de apertura ACTIVADO (%.1f s)", config.DURACION_APERTURA)


def marcar_override(activo: bool):
    """Llamado por el hilo de GPIO cuando el boton fisico NC cambia de estado."""
    global _estado
    with _lock:
        if activo:
            _estado = "OVERRIDE"
            gpio_ctrl.set_leds(verde=True, rojo=False)
        else:
            _estado = "BLOQUEADA"
            gpio_ctrl.set_leds(verde=False, rojo=True)


def denegar():
    """Deja constancia visual de una denegacion (LED rojo), sin tocar el
    estado logico de apertura."""
    with _lock:
        if _estado == "BLOQUEADA":
            gpio_ctrl.set_leds(verde=False, rojo=True)


def actualizar():
    """Cierre automatico NO bloqueante. Se llama en cada vuelta del hilo de
    IA, exista o no un cuadro nuevo que analizar."""
    global _estado
    with _lock:
        if (_estado == "ABIERTA"
                and (time.time() - _tiempo_apertura) > config.DURACION_APERTURA):
            _estado = "BLOQUEADA"
            gpio_ctrl.set_leds(verde=False, rojo=True)
            log.info("Rele desactivado, puerta BLOQUEADA")
