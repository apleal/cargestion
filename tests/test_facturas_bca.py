"""Contraste del motor con las 13 facturas reales de BCA / FONDEMAR."""
from decimal import Decimal

import pytest

from calculo.datos_bca import (
    CONCEPTOS_FIJOS_BCA,
    FACTURAS_BCA,
    config_bca_concurso,
    config_bca_normal,
)
from calculo.motor import coste_adquisicion, comision_neta

NORMAL = config_bca_normal()


def test_conceptos_fijos_140_12():
    assert CONCEPTOS_FIJOS_BCA == Decimal("140.12")


@pytest.mark.parametrize(
    "adjudicacion,comision_c_iva",
    [(a, c) for (_f, _d, a, c, nota) in FACTURAS_BCA if nota == "vigente"],
)
def test_facturas_tarifa_vigente(adjudicacion, comision_c_iva):
    """Las facturas de ago-2026 en el tramo 5.000-7.499 cuadran exactamente."""
    neta = comision_neta(NORMAL, adjudicacion)
    assert neta == Decimal("389.00")
    assert (neta * Decimal("1.21")).quantize(Decimal("0.01")) == comision_c_iva


def test_factura_con_descuento_50():
    """F19627246: 3.950 € en tramo 3.400-3.999 (366 neto) con 50 % de descuento."""
    neta_sin_desc = comision_neta(NORMAL, Decimal("3950"))
    assert neta_sin_desc == Decimal("366.00")
    neta_con_desc = comision_neta(NORMAL, Decimal("3950"), descuento_pct=Decimal("50"))
    assert neta_con_desc == Decimal("183.00")
    assert (neta_con_desc * Decimal("1.21")).quantize(Decimal("0.01")) == Decimal("221.43")


def test_coste_adquisicion_factura_vigente():
    """F19624701: adjudicación 6.700 -> total pagado 7.310,81 €."""
    total = coste_adquisicion(NORMAL, Decimal("6700"))
    # 6700 + 470,69 (389*1,21) + 140,12 = 7310,81
    assert total == Decimal("7310.81")


def test_concurso_solo_cuota_plana():
    concurso = config_bca_concurso()
    assert coste_adquisicion(concurso, Decimal("5000")) == Decimal("5351.00")
    assert comision_neta(concurso, Decimal("5000")) == Decimal("0.00")
