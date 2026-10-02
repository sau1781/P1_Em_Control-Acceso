# =============================================================================
#  opencv_%.bbappend
# -----------------------------------------------------------------------------
#  IMPORTANTE: la receta de OpenCV en meta-openembedded trae 'dnn' como
#  PACKAGECONFIG OPCIONAL (no viene activado por defecto en todas las
#  versiones/branches). Sin esto, la imagen compila sin ningun error, arranca
#  sin ningun error, y recien al llegar a la primera linea que usa
#  cv2.dnn.readNetFromCaffe(...) el programa revienta con AttributeError:
#  module 'cv2' has no attribute 'dnn'. Es el tipo de fallo que solo se ve
#  en la placa, nunca en el log de bitbake -por eso conviene declararlo
#  explicito aqui y no confiar en el valor por defecto de la receta.
#
#  'python3' agrega los bindings de Python (el paquete python3-opencv que
#  ya declaramos en RDEPENDS de control-acceso_1.0.bb depende de que este
#  PACKAGECONFIG este activo para siquiera EXISTIR como sub-paquete).
# =============================================================================
PACKAGECONFIG:append = " dnn python3"
