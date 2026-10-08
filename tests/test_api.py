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


def test_el_escaneo_anota_la_ultima_comprobacion(api):
    linea = "Opel Adam 1.4 Glam ecoFlex\t4062\t75.18\tPT46293\t2017\t116830\tGasolina\tManual"
    r1 = api.post(reverse("api_auto1_escaneo"), {"texto": linea}, format="json")
    v = models.Valoracion.objects.get(pk=r1.json()["valoracion_id"])
    assert v.ultima_comprobacion is not None

    # una pasada sin cambios también cuenta como comprobado
    models.Valoracion.objects.filter(pk=v.pk).update(ultima_comprobacion=None)
    api.post(reverse("api_auto1_escaneo"), {"texto": linea}, format="json")
    v.refresh_from_db()
    assert v.ultima_comprobacion is not None


def test_ficha_sin_precio_se_marca_vendido_a_la_segunda_pasada(api):
    linea = "Opel Adam 1.4 Glam ecoFlex\t4062\t75.18\tPT46293\t2017\t116830\tGasolina\tManual"
    api.post(reverse("api_auto1_escaneo"), {"texto": linea}, format="json")
    url = reverse("api_auto1_no_disponible")

    r1 = api.post(url, {"referencia": "PT46293"}, format="json")
    assert r1.json() == {"referencia": "PT46293", "fallos_seguidos": 1, "marcado_vendido": False}
    assert "PT46293" in [c["referencia"] for c in api.get(reverse("api_auto1_seguimiento")).json()]

    r2 = api.post(url, {"referencia": "PT46293"}, format="json")
    assert r2.json()["marcado_vendido"] is True
    v = models.Valoracion.objects.get(lote_id="PT46293")
    assert v.estado.nombre == "Vendido"
    # ya no se vigila
    assert "PT46293" not in [c["referencia"] for c in api.get(reverse("api_auto1_seguimiento")).json()]


def test_una_lectura_buena_pone_a_cero_los_fallos_de_ficha(api):
    linea = "Opel Adam 1.4 Glam ecoFlex\t4062\t75.18\tPT46293\t2017\t116830\tGasolina\tManual"
    api.post(reverse("api_auto1_escaneo"), {"texto": linea}, format="json")
    api.post(reverse("api_auto1_no_disponible"), {"referencia": "PT46293"}, format="json")
    assert models.Valoracion.objects.get(lote_id="PT46293").fallos_ficha == 1

    api.post(reverse("api_auto1_escaneo"), {"texto": linea}, format="json")
    assert models.Valoracion.objects.get(lote_id="PT46293").fallos_ficha == 0
    # la siguiente falta vuelve a contar desde 1, no marca vendido
    r = api.post(reverse("api_auto1_no_disponible"), {"referencia": "PT46293"}, format="json")
    assert r.json()["marcado_vendido"] is False


def test_no_disponible_con_referencia_desconocida_da_404(api):
    r = api.post(reverse("api_auto1_no_disponible"), {"referencia": "NOEXISTE"}, format="json")
    assert r.status_code == 404


def _dos_coches_uno_en_precio(api, web):
    """A (salida 7500, venta 15000 -> 15 %) escaneado ANTES que B (sin objetivo)."""
    la = "Seat Ibiza 1.0 TSI FR\t7500\t49.35\tAAA111\t2017\t51774\tGasolina\tManual"
    lb = "Audi A1 1.4 TFSI\t14000\t49.35\tBBB222\t2018\t60000\tGasolina\tManual"
    ra = api.post(reverse("api_auto1_escaneo"), {"texto": la}, format="json").json()
    api.post(reverse("api_auto1_escaneo"), {"texto": lb}, format="json")
    web.post(
        reverse("celda_update", args=[ra["valoracion_id"]]),
        {"campo": "precio_venta_estimado", "valor": "15000"},
    )
    sesion = models.SesionSubasta.objects.get(proveedor__nombre="Auto1")
    return sesion


def test_las_oportunidades_van_primero_en_la_lista_y_se_pueden_filtrar(api, web):
    sesion = _dos_coches_uno_en_precio(api, web)
    url = reverse("sesion_detalle", args=[sesion.pk])

    html = web.get(url).content.decode()
    assert html.index("Seat") < html.index("Audi")  # aunque B se escaneó después
    assert "Oportunidades (1)" in html

    solo = web.get(url, {"oportunidades": "1"}).content.decode()
    assert "Seat" in solo and "Audi" not in solo
    assert "← Ver activos" in solo


def test_el_panel_lista_las_oportunidades_con_su_objetivo(api, web):
    _dos_coches_uno_en_precio(api, web)
    html = web.get(reverse("panel")).content.decode()
    assert "En precio ahora mismo (1)" in html
    assert "🎯 15%" in html
    assert "Audi" not in html.split("En precio ahora mismo")[1].split("Próximas subastas")[0]


def test_la_lista_marca_los_coches_sin_comprobar(api, web):
    sesion = _dos_coches_uno_en_precio(api, web)
    models.Valoracion.objects.filter(lote_id="BBB222").update(ultima_comprobacion=None)
    html = web.get(reverse("sesion_detalle", args=[sesion.pk])).content.decode()
    assert "sin comprobar" in html
    assert "✓ " in html


def test_latido_registra_conexion_y_devuelve_si_hay_pasada_pedida(api, web):
    r = api.post(reverse("api_auto1_latido"), {"programada": "08:30"}, format="json")
    assert r.status_code == 200
    assert r.json() == {
        "pasada_solicitada": False, "ultima_pasada_fecha": None,
        "pausado": False, "detener": False,
    }
    srv = models.ServicioAuto1.obtener()
    assert srv.ultimo_latido is not None and srv.programada == "08:30"

    _auto1_con_un_coche()
    web.post(reverse("seguimiento_auto1_solicitar"))
    assert api.post(reverse("api_auto1_latido"), {}, format="json").json()["pasada_solicitada"] is True

    # al empezar la pasada se consume la petición y queda "en curso"
    api.post(reverse("api_auto1_latido"), {"en_curso": True, "consumir_solicitud": True}, format="json")
    srv.refresh_from_db()
    assert srv.pasada_solicitada is None and srv.en_curso_desde is not None
    assert api.post(reverse("api_auto1_latido"), {"en_curso": True}, format="json").json()["pasada_solicitada"] is False

    # al terminar deja de estar en curso
    api.post(reverse("api_auto1_latido"), {"en_curso": False}, format="json")
    srv.refresh_from_db()
    assert srv.en_curso_desde is None


def test_latido_sin_token_da_401(datos):
    assert APIClient().post(reverse("api_auto1_latido"), {}, format="json").status_code == 401


def test_latido_devuelve_la_fecha_de_la_ultima_pasada(api):
    from django.utils import timezone

    models.PasadaAuto1.objects.create(ok=True)
    r = api.post(reverse("api_auto1_latido"), {}, format="json")
    assert r.json()["ultima_pasada_fecha"] == timezone.localdate().isoformat()


def test_solicitar_pasada_exige_login_y_post(datos, client):
    url = reverse("seguimiento_auto1_solicitar")
    assert client.post(url).status_code == 302  # al login
    assert models.ServicioAuto1.obtener().pasada_solicitada is None


def test_solicitar_pasada_no_se_duplica(web):
    url = reverse("seguimiento_auto1_solicitar")
    assert web.get(url).status_code == 405
    web.post(url)
    primera = models.ServicioAuto1.obtener().pasada_solicitada
    assert primera is not None
    web.post(url)
    assert models.ServicioAuto1.obtener().pasada_solicitada == primera


def test_panel_muestra_boton_y_estado_del_servicio(web):
    from datetime import timedelta

    from django.utils import timezone

    _auto1_con_un_coche()
    models.PasadaAuto1.objects.create(ok=True, revisados=3)
    html = _panel_html(web)
    assert "Actualizar ahora" in html
    assert "todavía no se ha conectado" in html

    srv = models.ServicioAuto1.obtener()
    srv.ultimo_latido = timezone.now() - timedelta(seconds=20)
    srv.programada = "08:30"
    srv.save()
    html = _panel_html(web)
    assert "Servicio conectado" in html and "a las 08:30" in html

    srv.ultimo_latido = timezone.now() - timedelta(minutes=30)
    srv.save()
    html = _panel_html(web)
    assert "sin conexión" in html
    assert "❌" in html


def test_panel_con_pasada_pedida_o_en_curso_oculta_el_boton(web):
    from django.utils import timezone

    _auto1_con_un_coche()
    models.PasadaAuto1.objects.create(ok=True)
    srv = models.ServicioAuto1.obtener()
    srv.pasada_solicitada = timezone.now()
    srv.save()
    html = _panel_html(web)
    assert "Actualizar ahora" not in html
    assert "la recoge en menos de un minuto" in html

    srv.pasada_solicitada = None
    srv.en_curso_desde = timezone.now()
    srv.save()
    html = _panel_html(web)
    assert "Actualizar ahora" not in html
    assert "Pasada en curso" in html


# ---------------------------------------------------------------- pantalla de control
def test_latido_guarda_progreso_problemas_y_actividad(api):
    r = api.post(
        reverse("api_auto1_latido"),
        {
            "en_curso": True,
            "consumir_solicitud": True,
            "progreso": {"actual": 3, "total": 10, "referencia": "AB123"},
            "problemas": "",
            "log": ["Login en Auto1 correcto.", "[3/10] AB123: sin cambios"],
        },
        format="json",
    )
    assert r.status_code == 200
    assert r.json()["pausado"] is False and r.json()["detener"] is False
    srv = models.ServicioAuto1.obtener()
    assert (srv.progreso_actual, srv.progreso_total, srv.progreso_ref) == (3, 10, "AB123")
    assert models.EventoAuto1.objects.count() == 2

    # al terminar se limpia el progreso
    api.post(reverse("api_auto1_latido"), {"en_curso": False}, format="json")
    srv.refresh_from_db()
    assert srv.en_curso_desde is None and srv.progreso_total == 0


def test_latido_comunica_los_problemas_de_configuracion(api):
    api.post(
        reverse("api_auto1_latido"),
        {"problemas": "Faltan variables de entorno: AUTO1_EMAIL."},
        format="json",
    )
    assert "AUTO1_EMAIL" in models.ServicioAuto1.obtener().problemas
    api.post(reverse("api_auto1_latido"), {"problemas": ""}, format="json")
    assert models.ServicioAuto1.obtener().problemas == ""


def test_la_actividad_solo_conserva_las_ultimas_300_lineas(api):
    for bloque in range(4):
        api.post(
            reverse("api_auto1_latido"),
            {"log": [f"linea {bloque}-{n}" for n in range(100)]},
            format="json",
        )
    assert models.EventoAuto1.objects.count() == 300
    assert not models.EventoAuto1.objects.filter(texto="linea 0-0").exists()
    assert models.EventoAuto1.objects.filter(texto="linea 3-99").exists()


def test_pantalla_de_seguimiento_nunca_conectado_muestra_el_diagnostico(web):
    html = web.get(reverse("seguimiento_auto1")).content.decode()
    assert "Seguimiento automático de Auto1" in html
    assert "todavía no se ha conectado" in html
    assert "APP_TOKEN" in html and "AUTO1_EMAIL" in html
    assert "↻ Lanzar pasada ahora" in html


def test_pantalla_de_seguimiento_muestra_progreso_en_vivo(web):
    from django.utils import timezone

    srv = models.ServicioAuto1.obtener()
    srv.ultimo_latido = timezone.now()
    srv.programada = "08:30"
    srv.en_curso_desde = timezone.now()
    srv.progreso_actual, srv.progreso_total, srv.progreso_ref = 37, 112, "AB12345"
    srv.save()
    models.EventoAuto1.objects.create(texto="[37/112] AB12345: 4062 -> 3900")

    html = web.get(reverse("seguimiento_auto1")).content.decode()
    assert "Recogiendo datos de Auto1 ahora mismo" in html
    assert "Coche 37 de 112" in html and "AB12345" in html
    assert "width:33%" in html
    assert "Detener pasada" in html
    assert "↻ Lanzar pasada ahora" not in html  # el botón se oculta mientras trabaja
    assert "[37/112] AB12345: 4062 -&gt; 3900" in html  # actividad en directo (escapada)


def test_pantalla_muestra_los_problemas_que_comunica_el_servicio(web):
    from django.utils import timezone

    srv = models.ServicioAuto1.obtener()
    srv.ultimo_latido = timezone.now()
    srv.problemas = "Faltan variables de entorno: AUTO1_EMAIL, AUTO1_PASSWORD."
    srv.save()
    html = web.get(reverse("seguimiento_auto1")).content.decode()
    assert "problema de configuración" in html
    assert "AUTO1_PASSWORD" in html


def test_la_zona_parcial_no_es_una_pagina_completa(web):
    html = web.get(reverse("seguimiento_auto1"), {"parcial": "1"}).content.decode()
    assert "<!doctype" not in html.lower()
    assert "Actividad del servicio" in html


def test_acciones_lanzar_detener_y_cancelar(web):
    from django.utils import timezone

    url = reverse("seguimiento_auto1_accion")
    assert web.get(url).status_code == 405

    web.post(url, {"accion": "lanzar"})
    assert models.ServicioAuto1.obtener().pasada_solicitada is not None
    web.post(url, {"accion": "detener"})  # sin pasada en curso: cancela la petición
    assert models.ServicioAuto1.obtener().pasada_solicitada is None

    srv = models.ServicioAuto1.obtener()
    srv.en_curso_desde = timezone.now()
    srv.save()
    web.post(url, {"accion": "detener"})
    assert models.ServicioAuto1.obtener().detener_solicitada is True


def test_detener_llega_al_servicio_y_se_limpia_al_acabar(api, web):
    api.post(reverse("api_auto1_latido"), {"en_curso": True, "consumir_solicitud": True}, format="json")
    web.post(reverse("seguimiento_auto1_accion"), {"accion": "detener"})
    r = api.post(reverse("api_auto1_latido"), {"en_curso": True}, format="json")
    assert r.json()["detener"] is True
    api.post(reverse("api_auto1_latido"), {"en_curso": False}, format="json")
    assert models.ServicioAuto1.obtener().detener_solicitada is False


def test_pausar_y_reanudar_llegan_al_servicio(api, web):
    url = reverse("seguimiento_auto1_accion")
    web.post(url, {"accion": "pausar"})
    assert api.post(reverse("api_auto1_latido"), {}, format="json").json()["pausado"] is True
    web.post(url, {"accion": "reanudar"})
    assert api.post(reverse("api_auto1_latido"), {}, format="json").json()["pausado"] is False


def test_el_panel_avisa_de_que_el_seguimiento_esta_pausado(web):
    from django.utils import timezone

    _auto1_con_un_coche()
    models.PasadaAuto1.objects.create(ok=True)
    srv = models.ServicioAuto1.obtener()
    srv.pausado = True
    srv.ultimo_latido = timezone.now()
    srv.save()
    assert "PAUSADO" in _panel_html(web)


def test_el_menu_tiene_enlace_a_seguimiento(web):
    assert reverse("seguimiento_auto1") in _panel_html(web)
