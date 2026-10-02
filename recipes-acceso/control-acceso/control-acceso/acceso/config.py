#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acceso/config.py
=================
Toda la configuracion del sistema en un solo lugar, leida de variables de
entorno con valores por defecto razonables. Ningun otro modulo define rutas,
umbrales ni parametros propios: todos importan este archivo.

Por que separar esto: si el dia de manana algo cambia (la resolucion de la
camara, el umbral de confianza, la ruta de los modelos), se edita UNA linea
aqui y no hay que ir a buscarla entre 1000 lineas de logica de negocio.
"""

import os

# =============================================================================
# FUENTE DE VIDEO
# -----------------------------------------------------------------------------
# ACCESO_FUENTE decide de donde viene el video. Es la unica variable que
# distingue "estoy probando en mi PC" de "esto es la Raspberry Pi final":
#
#   "webcam"     -> camara USB/integrada del computador, en vivo.
#                   Es el modo normal para desarrollar y probar.
#   "archivo"    -> reproduce un video ya grabado (ACCESO_VIDEO_ARCHIVO).
#                   Util para repetir la misma prueba muchas veces.
#   "produccion" -> v4l2src + codificador de HARDWARE (v4l2h264enc).
#                   Solo funciona en la Raspberry Pi; en un PC este elemento
#                   de GStreamer no existe.
# =============================================================================
FUENTE = os.environ.get("ACCESO_FUENTE", "webcam").lower()
VIDEO_ARCHIVO = os.environ.get("ACCESO_VIDEO_ARCHIVO", "simulacion.mp4")
DISPOSITIVO_CAM = os.environ.get("ACCESO_CAM", "/dev/video0")

# --- Formato de captura. 640x480 no es capricho: 640*3 = 1920 bytes por
#     fila, multiplo de 4, lo que evita el problema del "stride" (relleno de
#     alineacion) al copiar el cuadro para la IA.
ANCHO_CAPTURA = int(os.environ.get("ACCESO_ANCHO", "640"))
ALTO_CAPTURA = int(os.environ.get("ACCESO_ALTO", "480"))
FPS_CAPTURA = int(os.environ.get("ACCESO_FPS", "15"))
GOP = int(os.environ.get("ACCESO_GOP", str(FPS_CAPTURA)))
BITRATE_BPS = int(os.environ.get("ACCESO_BITRATE", "1500000"))

# =============================================================================
# TRANSMISION AL PUESTO DE VIGILANCIA
# =============================================================================
HOST_VIGILANTE = os.environ.get("ACCESO_HOST", "127.0.0.1")
PUERTO_UDP = int(os.environ.get("ACCESO_PUERTO", "5000"))

# =============================================================================
# RUTAS
# -----------------------------------------------------------------------------
# En la Raspberry Pi con Yocto, /usr es de solo lectura: por eso todo lo que
# se ESCRIBE vive bajo ACCESO_DATA (que systemd monta como StateDirectory).
# Todo lo que solo se LEE (los modelos de deteccion) vive bajo
# ACCESO_MODELS.
# =============================================================================
DIR_DATOS = os.environ.get("ACCESO_DATA", os.path.join(os.getcwd(), "datos-prueba"))
DIR_MODELOS = os.environ.get("ACCESO_MODELS", os.getcwd())
DIR_EVIDENCIAS = os.path.join(DIR_DATOS, "evidencias")
RUTA_CSV = os.path.join(DIR_DATOS, "registro.csv")

# --- Detector de rostros (YuNet / ONNX). Reemplaza al SSD ResNet-10/Caffe
#     que se usaba antes: OpenCV 5.0 elimino el importador de Caffe, y ONNX
#     + cv2.FaceDetectorYN es la via que OpenCV mantiene activamente.
RUTA_MODELO_ROSTRO = os.path.join(DIR_MODELOS, "face_detection_yunet_2023mar.onnx")

# --- Detector general de objetos (MobileNet-SSD / Caffe, 20 clases VOC).
#     Formato Caffe: si la version de OpenCV instalada no trae el
#     importador (removido en 5.0), este detector se desactiva solo con un
#     aviso (ver deteccion_objetos.py); el acceso por rostro no depende de
#     este modulo.
RUTA_PROTOTXT_OBJETOS = os.path.join(DIR_MODELOS, "MobileNetSSD_deploy.prototxt")
RUTA_PESOS_OBJETOS = os.path.join(DIR_MODELOS, "MobileNetSSD_deploy.caffemodel")


# =============================================================================
# UMBRALES DE DECISION
# =============================================================================

# --- Deteccion de rostros.
UMBRAL_CONFIANZA_ROSTRO = float(os.environ.get("ACCESO_CONF_ROSTRO", "0.85"))
UMBRAL_IOU_NMS = 0.30            # supresion de no-maximos (cajas duplicadas)
# Nota: no se verifica IDENTIDAD, solo se cuenta cuantas caras hay en el
# cuadro. Cualquier cara humana autoriza el acceso (ver hilo_ia.py).

# --- Detector general de objetos.
UMBRAL_CONFIANZA_OBJETOS = float(os.environ.get("ACCESO_CONF_OBJETOS", "0.5"))
# Cada cuantos cuadros se corre el detector general. Es una segunda red
# neuronal completa; correrla en cada cuadro duplicaria el uso de CPU sin
# necesidad, porque un auto o un perro no aparecen y desaparecen en 66 ms.
INTERVALO_DETECCION_OBJETOS = int(os.environ.get("ACCESO_INTERVALO_OBJ", "10"))
# Clases que interesa registrar. Se excluye 'person': las personas ya las
# maneja el pipeline de rostros con mas detalle (identidad, no solo presencia).
CLASES_OBJETOS_VOC = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus",
    "car", "cat", "chair", "cow", "diningtable", "dog", "horse", "motorbike",
    "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor",
]
CLASES_DE_INTERES = {
    "car", "bus", "motorbike", "bicycle", "cat", "dog", "cow", "horse",
    "sheep", "bird", "aeroplane", "train", "boat",
}

# =============================================================================
# TEMPORIZACION DE LA PUERTA
# =============================================================================
TIEMPO_MAXIMO_DECISION = 10.0     # s sin decision valida -> negar por omision
DURACION_APERTURA = 3.0           # s que permanece activo el rele
COOLDOWN_EVIDENCIA = 10.0         # s entre fotos de evidencia de la misma persona
DIAS_RETENCION = int(os.environ.get("ACCESO_RETENCION_DIAS", "30"))
MARGEN_DISCO_MB = 200

# =============================================================================
# GPIO (libgpiod v2)
# =============================================================================
CHIP_GPIO = os.environ.get("ACCESO_GPIOCHIP", "/dev/gpiochip0")
PIN_BOTON = int(os.environ.get("ACCESO_PIN_BOTON", "17"))
PIN_VERDE = int(os.environ.get("ACCESO_PIN_VERDE", "27"))
PIN_ROJO = int(os.environ.get("ACCESO_PIN_ROJO", "22"))

# =============================================================================
# WATCHDOG DE SYSTEMD
# =============================================================================
LATIDO_MAXIMO_IA = 15.0


def preparar_directorios():
    """Crea los directorios de datos si no existen. Se llama una vez al
    arrancar, desde main.py."""
    os.makedirs(DIR_EVIDENCIAS, exist_ok=True)
