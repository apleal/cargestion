"""La tasación de mercado conoce los acabados (Allure < GT Line < GT) y descarta Canarias."""
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from tasador import models, services_fichas, tasacion_mercado as tm

pytestmark = pytest.mark.django_db

ORDEN = ["Active", "Allure", "GT Line", "GT"]
BASE = {"Active": 15800, "Allure": 17000, "GT Line": 18700, "GT": 20200}  # precio a 60.000 km
PENDIENTE = 0.06  # €/km


@pytest.fixture(autouse=True)
def sin_clave(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def coche():
    """Un Peugeot 308 GT Line de 60.000 km en la rejilla."""
    call_command("seed_datos")
    v, _ = services_fichas.crear_coche_en_rejilla(
        proveedor="Tasación IA", ubicacion="Tasación IA", referencia="IA-1", marca="Peugeot", modelo="308",
        version="1.2 PureTech 130 GT Line", acabado="GT Line", anio=2021, km=60000, combustible="gasolina",
        cambio="manual", potencia_cv=130,
    )
    return v


def anuncios_de(acabado, n, **extra):
    """n anuncios de un acabado, con km repartidos de 40.000 a 80.000 y el precio que le toca."""
    salida = []
    for i in range(n):
        km = 40000 + int(40000 * i / max(1, n - 1))
        salida.append({
            "id": f"{acabado[:3].upper()}{i}", "url": f"https://www.coches.net/x-{acabado}-{i}-covo.aspx".replace(" ", ""),
            "titulo": f"PEUGEOT 308 1.2 PureTech 130 {acabado} {i}", "precio": int(BASE[acabado] - PENDIENTE * (km - 60000)),
            "km": km, "anio": 2021, "cv": 130, "combustible": "Gasolina", "provincia": "Madrid", "profesional": True, **extra.pop("x", {}),
        })
    return salida


def pegado(anuncios):
    return json.dumps({"origen": "coches.net", "url": "https://www.coches.net/peugeot/308/segunda-mano/", "anuncios": anuncios})


class ClienteFalso:
    """Responde como lo haría Claude: la escala de acabados, el del coche y el de cada anuncio."""

    def __init__(self, anuncios, objetivo="GT Line", orden=None, excluir=(), etiquetas=None):
        self.llamadas = []
        self.messages = SimpleNamespace(create=self._crear)
        self.anuncios, self.objetivo, self.orden = anuncios, objetivo, ORDEN if orden is None else orden
        self.excluir, self.etiquetas = set(excluir), etiquetas

    def _crear(self, **kw):
        self.llamadas.append(kw)
        acabados = []
        for a in self.anuncios:
            if a["id"] in self.excluir:
                continue
            nombre = (self.etiquetas or {}).get(a["id"])
            if nombre is None:
                nombre = next((o for o in ORDEN if o.lower() in a["titulo"].lower() and not (o == "GT" and "gt line" in a["titulo"].lower())), "")
            acabados.append({"id": a["id"], "acabado": nombre})
        cuerpo = {
            "excluir": [{"id": i, "motivo": "otra motorización"} for i in self.excluir],
            "orden_acabados": self.orden, "acabado_objetivo": self.objetivo, "acabados_anuncios": acabados,
            "confianza": "alta", "resumen": "Los GT Line cuestan más que los Allure.",
        }
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(cuerpo))], stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1500, output_tokens=300),
        )


def tasar(coche, anuncios, **kw):
    return tm.tasar(coche, pegado(anuncios), cliente_ia=kw.pop("cliente", None) or ClienteFalso(anuncios), **kw)


# ------------------------------------------------------------------ el precio depende del acabado
def test_con_anuncios_suficientes_de_tu_acabado_solo_cuentan_esos(coche):
    anuncios = anuncios_de("Allure", 12) + anuncios_de("GT Line", 6) + anuncios_de("GT", 4)  # la mayoría, Allure
    t = tasar(coche, anuncios)
    assert t.valida and t.acabado_objetivo == "GT Line" and t.orden_acabados == ORDEN
    assert abs(t.precio_mercado - Decimal(BASE["GT Line"])) <= Decimal("100")  # 18.700 €, no la media de todos
    mezclado = tm.calcular_precio(anuncios, 60000)["precio_mercado"]
    assert t.precio_mercado > mezclado + 300  # mezclar acabados lo habría rebajado
    assert "Solo cuentan los 6 anuncios de tu acabado (GT Line)" in t.metodo_acabado
    detalle = {d["acabado"]: d for d in t.detalle_acabados}
    assert set(detalle) == {"Allure", "GT Line", "GT"} and detalle["GT Line"]["tuyo"] and not detalle["GT Line"]["estimado"]
    assert detalle["Allure"]["precio"] < detalle["GT Line"]["precio"] < detalle["GT"]["precio"]


def test_un_allure_vale_menos_que_un_gt_line_aunque_se_tase_con_los_mismos_anuncios(coche):
    anuncios = anuncios_de("Allure", 6) + anuncios_de("GT Line", 6)
    gt_line = tasar(coche, anuncios)
    allure = tasar(coche, anuncios, cliente=ClienteFalso(anuncios, objetivo="Allure"))
    assert gt_line.precio_sugerido - allure.precio_sugerido >= Decimal("1400")  # ~1.700 € de diferencia de acabado


def test_sin_anuncios_de_tu_acabado_se_estima_entre_los_vecinos(coche):
    anuncios = anuncios_de("Allure", 6) + anuncios_de("GT", 6)  # no hay ningún GT Line
    t = tasar(coche, anuncios)
    esperado = (BASE["Allure"] + BASE["GT"]) / 2  # entre Allure (17.000) y GT (20.200): ~18.600
    assert t.valida and abs(float(t.precio_mercado) - esperado) <= 250
    assert "Hay pocos anuncios de tu acabado (GT Line)" in t.metodo_acabado and "entre" in t.metodo_acabado
    fila = next(d for d in t.detalle_acabados if d["acabado"] == "GT Line")
    assert fila["estimado"] and fila["tuyo"] and fila["n"] == 0
    assert [d["acabado"] for d in t.detalle_acabados] == ["Allure", "GT Line", "GT"]  # en el orden de la escala


def test_si_solo_hay_acabados_inferiores_se_extrapola(coche):
    anuncios = anuncios_de("Active", 6) + anuncios_de("Allure", 6)  # el tuyo (GT Line) es el siguiente
    t = tasar(coche, anuncios)
    esperado = BASE["Allure"] + (BASE["Allure"] - BASE["Active"])  # 18.200: sigue el escalón que se ve
    assert abs(float(t.precio_mercado) - esperado) <= 250 and "a partir de" in t.metodo_acabado


@pytest.mark.parametrize("objetivo,factor", [("GT Line", 1.05), ("GT", 1.10), ("Active", 0.95)])
def test_con_un_solo_acabado_distinto_se_aplica_un_salto_por_escalon_y_se_avisa(coche, objetivo, factor):
    anuncios = anuncios_de("Allure", 8)
    t = tasar(coche, anuncios, cliente=ClienteFalso(anuncios, objetivo=objetivo))
    assert abs(float(t.precio_mercado) - BASE["Allure"] * factor) <= 120
    assert "poco fiable" in t.metodo_acabado and "5 % por escalón" in t.metodo_acabado and "solo de Allure" in t.metodo_acabado


def test_un_acabado_superior_nunca_sale_mas_barato_que_uno_inferior(coche):
    caro_allure = anuncios_de("Allure", 6)
    barato_gt = [{**a, "precio": a["precio"] - 3000} for a in anuncios_de("GT", 6)]  # datos raros: el GT, más barato
    t = tasar(coche, caro_allure + barato_gt)
    niveles = {d["acabado"]: d["precio"] for d in t.detalle_acabados}
    assert niveles["GT Line"] >= min(niveles["Allure"], niveles["GT"])  # no cae por debajo de los datos reales


def test_la_bajada_por_km_se_mide_dentro_de_cada_acabado(coche):
    anuncios = anuncios_de("Allure", 6) + anuncios_de("GT Line", 6) + anuncios_de("GT", 6)
    t = tasar(coche, anuncios)
    assert t.pendiente_propia and abs(t.depreciacion_1000km - Decimal("60")) <= Decimal("3")  # no se contamina con los acabados


def test_sin_informacion_de_acabados_se_calcula_como_siempre(coche):
    anuncios = anuncios_de("Allure", 8)
    t = tasar(coche, anuncios, cliente=ClienteFalso(anuncios, objetivo=""))  # la IA no sabe el acabado del coche
    assert t.valida and t.detalle_acabados == [] and t.metodo_acabado == "" and t.ia_usada


def test_con_menos_de_cuatro_anuncios_clasificados_no_hay_precio_por_acabado():
    comp = [{"km": 60000, "precio": 17000, "acabado": "Allure"}] * 3 + [{"km": 60000, "precio": 17000, "acabado": ""}] * 5
    with pytest.raises(tm.SinAcabados):
        tm.calcular_precio_por_acabados(comp, 60000, Decimal("5"), ORDEN, "GT Line")
    with pytest.raises(tm.SinAcabados):
        tm.calcular_precio_por_acabados(comp, 60000, Decimal("5"), ORDEN, "Inexistente")


def test_los_anuncios_sin_acabado_reconocible_se_dicen_y_no_se_usan(coche):
    anuncios = anuncios_de("GT Line", 6) + anuncios_de("Allure", 4)
    etiquetas = {a["id"]: "" for a in anuncios_de("Allure", 4)}  # la IA no sabe qué acabado son
    t = tasar(coche, anuncios, cliente=ClienteFalso(anuncios, etiquetas=etiquetas))
    assert t.valida and "4 anuncio(s) sin acabado reconocible" in t.nota


# ------------------------------------------------------------------ cómo se usa la IA con los acabados
def test_la_ia_recibe_el_acabado_y_las_instrucciones_hablan_de_la_escala(coche):
    anuncios = anuncios_de("Allure", 6) + anuncios_de("GT Line", 6)
    cliente = ClienteFalso(anuncios)
    tasar(coche, anuncios, cliente=cliente)
    (llamada,) = cliente.llamadas
    assert "acabado indicado por la persona: GT Line" in llamada["messages"][0]["content"]
    sistema = llamada["system"]
    assert "Allure < GT Line" in sistema and "un Allure vale menos que un GT Line" in sistema
    assert "NO excluyas un anuncio por tener otro acabado" in sistema
    esquema = llamada["output_config"]["format"]["schema"]
    assert {"orden_acabados", "acabado_objetivo", "acabados_anuncios"} <= set(esquema["required"])
    assert esquema["additionalProperties"] is False


def test_con_ia_los_otros_acabados_no_se_descartan_en_un_coche_de_la_rejilla(coche):
    anuncios = anuncios_de("Allure", 6) + anuncios_de("GT Line", 6)
    t = tasar(coche, anuncios)
    assert t.n_usados == 12 and not [e for e in t.excluidos if "título" in e["motivo"]]
    assert {a["acabado"] for a in t.anuncios} == {"Allure", "GT Line"}  # cada anuncio queda etiquetado


def test_sin_ia_el_acabado_si_filtra_por_el_titulo(coche):
    anuncios = anuncios_de("Allure", 6) + anuncios_de("GT Line", 6)
    t = tm.tasar(coche, pegado(anuncios), usar_ia=False)
    assert t.valida and t.n_usados == 6 and {a["acabado"] for a in t.anuncios} == {""}
    assert sum(1 for e in t.excluidos if "el título no lleva «gt line»" in e["motivo"]) == 6


def test_si_la_ia_falla_se_vuelve_al_filtro_por_titulo(coche):
    anuncios = anuncios_de("Allure", 6) + anuncios_de("GT Line", 6)
    roto = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("caída"))))
    t = tasar(coche, anuncios, cliente=roto)
    assert t.valida and not t.ia_usada and t.n_usados == 6 and "No se pudo consultar a la IA" in t.ia_error


def test_las_palabras_del_titulo_de_una_busqueda_son_un_filtro_duro_aunque_haya_ia():
    call_command("seed_datos")
    b = models.BusquedaOportunidad(
        marca="Peugeot", modelo="308", km_referencia=60000, anio=2021, combustible="gasolina", palabras_titulo="GT",
        url_listado="https://www.auto1.com/es/app/merchant/cars?x=1", precio_venta_estimado=Decimal("18000"),
    )
    b.aplicar_costes_por_defecto()
    b.save()
    anuncios = anuncios_de("Allure", 6) + anuncios_de("GT Line", 6)
    t = tm.tasar(b, pegado(anuncios), cliente_ia=ClienteFalso(anuncios, objetivo="GT Line"))
    assert t.n_usados == 6 and all("GT" in a["titulo"] for a in t.anuncios)  # los Allure quedan fuera, los puso la persona


def test_el_acabado_que_deduce_la_ia_se_guarda_si_el_coche_no_lo_tenia(coche):
    coche.vehiculo.acabado = ""
    coche.vehiculo.save()
    anuncios = anuncios_de("GT Line", 6) + anuncios_de("Allure", 6)
    tasar(coche, anuncios)
    assert models.Vehiculo.objects.get(pk=coche.vehiculo_id).acabado == "GT Line"
    coche.vehiculo.acabado = "GT"  # uno que ya tenía la persona no se pisa
    coche.vehiculo.save()
    tasar(coche, anuncios)
    assert models.Vehiculo.objects.get(pk=coche.vehiculo_id).acabado == "GT"


def test_los_nombres_de_acabado_de_la_ia_se_normalizan(coche):
    anuncios = anuncios_de("Allure", 6) + anuncios_de("GT Line", 6)
    etiquetas = {a["id"]: ("  gt   line " if a["id"].startswith("GT ") else "ALLURE") for a in anuncios}
    etiquetas[anuncios[0]["id"]] = "Inventado"  # un acabado que no está en la escala se descarta
    t = tasar(coche, anuncios, cliente=ClienteFalso(anuncios, orden=["Active", "Allure", "GT Line", "allure", "GT Line", "GT"], etiquetas=etiquetas))
    assert t.orden_acabados == ORDEN  # sin repetidos
    assert {a["acabado"] for a in t.anuncios} == {"", "Allure", "GT Line"}


# ------------------------------------------------------------------ Canarias
@pytest.mark.parametrize("provincia", ["Las Palmas", "Sta. C. Tenerife", "Santa Cruz de Tenerife", "S/C de Tenerife", "Canarias",
                                       "Las Palmas de Gran Canaria", "Gran Canaria", "Lanzarote", "Fuerteventura", "LAS PALMAS", "Tenerife"])
def test_las_provincias_de_canarias_se_reconocen(provincia):
    assert tm.es_canarias(provincia)


@pytest.mark.parametrize("provincia", ["Madrid", "Palma de Mallorca", "Baleares", "Valencia", "Sevilla", "Barcelona", "", None, "Castellón"])
def test_el_resto_no_es_canarias(provincia):
    assert not tm.es_canarias(provincia)


def test_los_anuncios_de_canarias_no_cuentan_y_se_dice(coche):
    ref = tm.referencia_de_valoracion(coche)
    buenos = anuncios_de("GT Line", 6)
    islas = [{**a, "id": f"I{i}", "provincia": p} for i, (a, p) in enumerate(zip(anuncios_de("GT Line", 3), ["Las Palmas", "Sta. C. Tenerife", "Canarias"]))]
    notas = []
    ok, malos = tm.filtrar_comparables(buenos + islas, ref, notas)
    assert len(ok) == 6 and len(malos) == 3 and all(m["motivo"].startswith("Canarias") for m in malos)
    assert notas == ["3 anuncio(s) de Canarias descartados: allí los precios son otros."]


def test_canarias_no_distorsiona_el_precio(coche):
    normales = anuncios_de("GT Line", 8)
    baratos_islas = [{**a, "id": f"I{i}", "precio": a["precio"] - 4000, "provincia": "Las Palmas"} for i, a in enumerate(anuncios_de("GT Line", 6))]
    con = tm.tasar(coche, pegado(normales + baratos_islas), usar_ia=False)
    sin = tm.tasar(coche, pegado(normales), usar_ia=False)
    assert con.valida and con.precio_sugerido == sin.precio_sugerido and con.n_usados == 8
    assert sum(1 for e in con.excluidos if e["motivo"].startswith("Canarias")) == 6 and "6 anuncio(s) de Canarias" in con.nota


def test_canarias_se_descarta_tambien_con_ia_y_en_las_busquedas(coche):
    anuncios = anuncios_de("GT Line", 6) + [{**a, "id": f"I{i}", "provincia": "Sta. C. Tenerife"} for i, a in enumerate(anuncios_de("GT Line", 4))]
    cliente = ClienteFalso(anuncios)
    t = tm.tasar(coche, pegado(anuncios), cliente_ia=cliente)
    assert t.n_usados == 6 and "Tenerife" not in cliente.llamadas[0]["messages"][0]["content"]  # ni siquiera se le mandan a la IA
    b = models.BusquedaOportunidad(marca="Peugeot", modelo="308", km_referencia=60000, anio=2021)
    ok, malos = tm.filtrar_comparables(anuncios, b)
    assert len(ok) == 6 and len(malos) == 4


# ------------------------------------------------------------------ pantalla
def test_el_resultado_enseña_la_escala_el_metodo_y_los_descartes(coche, client):
    get_user_model().objects.create_user("web", password="x")
    client.login(username="web", password="x")
    anuncios = anuncios_de("Allure", 6) + anuncios_de("GT", 6) + [{**a, "id": "ISLA", "provincia": "Las Palmas"} for a in anuncios_de("GT Line", 1)]
    t = tasar(coche, anuncios)
    html = client.get(reverse("tasacion_detalle", args=[t.pk])).content.decode()
    assert "Precio según el acabado" in html and "Active &lt; Allure &lt; GT Line &lt; GT" in html
    assert "tu coche" in html and "(estimado)" in html and "Hay pocos anuncios de tu acabado (GT Line)" in html
    assert "<th>Acabado</th>" in html and "Canarias: el mercado de las islas tiene otros precios" in html
    assert "Los GT Line cuestan más que los Allure." in html  # el resumen de la IA


def test_sin_acabados_la_pantalla_no_enseña_la_tabla(coche, client):
    get_user_model().objects.create_user("web", password="x")
    client.login(username="web", password="x")
    t = tm.tasar(coche, pegado(anuncios_de("GT Line", 8)), usar_ia=False)
    html = client.get(reverse("tasacion_detalle", args=[t.pk])).content.decode()
    assert "Precio según el acabado" not in html and "<th>Acabado</th>" not in html
