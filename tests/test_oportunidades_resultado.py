"""Oportunidades de Auto1: cálculo, registro del resultado del servicio y avisos."""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from tasador import models, services_oportunidades as so

pytestmark = pytest.mark.django_db

URL = "https://www.auto1.com/es/app/merchant/cars?channel=24h&countryOfOrigin=ES&page=1"


@pytest.fixture
def busqueda():
    call_command("seed_datos")
    b = models.BusquedaOportunidad(
        marca="Nissan", modelo="Qashqai", version="1.6 N-Connecta", anio=2018, km_referencia=136000,
        combustible="gasolina", cambio="manual", url_listado=URL, precio_venta_estimado=Decimal("14500"),
        estado_carroceria=models.EstadoCarroceria.objects.get(nombre="Estado normal"), piezas_pintura=4,
    )
    b.aplicar_costes_por_defecto()
    b.save()
    return b


@pytest.fixture
def api():
    call_command("seed_datos") if not models.Proveedor.objects.exists() else None
    user = get_user_model().objects.create_user("scraper-test")
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
    return c


def p10(b, iva=Decimal("0")):
    return so.evaluar(b, Decimal("1"), iva)["puja_maxima_10"]


def tarjeta(ref, precio, tipo="subasta", **extra):
    return {"referencia": ref, "nombre": f"Nissan Qashqai 1.6 N-Connecta {ref}", "tipo": tipo, "precio": precio,
            "km": 136492, "anio": 2018, "cv": 163, "cambio": "manual", "ubicacion": "ES, Madrid",
            "url": f"https://www.auto1.com/es/app/merchant/car/{ref}", **extra}


def linea(ref, precio, iva="40,00"):
    return f"Nissan Qashqai 1.6 N-Connecta\t{precio}\t{iva}\t{ref}\t2018\t136492\tGasolina\tManual"


def resultado(api, b, coches, **extra):
    cuerpo = {"origen": "programada", "paginas": 2, "leidos": 40, "encajan": len(coches), "coches": coches, **extra}
    return api.post(reverse("api_auto1_busqueda_resultado", args=[b.pk]), cuerpo, format="json")


def test_el_motor_da_tier_segun_el_precio(busqueda):
    tope = p10(busqueda)
    assert tope and tope > 5000
    barato = so.evaluar(busqueda, tope - Decimal("1500"))
    assert barato["tier"] in ("15", "12", "10") and barato["margen_10"] > 0
    justo = so.evaluar(busqueda, tope)
    assert justo["tier"] == "10" and justo["rentabilidad"] >= Decimal("0.0999")
    caro = so.evaluar(busqueda, tope + Decimal("800"))
    assert caro["tier"] == "" and caro["margen_10"] is None


def test_precio_max_del_listado_lleva_holgura(busqueda):
    assert so.precio_max_listado(busqueda) == int(p10(busqueda) + so.HOLGURA_LISTADO)


def test_sin_precio_de_venta_no_hay_candidatos(busqueda):
    busqueda.precio_venta_estimado = Decimal("0")
    assert so.precio_max_listado(busqueda) == 0


def test_la_api_de_busquedas_trae_el_precio_util_y_si_esta_pedida(busqueda, api):
    d = api.get(reverse("api_auto1_busquedas")).json()[0]
    assert d["precio_max_listado"] == so.precio_max_listado(busqueda) and d["solicitada"] is False


def test_resultado_registra_comprables_y_los_pasa_a_seguimiento(busqueda, api):
    tope = int(p10(busqueda, Decimal("40")))
    r = resultado(api, busqueda, [
        {"tarjeta": tarjeta("UA50404", tope - 1200), "linea": linea("UA50404", tope - 1200)},
        {"tarjeta": tarjeta("WF29649", tope + 1500), "linea": linea("WF29649", tope + 1500)},
        {"tarjeta": tarjeta("XX11111", 16148, tipo="compra_ya"), "linea": None},
    ])
    assert r.status_code == 201
    d = r.json()
    assert (d["estado"], d["revisados"], d["comprables"], d["nuevos_comprables"]) == ("ok", 2, 1, 1)
    assert [a["referencia"] for a in d["avisos"]] == ["UA50404"]
    assert d["avisos"][0]["tier"] in ("15", "12", "10") and d["avisos"][0]["url"].endswith("/UA50404")

    ops = {o.referencia: o for o in models.Oportunidad.objects.all()}
    assert ops["UA50404"].comprable and ops["UA50404"].evaluada and ops["UA50404"].margen_10 > 0
    assert not ops["WF29649"].comprable and ops["WF29649"].evaluada
    assert not ops["XX11111"].evaluada and ops["XX11111"].tipo == "compra_ya"

    # el comprable ya está en el seguimiento normal con la venta y costes de la búsqueda
    v = models.Valoracion.objects.get(lote_id="UA50404")
    assert ops["UA50404"].valoracion_id == v.pk
    assert v.precio_venta_estimado == busqueda.precio_venta_estimado
    assert v.coste_garantia == busqueda.coste_garantia and v.iva_anuncio == Decimal("40")
    assert services_tier(v) in ("15", "12", "10")
    assert not models.Valoracion.objects.filter(lote_id__in=["WF29649", "XX11111"]).exists()


def services_tier(v):
    from tasador import services
    return services.tier_precio_salida(v)


def test_la_ejecucion_deja_constancia_de_lo_leido(busqueda, api):
    resultado(api, busqueda, [{"tarjeta": tarjeta("A1", 3000), "linea": linea("A1", 3000)}], leidos=55, paginas=3)
    e = busqueda.ultima_ejecucion
    assert (e.estado, e.leidos, e.paginas, e.encajan, e.revisados) == ("ok", 55, 3, 1, 1)
    assert e.origen == "programada"


def test_no_se_vuelve_a_avisar_si_nada_cambia_y_si_baja_si(busqueda, api):
    tope = int(p10(busqueda, Decimal("40")))
    coche = lambda precio: [{"tarjeta": tarjeta("UA50404", precio), "linea": linea("UA50404", precio)}]
    assert resultado(api, busqueda, coche(tope - 1000)).json()["nuevos_comprables"] == 1
    r = resultado(api, busqueda, coche(tope - 1000)).json()
    assert (r["comprables"], r["nuevos_comprables"], r["avisos"]) == (1, 0, [])
    assert models.Valoracion.objects.filter(lote_id="UA50404").count() == 1

    r = resultado(api, busqueda, coche(tope - 1300)).json()
    assert r["nuevos_comprables"] == 1 and r["avisos"][0]["precio"] == str(tope - 1300)
    assert models.Valoracion.objects.filter(lote_id="UA50404").count() == 2  # retasación enlazada


def test_si_deja_de_ser_comprable_y_vuelve_avisa_otra_vez(busqueda, api):
    tope = int(p10(busqueda, Decimal("40")))
    coche = lambda precio: [{"tarjeta": tarjeta("UA50404", precio), "linea": linea("UA50404", precio)}]
    resultado(api, busqueda, coche(tope - 500))
    assert resultado(api, busqueda, coche(tope + 2000)).json()["comprables"] == 0
    assert resultado(api, busqueda, coche(tope - 500)).json()["nuevos_comprables"] == 1


def test_error_del_servicio_se_registra_y_libera_la_peticion(busqueda, api):
    from django.utils import timezone

    busqueda.solicitada = timezone.now()
    busqueda.save()
    r = resultado(api, busqueda, [], origen="manual", error="Se ha caído la sesión de Auto1")
    assert r.status_code == 201 and r.json()["estado"] == "error"
    busqueda.refresh_from_db()
    assert busqueda.solicitada is None
    assert "caído la sesión" in busqueda.ultima_ejecucion.error
    assert models.Oportunidad.objects.count() == 0


def test_un_coche_que_ya_tenias_en_seguimiento_conserva_tu_tasacion(busqueda, api):
    tope = int(p10(busqueda, Decimal("40")))
    resultado(api, busqueda, [{"tarjeta": tarjeta("UA50404", tope - 300), "linea": linea("UA50404", tope - 300)}])
    v = models.Valoracion.objects.get(lote_id="UA50404")
    v.precio_venta_estimado = Decimal("15900")
    v.save()
    resultado(api, busqueda, [{"tarjeta": tarjeta("UA50404", tope - 900), "linea": linea("UA50404", tope - 900)}])
    ultima = models.Valoracion.objects.filter(lote_id="UA50404").order_by("-created_at", "-id").first()
    assert ultima.precio_venta_estimado == Decimal("15900") and ultima.valoracion_anterior_id == v.pk


def test_latido_informa_de_busquedas_pedidas_y_las_libera(busqueda, api):
    from django.utils import timezone

    assert api.post(reverse("api_auto1_latido"), {}, format="json").json()["busquedas_pedidas"] == []
    busqueda.solicitada = timezone.now()
    busqueda.save()
    assert api.post(reverse("api_auto1_latido"), {}, format="json").json()["busquedas_pedidas"] == [busqueda.pk]
    r = api.post(reverse("api_auto1_latido"), {"busquedas_consumidas": [busqueda.pk]}, format="json").json()
    assert r["busquedas_pedidas"] == []


def test_latido_da_la_fecha_de_la_ultima_busqueda_programada(busqueda, api):
    assert api.post(reverse("api_auto1_latido"), {}, format="json").json()["ultima_busqueda_fecha"] is None
    resultado(api, busqueda, [])
    assert api.post(reverse("api_auto1_latido"), {}, format="json").json()["ultima_busqueda_fecha"] is not None
    resultado(api, busqueda, [], origen="manual")  # las manuales no cuentan como la programada
    e = models.EjecucionBusqueda.objects.filter(origen="programada").first()
    assert e is not None


def test_resultado_exige_token_y_busqueda_existente(busqueda, api):
    assert APIClient().post(reverse("api_auto1_busqueda_resultado", args=[busqueda.pk]), {}, format="json").status_code == 401
    assert api.post(reverse("api_auto1_busqueda_resultado", args=[9999]), {}, format="json").status_code == 404


# ---------------------------------------------------------------- pantallas
@pytest.fixture
def web(client, busqueda):
    get_user_model().objects.create_user("web", password="x")
    client.login(username="web", password="x")
    return client


def test_la_lista_dice_que_aun_no_se_ha_buscado(web, busqueda):
    html = web.get(reverse("oportunidades_lista")).content.decode()
    assert "Todavía no se ha buscado" in html and "Buscar ahora" in html


def test_buscar_ahora_deja_la_peticion_y_la_lista_la_muestra(web, busqueda):
    assert web.get(reverse("busqueda_buscar_ahora", args=[busqueda.pk])).status_code == 405
    r = web.post(reverse("busqueda_buscar_ahora", args=[busqueda.pk]), follow=True)
    busqueda.refresh_from_db()
    assert busqueda.solicitada is not None
    html = r.content.decode()
    assert "Pedida" in html and "esperando al servicio" in html and "no está conectado" in html


def test_no_se_puede_buscar_ahora_una_busqueda_pausada(web, busqueda):
    busqueda.activa = False
    busqueda.save()
    assert "Buscar ahora" not in web.get(reverse("oportunidades_lista")).content.decode()


def test_la_lista_muestra_lo_ultimo_leido_y_los_comprables(web, busqueda, api):
    tope = int(p10(busqueda, Decimal("40")))
    resultado(api, busqueda, [
        {"tarjeta": tarjeta("UA50404", tope - 1200), "linea": linea("UA50404", tope - 1200)},
        {"tarjeta": tarjeta("WF29649", tope + 1500), "linea": linea("WF29649", tope + 1500)},
    ], leidos=70)
    html = web.get(reverse("oportunidades_lista")).content.decode()
    assert "Se pueden comprar ahora (1)" in html and "UA50404" in html and "WF29649" not in html
    assert "70 leídos" in html and "2 encajan" in html and "1 comprable" in html
    assert "https://www.auto1.com/es/app/merchant/car/UA50404" in html and "Abrir en Auto1" in html


def test_un_error_se_ve_en_la_lista(web, busqueda, api):
    resultado(api, busqueda, [], error="Se ha caído la sesión de Auto1")
    html = web.get(reverse("oportunidades_lista")).content.decode()
    assert "Se ha caído la sesión de Auto1" in html and "Se pueden comprar ahora (0)" in html


def test_pantalla_de_coches_de_la_busqueda(web, busqueda, api):
    tope = int(p10(busqueda, Decimal("40")))
    resultado(api, busqueda, [
        {"tarjeta": tarjeta("UA50404", tope - 1200), "linea": linea("UA50404", tope - 1200)},
        {"tarjeta": tarjeta("WF29649", tope + 1500), "linea": linea("WF29649", tope + 1500)},
        {"tarjeta": tarjeta("YA1", 16148, tipo="compra_ya"), "linea": None},
    ])
    # en la siguiente búsqueda ya no sale WF29649
    resultado(api, busqueda, [
        {"tarjeta": tarjeta("UA50404", tope - 1200), "linea": linea("UA50404", tope - 1200)},
        {"tarjeta": tarjeta("YA1", 16148, tipo="compra_ya"), "linea": None},
    ])
    html = web.get(reverse("busqueda_coches", args=[busqueda.pk])).content.decode()
    assert "En el listado ahora (2)" in html and "UA50404" in html and "compra ya: sin calcular" in html
    assert "Ya no salen en el listado (1)" in html and "WF29649" in html
    assert "Historial de búsquedas" in html


def test_las_pantallas_nuevas_exigen_login(client, busqueda):
    assert client.get(reverse("busqueda_coches", args=[busqueda.pk])).status_code == 302
    assert client.post(reverse("busqueda_buscar_ahora", args=[busqueda.pk])).status_code == 302
