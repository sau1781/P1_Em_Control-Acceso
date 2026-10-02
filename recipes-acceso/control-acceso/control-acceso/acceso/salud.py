#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acceso/salud.py
=================
Hilo de baja prioridad que reporta metricas cada 5 s y alimenta el watchdog
de systemd. Si el hilo de IA se cuelga, este hilo deja de notificar a
systemd a proposito, y systemd mata y reinicia el servicio solo.
"""

import os
import time
import logging
import threading

from acceso import config, bitacora, estado_puerta, hilo_ia
from acceso.metricas import METRICAS, sd_notify

log = logging.getLogger("acceso.salud")


def ejecutar(cola_imagenes, parada: threading.Event):
    intervalo_wd = int(os.environ.get("WATCHDOG_USEC", "0")) / 2_000_000.0
    ultima_purga = 0.0

    while not parada.wait(5.0):
        latencia = time.time() - hilo_ia.obtener_latido()
        if intervalo_wd > 0:
            if latencia < config.LATIDO_MAXIMO_IA:
                sd_notify("WATCHDOG=1")
            else:
                log.error("Hilo de IA sin latido hace %.1f s: no se notifica "
                          "al watchdog, systemd reiniciara el servicio.",
                          latencia)

        try:
            with open("/proc/self/status", encoding="utf-8") as f:
                rss = next((l.split()[1] for l in f if l.startswith("VmRSS")), "?")
            fds = len(os.listdir("/proc/self/fd"))
        except OSError:
            rss, fds = "?", -1

        log.info("SALUD rss_kb=%s fds=%d puerta=%s cola=%d %s",
                 rss, fds, estado_puerta.estado_actual(),
                 cola_imagenes.qsize(), METRICAS.reporte())

        if time.time() - ultima_purga > 3600:
            ultima_purga = time.time()
            bitacora.purgar_evidencias()
