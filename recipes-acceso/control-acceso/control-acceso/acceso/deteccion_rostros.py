#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acceso/deteccion_rostros.py
=============================
Ubica rostros en un cuadro usando YuNet, el detector facial que el propio
OpenCV mantiene y recomienda (paper: Wu et al., "YuNet: A Tiny
Millisecond-level Face Detector"). Solo responde "aqui hay una cara", no
"de quien es": en esta version del sistema eso alcanza, cualquier cara
humana autoriza el acceso (ver acceso/hilo_ia.py).

POR QUE YUNET Y NO EL SSD RESNET-10 (CAFFE) QUE USABA LA VERSION ANTERIOR:
    OpenCV 5.0 elimino por completo el importador de modelos Caffe
    (cv2.dnn.readNetFromCaffe ya no existe: no cambio de nombre, se borro
    del codigo fuente). YuNet viene en formato ONNX y se carga con la API
    especifica cv2.FaceDetectorYN, que OpenCV mantiene activamente y sigue
    funcionando igual en OpenCV 4.x y 5.x. Ademas, YuNet ya incluye su
    propia supresion de no-maximos (NMS) internamente: no hace falta
    escribir el filtro de cajas duplicadas a mano como con la SSD vieja.

Archivo de modelo esperado (ver config.RUTA_MODELO_ROSTRO):
    face_detection_yunet_2023mar.onnx
"""

import logging
import numpy as np
import cv2

from acceso import config

log = logging.getLogger("acceso.rostros")

_detector = None


def cargar():
    """Carga el detector. Se llama una sola vez desde main.py."""
    global _detector
    tam_inicial = (config.ANCHO_CAPTURA, config.ALTO_CAPTURA)

    # cv2.FaceDetectorYN.create (forma nueva, jerarquica) vs.
    # cv2.FaceDetectorYN_create (forma plana, versiones mas viejas de las
    # bindings de Python). Se intenta la nueva y se cae a la vieja, para que
    # el mismo codigo sirva en distintas versiones de OpenCV sin tocar nada.
    if hasattr(cv2, "FaceDetectorYN") and hasattr(cv2.FaceDetectorYN, "create"):
        _detector = cv2.FaceDetectorYN.create(
            config.RUTA_MODELO_ROSTRO, "", tam_inicial,
            float(config.UMBRAL_CONFIANZA_ROSTRO),
            float(config.UMBRAL_IOU_NMS),
            5000,
        )
    else:
        _detector = cv2.FaceDetectorYN_create(
            config.RUTA_MODELO_ROSTRO, "", tam_inicial,
            float(config.UMBRAL_CONFIANZA_ROSTRO),
            float(config.UMBRAL_IOU_NMS),
            5000,
        )
    log.info("Detector de rostros YuNet (ONNX) cargado.")


def detectar(frame: np.ndarray) -> list:
    """Devuelve una lista de cajas [x1, y1, x2, y2] (enteros, en pixeles del
    frame original), una por rostro. La supresion de duplicados ya viene
    resuelta adentro de YuNet, no hace falta filtrarla aqui."""
    alto, ancho = frame.shape[:2]
    _detector.setInputSize((ancho, alto))
    _, caras = _detector.detect(frame)

    cajas = []
    if caras is not None:
        for cara in caras:
            # YuNet devuelve [x, y, w, h, 5x(landmark_x, landmark_y), score]
            # en pixeles ya referidos al frame original (no hace falta
            # reescalar como con la SSD vieja).
            x, y, w, h = cara[:4].astype(int)
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(ancho, x + w), min(alto, y + h)
            cajas.append(np.array([x1, y1, x2, y2]))
    return cajas


def recortar_rostro(frame: np.ndarray, caja) -> np.ndarray:
    """Extrae la region de la cara de un cuadro, dado el resultado de
    detectar(). Se usa para guardar la foto de evidencia."""
    x1, y1, x2, y2 = caja
    return frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
