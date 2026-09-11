from django.urls import path

from . import views

urlpatterns = [
    path("", views.panel, name="panel"),

    path("subastas/", views.sesion_lista, name="sesion_lista"),
    path("subastas/nueva/", views.sesion_nueva, name="sesion_nueva"),
    path("subastas/<int:pk>/", views.sesion_detalle, name="sesion_detalle"),
    path("subastas/<int:pk>/pegar/", views.sesion_pegar, name="sesion_pegar"),
    path("subastas/<int:pk>/sala/", views.sesion_sala, name="sesion_sala"),

    path("valoraciones/", views.valoracion_lista, name="valoracion_lista"),
    path("valoraciones/nueva/", views.valoracion_nueva, name="valoracion_nueva"),
    path("valoraciones/<int:pk>/", views.valoracion_editar, name="valoracion_editar"),
    path("valoraciones/<int:pk>/celda/", views.celda_update, name="celda_update"),
    path("valoraciones/calcular/", views.calcular_api, name="calcular_api"),
    path("valoraciones/pegar/", views.pegar_lotes, name="pegar_lotes"),

    path("vehiculos/<int:pk>/", views.vehiculo_detalle, name="vehiculo_detalle"),
    path("buscar/", views.buscar_vehiculo, name="buscar_vehiculo"),
]
