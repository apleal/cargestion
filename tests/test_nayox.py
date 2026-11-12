"""Nayox: ficha de inspección en PDF -> coche en la rejilla -> tasar."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse

from tasador import models, nayox, services_nayox

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures"
PDF_LEON = (FIXTURES / "nayox_ficha_ejemplo.pdf").read_bytes()  # SEAT León gasolina, manual, con daños
PDF_FORMENTOR = (FIXTURES / "nayox_ficha_ejemplo2.pdf").read_bytes()  # CUPRA Formentor PHEV, sin daños, con reserva de dominio

# Texto con la estructura de una ficha real (datos inventados), incluidas las ligaduras «ﬁ»
TEXTO = """CUPRA - FORMENTOR 2023
1.5 E-HYBRID 272H 175 HYBRID PHEV 25.8KWH VZ DSG
AUTOMATICO - 65 000 KM
Número de expediente : CCF0000
VIN : ZDCJK02A0PF000000
Matrícula : 0000XYZ
INFORMACIONES VEHÍCULOS
Matrícula
0000XYZ
Marca
CUPRA
Modelo
FORMENTOR
Fecha de matriculación
23/08/2023
Combustible
HIBRIDO (GASOLINA - ELÉCTRICO)
Transmisión
AUTOMÁTICO
kW
130
INFORMACIÓN GENERAL DEL VEHÍCULO
¿Dispone de la ﬁcha técnica?
Si
IVA deducible
No
¿Tiene reserva de dominio?
Si
Adquirido en:
Red oﬁcial
"""


# ------------------------------------------------------------------ el lector del PDF
def test_lee_la_ficha_de_un_leon_con_daños_y_la_itv_caducada():
    f = nayox.leer_ficha(PDF_LEON)
    assert (f.expediente, f.matricula, f.vin) == ("TEST001", "0000ABC", "VSSZZZ5FZMR000001")
    assert (f.marca, f.modelo, f.version) == ("SEAT", "LEON", "1.5 TSI 150 CV FR")
    assert (f.anio, f.fecha_matriculacion, f.km) == (2021, date(2021, 3, 15), 54500)  # km actuales, no los de la cabecera
    assert (f.combustible, f.cambio, f.potencia_kw, f.potencia_cv) == ("gasolina", "manual", 110, 150)
    assert f.primera_mano is False and f.iva_deducible is True and f.reserva_dominio is False
    assert "Rayado en puerta" in f.danos_carroceria and not f.carroceria_sin_danos
    assert f.mantenimiento_red_oficial is False and f.proxima_itv == date(2025, 3, 1)
    assert f.equipamiento == ["GPS", "Bluetooth"] and f.color == "Blanco"
    assert any("Daños de carrocería" in a for a in f.avisos(date(2026, 11, 12)))
    assert any("ITV está caducada" in a for a in f.avisos(date(2026, 11, 12)))


def test_lee_un_hibrido_enchufable_con_su_potencia_total():
    f = nayox.leer_ficha(PDF_FORMENTOR)
    assert (f.marca, f.modelo, f.combustible, f.cambio) == ("CUPRA", "FORMENTOR", "phev", "automatico")
    assert f.potencia_cv == 272 and f.potencia_kw == 130  # los «272H» de la versión, no los kW pasados a CV (177)
    assert f.carroceria_sin_danos and f.reserva_dominio is True
    assert f.avisos(date(2026, 11, 12)) == ["Tiene reserva de dominio: hay que cancelarla antes de poder transferirlo."]


def test_normaliza_ligaduras_y_lee_preguntas_con_acentos():
    f = nayox.interpretar(TEXTO)
    assert f.adquirido_en == "Red oficial"  # «oﬁcial» con ligadura -> «oficial»
    assert (f.iva_deducible, f.reserva_dominio) == (False, True)
    assert f.km == 65000 and f.version.endswith("VZ DSG") and f.anio == 2023


@pytest.mark.parametrize(
    "texto,version,esperado",
    [
        ("HIBRIDO (GASOLINA - ELÉCTRICO)", "1.5 E-HYBRID 272H PHEV", "phev"),
        ("HIBRIDO (GASOLINA - ELÉCTRICO)", "1.5 TSI MHEV", "hibrido"),
        ("ELÉCTRICO", "100% EV", "electrico"),
        ("DIESEL", "2.0 TDI", "diesel"),
        ("GASOIL", "", "diesel"),
        ("GASOLINA", "1.0 TSI", "gasolina"),
        ("GLP", "", "glp"),
        ("HIDRÓGENO", "", "otro"),
        ("", "", ""),
    ],
)
def test_traduce_el_combustible(texto, version, esperado):
    assert nayox._combustible(texto, version) == esperado


def test_sin_potencia_en_la_version_se_pasan_los_kw_a_cv():
    texto = TEXTO.replace("272H 175 ", "")
    assert nayox.interpretar(texto).potencia_cv == round(130 * 1.36)


@pytest.mark.parametrize(
    "contenido,mensaje",
    [
        (b"", "no es un PDF"),
        (b"hola esto es texto", "no es un PDF"),
        (b"%PDF-1.4 roto roto roto", "No he podido leer el PDF"),
        pytest.param(b"%PDF" + b"0" * (nayox.MAX_BYTES + 1), "pesa demasiado", id="mas-de-10-MB"),
    ],
    ids=["vacio", "texto", "roto", "mas-de-10-MB"],
)
def test_un_archivo_que_no_vale_da_un_error_que_se_entiende(contenido, mensaje):
    with pytest.raises(nayox.NayoxError, match=mensaje):
        nayox.leer_ficha(contenido)


def test_un_pdf_que_no_es_de_nayox_no_se_importa():
    from io import BytesIO

    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    salida = BytesIO()
    w.write(salida)
    with pytest.raises(nayox.NayoxError, match="No reconozco este PDF"):
        nayox.leer_ficha(salida.getvalue())


def test_sin_identificador_del_coche_no_se_importa():
    texto = "CUPRA - FORMENTOR 2023\n1.5\nAUTOMATICO - 65 000 KM\n"
    f = nayox.interpretar(texto)
    assert f.marca == "CUPRA" and not (f.expediente or f.matricula or f.vin)


def test_las_siglas_cortas_no_se_estropean_al_pasar_a_minusculas():
    assert nayox._capitalizar("CUPRA") == "Cupra" and nayox._capitalizar("BMW") == "BMW"
    assert nayox._capitalizar("SERIE 3") == "Serie 3" and nayox._capitalizar("GOLF GTI") == "Golf GTI"


# ------------------------------------------------------------------ importar: el coche en la rejilla
@pytest.fixture
def datos():
    call_command("seed_datos")
    call_command("seed_datos")  # cada despliegue lo ejecuta: no debe duplicar


def test_el_seed_crea_nayox_sin_comision(datos):
    p = models.Proveedor.objects.get(nombre="Nayox")
    t = models.TipoSubasta.objects.get(proveedor=p)
    assert t.es_predeterminado and t.cuota_plana == Decimal("0") and not t.aplica_conceptos_fijos
    assert models.Proveedor.objects.filter(nombre="Nayox").count() == 1


def test_importar_crea_el_coche_con_sus_datos(datos):
    ficha = nayox.leer_ficha(PDF_FORMENTOR)
    v, repetida = services_nayox.importar_ficha(ficha, hoy=date(2026, 11, 12))
    assert repetida is False
    veh = models.Vehiculo.objects.get(pk=v.vehiculo_id)  # lo guardado, no el objeto recién creado
    assert (veh.marca, veh.modelo, veh.matricula, veh.bastidor) == ("Cupra", "Formentor", "0000DEF", "VSSZZZ5FZMR000002")
    assert veh.version.startswith("1.5 E-HYBRID 272H") and (veh.potencia_cv, veh.anio, veh.km_ultimo_conocido) == (272, 2023, 65000)
    assert (veh.combustible, veh.cambio, veh.fecha_primera_matriculacion) == ("phev", "automatico", date(2023, 8, 23))
    assert v.proveedor.nombre == "Nayox" and v.lote_id == "TEST002" and v.kilometros == 65000
    assert v.precio_salida == 0 and v.sesion_subasta.proveedor.nombre == "Nayox"
    assert "reserva de dominio" in v.observaciones and "expediente TEST002" in v.observaciones


def test_sin_daños_de_carroceria_se_pone_muy_buen_estado_y_con_daños_se_deja_normal(datos):
    sin_danos, _ = services_nayox.importar_ficha(nayox.leer_ficha(PDF_FORMENTOR))
    con_danos, _ = services_nayox.importar_ficha(nayox.leer_ficha(PDF_LEON))
    assert sin_danos.estado_carroceria.nombre == "Muy buen estado" and sin_danos.piezas_pintura == 2
    assert con_danos.estado_carroceria.nombre == "Estado normal"
    assert "Rayado en puerta" in con_danos.observaciones


def test_la_puja_maxima_sale_en_cuanto_hay_precio_de_venta(datos):
    v, _ = services_nayox.importar_ficha(nayox.leer_ficha(PDF_LEON))
    assert not v.r_puja_maxima_principal  # sin precio de venta no hay puja máxima
    v.precio_venta_estimado = Decimal("15000")
    from tasador import services

    services.recalcular_y_guardar(v)
    assert v.r_puja_maxima_principal and Decimal("8000") < v.r_puja_maxima_principal < Decimal("15000")


def test_importar_otra_vez_la_misma_ficha_actualiza_y_no_duplica_el_coche(datos):
    f = nayox.leer_ficha(PDF_LEON)
    primera, _ = services_nayox.importar_ficha(f)
    primera.precio_venta_estimado = Decimal("15000")
    primera.save()
    segunda, repetida = services_nayox.importar_ficha(f)
    assert repetida is True and segunda.vehiculo_id == primera.vehiculo_id
    assert models.Vehiculo.objects.filter(matricula="0000ABC").count() == 1
    assert segunda.precio_venta_estimado == Decimal("15000")  # la venta ya tasada se conserva
    assert segunda.valoracion_anterior_id == primera.pk


def test_sin_el_proveedor_nayox_da_un_error_claro():
    call_command("seed_datos")
    models.Proveedor.objects.filter(nombre="Nayox").delete()
    with pytest.raises(nayox.NayoxError, match="seed_datos"):
        services_nayox.importar_ficha(nayox.leer_ficha(PDF_LEON))


# ------------------------------------------------------------------ pantallas
@pytest.fixture
def web(client, datos, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_user_model().objects.create_user("web", password="x")
    client.login(username="web", password="x")
    return client


def _subir(web, *archivos):
    return web.post(reverse("nayox_importar"), {"pdf": [SimpleUploadedFile(n, c, content_type="application/pdf") for n, c in archivos]})


def test_el_menu_enlaza_con_nayox_y_la_pantalla_pide_el_pdf(web):
    html = web.get(reverse("nayox_importar")).content.decode()
    assert 'href="/nayox/"' in html and 'type="file"' in html and "multiple" in html and 'enctype="multipart/form-data"' in html
    assert "El PDF no trae precio" in html


def test_subir_un_pdf_importa_el_coche_y_lleva_directo_a_tasarlo(web):
    r = _subir(web, ("ficha.pdf", PDF_FORMENTOR))
    v = models.Valoracion.objects.get(proveedor__nombre="Nayox")
    assert r.status_code == 302 and r.url == reverse("valoracion_tasar", args=[v.pk])
    html = web.get(r.url).content.decode()
    assert "Tasar: Cupra Formentor" in html and "65.000 km" in html and "272 CV" in html
    assert "https://www.coches.net/cupra/formentor/segunda-mano/?MinYear=2022" in html and "MinKms=40000" in html


def test_los_mensajes_cuentan_lo_importado_y_los_avisos(web):
    r = _subir(web, ("ficha.pdf", PDF_FORMENTOR))
    texto = " ".join(str(m) for m in web.get(r.url).context["messages"])
    assert "Importado: CUPRA FORMENTOR" in texto and "65.000 km" in texto and "expediente TEST002" in texto
    assert "reserva de dominio" in texto


def test_subir_varios_pdfs_lleva_a_la_rejilla_de_nayox(web):
    r = _subir(web, ("a.pdf", PDF_LEON), ("b.pdf", PDF_FORMENTOR))
    assert models.Valoracion.objects.filter(proveedor__nombre="Nayox").count() == 2
    sesion = models.SesionSubasta.objects.get(proveedor__nombre="Nayox")
    assert r.status_code == 302 and r.url == reverse("sesion_detalle", args=[sesion.pk])
    rejilla = web.get(r.url).content.decode()
    assert "Leon" in rejilla and "Formentor" in rejilla and "🧮 Tasar" in rejilla  # los dos, con su botón de tasar


def test_un_archivo_malo_no_impide_importar_los_buenos(web):
    r = _subir(web, ("roto.pdf", b"%PDF-1.4 roto"), ("ficha.pdf", PDF_LEON))
    assert models.Valoracion.objects.filter(proveedor__nombre="Nayox").count() == 1
    assert r.status_code == 302
    texto = " ".join(str(m) for m in web.get(r.url).context["messages"])
    assert "roto.pdf: No he podido leer el PDF" in texto


def test_sin_archivo_o_con_uno_que_no_es_pdf_se_explica_y_no_importa_nada(web):
    r = web.post(reverse("nayox_importar"), {})
    assert r.status_code == 200 and "Elige al menos un PDF" in r.content.decode()
    r = _subir(web, ("nota.txt", b"hola"))
    assert r.status_code == 200 and "nota.txt: El archivo no es un PDF" in r.content.decode()
    assert not models.Valoracion.objects.filter(proveedor__nombre="Nayox").exists()


def test_la_pantalla_lista_los_ultimos_de_nayox_con_su_enlace_de_tasar(web):
    _subir(web, ("ficha.pdf", PDF_LEON))
    v = models.Valoracion.objects.get(proveedor__nombre="Nayox")
    html = web.get(reverse("nayox_importar")).content.decode()
    assert "Últimos de Nayox" in html and "TEST001" in html and reverse("valoracion_tasar", args=[v.pk]) in html


def test_nayox_exige_sesion(client, datos):
    assert client.get(reverse("nayox_importar")).status_code == 302
    assert client.post(reverse("nayox_importar"), {}).status_code == 302


def test_la_sesion_de_nayox_se_ve_siempre_en_la_lista_de_subastas(web):
    _subir(web, ("ficha.pdf", PDF_LEON))
    sesion = models.SesionSubasta.objects.get(proveedor__nombre="Nayox")
    sesion.fecha = date(2026, 1, 5)  # fuera de la semana en curso
    sesion.save()
    assert "Nayox" in web.get(reverse("sesion_lista")).content.decode()


def test_tasar_un_coche_de_nayox_funciona_como_cualquier_otro(web):
    from tasador import tasacion_mercado as tm

    r = _subir(web, ("ficha.pdf", PDF_FORMENTOR))
    v = models.Valoracion.objects.get(proveedor__nombre="Nayox")
    anuncios = [
        {"id": f"N{i}", "url": f"https://www.coches.net/x-{i}-covo.aspx", "titulo": f"CUPRA FORMENTOR VZ {i}", "precio": 30000 - i * 400,
         "km": 40000 + i * 4000, "anio": 2023, "cv": 272, "combustible": "Híbrido", "provincia": "Madrid"}
        for i in range(10)
    ]
    import json

    t = tm.tasar(v, json.dumps({"origen": "coches.net", "anuncios": anuncios}), usar_ia=False)
    assert t.valida and t.vehiculo == v.vehiculo and t.n_usados == 10
    t.aplicar()
    v.refresh_from_db()
    assert v.precio_venta_estimado == t.precio_sugerido and v.r_puja_maxima_principal > 0


# ------------------------------------------------------------------ el acabado: marca, modelo y acabado con km
@pytest.mark.parametrize(
    "version,esperado",
    [
        ("1.5 E-HYBRID 272H 175 HYBRID PHEV 25.8KWH VZ DSG", "VZ"),
        ("1.5 TSI 150 CV FR", "FR"),
        ("2.0 TDI 150 CV STYLE S-TRONIC", "STYLE"),
        ("1.3 DIG-T N-CONNECTA", "N-CONNECTA"),
        ("1.0 TSI", ""),  # TSI es el motor, no el acabado
        ("1.5 DCI 110", ""),
        ("", ""),
    ],
)
def test_deduce_el_acabado_de_la_version(version, esperado):
    assert nayox.adivinar_acabado(version) == esperado


def test_la_importacion_guarda_el_acabado_y_no_pisa_el_que_ya_corrigiste(datos):
    v, _ = services_nayox.importar_ficha(nayox.leer_ficha(PDF_FORMENTOR))
    assert models.Vehiculo.objects.get(pk=v.vehiculo_id).acabado == "VZ"
    veh = v.vehiculo
    veh.acabado = "VZ CARBON"  # corregido a mano
    veh.save()
    services_nayox.importar_ficha(nayox.leer_ficha(PDF_FORMENTOR))
    assert models.Vehiculo.objects.get(pk=v.vehiculo_id).acabado == "VZ CARBON"


def _anuncio(i, titulo, km=None, **extra):
    return {"id": f"A{i}", "url": f"https://www.coches.net/x-{i}-covo.aspx", "titulo": titulo, "precio": 30000 - i * 300,
            "km": km if km is not None else 40000 + i * 4000, "anio": 2023, "cv": 272, "combustible": "Híbrido", "provincia": "Madrid", **extra}


def test_solo_cuentan_los_anuncios_cuyo_titulo_lleva_el_acabado(datos):
    import json

    from tasador import tasacion_mercado as tm

    v, _ = services_nayox.importar_ficha(nayox.leer_ficha(PDF_FORMENTOR))  # acabado VZ
    anuncios = [_anuncio(i, f"CUPRA FORMENTOR 1.5 e-HYBRID VZ DSG {i}") for i in range(8)] + [
        _anuncio(20 + i, "CUPRA FORMENTOR 1.4 e-HYBRID DSG") for i in range(4)  # sin acabado
    ]
    t = tm.tasar(v, json.dumps({"anuncios": anuncios}), usar_ia=False)
    assert t.valida and t.n_usados == 8
    assert sum(1 for e in t.excluidos if "el título no lleva «vz»" in e["motivo"]) == 4


def test_si_casi_todo_se_descarta_por_el_acabado_el_error_lo_dice(datos):
    import json

    from tasador import tasacion_mercado as tm

    v, _ = services_nayox.importar_ficha(nayox.leer_ficha(PDF_FORMENTOR))
    anuncios = [_anuncio(i, "CUPRA FORMENTOR 1.4 e-HYBRID DSG") for i in range(8)]
    t = tm.tasar(v, json.dumps({"anuncios": anuncios}), usar_ia=False)
    assert not t.valida and "8 anuncios se han descartado porque su título no lleva «VZ»" in t.error
    assert "corrígelo" in t.error


def test_sin_acabado_se_usan_anuncios_de_cualquier_acabado(datos):
    import json

    from tasador import tasacion_mercado as tm

    v, _ = services_nayox.importar_ficha(nayox.leer_ficha(PDF_FORMENTOR))
    v.vehiculo.acabado = ""
    v.vehiculo.save()
    anuncios = [_anuncio(i, "CUPRA FORMENTOR 1.4 e-HYBRID DSG") for i in range(8)]
    assert tm.tasar(v, json.dumps({"anuncios": anuncios}), usar_ia=False).valida


def test_la_busqueda_de_oportunidades_tambien_respeta_las_palabras_del_titulo(datos):
    from tasador import tasacion_mercado as tm

    b = models.BusquedaOportunidad(marca="Seat", modelo="Ibiza", km_referencia=60000, palabras_titulo="FR")
    buenos, malos = tm.filtrar_comparables(
        [_anuncio(1, "SEAT IBIZA 1.0 TSI FR", km=60000), _anuncio(2, "SEAT IBIZA 1.0 TSI STYLE", km=60000)], b
    )
    assert [a["id"] for a in buenos] == ["A1"] and malos[0]["motivo"] == "el título no lleva «fr»"


def test_la_pantalla_de_tasar_deja_ver_y_cambiar_el_acabado(web):
    _subir(web, ("ficha.pdf", PDF_FORMENTOR))
    v = models.Valoracion.objects.get(proveedor__nombre="Nayox")
    html = web.get(reverse("valoracion_tasar", args=[v.pk])).content.decode()
    assert 'name="acabado" value="VZ"' in html and "acabado VZ" in html
    r = web.post(reverse("valoracion_acabado", args=[v.pk]), {"acabado": "  VZ   Carbon  "}, follow=True)
    assert models.Vehiculo.objects.get(pk=v.vehiculo_id).acabado == "VZ Carbon" and "Acabado guardado" in r.content.decode()
    web.post(reverse("valoracion_acabado", args=[v.pk]), {"acabado": ""})
    assert models.Vehiculo.objects.get(pk=v.vehiculo_id).acabado == ""
    assert web.get(reverse("valoracion_acabado", args=[v.pk])).status_code == 405


def test_las_observaciones_dejan_itv_en_mayusculas(datos):
    v, _ = services_nayox.importar_ficha(nayox.leer_ficha(PDF_FORMENTOR), hoy=date(2026, 11, 12))
    assert "próxima ITV" in v.observaciones
