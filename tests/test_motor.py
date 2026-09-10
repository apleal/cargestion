"""Pruebas del motor: desglose completo, puja máxima y coherencia."""
from decimal import Decimal

import pytest

from calculo.datos_bca import config_bca_concurso, config_bca_normal
from calculo.motor import escenarios, evaluar, precio_venta_minimo, puja_maxima
from calculo.tipos import EntradaValoracion

NORMAL = config_bca_normal()

# SEAT Arona: venta 15.000, gastos de preparación 1.285 (netos).
ARONA = EntradaValoracion(
    precio_venta=Decimal("15000"),
    gastos_preparacion=Decimal("1285"),
)


def test_desglose_valores_conocidos():
    d = evaluar(NORMAL, ARONA, Decimal("10000"))
    # tramo 10.000-12.499 -> 416 neto -> 503,36 c/IVA
    assert d.comision_neta == Decimal("416.00")
    assert d.comision_coste == Decimal("503.36")
    assert d.conceptos_fijos == Decimal("140.12")
    assert d.coste_adquisicion == Decimal("10643.48")
    assert d.coste_total == Decimal("11928.48")
    # margen bruto 15.000 - 10.643,48 = 4.356,52
    assert d.margen_bruto == Decimal("4356.52")
    # IVA REBU = 4.356,52 * 21/121
    assert d.iva_rebu == Decimal("756.09")
    assert d.margen_neto == Decimal("3600.43")
    assert d.beneficio_neto == Decimal("2315.43")


def test_rentabilidad_decreciente_con_la_puja():
    anterior = Decimal("999999")
    for puja in range(4000, 13000, 500):
        r = evaluar(NORMAL, ARONA, Decimal(puja)).rentabilidad_coste
        assert r < anterior
        anterior = r


def test_puja_maxima_alcanza_el_objetivo():
    for objetivo in [Decimal("0.15"), Decimal("0.12"), Decimal("0.10")]:
        pmax = puja_maxima(NORMAL, ARONA, objetivo)
        assert pmax is not None
        r = evaluar(NORMAL, ARONA, pmax).rentabilidad_coste
        # a la puja máxima la rentabilidad roza el objetivo por arriba
        assert r >= objetivo
        # y un euro más ya no cumple
        assert evaluar(NORMAL, ARONA, pmax + Decimal("1")).rentabilidad_coste < objetivo


def test_puja_maxima_ordenada_por_objetivo():
    p15 = puja_maxima(NORMAL, ARONA, Decimal("0.15"))
    p12 = puja_maxima(NORMAL, ARONA, Decimal("0.12"))
    p10 = puja_maxima(NORMAL, ARONA, Decimal("0.10"))
    assert p15 < p12 < p10


def test_puja_maxima_rango_esperado():
    # Con estos números la puja máxima al 15 % está sobre los 10.500 €.
    p15 = puja_maxima(NORMAL, ARONA, Decimal("0.15"))
    assert Decimal("10000") < p15 < Decimal("11000")


def test_objetivo_inalcanzable_devuelve_none():
    coche_malo = EntradaValoracion(
        precio_venta=Decimal("3000"),
        gastos_preparacion=Decimal("3000"),
    )
    assert puja_maxima(NORMAL, coche_malo, Decimal("0.15")) is None


def test_precio_venta_minimo_deja_beneficio_cero():
    puja = Decimal("9000")
    vmin = precio_venta_minimo(NORMAL, ARONA, puja)
    entrada = EntradaValoracion(
        precio_venta=vmin, gastos_preparacion=ARONA.gastos_preparacion
    )
    beneficio = evaluar(NORMAL, entrada, puja).beneficio_neto
    assert abs(beneficio) <= Decimal("0.02")


def test_escenarios_devuelve_uno_por_objetivo():
    esc = escenarios(NORMAL, ARONA)
    assert len(esc) == 3
    assert [e.objetivo for e in esc] == [Decimal("0.15"), Decimal("0.12"), Decimal("0.10")]
    assert all(e.puja_maxima is not None and e.desglose is not None for e in esc)


def test_concurso_bca_usa_cuota_plana():
    d = evaluar(config_bca_concurso(), ARONA, Decimal("10000"))
    assert d.coste_adquisicion == Decimal("10351.00")
    assert d.comision_coste == Decimal("0.00")
    assert d.conceptos_fijos == Decimal("0.00")


def test_base_margen_adjudicacion_vs_adquisicion():
    entrada_adj = EntradaValoracion(
        precio_venta=Decimal("15000"),
        gastos_preparacion=Decimal("1285"),
        base_margen="adjudicacion",
    )
    d_adj = evaluar(NORMAL, entrada_adj, Decimal("10000"))
    d_adq = evaluar(NORMAL, ARONA, Decimal("10000"))
    # con base "adjudicación" el margen es mayor (no resta comisión ni gestión)
    assert d_adj.margen_bruto > d_adq.margen_bruto
    assert d_adj.beneficio_neto > d_adq.beneficio_neto
