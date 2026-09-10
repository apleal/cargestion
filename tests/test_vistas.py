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


LINEA = "3\tCitroën C1 C1 1.0 VTI FEEL 72\t53 KW (72 CV), Gasolina, Manual, 79328 Km, 2019\t9553LDF\t17/12/2019\tBCA Madrid"


def _sesion():
    from tasador.models import Proveedor, SesionSubasta
    bca = Proveedor.objects.get(nombre="BCA")
    return SesionSubasta.objects.create(
        proveedor=bca,
        ubicacion=bca.ubicaciones.first(),
        fecha="2026-09-15",
    )


def test_pegar_crea_lotes_en_sesion_y_rejilla(cliente):
    from tasador.models import Valoracion

    s = _sesion()
    resp = cliente.post(
        reverse("sesion_pegar", args=[s.pk]), {"texto": LINEA + "\n" + LINEA.replace("\t3\t", "\t1\t")}
    )
    assert resp.status_code == 302
    assert Valoracion.objects.filter(sesion_subasta=s).count() == 2

    rejilla = cliente.get(reverse("sesion_detalle", args=[s.pk]))
    assert rejilla.status_code == 200
    assert b"Citro" in rejilla.content
    # ordenadas por lote: la 2 (lote 3) despues de la 1 (lote 1)... comprobamos que hay orden
    contenido = rejilla.content.decode()
    assert contenido.index("9553LDF") >= 0


def test_celda_update_recalcula_puja(cliente):
    from tasador.models import Valoracion

    s = _sesion()
    cliente.post(reverse("sesion_pegar", args=[s.pk]), {"texto": LINEA})
    v = Valoracion.objects.filter(sesion_subasta=s).first()

    resp = cliente.post(
        reverse("celda_update", args=[v.pk]),
        {"campo": "precio_venta_estimado", "valor": "9000"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["puja_15"] is not None
    v.refresh_from_db()
    assert v.precio_venta_estimado == 9000
    assert v.r_puja_maxima_principal is not None
