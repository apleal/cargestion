"""Motor en modo Auto1 (pestaña Auto1_IA del Excel)."""
from decimal import Decimal

import pytest

from calculo.datos_auto1 import GESTION_AUTO1, config_auto1
from calculo.motor import escenarios, evaluar, puja_maxima, tarifa_auto1_neta
from calculo.tipos import EntradaValoracion

CFG = config_auto1()


def test_tarifa_es_iva_entre_021():
    assert tarifa_auto1_neta(Decimal("307.02")) == Decimal("1462.00")
    assert tarifa_auto1_neta(Decimal("49.35")) == Decimal("235.00")
    assert tarifa_auto1_neta(Decimal("0")) == Decimal("0.00")


def test_desglose_golf_r_contra_excel():
    """Fila 2 de Auto1_IA: VW Golf R. B=19.090, IVA=307,02, venta=23.500."""
    e = EntradaValoracion(
        precio_venta=Decimal("23500"),
        gastos_preparacion=Decimal("1233"),  # prep sin tarifa ni gestión
        iva_anuncio=Decimal("307.02"),
    )
    d = evaluar(CFG, e, Decimal("19090"))
    assert d.comision_neta == Decimal("1462.00")           # tarifa Auto1
    assert d.compra_coche == Decimal("17320.98")           # L del Excel
    assert d.margen_bruto == Decimal("6179.02")            # M
    assert d.iva_rebu == Decimal("1072.39")                # N
    assert d.margen_neto == Decimal("5106.63")             # O
    assert d.conceptos_fijos == GESTION_AUTO1
    # coste total = compra_coche + tarifa + gestión + prep
    assert d.coste_total == Decimal("17320.98") + Decimal("1462.00") + GESTION_AUTO1 + Decimal("1233")


def test_iva_cero_no_hay_tarifa():
    e = EntradaValoracion(
        precio_venta=Decimal("19000"),
        gastos_preparacion=Decimal("1000"),
        iva_anuncio=Decimal("0"),
    )
    d = evaluar(CFG, e, Decimal("15950"))
    assert d.comision_neta == Decimal("0.00")
    assert d.compra_coche == Decimal("15950.00")


def test_puja_maxima_auto1_alcanza_objetivo():
    e = EntradaValoracion(
        precio_venta=Decimal("23500"),
        gastos_preparacion=Decimal("1233"),
        iva_anuncio=Decimal("307.02"),
    )
    for obj in [Decimal("0.15"), Decimal("0.12"), Decimal("0.10")]:
        p = puja_maxima(CFG, e, obj)
        assert p is not None
        r = evaluar(CFG, e, p).rentabilidad_coste
        assert r >= obj
        assert evaluar(CFG, e, p + Decimal("2")).rentabilidad_coste < obj


def test_escenarios_auto1():
    e = EntradaValoracion(
        precio_venta=Decimal("15000"),
        gastos_preparacion=Decimal("1200"),
        iva_anuncio=Decimal("150"),
    )
    esc = escenarios(CFG, e)
    assert len(esc) == 3
    # objetivo más bajo -> se puede pujar más
    assert esc[0].puja_maxima < esc[1].puja_maxima < esc[2].puja_maxima
