"""Humo: las páginas cargan y el cálculo en vivo responde."""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def cliente(client):
    call_command("seed_datos")
    User = get_user_model()
    User.objects.create_user("t", password="t")
    client.login(username="t", password="t")
    return client


def test_panel_carga(cliente):
    assert cliente.get(reverse("panel")).status_code == 200


def test_valoracion_nueva_carga(cliente):
    assert cliente.get(reverse("valoracion_nueva")).status_code == 200


def test_calcular_api_devuelve_escenarios(cliente):
    from tasador.models import TipoSubasta

    tipo = TipoSubasta.objects.get(nombre="BCA normal")
    resp = cliente.post(
        reverse("calcular_api"),
        {
            "tipo_subasta": tipo.pk,
            "regimen_fiscal": "rebu",
            "precio_venta_estimado": "15000",
            "piezas_pintura": "4",
            "coste_alberto": "50",
            "coste_gasolina": "40",
            "coste_pintura_por_pieza": "87",
            "coste_garantia": "225",
            "coste_mecanica": "200",
            "coste_cambio_titularidad": "72",
            "coste_transporte": "350",
            "puja": "10000",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["escenarios"]) == 3
    assert data["escenarios"][0]["puja_maxima"] is not None
    assert data["desglose"]["coste_adquisicion"] == "10643.48"


def test_pegar_lotes_previsualiza(cliente):
    linea = "3\tCitroën C1 C1 1.0 VTI FEEL 72\t53 KW (72 CV), Gasolina, Manual, 79328 Km, 2019\t9553LDF\t17/12/2019\tBCA Madrid"
    resp = cliente.post(reverse("pegar_lotes"), {"texto": linea})
    assert resp.status_code == 200
    assert b"Citro" in resp.content
