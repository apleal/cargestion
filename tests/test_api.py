"""API para n8n u otras automatizaciones: seguimiento y registro de escaneos de Auto1."""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from tasador import models, services

pytestmark = pytest.mark.django_db


@pytest.fixture
def datos():
    call_command("seed_datos")


@pytest.fixture
def api(datos):
    User = get_user_model()
    user = User.objects.create_user("n8n-test")
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client


def test_sin_token_da_401(datos):
    client = APIClient()
    resp = client.get(reverse("api_auto1_seguimiento"))
    assert resp.status_code == 401


def test_crear_token_api_comando(datos, capsys):
    call_command("crear_token_api", usuario="n8n")
    user = get_user_model().objects.get(username="n8n")
    assert Token.objects.filter(user=user).exists()
    out = capsys.readouterr().out
    assert "Token:" in out
    # idempotente: no revienta ni duplica al volver a ejecutarlo
    call_command("crear_token_api", usuario="n8n")
    assert Token.objects.filter(user=user).count() == 1


def test_seguimiento_solo_lista_no_finales(api):
    auto1 = models.Proveedor.objects.get(nombre="Auto1")
    sesion = services.sesion_auto1_continua()
    finalizado = models.EstadoValoracion.objects.filter(es_final=True).first()
    interesante = models.EstadoValoracion.objects.get(nombre="Interesante")

    v_activo = models.Valoracion.objects.create(
        vehiculo=models.Vehiculo.objects.create(marca="Seat", modelo="Ibiza", anio=2020),
        proveedor=auto1,
        tipo_subasta=auto1.tipos_subasta.get(nombre="Auto1"),
        sesion_subasta=sesion,
        lote_id="AAA111",
        precio_venta_estimado=Decimal("10000"),
        estado=interesante,
    )
    v_vendido = models.Valoracion.objects.create(
        vehiculo=models.Vehiculo.objects.create(marca="Audi", modelo="A1", anio=2019),
        proveedor=auto1,
        tipo_subasta=auto1.tipos_subasta.get(nombre="Auto1"),
        sesion_subasta=sesion,
        lote_id="BBB222",
        precio_venta_estimado=Decimal("12000"),
        estado=finalizado,
    )

    resp = api.get(reverse("api_auto1_seguimiento"))
    assert resp.status_code == 200
    refs = [row["referencia"] for row in resp.json()]
    assert "AAA111" in refs
    assert "BBB222" not in refs
    fila = next(r for r in resp.json() if r["referencia"] == "AAA111")
    assert fila["url"] == "https://www.auto1.com/es/app/merchant/car/AAA111"


def test_registrar_escaneo_crea_valoracion_y_calcula(api):
    linea = "Opel Adam 1.4 Glam ecoFlex\t4062\t75.18\tPT46293\t2017\t116830\tGasolina\tManual"
    resp = api.post(reverse("api_auto1_escaneo"), {"texto": linea}, format="json")
    assert resp.status_code == 201
    data = resp.json()
    assert data["referencia"] == "PT46293"
    assert data["es_retasacion"] is False
    assert data["precio_salida"] == "4062"
    assert models.Valoracion.objects.filter(lote_id="PT46293").exists()


def test_registrar_escaneo_detecta_retasacion_y_hereda_venta(api):
    l1 = "Opel Adam 1.4 Glam ecoFlex\t4062\t75.18\tPT46293\t2017\t116830\tGasolina\tManual"
    r1 = api.post(reverse("api_auto1_escaneo"), {"texto": l1}, format="json")
    v1 = models.Valoracion.objects.get(pk=r1.json()["valoracion_id"])
    v1.precio_venta_estimado = Decimal("7500")
    v1.save()
    services.recalcular_y_guardar(v1)

    l2 = "Opel Adam 1.4 Glam ecoFlex\t3900\t75.18\tPT46293\t2017\t116900\tGasolina\tManual"
    r2 = api.post(reverse("api_auto1_escaneo"), {"texto": l2}, format="json")
    assert r2.status_code == 201
    data = r2.json()
    assert data["es_retasacion"] is True
    assert data["precio_venta_estimado"] == "7500.00"  # heredado, no 0
    assert data["tier"] is not None  # con venta 7500 y salida 3900 ya calcula algo
    assert data["puja_maxima_15"] is not None


def test_escaneo_sin_cambios_no_crea_tasacion_nueva(api):
    linea = "Opel Adam 1.4 Glam ecoFlex\t4062\t75.18\tPT46293\t2017\t116830\tGasolina\tManual"
    r1 = api.post(reverse("api_auto1_escaneo"), {"texto": linea}, format="json")
    assert r1.status_code == 201
    assert r1.json()["sin_cambios"] is False

    r2 = api.post(reverse("api_auto1_escaneo"), {"texto": linea}, format="json")
    assert r2.status_code == 200
    assert r2.json()["sin_cambios"] is True
    assert r2.json()["valoracion_id"] == r1.json()["valoracion_id"]
    assert models.Valoracion.objects.filter(lote_id="PT46293").count() == 1


def test_escaneo_con_bajada_informa_precio_anterior_y_variacion(api):
    l1 = "Opel Adam 1.4 Glam ecoFlex\t4062\t75.18\tPT46293\t2017\t116830\tGasolina\tManual"
    l2 = "Opel Adam 1.4 Glam ecoFlex\t3900\t75.18\tPT46293\t2017\t116830\tGasolina\tManual"
    api.post(reverse("api_auto1_escaneo"), {"texto": l1}, format="json")
    r2 = api.post(reverse("api_auto1_escaneo"), {"texto": l2}, format="json")
    assert r2.status_code == 201
    data = r2.json()
    assert data["precio_anterior"] == "4062.00"
    assert data["variacion"] == "-162.00"
    assert models.Valoracion.objects.filter(lote_id="PT46293").count() == 2


def test_la_api_usa_una_unica_sesion_de_auto1(api):
    l1 = "Opel Adam 1.4 Glam ecoFlex\t4062\t75.18\tPT46293\t2017\t116830\tGasolina\tManual"
    l2 = "Seat Ibiza 1.0 TSI FR\t9000\t49.35\tWH27138\t2017\t51774\tGasolina\tManual"
    api.post(reverse("api_auto1_escaneo"), {"texto": l1}, format="json")
    api.post(reverse("api_auto1_escaneo"), {"texto": l2}, format="json")
    sesiones = models.SesionSubasta.objects.filter(proveedor__nombre="Auto1")
    assert sesiones.count() == 1


def test_registrar_escaneo_texto_invalido_da_400(api):
    resp = api.post(reverse("api_auto1_escaneo"), {"texto": ""}, format="json")
    assert resp.status_code == 400


def test_registrar_pasada_requiere_token_y_guarda_el_parte(api, datos):
    sin_token = APIClient().post(reverse("api_auto1_pasada"), {"ok": True}, format="json")
    assert sin_token.status_code == 401

    resp = api.post(
        reverse("api_auto1_pasada"),
        {"ok": True, "revisados": 120, "con_cambios": 5, "sin_cambios": 110,
         "sin_precio": 4, "errores": 1, "detalle": "Sin precio: AAA111"},
        format="json",
    )
    assert resp.status_code == 201
    p = models.PasadaAuto1.objects.get()
    assert p.ok and p.revisados == 120 and p.sin_precio == 4


def _panel_html(client):
    return client.get(reverse("panel")).content.decode()


@pytest.fixture
def web(datos, client):
    User = get_user_model()
    User.objects.create_user("web", password="x")
    client.login(username="web", password="x")
    return client


def _auto1_con_un_coche():
    auto1 = models.Proveedor.objects.get(nombre="Auto1")
    models.Valoracion.objects.create(
        vehiculo=models.Vehiculo.objects.create(marca="Seat", modelo="Ibiza", anio=2020),
        proveedor=auto1,
        tipo_subasta=auto1.tipos_subasta.get(nombre="Auto1"),
        sesion_subasta=services.sesion_auto1_continua(),
        lote_id="AAA111",
        precio_venta_estimado=Decimal("10000"),
        estado=models.EstadoValoracion.objects.get(nombre="Interesante"),
    )


def test_panel_sin_auto1_no_muestra_la_tarjeta_de_seguimiento(web):
    assert "eguimiento de Auto1" not in _panel_html(web)


def test_panel_avisa_si_nunca_ha_llegado_una_pasada(web):
    _auto1_con_un_coche()
    html = _panel_html(web)
    assert "todavía no ha dado señales" in html


def test_panel_avisa_si_la_ultima_pasada_fallo(web):
    _auto1_con_un_coche()
    models.PasadaAuto1.objects.create(ok=False, detalle="Auto1 pide captcha")
    html = _panel_html(web)
    assert "ha FALLADO" in html
    assert "Auto1 pide captcha" in html


def test_panel_avisa_si_lleva_mas_de_36h_sin_pasadas(web):
    from datetime import timedelta

    from django.utils import timezone

    _auto1_con_un_coche()
    models.PasadaAuto1.objects.create(ok=True, fecha=timezone.now() - timedelta(hours=40))
    assert "sin dar señales" in _panel_html(web)


def test_panel_muestra_ok_si_hay_pasada_reciente(web):
    _auto1_con_un_coche()
    models.PasadaAuto1.objects.create(ok=True, revisados=10, con_cambios=2)
    html = _panel_html(web)
    assert "Seguimiento de Auto1 funcionando" in html
    assert "10 coches revisados" in html
