#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acceso/bitacora.py
===================
Escritura de la bitacora CSV y gestion de la carpeta de evidencias. Es el
"papel" del sistema: todo lo que ocurre queda anotado aqui, con marca de
tiempo, para poder auditar despues quien entro, cuando y por que se le negó
el paso.
"""

import os
import csv
import time
import shutil
import logging
import threading
from datetime import datetime

from acceso import config

log = logging.getLogger("acceso.bitacora")

_lock_csv = threading.Lock()


def espacio_libre_mb(ruta=None) -> float:
    """MB libres en el sistema de archivos que contiene `ruta`."""
    ruta = ruta or config.DIR_DATOS
    try:
        return shutil.disk_usage(ruta).free / (1024 * 1024)
    except OSError:
        return 0.0


def registrar_evento(evento: str, detalle: str = "") -> str:
    """Escribe una linea en la bitacora CSV y la fuerza a disco con fsync.

    El flush + fsync no es paranoia: sin el, un corte de energia puede
    perder los ultimos eventos, y la bitacora de un control de acceso es
    evidencia, no un log de depuracion.
    """
    marca = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    with _lock_csv:
        try:
            nuevo = not os.path.exists(config.RUTA_CSV)
            with open(config.RUTA_CSV, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if nuevo:
                    w.writerow(["timestamp", "evento", "detalle"])
                w.writerow([marca, evento, detalle])
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            log.error("No se pudo escribir la bitacora: %s", e)
    log.info("EVENTO: %s (%s)", evento, detalle)
    return marca


def purgar_evidencias():
    """Borra fotos de evidencia mas viejas que config.DIAS_RETENCION."""
    limite = time.time() - config.DIAS_RETENCION * 86400
    borradas = 0
    try:
        for nombre in os.listdir(config.DIR_EVIDENCIAS):
            ruta = os.path.join(config.DIR_EVIDENCIAS, nombre)
            try:
                if os.path.isfile(ruta) and os.path.getmtime(ruta) < limite:
                    os.remove(ruta)
                    borradas += 1
            except OSError:
                continue
    except OSError:
        return
    if borradas:
        log.info("Retencion: %d imagenes eliminadas (>%d dias)",
                 borradas, config.DIAS_RETENCION)


def indice_inicial_evidencias() -> int:
    """Siguiente indice libre para multifilesink, para no sobrescribir fotos
    de una corrida anterior tras un reinicio del servicio."""
    maximo = -1
    try:
        for nombre in os.listdir(config.DIR_EVIDENCIAS):
            if nombre.startswith("foto_") and nombre.endswith(".jpg"):
                try:
                    maximo = max(maximo, int(nombre[5:-4]))
                except ValueError:
                    pass
    except OSError:
        pass
    return maximo + 1


def hay_espacio_para_evidencia() -> bool:
    """Evita pedir una foto si el disco esta casi lleno."""
    libre = espacio_libre_mb()
    if libre < config.MARGEN_DISCO_MB:
        log.warning("Disco bajo (%.0f MB): se omite la evidencia fotografica.",
                    libre)
        return False
    return True
