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
    sesion = services.sesion_auto1_de_hoy()
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


def test_registrar_escaneo_texto_invalido_da_400(api):
    resp = api.post(reverse("api_auto1_escaneo"), {"texto": ""}, format="json")
    assert resp.status_code == 400
