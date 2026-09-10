"""Pruebas de la selección de tramo, con foco en los límites (±1 céntimo)."""
from decimal import Decimal

import pytest

from calculo.datos_bca import TRAMOS_BCA_OTROS, config_bca_normal
from calculo.motor import comision_neta, tramo_para

CONFIG = config_bca_normal()

# (puja, cuota_neta_esperada)
LIMITES = [
    (Decimal("0.00"), Decimal("135")),
    (Decimal("399.00"), Decimal("135")),
    (Decimal("399.99"), Decimal("135")),  # hueco entre tramos -> tramo inferior
    (Decimal("400.00"), Decimal("175")),
    (Decimal("4999.99"), Decimal("372")),
    (Decimal("5000.00"), Decimal("389")),
    (Decimal("7499.99"), Decimal("389")),
    (Decimal("7500.00"), Decimal("406")),
    (Decimal("7500.01"), Decimal("406")),
    (Decimal("19999.99"), Decimal("507")),
]


@pytest.mark.parametrize("puja,esperado", LIMITES)
def test_cuota_en_limites(puja, esperado):
    assert comision_neta(CONFIG, puja) == esperado


def test_tramo_porcentual_desde_20000():
    assert comision_neta(CONFIG, Decimal("20000")) == Decimal("520.00")  # 2,60 %
    assert comision_neta(CONFIG, Decimal("30000")) == Decimal("780.00")


def test_tabla_sin_huecos_ni_solapes():
    """Los tramos deben cubrir [0, inf) de forma contigua."""
    orden = sorted(TRAMOS_BCA_OTROS, key=lambda t: t.desde)
    assert orden[0].desde == Decimal("0")
    for anterior, siguiente in zip(orden, orden[1:]):
        assert anterior.hasta is not None
        # el siguiente 'desde' es el 'hasta' anterior + 1 (los límites son en euros enteros)
        assert siguiente.desde == anterior.hasta + Decimal("1")
    assert orden[-1].hasta is None


def test_todas_las_pujas_tienen_tramo():
    for puja in [Decimal("0"), Decimal("1250.50"), Decimal("9999.99"), Decimal("50000")]:
        assert tramo_para(CONFIG, puja) is not None
