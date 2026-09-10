from django.urls import path

from . import views

urlpatterns = [
    path("", views.panel, name="panel"),
    path("valoraciones/", views.valoracion_lista, name="valoracion_lista"),
    path("valoraciones/nueva/", views.valoracion_nueva, name="valoracion_nueva"),
    path("valoraciones/<int:pk>/", views.valoracion_editar, name="valoracion_editar"),
    path("valoraciones/calcular/", views.calcular_api, name="calcular_api"),
    path("valoraciones/pegar/", views.pegar_lotes, name="pegar_lotes"),
    path("vehiculos/<int:pk>/", views.vehiculo_detalle, name="vehiculo_detalle"),
    path("subastas/<int:pk>/", views.sesion_detalle, name="sesion_detalle"),
]
