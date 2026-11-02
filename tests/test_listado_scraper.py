"""Lector de listados de Auto1: interpreta las tarjetas reales (HTML copiado de Auto1)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper_auto1"))

from listado import filtrar, parsear_tarjetas, url_pagina  # noqa: E402


def _titulo(ref, nombre):
    return (
        '<div class="big-car-card__title big-car-card__title--bottom"><a data-qa-id="car-card-title" '
        'data-ppr-eligible="true" data-auction-identifier="23699b86" '
        f'href="/es/app/merchant/car/{ref}?searchId=104512383_40ec&amp;impression-id=d775-{ref}'
        f'&amp;impression-datetime=Mon%2C+02+Nov+2026+06%3A27%3A15+GMT" data-impression-id="x">{nombre}</a></div>'
    )


def _specs(ref, km="136.492 km", matric="03/2018", pot="120 KW / 163 CV", cambio="Cambio tipo manual"):
    return (
        '<div class="big-car-card__footer-specs"><div class="car-specs-list"><table><tbody>'
        f"<tr><th>Referencia:</th><td>{ref}</td></tr>"
        f"<tr><th>Lectura cuentakilómetros:</th><td>{km}</td></tr>"
        f"<tr><th>1ª Matriculación:</th><td>{matric}</td></tr>"
        f"<tr><th>Potencia:</th><td>{pot}</td></tr>"
        "<tr><th>Combustible:</th><td>Gasolina</td></tr>"
        f"<tr><th>Caja de cambios:</th><td>{cambio}</td></tr>"
        "<tr><th>Ubicación:</th><td>ES, Santa Marta de Tormes</td></tr>"
        "</tbody></table></div></div>"
    )


PRECIO_SUBASTA = (
    '<span class="price-value"><span class="price-value font-size-13 font-weight-bold" '
    'data-qa-id="bigSearchCard__status--minimumBidValue"><span class="BK_Kxc6eqLW47hiUwi0X">9839&nbsp;€</span></span></span>'
)
PRECIO_COMPRA_YA = (
    '<div class="carCard__statusBar carCard__statusBar--instant"><div><span data-qa-id="carCard__name" '
    'class="carCard__name">Compra Ahora</span></div></div>'
    '<div data-qa-id="bigSearchCard__status--price" class="bigSearchCard__status--price"><div class="price-diff">'
    '<span class="price-value"><span class="price-value font-weight-semibold font-14" '
    'data-qa-id="bigSearchCard__status--IPPrice"><span class="BK_Kxc6eqLW47hiUwi0X">16.148&nbsp;€</span></span></span></div></div>'
)
PRECIO_PARTICULAR = (
    '<div data-qa-id="bigSearchCard__status--price" class="bigSearchCard__status--price bigSearchCard__status--expectation">'
    '<div><span class="price-type" data-qa-id="bigSearchCard__status--minimumBidLabel">Puja mínima:</span>'
    '<span class="price-value"><span class="price-value font-size-13 font-weight-bold" '
    'data-qa-id="bigSearchCard__status--minimumBidValue"><span class="BK_Kxc6eqLW47hiUwi0X">10.535&nbsp;€</span></span></span></div>'
    '<div><span class="price-type" data-qa-id="bigSearchCard__status--expectationLabel-customerExpectation">Expectativa del cliente:</span>'
    '<span class="price-value"><span class="price-value font-weight-bold" data-qa-id="bigSearchCard__status--expectationValue">'
    '<span class="BK_Kxc6eqLW47hiUwi0X">15.133&nbsp;€</span></span></span></div></div>'
)


def tarjeta(ref, nombre, precio_html, **specs):
    return (
        '<div class="big-car-card__container">'
        + _titulo(ref, nombre) + precio_html + _specs(ref, **specs) + "</div>"
    )


PAGINA = (
    "<html><body><div class='lista'>"
    + tarjeta("UA50404", "Nissan Qashqai 1.6 N-Connecta", PRECIO_SUBASTA)
    + tarjeta("XX11111", "Nissan Qashqai 1.2 DIG-T Acenta", PRECIO_COMPRA_YA, km="95.000 km", pot="85 KW / 115 CV")
    + tarjeta("WF29649", "Nissan Qashqai 1.3 DIG-T N-Connecta", PRECIO_PARTICULAR, km="150.200 km",
              cambio="Cambio automático")
    + "</div></body></html>"
)


def test_lee_las_tres_tarjetas_con_sus_datos():
    t = {c["referencia"]: c for c in parsear_tarjetas(PAGINA)}
    assert list(t) == ["UA50404", "XX11111", "WF29649"]
    a = t["UA50404"]
    assert a["nombre"] == "Nissan Qashqai 1.6 N-Connecta"
    assert a["url"] == "https://www.auto1.com/es/app/merchant/car/UA50404"
    assert (a["km"], a["mes"], a["anio"], a["cv"], a["kw"]) == (136492, 3, 2018, 163, 120)
    assert (a["combustible"], a["cambio"]) == ("Gasolina", "manual")
    assert a["ubicacion"] == "ES, Santa Marta de Tormes"


def test_distingue_subasta_compra_ya_y_particular():
    t = {c["referencia"]: c for c in parsear_tarjetas(PAGINA)}
    assert (t["UA50404"]["tipo"], t["UA50404"]["precio"]) == ("subasta", 9839)
    assert (t["XX11111"]["tipo"], t["XX11111"]["precio"]) == ("compra_ya", 16148)
    p = t["WF29649"]
    assert (p["tipo"], p["precio"], p["expectativa"]) == ("particular", 10535, 15133)
    assert p["cambio"] == "automatico"


def test_no_depende_de_la_clase_ofuscada_del_precio():
    pagina = PAGINA.replace("BK_Kxc6eqLW47hiUwi0X", "OTRA_CLASE_NUEVA")
    assert [c["precio"] for c in parsear_tarjetas(pagina)] == [9839, 16148, 10535]


def test_sin_contenedor_se_ancla_en_el_titulo():
    pagina = PAGINA.replace('<div class="big-car-card__container">', "<div>")
    assert [c["referencia"] for c in parsear_tarjetas(pagina)] == ["UA50404", "XX11111", "WF29649"]


def test_pagina_sin_coches_o_con_repetidos():
    assert parsear_tarjetas("<html><body>Sin resultados</body></html>") == []
    assert len(parsear_tarjetas(PAGINA + PAGINA)) == 3


BUSQ = {"km_min": 126000, "km_max": 146000, "potencia_cv": 163, "tolerancia_cv": 5,
        "cambio": "manual", "palabras_titulo": ""}


def test_filtra_por_km_cv_y_cambio_con_motivo():
    ok, no = filtrar(parsear_tarjetas(PAGINA), BUSQ)
    assert [c["referencia"] for c in ok] == ["UA50404"]
    motivos = {c["referencia"]: m for c, m in no}
    assert "km por debajo" in motivos["XX11111"]
    assert "km por encima" in motivos["WF29649"]


def test_filtro_de_cv_y_de_cambio_solos():
    tarjetas = parsear_tarjetas(PAGINA)
    ok, no = filtrar(tarjetas, {"potencia_cv": 163, "tolerancia_cv": 5})
    assert {c["referencia"] for c in ok} == {"UA50404", "WF29649"}
    assert "potencia distinta" in dict((c["referencia"], m) for c, m in no)["XX11111"]
    ok, no = filtrar(tarjetas, {"cambio": "manual"})
    assert {c["referencia"] for c in ok} == {"UA50404", "XX11111"}


def test_filtro_de_palabras_del_titulo():
    ok, _ = filtrar(parsear_tarjetas(PAGINA), {"palabras_titulo": "dig-t n-connecta"})
    assert [c["referencia"] for c in ok] == ["WF29649"]


def test_un_dato_que_falta_no_descarta_pero_sin_precio_si():
    t = parsear_tarjetas(PAGINA)[0]
    t["cv"] = None
    t["cambio"] = ""
    ok, _ = filtrar([t], BUSQ)
    assert ok == [t]
    t["precio"] = None
    ok, no = filtrar([t], BUSQ)
    assert ok == [] and no[0][1] == "sin precio en la tarjeta"


def test_url_de_pagina_conserva_los_filtros_y_cambia_page():
    url = "https://www.auto1.com/es/app/merchant/cars?channel=24h&manufacturers=Nissan%7CQashqai&page=1&regFrom=2013"
    u = url_pagina(url, 3)
    assert u.count("page=") == 1 and "page=3" in u
    assert "manufacturers=Nissan%7CQashqai" in u and "regFrom=2013" in u and "channel=24h" in u


class NavegadorFalso:
    """Un 'driver' mínimo: cada page=N devuelve las tarjetas que se le hayan dado."""

    def __init__(self, paginas):
        self.paginas = paginas
        self.current_url = ""
        self.page_source = ""
        self.visitadas = []

    def get(self, url):
        self.current_url = url
        n = int(url.split("page=")[1].split("&")[0])
        self.visitadas.append(n)
        self.page_source = self.paginas.get(n, "<html><body>Sin resultados</body></html>")

    def execute_script(self, js):
        return None


def _reloj_rapido(monkeypatch):
    """Reloj falso: avanza 1 s por consulta y no duerme, así las esperas no cuestan tiempo real."""
    import listado

    ticks = iter(range(0, 10**7))
    monkeypatch.setattr(listado, "_ahora", lambda: float(next(ticks)))
    monkeypatch.setattr(listado, "_dormir", lambda s: None)
    return ticks


def _pagina(*refs):
    return "<html><body>" + "".join(tarjeta(r, f"Nissan Qashqai {r}", PRECIO_SUBASTA) for r in refs) + "</body></html>"


def test_recorre_las_paginas_hasta_que_no_hay_mas(monkeypatch):
    import listado

    _reloj_rapido(monkeypatch)
    nav = NavegadorFalso({1: _pagina("A1", "A2"), 2: _pagina("B1", "B2"), 3: _pagina("C1")})
    res = listado.leer_listado(nav, "https://www.auto1.com/es/app/merchant/cars?page=1&x=1", max_paginas=10, log=lambda m: None)
    assert [t["referencia"] for t in res["tarjetas"]] == ["A1", "A2", "B1", "B2", "C1"]
    assert res["paginas"] == 3 and res["aviso"] == "" and nav.visitadas == [1, 2, 3, 4]


def test_se_para_si_una_pagina_repite_las_anteriores(monkeypatch):
    import listado

    _reloj_rapido(monkeypatch)
    nav = NavegadorFalso({1: _pagina("A1", "A2"), 2: _pagina("A1", "A2"), 3: _pagina("Z9")})
    res = listado.leer_listado(nav, "https://www.auto1.com/es/app/merchant/cars?page=1", max_paginas=10, log=lambda m: None)
    assert [t["referencia"] for t in res["tarjetas"]] == ["A1", "A2"] and nav.visitadas == [1, 2]


def test_avisa_si_llega_al_limite_de_paginas(monkeypatch):
    import listado

    _reloj_rapido(monkeypatch)
    nav = NavegadorFalso({1: _pagina("A1"), 2: _pagina("B1")})
    res = listado.leer_listado(nav, "https://www.auto1.com/es/app/merchant/cars?page=1", max_paginas=2, log=lambda m: None)
    assert res["paginas"] == 2 and "límite de 2 páginas" in res["aviso"]


def test_primera_pagina_vacia_da_aviso_y_sesion_caida_da_error(monkeypatch):
    import listado
    import pytest

    _reloj_rapido(monkeypatch)
    res = listado.leer_listado(NavegadorFalso({}), "https://www.auto1.com/es/app/merchant/cars?page=1", log=lambda m: None)
    assert res["tarjetas"] == [] and "ninguna tarjeta" in res["aviso"]

    class Caida(NavegadorFalso):
        def get(self, url):
            super().get(url)
            self.current_url = "https://www.auto1.com/es/merchant/signin"

    with pytest.raises(RuntimeError, match="caído la sesión"):
        listado.leer_listado(Caida({}), "https://www.auto1.com/es/app/merchant/cars?page=1", log=lambda m: None)


def test_una_pagina_sin_coches_se_da_por_vacia_rapido(monkeypatch):
    import listado

    llamadas = {"n": 0}
    ticks = iter(range(0, 10**7))

    def reloj():
        llamadas["n"] += 1
        return float(next(ticks))

    monkeypatch.setattr(listado, "_ahora", reloj)
    monkeypatch.setattr(listado, "_dormir", lambda s: None)
    nav = NavegadorFalso({})
    nav.get("https://www.auto1.com/es/app/merchant/cars?page=2")
    listado._esperar_tarjetas(nav, 25, sin_tarjetas=6)
    rapido = llamadas["n"]
    llamadas["n"] = 0
    listado._esperar_tarjetas(nav, 25)
    assert rapido < llamadas["n"] / 2  # con «sin_tarjetas» deja de esperar mucho antes


def test_la_primera_pagina_espera_mas_que_las_siguientes(monkeypatch):
    import listado

    pedidos = []
    original = listado._esperar_tarjetas
    monkeypatch.setattr(listado, "_esperar_tarjetas",
                        lambda d, s, sin_tarjetas=None: pedidos.append(sin_tarjetas) or original(d, s, sin_tarjetas))
    _reloj_rapido(monkeypatch)
    nav = NavegadorFalso({1: _pagina("A1"), 2: _pagina("B1")})
    listado.leer_listado(nav, "https://www.auto1.com/es/app/merchant/cars?page=1", max_paginas=3, log=lambda m: None)
    assert pedidos[0] is None and all(p == 6 for p in pedidos[1:])
