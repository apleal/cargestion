"""Servicio: recorrer las búsquedas de Oportunidades (listado → fichas → app → aviso)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper_auto1"))

import pytest  # noqa: E402

import scraper  # noqa: E402

BUSQUEDA = {
    "id": 7, "nombre": "Nissan Qashqai 1.6", "url_listado": "https://www.auto1.com/es/app/merchant/cars?x=1",
    "km_min": 126000, "km_max": 146000, "potencia_cv": 163, "tolerancia_cv": 5, "cambio": "manual",
    "palabras_titulo": "", "precio_max_listado": 9000, "solicitada": False,
}


def tarj(ref, precio, tipo="subasta", km=136000, cv=163, cambio="manual"):
    return {"referencia": ref, "nombre": f"Nissan Qashqai {ref}", "url": f"https://www.auto1.com/es/app/merchant/car/{ref}",
            "tipo": tipo, "precio": precio, "expectativa": None, "km": km, "anio": 2018, "mes": 3, "cv": cv,
            "kw": 120, "combustible": "Gasolina", "cambio": cambio, "ubicacion": "ES, Madrid"}


@pytest.fixture
def cfg():
    return {"app_url": "https://app.test", "app_token": "t" * 40, "dry_run": False, "pause": 0,
            "search_max_pages": 5, "tg_token": "TG", "tg_chat": "1", "webhook": ""}


@pytest.fixture
def entorno(monkeypatch, cfg):
    """Sustituye navegador y app por piezas simuladas y deja constancia de lo que pasa."""
    reg = {"fichas": [], "resultados": [], "telegram": [], "cierres": 0}

    class Driver:
        def quit(self):
            reg["cierres"] += 1

    monkeypatch.setattr(scraper, "crear_driver", lambda c: Driver())
    monkeypatch.setattr(scraper, "login", lambda d, c: None)
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    monkeypatch.setattr(scraper, "busquedas_activas", lambda c: [BUSQUEDA])
    reg["tarjetas"] = [
        tarj("OK1", 8000), tarj("CARO", 12000), tarj("KMALTO", 7000, km=170000),
        tarj("CVRARO", 7000, cv=110), tarj("DIESELAUTO", 7000, cambio="automatico"),
        tarj("YA1", 7000, tipo="compra_ya"),
    ]
    monkeypatch.setattr(
        scraper.listado, "leer_listado",
        lambda driver, url, max_paginas, pausa, log: {"tarjetas": reg["tarjetas"], "paginas": 2, "aviso": ""},
    )

    def ficha(driver, url):
        reg["fichas"].append(url.rsplit("/", 1)[-1])
        ref = url.rsplit("/", 1)[-1]
        return {"estado": "ok", "datos": {"nombre": "Nissan Qashqai", "precio": 8000, "tarifa": "40,00",
                                           "referencia": ref, "anio": 2018, "km": 136000,
                                           "combustible": "Gasolina", "cambio": "Manual"}}

    monkeypatch.setattr(scraper, "leer_ficha", ficha)

    def resultado(c, bid, cuerpo):
        reg["resultados"].append((bid, cuerpo))
        return {"avisos": reg.get("avisos", []), "comprables": len(reg.get("avisos", [])),
                "nuevos_comprables": len(reg.get("avisos", []))}

    monkeypatch.setattr(scraper, "enviar_resultado_busqueda", resultado)
    monkeypatch.setattr(scraper, "enviar_aviso", lambda c, texto, extra=None: reg["telegram"].append(texto))
    return reg


def test_solo_abre_la_ficha_de_lo_que_encaja_y_esta_a_precio(entorno, cfg):
    scraper.ejecutar_busquedas(cfg, origen="manual")
    assert entorno["fichas"] == ["OK1"]  # CARO, KMALTO, CVRARO, DIESELAUTO y compra ya no se abren
    (bid, cuerpo), = entorno["resultados"]
    assert bid == 7 and cuerpo["origen"] == "manual"
    assert (cuerpo["leidos"], cuerpo["encajan"], cuerpo["paginas"]) == (6, 3, 2)
    refs = {c["tarjeta"]["referencia"]: c["linea"] for c in cuerpo["coches"]}
    assert set(refs) == {"OK1", "CARO", "YA1"}
    assert refs["OK1"].split("\t")[:4] == ["Nissan Qashqai", "8000", "40,00", "OK1"]
    assert refs["CARO"] is None and refs["YA1"] is None
    assert entorno["cierres"] == 1  # el navegador siempre se cierra
    assert entorno["telegram"] == []  # sin comprables nuevos no se molesta


def test_avisa_por_telegram_de_los_comprables_nuevos(entorno, cfg):
    entorno["avisos"] = [{"busqueda": "Nissan Qashqai 1.6", "referencia": "OK1", "nombre": "Nissan Qashqai OK1",
                          "url": "https://www.auto1.com/es/app/merchant/car/OK1", "tipo": "subasta",
                          "precio": "8000.00", "tier": "12", "puja_maxima_10": "8600.00", "margen_10": "600.00",
                          "km": 136000, "anio": 2018}]
    scraper.ejecutar_busquedas(cfg)
    (texto,) = entorno["telegram"]
    assert "OPORTUNIDADES AUTO1 (1)" in texto and "Nissan Qashqai OK1 (OK1)" in texto
    assert "8.000 €" in texto and "llega al 12 %" in texto and "600 €" in texto and "/car/OK1" in texto


def test_un_fallo_se_registra_en_la_app_y_no_para_el_servicio(entorno, cfg, monkeypatch):
    def roto(*a, **k):
        raise RuntimeError("Se ha caído la sesión de Auto1")

    monkeypatch.setattr(scraper.listado, "leer_listado", roto)
    scraper.ejecutar_busquedas(cfg)
    (bid, cuerpo), = entorno["resultados"]
    assert bid == 7 and "caído la sesión" in cuerpo["error"] and cuerpo["coches"] == []
    assert entorno["cierres"] == 1


def test_si_no_puede_entrar_en_auto1_lo_registra_y_avisa(entorno, cfg, monkeypatch):
    def sin_login(d, c):
        raise RuntimeError("login incorrecto")

    monkeypatch.setattr(scraper, "login", sin_login)
    scraper.ejecutar_busquedas(cfg)
    assert "login incorrecto" in entorno["resultados"][0][1]["error"]
    assert "no se pudo buscar" in entorno["telegram"][0]
    assert entorno["cierres"] == 1


def test_solo_ejecuta_las_pedidas_y_no_abre_navegador_si_no_hay(entorno, cfg, monkeypatch):
    scraper.ejecutar_busquedas(cfg, ids=[99])
    assert entorno["resultados"] == [] and entorno["cierres"] == 0


def test_dry_run_no_envia_nada(entorno, cfg):
    cfg["dry_run"] = True
    scraper.ejecutar_busquedas(cfg)
    assert entorno["resultados"] == [] and entorno["fichas"] == ["OK1"]


def test_el_log_cuenta_por_que_descarta_y_cuando_termina(entorno, cfg, capsys):
    scraper.ejecutar_busquedas(cfg, origen="manual")
    salida = capsys.readouterr().out
    assert "6 coches leídos, 3 encajan, 3 descartados" in salida
    assert "1 × km por encima" in salida and "1 × potencia distinta" in salida and "1 × cambio distinto" in salida
    assert "Oportunidades terminadas: 1 búsqueda(s), 0 aviso(s)" in salida


def test_si_no_hay_telegram_lo_dice_en_vez_de_callar(entorno, cfg, capsys):
    cfg["tg_token"] = cfg["tg_chat"] = ""
    entorno["avisos"] = [{"busqueda": "x", "referencia": "OK1", "nombre": "Nissan Qashqai OK1", "url": "u",
                          "tipo": "subasta", "precio": "8000.00", "tier": "15", "margen_10": None, "km": 1}]
    scraper.ejecutar_busquedas(cfg)
    assert "Aviso NO enviado: este servicio no tiene Telegram configurado" in capsys.readouterr().out
