"""Oportunidades de Auto1 · fase 1: búsquedas guardadas."""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from tasador import models

pytestmark = pytest.mark.django_db

LINEA = "Seat Ibiza 1.0 TSI FR Crono\t9161\t49,35\tWH27138\t2017\t51774\tGasolina\tManual"
URL = "https://www.auto1.com/es/app/merchant/cars?channel=24h&countries=ES&dir=desc&page=1&sort=closingSoon"


@pytest.fixture
def web(client):
    call_command("seed_datos")
    get_user_model().objects.create_user("web", password="x")
    client.login(username="web", password="x")
    return client


def _crear(web, **extra):
    datos = {
        "linea_plugin": LINEA, "url_listado": URL, "precio_venta_estimado": "10500",
        "tolerancia_km": "10000", "palabras_titulo": "",
        "estado_carroceria": models.EstadoCarroceria.objects.get(nombre="Estado normal").pk,
    }
    datos.update(extra)
    return web.post(reverse("busqueda_nueva"), datos)


def test_las_paginas_exigen_login(client):
    call_command("seed_datos")
    for nombre in ("oportunidades_lista", "busqueda_nueva"):
        assert client.get(reverse(nombre)).status_code == 302


def test_la_lista_vacia_explica_que_hace_falta(web):
    html = web.get(reverse("oportunidades_lista")).content.decode()
    assert "Oportunidades de Auto1" in html and "Aún no tienes ninguna búsqueda" in html
    assert "En preparación" in html  # honesto: el escaneo llega en otra fase
    assert reverse("busqueda_nueva") in html


def test_crear_una_busqueda_lee_el_coche_de_la_linea_del_plugin(web):
    r = _crear(web)
    assert r.status_code == 302 and r.url == reverse("oportunidades_lista")
    b = models.BusquedaOportunidad.objects.get()
    assert (b.marca, b.modelo, b.version) == ("Seat", "Ibiza", "1.0 TSI FR Crono")
    assert b.anio == 2017 and b.km_referencia == 51774
    assert b.combustible == "gasolina" and b.cambio == "manual"
    assert b.referencia_origen == "WH27138"
    assert b.precio_venta_estimado == Decimal("10500") and b.pais == "ES"
    assert b.activa is True and b.tolerancia_km == 10000
    assert b.rango_km == (41774, 61774)


def test_los_costes_arrancan_con_los_de_siempre(web):
    _crear(web)
    b = models.BusquedaOportunidad.objects.get()
    p = models.ParametrosCoste.vigentes()
    assert b.coste_alberto == p.comision_alberto and b.coste_garantia == p.garantia
    assert b.coste_pintura_por_pieza == p.pintura_por_pieza and b.coste_mecanica == p.mecanica
    normal = models.EstadoCarroceria.objects.get(nombre="Estado normal")
    assert b.estado_carroceria == normal and b.piezas_pintura == normal.piezas_estimadas


def test_la_tolerancia_de_km_se_puede_cambiar(web):
    _crear(web, tolerancia_km="5000")
    assert models.BusquedaOportunidad.objects.get().rango_km == (46774, 56774)


def test_una_linea_ilegible_no_crea_nada_y_lo_explica(web):
    r = _crear(web, linea_plugin="esto no es una línea del plugin")
    assert r.status_code == 200 and "No reconozco la línea" in r.content.decode()
    assert models.BusquedaOportunidad.objects.count() == 0


def test_hace_falta_la_linea_al_crear(web):
    r = _crear(web, linea_plugin="")
    assert r.status_code == 200 and models.BusquedaOportunidad.objects.count() == 0


@pytest.mark.parametrize(
    "url,mensaje",
    [
        ("https://www.google.com/es/app/merchant/cars?x=1", "enlace de Auto1"),
        ("http://www.auto1.com/es/app/merchant/cars", "enlace de Auto1"),
        ("https://auto1.com.malicioso.net/es/app/merchant/cars", "enlace de Auto1"),
        ("https://www.auto1.com/es/app/merchant/car/AB12345", "no es un listado"),
        ("no es un enlace", "Introduzca una URL válida"),
    ],
)
def test_solo_se_aceptan_listados_de_auto1(web, url, mensaje):
    r = _crear(web, url_listado=url)
    assert r.status_code == 200 and mensaje in r.content.decode()
    assert models.BusquedaOportunidad.objects.count() == 0


def test_el_precio_de_venta_debe_ser_positivo(web):
    assert _crear(web, precio_venta_estimado="0").status_code == 200
    assert _crear(web, precio_venta_estimado="-5").status_code == 200
    assert models.BusquedaOportunidad.objects.count() == 0


def test_la_lista_muestra_la_busqueda_con_su_rango_de_km(web):
    _crear(web, palabras_titulo="1.0 TSI")
    html = web.get(reverse("oportunidades_lista")).content.decode()
    assert "Seat Ibiza" in html and "1.0 TSI FR Crono" in html
    assert "título con «1.0 TSI»" in html
    assert "51.774" in html and "10.000" in html and "Activa" in html


def test_editar_cambia_precio_y_costes_sin_perder_el_coche(web):
    _crear(web)
    b = models.BusquedaOportunidad.objects.get()
    html = web.get(reverse("busqueda_editar", args=[b.pk])).content.decode()
    assert "Costes de preparación" in html and "Coche de referencia" in html

    datos = {
        "url_listado": URL, "precio_venta_estimado": "11000", "tolerancia_km": "8000",
        "palabras_titulo": "", "estado_carroceria": b.estado_carroceria_id, "piezas_pintura": "4",
        "marca": "Seat", "modelo": "Ibiza", "version": "1.0 TSI FR Crono", "anio": "2017",
        "km_referencia": "51774", "combustible": "gasolina", "cambio": "manual",
        "coste_alberto": "60", "coste_gasolina": "40", "coste_pintura_por_pieza": "87",
        "coste_garantia": "225", "coste_mecanica": "200", "coste_cambio_titularidad": "72",
        "coste_transporte": "350", "coste_itv": "0", "coste_tapiceria": "0", "coste_tintado": "0",
        "coste_otros": "0", "activa": "on",
    }
    r = web.post(reverse("busqueda_editar", args=[b.pk]), datos)
    assert r.status_code == 302
    b.refresh_from_db()
    assert b.precio_venta_estimado == Decimal("11000") and b.coste_alberto == Decimal("60")
    assert b.tolerancia_km == 8000 and b.referencia_origen == "WH27138"


def test_al_editar_se_puede_cambiar_el_coche_de_referencia_pegando_otra_linea(web):
    _crear(web)
    b = models.BusquedaOportunidad.objects.get()
    nueva = "Audi A1 1.4 TFSI\t14000\t60,5\tAB99999\t2018\t60000\tGasolina\tManual"
    datos = {
        "linea_plugin": nueva, "url_listado": URL, "precio_venta_estimado": "10500", "tolerancia_km": "10000",
        "palabras_titulo": "", "estado_carroceria": b.estado_carroceria_id, "piezas_pintura": "4",
        "marca": "Seat", "modelo": "Ibiza", "version": "x", "anio": "2017", "km_referencia": "51774",
        "combustible": "", "cambio": "",
        "coste_alberto": "50", "coste_gasolina": "40", "coste_pintura_por_pieza": "87",
        "coste_garantia": "225", "coste_mecanica": "200", "coste_cambio_titularidad": "72",
        "coste_transporte": "350", "coste_itv": "0", "coste_tapiceria": "0", "coste_tintado": "0",
        "coste_otros": "0", "activa": "on",
    }
    assert web.post(reverse("busqueda_editar", args=[b.pk]), datos).status_code == 302
    b.refresh_from_db()
    assert (b.marca, b.modelo, b.anio, b.km_referencia) == ("Audi", "A1", 2018, 60000)
    assert b.referencia_origen == "AB99999"


def test_cambiar_el_estado_de_carroceria_actualiza_las_piezas(web):
    _crear(web)
    b = models.BusquedaOportunidad.objects.get()
    malo = models.EstadoCarroceria.objects.get(nombre="Mal estado")
    datos = {
        "url_listado": URL, "precio_venta_estimado": "10500", "tolerancia_km": "10000",
        "palabras_titulo": "", "estado_carroceria": malo.pk, "piezas_pintura": str(b.piezas_pintura),
        "marca": b.marca, "modelo": b.modelo, "version": b.version, "anio": "2017",
        "km_referencia": "51774", "combustible": "gasolina", "cambio": "manual",
        "coste_alberto": "50", "coste_gasolina": "40", "coste_pintura_por_pieza": "87",
        "coste_garantia": "225", "coste_mecanica": "200", "coste_cambio_titularidad": "72",
        "coste_transporte": "350", "coste_itv": "0", "coste_tapiceria": "0", "coste_tintado": "0",
        "coste_otros": "0", "activa": "on",
    }
    web.post(reverse("busqueda_editar", args=[b.pk]), datos)
    b.refresh_from_db()
    assert b.piezas_pintura == malo.piezas_estimadas


def test_pausar_y_reactivar(web):
    _crear(web)
    b = models.BusquedaOportunidad.objects.get()
    assert web.get(reverse("busqueda_alternar", args=[b.pk])).status_code == 405
    web.post(reverse("busqueda_alternar", args=[b.pk]))
    b.refresh_from_db()
    assert b.activa is False
    assert "Pausada" in web.get(reverse("oportunidades_lista")).content.decode()
    web.post(reverse("busqueda_alternar", args=[b.pk]))
    b.refresh_from_db()
    assert b.activa is True


def test_eliminar_solo_por_post(web):
    _crear(web)
    b = models.BusquedaOportunidad.objects.get()
    assert web.get(reverse("busqueda_eliminar", args=[b.pk])).status_code == 405
    assert models.BusquedaOportunidad.objects.count() == 1
    web.post(reverse("busqueda_eliminar", args=[b.pk]))
    assert models.BusquedaOportunidad.objects.count() == 0


def test_el_menu_enlaza_con_oportunidades(web):
    assert reverse("oportunidades_lista") in web.get(reverse("panel")).content.decode()
