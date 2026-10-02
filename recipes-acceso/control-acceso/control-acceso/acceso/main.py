#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acceso/main.py
================
Punto de entrada del programa. Su unico trabajo es CONECTAR los modulos
entre si: no contiene logica de negocio propia. Si queres entender que hace
el sistema en detalle, este archivo te dice el ORDEN en que ocurren las
cosas; cada modulo importado explica el COMO.

Orden de arranque:
    1. Preparar carpetas y cargar los dos modelos (rostros y detección
       general de objetos).
    2. Construir el pipeline de GStreamer y conectar los callbacks.
    3. Arrancar los hilos de trabajo (IA, salud, GPIO).
    4. Poner el pipeline en PLAYING y correr el bucle principal de GLib
       hasta que llegue una señal de apagado.
"""

import os
import sys
import signal
import logging
import threading
from queue import Queue

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gst, GLib  # noqa: E402

from acceso import (config, bitacora, gpio_ctrl, estado_puerta,
                    deteccion_rostros, deteccion_objetos,
                    pipeline_gstreamer, hilo_ia, salud)
from acceso.metricas import sd_notify, METRICAS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("acceso.main")

_parada = threading.Event()
_pipeline = None
_contexto_bus = {"codigo_salida": 0}


def _apagado_ordenado(loop):
    """Manejador de SIGINT/SIGTERM. Envia EOS y espera a que los sinks
    cierren sus archivos antes de terminar, para que la ultima foto de
    evidencia quede integra y no truncada."""
    log.info("Apagado solicitado: enviando EOS...")
    _parada.set()
    if _pipeline is not None:
        _pipeline.send_event(Gst.Event.new_eos())
        bus = _pipeline.get_bus()
        bus.timed_pop_filtered(5 * Gst.SECOND,
                               Gst.MessageType.EOS | Gst.MessageType.ERROR)
    if loop.is_running():
        loop.quit()
    return False  # GLib: no repetir este manejador


def arrancar() -> int:
    global _pipeline

    # --- 1. Preparacion.
    config.preparar_directorios()
    bitacora.purgar_evidencias()
    log.info("Datos en %s (%.0f MB libres)",
             config.DIR_DATOS, bitacora.espacio_libre_mb())

    deteccion_rostros.cargar()
    deteccion_objetos.cargar()

    gpio_ctrl.init_gpio()
    gpio_ctrl.set_leds(verde=False, rojo=True)

    # --- 2. GStreamer.
    Gst.init(None)
    descripcion = pipeline_gstreamer.construir_descripcion()
    log.info("Fuente de video: %s", config.FUENTE)
    log.info("Pipeline:%s", descripcion)
    try:
        _pipeline = Gst.parse_launch(descripcion)
    except GLib.Error as e:
        log.critical("No se pudo construir el pipeline: %s", e)
        return 1

    cola_imagenes = Queue(maxsize=2)
    evento_foto = threading.Event()
    pipeline_gstreamer.conectar(_pipeline, cola_imagenes, evento_foto)

    sink_foto = _pipeline.get_by_name("sink_foto")
    if sink_foto is not None:
        sink_foto.set_property("index", bitacora.indice_inicial_evidencias())

    loop = GLib.MainLoop()
    bus = _pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", pipeline_gstreamer.manejador_bus, loop, _contexto_bus)

    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, _apagado_ordenado, loop)

    # --- 3. Hilos de trabajo.
    hilos = [
        threading.Thread(target=hilo_ia.ejecutar,
                         args=(cola_imagenes, evento_foto, _parada),
                         name="IA", daemon=True),
        threading.Thread(target=salud.ejecutar,
                         args=(cola_imagenes, _parada),
                         name="Salud", daemon=True),
        threading.Thread(target=gpio_ctrl.hilo_override,
                         args=(_parada,),
                         name="GPIO", daemon=True),
    ]
    for h in hilos:
        h.start()

    log.info("=== SISTEMA DE CONTROL DE ACCESO ===")
    bitacora.registrar_evento("Sistema iniciado")

    if _pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
        log.critical("El pipeline no pudo pasar a PLAYING. Buscando la causa exacta...")
        bus = _pipeline.get_bus()
        while True:
            mensaje = bus.pop_filtered(
                Gst.MessageType.ERROR | Gst.MessageType.WARNING)
            if mensaje is None:
                break
            if mensaje.type == Gst.MessageType.ERROR:
                err, depuracion = mensaje.parse_error()
                log.critical("  Causa: %s | %s", err, depuracion)
            else:
                err, depuracion = mensaje.parse_warning()
                log.warning("  Aviso relacionado: %s | %s", err, depuracion)
        _parada.set()
        _pipeline.set_state(Gst.State.NULL)
        return 1

    sd_notify("READY=1\nSTATUS=Pipeline en PLAYING")

    try:
        loop.run()
    finally:
        sd_notify("STOPPING=1")
        _parada.set()
        _pipeline.set_state(Gst.State.NULL)
        for h in hilos:
            h.join(timeout=2.0)
        bitacora.registrar_evento("Sistema detenido")
        gpio_ctrl.liberar_gpio()
        log.info("Metricas finales: %s", METRICAS.reporte())

    return _contexto_bus["codigo_salida"]


if __name__ == "__main__":
    sys.exit(arrancar())
