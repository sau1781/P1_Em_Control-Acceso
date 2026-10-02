#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acceso/hilo_ia.py
===================
El cerebro de las decisiones de acceso. Corre en su PROPIO hilo, separado
del hilo de streaming de GStreamer, para que una inferencia lenta nunca
detenga la transmision de video al vigilante.

LOGICA DE DECISION:

    1. Se ubica cada rostro humano en el cuadro (deteccion_rostros).
    2. Regla de acceso:
         - 0 rostros                                      -> nada (timeout aparte)
         - 1 rostro (cualquiera, sin verificar identidad)  -> ACCESO AUTORIZADO
         - 2 o mas rostros                                 -> DENEGADO (tailgating)
       El sistema NO verifica de quien es la cara, solo CUANTAS personas hay.
       El requisito es "una persona por vez", no "una persona conocida por vez".
    3. Por separado (con mucha menor frecuencia, ver
       deteccion_objetos.INTERVALO_DETECCION_OBJETOS) se corre el detector
       general de objetos. Si aparece un auto, un perro, un gato, etc., se
       registra en la bitacora como informacion de contexto, pero JAMAS
       decide si la puerta abre.
"""

import time
import logging
import threading
from queue import Empty

from acceso import config, bitacora, estado_puerta, deteccion_rostros, deteccion_objetos
from acceso.metricas import METRICAS

log = logging.getLogger("acceso.ia")

latido_ia = time.time()
_lock_latido = threading.Lock()


def obtener_latido() -> float:
    with _lock_latido:
        return latido_ia


def ejecutar(cola_imagenes, evento_foto, parada: threading.Event):
    """Bucle principal del hilo de IA. `parada` es la señal global de
    apagado ordenado que main.py activa al recibir SIGINT/SIGTERM."""
    global latido_ia

    tiempo_ultima_decision = time.time()
    tiempo_ultima_foto = 0.0

    while not parada.is_set():
        with _lock_latido:
            latido_ia = time.time()

        estado_puerta.actualizar()

        vencido = (time.time() - tiempo_ultima_decision) > config.TIEMPO_MAXIMO_DECISION
        en_reposo = estado_puerta.estado_actual() == "BLOQUEADA"
        if vencido and en_reposo:
            tiempo_ultima_decision = time.time()
            bitacora.registrar_evento(
                "Timeout expirado - Acceso denegado por omision")
            estado_puerta.denegar()

        try:
            frame = cola_imagenes.get(timeout=0.25)
        except Empty:
            continue

        # (a) Deteccion general de objetos: solo cada N cuadros, solo bitacora.
        if deteccion_objetos.toca_evaluar_este_cuadro():
            t0 = time.perf_counter()
            for clase, confianza, _caja in deteccion_objetos.detectar(frame):
                bitacora.registrar_evento(
                    "Evento detectado", f"{clase} (confianza={confianza:.2f})")
            with METRICAS.lock:
                METRICAS.inferencia_ms_acum += (time.perf_counter() - t0) * 1000.0

        # (b) Deteccion de rostros: esto SI decide la puerta.
        t0 = time.perf_counter()
        cajas = deteccion_rostros.detectar(frame)
        with METRICAS.lock:
            METRICAS.frames_inferidos += 1
            METRICAS.inferencia_ms_acum += (time.perf_counter() - t0) * 1000.0

        if not cajas:
            continue

        tiempo_ultima_decision = time.time()
        ahora = time.time()
        evidencia_permitida = (ahora - tiempo_ultima_foto) > config.COOLDOWN_EVIDENCIA

        if len(cajas) > 1:
            if evidencia_permitida and bitacora.hay_espacio_para_evidencia():
                evento_foto.set()
                tiempo_ultima_foto = ahora
            bitacora.registrar_evento(
                "ALERTA Tailgating - Acceso denegado", f"rostros={len(cajas)}")
            estado_puerta.denegar()
            continue

        if evidencia_permitida:
            if bitacora.hay_espacio_para_evidencia():
                evento_foto.set()
                tiempo_ultima_foto = ahora
            bitacora.registrar_evento("Acceso autorizado", "1 rostro detectado")
        estado_puerta.abrir_puerta()

    log.info("Hilo de IA finalizado.")
