#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acceso/metricas.py
====================
Contadores de desempeno (para poder demostrar que el callback de GStreamer
es rapido y que no hay fugas de memoria) y el envio de "estoy vivo" a
systemd para el watchdog.
"""

import os
import socket
import threading


class Metricas:
    """Contadores compartidos entre el hilo de streaming y el de IA.

    Se protegen con un lock porque varios hilos escriben a la vez; el reporte
    toma el lock para que los numeros que se imprimen juntos correspondan al
    mismo instante.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.frames_capturados = 0
        self.frames_descartados = 0
        self.frames_inferidos = 0
        self.callback_us_max = 0.0
        self.callback_us_acum = 0.0
        self.inferencia_ms_acum = 0.0

    def reporte(self) -> str:
        with self.lock:
            n = max(1, self.frames_capturados)
            m = max(1, self.frames_inferidos)
            return (
                f"capturados={self.frames_capturados} "
                f"descartados={self.frames_descartados} "
                f"inferidos={self.frames_inferidos} "
                f"callback_us_prom={self.callback_us_acum / n:.0f} "
                f"callback_us_max={self.callback_us_max:.0f} "
                f"inferencia_ms_prom={self.inferencia_ms_acum / m:.1f}"
            )


# Instancia unica compartida por todo el programa.
METRICAS = Metricas()


def sd_notify(mensaje: str):
    """Envia un mensaje al socket de notificacion de systemd, si existe.

    Fuera de systemd (por ejemplo corriendo el script a mano en un PC) la
    variable NOTIFY_SOCKET no existe, y esta funcion simplemente no hace
    nada: es seguro llamarla siempre.
    """
    ruta = os.environ.get("NOTIFY_SOCKET")
    if not ruta:
        return
    try:
        if ruta.startswith("@"):
            ruta = "\0" + ruta[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(ruta)
            s.sendall(mensaje.encode("utf-8"))
    except OSError:
        pass
