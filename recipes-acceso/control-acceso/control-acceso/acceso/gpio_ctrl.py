#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acceso/gpio_ctrl.py
=====================
Todo lo que toca pines fisicos vive aqui, y solo aqui. Si mañana cambia el
numero de pin o la biblioteca de GPIO, este es el unico archivo que se toca.

Usa libgpiod v2 (paquete python3-libgpiod). En Yocto 6.0 con kernel 6.x,
RPi.GPIO NO funciona; libgpiod es la via soportada.

Si la biblioteca no esta instalada (por ejemplo, corriendo en un PC de
escritorio sin GPIO), este modulo degrada solo: imprime lo que habria hecho
en vez de fallar, para que el mismo codigo sirva para desarrollo y para la
placa final.
"""

import logging
import threading
from datetime import timedelta

from acceso import config, bitacora, estado_puerta

log = logging.getLogger("acceso.gpio")

try:
    import gpiod
    from gpiod.line import Direction, Value, Edge, Bias
    GPIO_DISPONIBLE = True
except ImportError:
    GPIO_DISPONIBLE = False
    log.warning("libgpiod no disponible: GPIO en modo simulacion (solo consola).")

_salidas = None


def init_gpio():
    """Reserva los pines de salida en estado seguro (rojo encendido).

    Nota de arranque: el estado del GPIO ANTES de que este proceso exista lo
    define el firmware, no Python. En /boot/config.txt de la Raspberry Pi hay
    que declarar gpio=27=op,dl y gpio=22=op,dh para que durante el arranque
    del kernel el rele este desactivado y el LED rojo encendido.
    """
    global _salidas
    if not GPIO_DISPONIBLE:
        return
    try:
        _salidas = gpiod.request_lines(
            config.CHIP_GPIO,
            consumer="acceso-salidas",
            config={
                config.PIN_VERDE: gpiod.LineSettings(
                    direction=Direction.OUTPUT, output_value=Value.INACTIVE),
                config.PIN_ROJO: gpiod.LineSettings(
                    direction=Direction.OUTPUT, output_value=Value.ACTIVE),
            },
        )
        log.info("GPIO inicializado en %s (verde=%d rojo=%d boton=%d)",
                 config.CHIP_GPIO, config.PIN_VERDE, config.PIN_ROJO,
                 config.PIN_BOTON)
    except OSError as e:
        log.error("No se pudo reservar GPIO: %s (se continua en simulacion)", e)
        _salidas = None


def set_leds(verde: bool, rojo: bool):
    """Actualiza los indicadores. Nunca lanza: un fallo de GPIO no debe matar
    el pipeline de video ni la bitacora."""
    if _salidas is None:
        log.debug("[SIM] LED verde=%s rojo=%s", verde, rojo)
        return
    try:
        _salidas.set_values({
            config.PIN_VERDE: Value.ACTIVE if verde else Value.INACTIVE,
            config.PIN_ROJO: Value.ACTIVE if rojo else Value.INACTIVE,
        })
    except OSError as e:
        log.error("Fallo al escribir GPIO: %s", e)


def liberar_gpio():
    if _salidas is not None:
        try:
            set_leds(verde=False, rojo=True)
            _salidas.release()
        except Exception:
            pass


def hilo_override(parada: threading.Event):
    """Observa el boton fisico Normalmente Cerrado (NC).

    Por que NC y no NO: con un contacto NC, el estado sano del lazo es
    'cerrado'. Tanto una pulsacion legitima como un cable cortado producen el
    MISMO evento (apertura del lazo), y el sistema no puede distinguirlos:
    esa es la propiedad buscada. Un sabotaje del cableado falla hacia el
    estado seguro (permite salir) en vez de dejar a alguien encerrado.

    Este hilo NO abre la puerta: la apertura fisica la hace el propio
    contacto, cableado en serie con la alimentacion de la cerradura,
    independiente del Pi. Aqui solo se OBSERVA el evento para registrarlo.
    """
    if not GPIO_DISPONIBLE:
        log.warning("Hilo de override inactivo: sin libgpiod.")
        return
    try:
        peticion = gpiod.request_lines(
            config.CHIP_GPIO,
            consumer="acceso-boton",
            config={config.PIN_BOTON: gpiod.LineSettings(
                direction=Direction.INPUT,
                bias=Bias.PULL_UP,
                edge_detection=Edge.BOTH,
                debounce_period=timedelta(milliseconds=50),
            )},
        )
    except OSError as e:
        log.error("No se pudo abrir el boton de override: %s", e)
        return

    with peticion:
        while not parada.is_set():
            if not peticion.wait_edge_events(timeout=timedelta(seconds=1)):
                continue
            for ev in peticion.read_edge_events():
                if ev.event_type == ev.Type.RISING_EDGE:
                    bitacora.registrar_evento(
                        "OVERRIDE - Salida manual (boton NC abierto)")
                    estado_puerta.marcar_override(True)
                else:
                    bitacora.registrar_evento(
                        "OVERRIDE - Lazo NC restablecido")
                    estado_puerta.marcar_override(False)
