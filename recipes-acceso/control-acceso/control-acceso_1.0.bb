# =============================================================================
#  control-acceso_1.0.bb
#  Reemplaza el archivo del mismo nombre que ya tenias en
#  meta-control-acceso/recipes-acceso/control-acceso/
# =============================================================================
SUMMARY = "Sistema de Control de Acceso Industrial Autonomo (TEC)"
DESCRIPTION = "Pipeline GStreamer asincrono con deteccion de rostros YuNet \
(ONNX) y deteccion general de objetos (MobileNet-SSD) sobre OpenCV DNN, \
bitacora persistente y override por hardware."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# "file://acceso" apunta a una CARPETA (no un archivo suelto): el fetcher
# local de BitBake copia directorios completos de forma recursiva, asi que
# los 10 modulos de acceso/ viajan juntos sin listarlos uno por uno. Si se
# agrega o se borra un .py dentro de acceso/, no hay que tocar esta receta.
#
# El modelo de rostros (YuNet, ONNX) NO se bundlea como file:// local: el
# archivo original vive en GitHub bajo Git LFS, y la URL normal
# (raw.githubusercontent.com) devuelve solo un puntero de texto de 131
# bytes, no el binario real. Se fetch directo desde el servidor de medios
# de LFS, con su checksum, para que BitBake lo descargue y verifique solo
# durante do_fetch (igual que cualquier otro SRC_URI remoto).
SRC_URI = " \
    file://acceso \
    file://control-acceso.service \
    file://MobileNetSSD_deploy.prototxt \
    file://MobileNetSSD_deploy.caffemodel \
    https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet/face_detection_yunet_2023mar.onnx;downloadfilename=face_detection_yunet_2023mar.onnx \
"
SRC_URI[sha256sum] = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"


inherit systemd useradd
S = "${UNPACKDIR}"

SYSTEMD_SERVICE:${PN} = "control-acceso.service"
SYSTEMD_AUTO_ENABLE = "enable"

USERADD_PACKAGES = "${PN}"
USERADD_PARAM:${PN} = "--system --no-create-home --shell /sbin/nologin -g acceso \
                       acceso"
GROUPADD_PARAM:${PN} = "--system acceso"

# -----------------------------------------------------------------------------
# Cada plugin de GStreamer y cada modulo de Python se declara a nivel de
# SUBPAQUETE, no como el metapaquete completo (gstreamer1.0-plugins-good
# entero, por ejemplo): asi la imagen no arrastra decenas de MB de cosas que
# el pipeline nunca usa, y si algun elemento falta, el error de bitbake dice
# exactamente cual falta en vez de "funciona porque cayo todo adentro".
#
# python3-numpy y python3-pygobject viven en meta-openembedded/meta-python:
# confirmar con "bitbake-layers show-layers" que esa capa este agregada
# (ver la nota sobre bblayers.conf mas abajo).
# -----------------------------------------------------------------------------
RDEPENDS:${PN} = " \
    python3-core \
    python3-numpy \
    python3-pygobject \
    python3-gpiod \
    python3-opencv \
    gstreamer1.0 \
    gstreamer1.0-python \
    gstreamer1.0-plugins-base-app \
    gstreamer1.0-plugins-base-videoconvertscale \
    gstreamer1.0-plugins-base-videorate \
    gstreamer1.0-plugins-good-video4linux2 \
    gstreamer1.0-plugins-good-jpeg \
    gstreamer1.0-plugins-good-multifile \
    gstreamer1.0-plugins-good-rtp \
    gstreamer1.0-plugins-good-udp \
    gstreamer1.0-plugins-bad-videoparsersbad \
"

do_install() {
    # El paquete Python completo (10 modulos + __init__.py) se copia entero
    # a /usr/share/control-acceso/acceso/, preservando la estructura de
    # carpeta para que "python3 -m acceso.main" funcione igual que en el PC.
    install -d ${D}${datadir}/control-acceso/acceso
    cp -r ${S}/acceso/. ${D}${datadir}/control-acceso/acceso/
    chown -R root:root ${D}${datadir}/control-acceso
    find ${D}${datadir}/control-acceso -type d -exec chmod 0755 {} \;
    find ${D}${datadir}/control-acceso -type f -exec chmod 0644 {} \;
    find ${D}${datadir}/control-acceso/acceso -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

    # Modelos: solo lectura, junto al codigo.
    install -m 0644 ${S}/face_detection_yunet_2023mar.onnx \
                    ${D}${datadir}/control-acceso/
    install -m 0644 ${S}/MobileNetSSD_deploy.prototxt ${D}${datadir}/control-acceso/
    install -m 0644 ${S}/MobileNetSSD_deploy.caffemodel ${D}${datadir}/control-acceso/

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${S}/control-acceso.service ${D}${systemd_system_unitdir}/

    # El directorio de datos escribibles (/var/lib/control-acceso) lo crea
    # systemd solo via StateDirectory= en el .service; no se toca aqui.
}

FILES:${PN} += "${datadir}/control-acceso ${systemd_system_unitdir}"

INSANE_SKIP:${PN} += "already-stripped"
