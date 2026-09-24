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
    assert data["desglose"]["coste_adquisicion"] == "10541.47"
    conceptos = [x["concepto"] for x in data["preparacion"]]
    assert any("Pintura" in c and "4 " in c and "87" in c for c in conceptos)
    pintura = next(x for x in data["preparacion"] if "Pintura" in x["concepto"])
    assert pintura["importe"] == "348.00"


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
    html = rejilla.content.decode()
    assert "Citro" in html

    import re
    thead = re.search(r"<thead>(.*?)</thead>", html, re.S).group(1)
    cols = [c.strip() for c in re.findall(r"<th[^>]*>(.*?)</th>", thead)]
    # el boton Costes va primero (para poder pulsarlo con tiempo), luego la
    # puja justo despues de Km, y no debe haber columna "Estado"
    assert cols[:8] == ["", "Lote", "Coche", "Matrícula", "Km", "Puja 15%", "Puja 12%", "Puja 10%"]
    assert "Estado" not in cols
    # boton Costes, no enlace de texto
    assert 'class="btn mini-btn"' in html


def test_retasacion_auto1_detecta_bajada_de_precio(cliente):
    """Pegar dos veces el mismo coche de Auto1 (precio distinto) enlaza y marca la bajada."""
    from tasador.models import Proveedor, SesionSubasta, Valoracion

    auto1 = Proveedor.objects.get(nombre="Auto1")
    s1 = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-10"
    )
    s2 = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-11"
    )
    linea_1 = "Seat Ibiza 1.0 TSI FR Crono\t9161\t49,35\tWH27138\t2017\t51774\tGasolina\tManual"
    linea_2 = "Seat Ibiza 1.0 TSI FR Crono\t8500\t49,35\tWH27138\t2017\t51900\tGasolina\tManual"

    r1 = cliente.get(reverse("sesion_detalle", args=[s1.pk]))  # asegura csrf cookie
    tok = r1.cookies.get("csrftoken")
    cliente.post(reverse("sesion_pegar", args=[s1.pk]), {"texto": linea_1})
    v1 = Valoracion.objects.get(lote_id="WH27138", sesion_subasta=s1)
    assert v1.precio_salida == 9161

    cliente.post(reverse("sesion_pegar", args=[s2.pk]), {"texto": linea_2})
    v2 = Valoracion.objects.get(lote_id="WH27138", sesion_subasta=s2)
    assert v2.valoracion_anterior_id == v1.pk
    assert v2.precio_salida == 8500

    grid = cliente.get(reverse("sesion_detalle", args=[s2.pk])).content.decode()
    assert "↓ 661" in grid or "661" in grid  # 9161 - 8500 = 661
    assert "retasado" in grid


def test_auto1_no_se_confunde_con_coche_parecido_de_bca(cliente):
    """Bug real: un Citroën C1 2019 de BCA (con matrícula) y un Citroën C1
    2019 de Auto1 (sin matrícula, km parecidos) son coches DISTINTOS -
    Auto1 no debe colgarse del vehículo de BCA solo por marca/modelo/año/km."""
    from tasador.models import Proveedor, SesionSubasta, Valoracion

    s_bca = _sesion()
    cliente.post(reverse("sesion_pegar", args=[s_bca.pk]), {"texto": LINEA})
    v_bca = Valoracion.objects.get(vehiculo__matricula="9553LDF")
    assert v_bca.vehiculo.km_ultimo_conocido == 79328

    auto1 = Proveedor.objects.get(nombre="Auto1")
    s_auto1 = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-16"
    )
    # mismo marca/modelo/año, km dentro del margen del ±5% de matching -
    # antes del fix esto se colgaba del coche de BCA de arriba.
    linea_auto1 = "Citroën C1 1.0 VTI Feel\t4200\t0\tAP99999\t2019\t80000\tGasolina\tManual"
    cliente.post(reverse("sesion_pegar", args=[s_auto1.pk]), {"texto": linea_auto1})

    v_auto1 = Valoracion.objects.get(lote_id="AP99999")
    assert v_auto1.vehiculo_id != v_bca.vehiculo_id
    assert v_auto1.vehiculo.matricula == ""
    assert v_auto1.valoracion_anterior is None


def test_auto1_misma_referencia_enlaza_aunque_cambien_mucho_los_km(cliente):
    """El código de referencia de Auto1 es el identificador fiable entre
    escaneos, no el margen de km (que puede fallar si el coche recorre
    mucho entre un escaneo y el siguiente)."""
    from tasador.models import Proveedor, SesionSubasta, Valoracion

    auto1 = Proveedor.objects.get(nombre="Auto1")
    s1 = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-10"
    )
    s2 = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-20"
    )
    linea_1 = "Citroën C1 1.0 VTI Feel\t4200\t0\tAP99999\t2019\t50000\tGasolina\tManual"
    # +15.000 km entre escaneos: muy por encima del margen de ±5%/2.000 km
    linea_2 = "Citroën C1 1.0 VTI Feel\t3900\t0\tAP99999\t2019\t65000\tGasolina\tManual"

    cliente.post(reverse("sesion_pegar", args=[s1.pk]), {"texto": linea_1})
    v1 = Valoracion.objects.get(lote_id="AP99999", sesion_subasta=s1)
    cliente.post(reverse("sesion_pegar", args=[s2.pk]), {"texto": linea_2})
    v2 = Valoracion.objects.get(lote_id="AP99999", sesion_subasta=s2)

    assert v2.vehiculo_id == v1.vehiculo_id
    assert v2.valoracion_anterior_id == v1.pk


def test_en_precio_se_marca_cuando_salida_por_debajo_de_puja(cliente):
    from tasador.models import Proveedor, SesionSubasta, Valoracion

    auto1 = Proveedor.objects.get(nombre="Auto1")
    s = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-11"
    )
    linea = "Seat Ibiza 1.0 TSI FR Crono\t7500\t49,35\tWH27138\t2017\t51774\tGasolina\tManual"
    cliente.post(reverse("sesion_pegar", args=[s.pk]), {"texto": linea})
    v = Valoracion.objects.get(lote_id="WH27138")
    # venta alta y precio de salida bajo -> la puja maxima al 15% deberia superar la salida (7500)
    resp = cliente.post(
        reverse("celda_update", args=[v.pk]),
        {"campo": "precio_venta_estimado", "valor": "15000"},
    )
    data = resp.json()
    assert data["en_precio"] is True
    assert data["tier"] == "15"

    grid = cliente.get(reverse("sesion_detalle", args=[s.pk])).content.decode()
    assert "🎯 15%" in grid
    assert "tier-15" in grid

    panel = cliente.get(reverse("panel")).content.decode()
    assert "En precio ahora mismo" in panel


def test_buscar_por_referencia_auto1_lleva_al_historico(cliente):
    from tasador.models import Proveedor, SesionSubasta, Valoracion

    auto1 = Proveedor.objects.get(nombre="Auto1")
    s = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-11"
    )
    cliente.post(
        reverse("sesion_pegar", args=[s.pk]),
        {"texto": "Seat Ibiza 1.0 TSI FR Crono\t9161\t49,35\tWH27138\t2017\t51774\tGasolina\tManual"},
    )
    v = Valoracion.objects.get(lote_id="WH27138")

    resp = cliente.get(reverse("buscar_vehiculo"), {"q": "WH27138"})
    assert resp.status_code == 302
    assert resp.url == reverse("vehiculo_detalle", args=[v.vehiculo_id])

    # sin resultados: no rompe, avisa y vuelve
    resp2 = cliente.get(reverse("buscar_vehiculo"), {"q": "NOEXISTE"}, follow=True)
    assert resp2.status_code == 200


def test_historico_vehiculo_marca_comprable_y_muestra_hora(cliente):
    from tasador.models import Proveedor, SesionSubasta, Valoracion

    auto1 = Proveedor.objects.get(nombre="Auto1")
    s1 = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-10"
    )
    s2 = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-11"
    )
    linea_barato = "Seat Ibiza 1.0 TSI FR Crono\t7000\t49,35\tWH27138\t2017\t51774\tGasolina\tManual"
    linea_caro = "Seat Ibiza 1.0 TSI FR Crono\t12000\t49,35\tWH27138\t2017\t51800\tGasolina\tManual"

    cliente.post(reverse("sesion_pegar", args=[s1.pk]), {"texto": linea_barato})
    v1 = Valoracion.objects.get(sesion_subasta=s1)
    cliente.post(reverse("celda_update", args=[v1.pk]), {"campo": "precio_venta_estimado", "valor": "15000"})

    cliente.post(reverse("sesion_pegar", args=[s2.pk]), {"texto": linea_caro})
    v2 = Valoracion.objects.get(sesion_subasta=s2)
    cliente.post(reverse("celda_update", args=[v2.pk]), {"campo": "precio_venta_estimado", "valor": "15000"})

    resp = cliente.get(reverse("vehiculo_detalle", args=[v1.vehiculo_id]))
    html = resp.content.decode()
    assert "tier-15" in html   # barato: llega al 15 %
    assert "✗ no llega" in html  # caro: no llega ni al 10 %
    assert ":" in html  # hora visible (H:i)


def test_rejilla_auto1_agrupa_por_coche_y_ordena_por_ultimo_escaneo(cliente):
    """En Auto1, si el mismo coche se pega dos veces en la misma sesion, la
    rejilla solo muestra la mas reciente como fila principal, con un "+1"
    para la anterior, y esa fila principal va primero (mas reciente)."""
    from tasador.models import Proveedor, SesionSubasta, Valoracion

    auto1 = Proveedor.objects.get(nombre="Auto1")
    s = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-11"
    )
    cliente.post(
        reverse("sesion_pegar", args=[s.pk]),
        {"texto": "Opel Adam 1.4 Glam ecoFlex\t4062\t75.18\tPT46293\t2017\t116830\tGasolina\tManual"},
    )
    cliente.post(
        reverse("sesion_pegar", args=[s.pk]),
        {"texto": "Fiat 500 1.2 Lounge\t4152\t140.28\tTL47170\t2014\t99047\tGasolina\tManual"},
    )
    cliente.post(
        reverse("sesion_pegar", args=[s.pk]),
        {"texto": "Opel Adam 1.4 Glam ecoFlex\t3900\t75.18\tPT46293\t2017\t116900\tGasolina\tManual"},
    )
    assert Valoracion.objects.filter(sesion_subasta=s).count() == 3

    resp = cliente.get(reverse("sesion_detalle", args=[s.pk]))
    assert len(resp.context["lotes"]) == 2  # agrupado: Opel (ultimo) + Fiat
    html = resp.content.decode()
    # solo una fila <tr> visible por PT46293: la del ultimo escaneo (3900), no la de 4062
    assert html.count('<tr data-row="') == 2
    assert "+1 anterior" in html
    assert "3.900 €" in html  # el precio de salida visible es el mas reciente
    hist = html.split('class="historial-mini"')[1]
    assert "4.062" in hist  # el anterior esta dentro del desplegable


def test_ficha_auto1_oculta_fechas_y_manda_piezas_por_carroceria(cliente):
    from tasador.models import EstadoCarroceria, Proveedor, SesionSubasta, Valoracion

    auto1 = Proveedor.objects.get(nombre="Auto1")
    s = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-11"
    )
    cliente.post(
        reverse("sesion_pegar", args=[s.pk]),
        {"texto": "Opel Adam 1.4 Glam ecoFlex\t4062\t75.18\tPT46293\t2017\t116830\tGasolina\tManual"},
    )
    v = Valoracion.objects.get(lote_id="PT46293")

    resp = cliente.get(reverse("valoracion_editar", args=[v.pk]))
    html = resp.content.decode()
    assert "<label>Fecha valoración</label>" not in html
    assert 'type="hidden"' in html and 'name="fecha_valoracion"' in html

    desgastado = EstadoCarroceria.objects.get(nombre="Desgastado")
    assert f'"{desgastado.pk}":6' in html.replace(" ", "")


def test_enlace_buscar_comparables_en_rejilla_y_ficha(cliente):
    from tasador.models import Proveedor, SesionSubasta, Valoracion

    auto1 = Proveedor.objects.get(nombre="Auto1")
    s = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-11"
    )
    cliente.post(
        reverse("sesion_pegar", args=[s.pk]),
        {"texto": "Opel Adam 1.4 Glam ecoFlex\t4062\t75.18\tPT46293\t2017\t116830\tGasolina\tManual"},
    )
    v = Valoracion.objects.get(lote_id="PT46293")

    grid = cliente.get(reverse("sesion_detalle", args=[s.pk])).content.decode()
    assert "google.com/search?q=Opel+Adam+2017" in grid

    ficha = cliente.get(reverse("valoracion_editar", args=[v.pk])).content.decode()
    assert "google.com/search?q=Opel+Adam+2017" in ficha
    assert "ver precios parecidos" in ficha


def test_guardar_costes_no_borra_los_km(cliente):
    """Bug real: guardar la ficha de costes (p. ej. al tocar el transporte)
    no debe vaciar los km del coche."""
    from tasador.models import Proveedor, SesionSubasta, Valoracion

    bca = Proveedor.objects.get(nombre="BCA")
    s = SesionSubasta.objects.create(
        proveedor=bca, ubicacion=bca.ubicaciones.get(nombre="BCA Barcelona"), fecha="2026-09-15"
    )
    cliente.post(
        reverse("sesion_pegar", args=[s.pk]),
        {"texto": LINEA},  # Citroen C1, 79328 km
    )
    v = Valoracion.objects.get(vehiculo__matricula="9553LDF")
    assert v.kilometros == 79328

    form_data = {
        "proveedor": v.proveedor_id, "tipo_subasta": v.tipo_subasta_id,
        "regimen_fiscal": "rebu", "iva_anuncio": "0", "precio_salida": "0",
        "precio_venta_estimado": "9000", "descuento_comision_pct": "0",
        "estado_carroceria": v.estado_carroceria_id, "piezas_pintura": "4",
        "fecha_valoracion": "2026-09-15",
        "coste_alberto": "50", "coste_gasolina": "40", "coste_pintura_por_pieza": "87",
        "coste_garantia": "225", "coste_mecanica": "200", "coste_cambio_titularidad": "72",
        "coste_transporte": "80",  # <- lo que se estaba tocando cuando fallaba
        "coste_itv": "0", "coste_tapiceria": "0", "coste_tintado": "0", "coste_otros": "0",
        "estado": v.estado_id,
    }
    resp = cliente.post(reverse("valoracion_editar", args=[v.pk]), form_data)
    assert resp.status_code == 302

    v.refresh_from_db()
    assert v.kilometros == 79328  # no se ha borrado
    assert v.coste_transporte == Decimal("80.00")


def test_config_transporte_actualiza_precio_por_zona(cliente):
    from tasador.models import Proveedor, TarifaTransporte

    bca = Proveedor.objects.get(nombre="BCA")
    barcelona = TarifaTransporte.objects.get(proveedor=bca, origen="Barcelona")
    resp = cliente.post(
        reverse("config_transporte"),
        {"proveedor": bca.pk, f"precio_{barcelona.pk}": "80"},
    )
    assert resp.status_code == 302
    barcelona.refresh_from_db()
    assert barcelona.precio == Decimal("80.00")


def test_ficha_costes_enlaza_de_vuelta_a_la_subasta(cliente):
    from tasador.models import Proveedor, SesionSubasta, Valoracion

    bca = Proveedor.objects.get(nombre="BCA")
    s = SesionSubasta.objects.create(
        proveedor=bca, ubicacion=bca.ubicaciones.get(nombre="BCA Madrid"), fecha="2026-09-15"
    )
    cliente.post(reverse("sesion_pegar", args=[s.pk]), {"texto": LINEA})
    v = Valoracion.objects.get(vehiculo__matricula="9553LDF")

    html = cliente.get(reverse("valoracion_editar", args=[v.pk])).content.decode()
    assert reverse("sesion_detalle", args=[s.pk]) in html
    assert "Volver a la subasta" in html
    assert "<label>Fecha valoración</label>" not in html


def test_eliminar_vehiculo_borra_coche_y_tasaciones(cliente):
    """Coches ya vendidos (p. ej. de Auto1) se pueden quitar del todo."""
    from tasador.models import Valoracion, Vehiculo

    s = _sesion()
    cliente.post(reverse("sesion_pegar", args=[s.pk]), {"texto": LINEA})
    v = Valoracion.objects.get(vehiculo__matricula="9553LDF")
    veh_pk = v.vehiculo_id

    # por GET no se puede borrar (evita clics/prefetch accidentales)
    assert cliente.get(reverse("vehiculo_eliminar", args=[veh_pk])).status_code == 405

    resp = cliente.post(reverse("vehiculo_eliminar", args=[veh_pk]))
    assert resp.status_code == 302
    assert not Vehiculo.objects.filter(pk=veh_pk).exists()
    assert not Valoracion.objects.filter(vehiculo_id=veh_pk).exists()


def test_favorito_se_marca_y_persiste_en_la_retasacion(cliente):
    """El favorito es del coche, no de la tasación: sobrevive a un repegado."""
    from tasador.models import Proveedor, SesionSubasta, Valoracion

    s1 = _sesion()
    cliente.post(reverse("sesion_pegar", args=[s1.pk]), {"texto": LINEA})
    v1 = Valoracion.objects.get(vehiculo__matricula="9553LDF")
    veh_pk = v1.vehiculo_id

    resp = cliente.post(
        reverse("vehiculo_favorito_toggle", args=[veh_pk]),
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert resp.status_code == 200
    assert resp.json() == {"favorito": True}
    v1.vehiculo.refresh_from_db()
    assert v1.vehiculo.favorito is True

    # se retasa el mismo coche (misma matrícula) en otra sesión
    bca = Proveedor.objects.get(nombre="BCA")
    s2 = SesionSubasta.objects.create(
        proveedor=bca, ubicacion=bca.ubicaciones.first(), fecha="2026-09-20"
    )
    cliente.post(reverse("sesion_pegar", args=[s2.pk]), {"texto": LINEA})
    v2 = Valoracion.objects.get(vehiculo__matricula="9553LDF", sesion_subasta=s2)
    assert v2.vehiculo_id == veh_pk
    assert v2.vehiculo.favorito is True

    # desmarcar
    resp = cliente.post(
        reverse("vehiculo_favorito_toggle", args=[veh_pk]),
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert resp.json() == {"favorito": False}


def test_favoritos_lista_muestra_coches_marcados(cliente):
    from tasador.models import Valoracion

    s = _sesion()
    cliente.post(reverse("sesion_pegar", args=[s.pk]), {"texto": LINEA})
    v = Valoracion.objects.get(vehiculo__matricula="9553LDF")

    resp = cliente.get(reverse("favoritos_lista"))
    assert "Sin favoritos todavía" in resp.content.decode()

    cliente.post(
        reverse("vehiculo_favorito_toggle", args=[v.vehiculo_id]),
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    html = cliente.get(reverse("favoritos_lista")).content.decode()
    assert "Citroën" in html
    assert "9553LDF" in html


def test_celda_origen_actualiza_transporte(cliente):
    from tasador.models import TarifaTransporte, Valoracion

    tt = TarifaTransporte.objects.filter(origen="Sevilla").first()
    tt.precio = 470
    tt.save()

    s = _sesion()
    cliente.post(reverse("sesion_pegar", args=[s.pk]), {"texto": LINEA})
    v = Valoracion.objects.filter(sesion_subasta=s).first()

    resp = cliente.post(
        reverse("celda_update", args=[v.pk]),
        {"campo": "zona_origen", "valor": "Sevilla"},
    )
    assert resp.status_code == 200
    assert resp.json()["transporte"] == "470.00"
    v.refresh_from_db()
    assert v.zona_origen == "Sevilla"
    assert v.coste_transporte == 470


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
