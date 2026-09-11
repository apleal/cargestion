from django.urls import path

from . import api_views

urlpatterns = [
    path("auto1/seguimiento/", api_views.SeguimientoAuto1View.as_view(), name="api_auto1_seguimiento"),
    path("auto1/escaneo/", api_views.RegistrarEscaneoAuto1View.as_view(), name="api_auto1_escaneo"),
]
