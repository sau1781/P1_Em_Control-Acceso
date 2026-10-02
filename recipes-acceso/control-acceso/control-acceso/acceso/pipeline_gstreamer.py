#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acceso/pipeline_gstreamer.py
==============================
Todo lo que habla directamente con GStreamer vive aqui: la descripcion de
la tuberia de video y los dos callbacks que GStreamer invoca desde SUS
PROPIOS hilos (no el hilo principal de Python).

TOPOLOGIA (la misma idea en las tres fuentes de video posibles):

    fuente -> tee ─┬─ queue(leaky) -> codificador -> RTP -> UDP (vigilante)
                   ├─ queue(leaky) -> [sonda] -> jpegenc -> multifilesink (evidencia)
                   └─ queue(leaky) -> BGR -> appsink (entrega a Python / IA)

Un 'tee' es SINCRONO: sin las 'queue', empuja el cuadro a una rama, espera
a que vuelva, y recien entonces se lo entrega a la siguiente. Cada 'queue'
crea un HILO nuevo, que es lo que realmente desacopla las tres ramas. Las
tres declaran leaky=downstream: si una rama se satura (red lenta, disco
lleno), prefiere botar cuadros viejos antes que bloquear al 'tee' entero.
"""

import time
import logging

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gst, GLib  # noqa: E402

import numpy as np

from acceso import config
from acceso.metricas import METRICAS

log = logging.getLogger("acceso.pipeline")

# Se llenan en construir() y se usan desde los callbacks.
_cola_imagenes = None
_evento_foto = None


def construir_descripcion() -> str:
    """Arma el string de gst-launch segun config.FUENTE.

    ACCESO_FUENTE=webcam     -> camara del PC/portatil, codificador SOFTWARE
                                (x264enc). Este es el modo de desarrollo.
    ACCESO_FUENTE=archivo    -> reproduce config.VIDEO_ARCHIVO en vez de una
                                camara en vivo. Util para repetir pruebas.
    ACCESO_FUENTE=produccion -> v4l2src + codificador de HARDWARE
                                (v4l2h264enc). SOLO funciona en la
                                Raspberry Pi: el chip que hace ese trabajo
                                no existe en un PC ni en QEMU.
    """
    if config.FUENTE == "produccion":
        fuente = (f"v4l2src device={config.DISPOSITIVO_CAM} io-mode=4 ! "
                  f"video/x-raw,width={config.ANCHO_CAPTURA},"
                  f"height={config.ALTO_CAPTURA},framerate={config.FPS_CAPTURA}/1")
        # NV12 es obligatorio: el bloque V4L2 M2M del BCM2711 no acepta otro
        # formato de entrada. level=(string)4 evita que el elemento negocie
        # mal el nivel H.264 y aborte el enlace.
        codificador = (
            "videoconvert ! video/x-raw,format=NV12 ! "
            f"v4l2h264enc extra-controls=\"controls,h264_profile=4,"
            f"video_bitrate={config.BITRATE_BPS},"
            f"h264_i_frame_period={config.GOP}\" ! "
            "video/x-h264,level=(string)4"
        )
    elif config.FUENTE == "archivo":
        fuente = (f"filesrc location={config.VIDEO_ARCHIVO} ! decodebin ! "
                  f"videoconvert ! videorate ! "
                  f"video/x-raw,framerate={config.FPS_CAPTURA}/1")
        codificador = ("videoconvert ! video/x-raw,format=I420 ! "
                       f"x264enc tune=zerolatency speed-preset=ultrafast "
                       f"bitrate={config.BITRATE_BPS // 1000} "
                       f"key-int-max={config.GOP}")
    else:  # "webcam" (por defecto): camara en vivo, codificador software
        fuente = (f"v4l2src device={config.DISPOSITIVO_CAM} ! "
                  f"videoconvert ! videoscale ! "
                  f"video/x-raw,width={config.ANCHO_CAPTURA},"
                  f"height={config.ALTO_CAPTURA} ! videorate ! "
                  f"video/x-raw,framerate={config.FPS_CAPTURA}/1")
        codificador = ("videoconvert ! video/x-raw,format=I420 ! "
                       f"x264enc tune=zerolatency speed-preset=ultrafast "
                       f"bitrate={config.BITRATE_BPS // 1000} "
                       f"key-int-max={config.GOP}")

    # config-interval=1 reinyecta SPS/PPS cada segundo: sin esto, un
    # vigilante que se conecte a mitad de transmision ve pantalla negra
    # indefinidamente porque nunca recibe los parametros de secuencia.
    return f"""
        {fuente} ! tee name=t

        t. ! queue name=rama_udp max-size-buffers=4 max-size-bytes=0
                   max-size-time=0 leaky=downstream !
             {codificador} !
             h264parse config-interval=1 !
             rtph264pay config-interval=1 pt=96 !
             udpsink host={config.HOST_VIGILANTE} port={config.PUERTO_UDP}
                     sync=false async=false

        t. ! queue name=rama_foto max-size-buffers=2 max-size-bytes=0
                   max-size-time=0 leaky=downstream !
             videoconvert ! jpegenc quality=90 !
             multifilesink name=sink_foto
                           location={config.DIR_EVIDENCIAS}/foto_%05d.jpg
                           async=false sync=false

        t. ! queue name=rama_ia max-size-buffers=2 max-size-bytes=0
                   max-size-time=0 leaky=downstream !
             videoconvert ! videoscale !
             video/x-raw,format=BGR,width={config.ANCHO_CAPTURA},
                   height={config.ALTO_CAPTURA} !
             appsink name=vision_sink emit-signals=true sync=false
                     drop=true max-buffers=2
    """


def conectar(pipeline, cola_imagenes, evento_foto):
    """Engancha los callbacks a los elementos con nombre del pipeline ya
    construido. Se llama una vez desde main.py."""
    global _cola_imagenes, _evento_foto
    _cola_imagenes = cola_imagenes
    _evento_foto = evento_foto

    rama_foto = pipeline.get_by_name("rama_foto")
    rama_foto.get_static_pad("src").add_probe(
        Gst.PadProbeType.BUFFER, _probe_guardar_foto)

    appsink = pipeline.get_by_name("vision_sink")
    appsink.connect("new-sample", _en_nuevo_cuadro_appsink)


def _en_nuevo_cuadro_appsink(appsink):
    """Callback del appsink. Corre en el HILO DE STREAMING de GStreamer, no
    en el hilo principal de Python: debe retornar en microsegundos.

    Envuelto en try/except porque una excepcion de Python aqui dentro la
    atrapa GStreamer (que invoca este callback desde C) y por si sola NO
    detiene el pipeline: solo se imprime el traceback y GStreamer sigue
    llamando al callback en el siguiente cuadro, silenciosa e
    indefinidamente. Se prefiere registrar el error y devolver un FlowReturn
    de error explicito.
    """
    t0 = time.perf_counter()
    try:
        return _callback_interno(appsink, t0)
    except Exception:
        log.exception("Fallo en el callback del appsink")
        return Gst.FlowReturn.ERROR


def _callback_interno(appsink, t0):
    sample = appsink.emit("pull-sample")
    if sample is None:
        return Gst.FlowReturn.ERROR

    buf = sample.get_buffer()
    caps = sample.get_caps()
    estructura = caps.get_structure(0)
    ancho = estructura.get_value("width")
    alto = estructura.get_value("height")
    if ancho is None or alto is None:
        return Gst.FlowReturn.ERROR

    ok, map_info = buf.map(Gst.MapFlags.READ)
    if not ok:
        return Gst.FlowReturn.ERROR
    try:
        # El stride (bytes reales por fila) puede superar ancho*3 porque
        # GStreamer alinea cada fila a 4 bytes. Se deriva dividiendo el
        # tamano total del buffer entre el alto en vez de usar la API de
        # GstVideo.VideoFrame, que ha cambiado de forma incompatible entre
        # versiones de PyGObject. Esta division funciona igual en cualquier
        # version porque solo depende de Gst.Buffer.map(), API estable
        # desde GStreamer 1.0.
        stride = map_info.size // alto
        if stride < ancho * 3:
            return Gst.FlowReturn.ERROR

        crudo = bytes(map_info.data[:stride * alto])
        # .copy() rompe el vinculo con la memoria del GstBuffer: es
        # obligatorio, porque esa memoria vuelve al pool de GStreamer en
        # cuanto se hace unmap() y sera reescrita por el siguiente cuadro.
        frame = (np.frombuffer(crudo, dtype=np.uint8)
                 .reshape(alto, stride // 3, 3)[:, :ancho, :]
                 .copy())
    finally:
        buf.unmap(map_info)

    try:
        _cola_imagenes.put_nowait(frame)
        with METRICAS.lock:
            METRICAS.frames_capturados += 1
    except Exception:  # Queue.Full
        with METRICAS.lock:
            METRICAS.frames_capturados += 1
            METRICAS.frames_descartados += 1

    us = (time.perf_counter() - t0) * 1e6
    with METRICAS.lock:
        METRICAS.callback_us_acum += us
        METRICAS.callback_us_max = max(METRICAS.callback_us_max, us)

    return Gst.FlowReturn.OK


def _probe_guardar_foto(pad, info):
    """Obturador de la rama de evidencia. Por omision DESCARTA todos los
    cuadros; solo deja pasar uno cuando hilo_ia.py levanta 'evento_foto'."""
    if _evento_foto.is_set():
        _evento_foto.clear()
        return Gst.PadProbeReturn.PASS
    return Gst.PadProbeReturn.DROP


def manejador_bus(bus, mensaje, loop, contexto):
    """Watch del bus. Corre en el HILO DEL MAIN LOOP, por eso es seguro
    llamar loop.quit() desde aqui. 'contexto' es un dict mutable donde se
    deja el codigo de salida para que main.py lo lea despues de loop.run()."""
    t = mensaje.type

    if t == Gst.MessageType.ERROR:
        err, depuracion = mensaje.parse_error()
        log.error("GStreamer: %s | %s", err, depuracion)
        contexto["codigo_salida"] = 1
        loop.quit()

    elif t == Gst.MessageType.WARNING:
        err, depuracion = mensaje.parse_warning()
        log.warning("GStreamer: %s | %s", err, depuracion)

    elif t == Gst.MessageType.EOS:
        log.info("Fin de flujo (EOS) recibido.")
        if config.FUENTE != "archivo":
            # Con camara en vivo, un EOS significa que la camara desaparecio:
            # es un fallo, no un final normal.
            log.error("EOS inesperado con camara en vivo: se solicita reinicio.")
            contexto["codigo_salida"] = 1
        loop.quit()

    return True
