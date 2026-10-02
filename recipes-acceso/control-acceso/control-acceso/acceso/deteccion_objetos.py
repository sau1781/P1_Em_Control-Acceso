#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acceso/deteccion_objetos.py
==============================
Segunda red neuronal, independiente de la de rostros: MobileNet-SSD,
entrenada sobre el conjunto VOC (20 clases, incluye car, bus, motorbike,
cat, dog, cow, horse, sheep, bird, person, etc.).

Su trabajo es DISTINTO al de deteccion_rostros.py: esta red mira el cuadro
completo y responde "que tipo de cosas hay aqui", sin importar si son
personas o no. Se usa solo para BITACORA Y ALERTA -nunca para decidir si la
puerta abre-. La decision de acceso depende exclusivamente de cuantas caras
humanas hay en el cuadro (ver acceso/deteccion_rostros.py y acceso/hilo_ia.py).

DEGRADACION SEGURA: este modelo esta en formato Caffe (.prototxt +
.caffemodel), y OpenCV 5.0 elimino el importador de modelos Caffe
(cv2.dnn.readNetFromCaffe ya no existe en esa version). Si la version de
OpenCV instalada no lo soporta -o si los archivos del modelo faltan- este
modulo lo detecta en cargar(), imprime UN aviso, y queda desactivado en
silencio por el resto de la corrida: nunca lanza una excepcion hacia
main.py. Esto es intencional: la deteccion general de objetos es
informativa (bitacora), no es parte del requisito de acceso, asi que su
ausencia no debe tumbar el sistema completo. Migrar este modelo a ONNX
(igual que se hizo con el detector de rostros) queda como trabajo futuro.
"""

import logging
import numpy as np
import cv2

from acceso import config

log = logging.getLogger("acceso.objetos")

_red = None
_disponible = False
_contador_cuadros = 0


def cargar():
    """Intenta cargar la red. Nunca lanza: si falla, queda desactivada y se
    avisa una sola vez por que."""
    global _red, _disponible
    try:
        _red = cv2.dnn.readNetFromCaffe(config.RUTA_PROTOTXT_OBJETOS,
                                        config.RUTA_PESOS_OBJETOS)
        _red.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        _red.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        _disponible = True
        log.info("Red de deteccion general (MobileNet-SSD, %d clases VOC) cargada.",
                 len(config.CLASES_OBJETOS_VOC))
    except AttributeError:
        log.warning(
            "Esta version de OpenCV (%s) no incluye el importador de "
            "modelos Caffe (fue eliminado en OpenCV 5.0). La deteccion "
            "general de objetos (autos, animales, etc.) queda DESACTIVADA "
            "para esta corrida. El acceso por rostro NO se ve afectado. "
            "Para reactivarla hay que migrar MobileNet-SSD a formato ONNX.",
            cv2.__version__)
        _disponible = False
    except (cv2.error, FileNotFoundError) as e:
        log.warning(
            "No se pudo cargar el detector general de objetos (%s). Queda "
            "DESACTIVADO para esta corrida. El acceso por rostro no se ve "
            "afectado.", e)
        _disponible = False


def toca_evaluar_este_cuadro() -> bool:
    """Devuelve True solo cada config.INTERVALO_DETECCION_OBJETOS cuadros.
    Si el modelo no cargo, devuelve False siempre (costo cero)."""
    global _contador_cuadros
    if not _disponible:
        return False
    _contador_cuadros += 1
    return _contador_cuadros % config.INTERVALO_DETECCION_OBJETOS == 0


def detectar(frame: np.ndarray) -> list:
    """Devuelve tuplas (clase:str, confianza:float, caja) para los objetos
    de config.CLASES_DE_INTERES. Se excluye 'person' adrede: las personas
    ya las maneja con mas detalle deteccion_rostros.py."""
    if not _disponible:
        return []

    alto, ancho = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(
        cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
    _red.setInput(blob)
    detecciones = _red.forward()

    hallazgos = []
    for i in range(detecciones.shape[2]):
        confianza = float(detecciones[0, 0, i, 2])
        if confianza <= config.UMBRAL_CONFIANZA_OBJETOS:
            continue
        id_clase = int(detecciones[0, 0, i, 1])
        if id_clase < 0 or id_clase >= len(config.CLASES_OBJETOS_VOC):
            continue
        clase = config.CLASES_OBJETOS_VOC[id_clase]
        if clase not in config.CLASES_DE_INTERES:
            continue
        caja = (detecciones[0, 0, i, 3:7]
                * np.array([ancho, alto, ancho, alto])).astype(int)
        hallazgos.append((clase, confianza, caja))
    return hallazgos
