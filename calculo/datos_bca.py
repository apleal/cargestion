"""Datos de referencia de BCA (tabla pública contrastada con 13 facturas reales).

Estas constantes son el "seed" del proveedor BCA. La aplicación las carga en la
base de datos y a partir de ahí se editan desde el panel; el motor de cálculo
nunca las lee directamente. Se mantienen aquí también para las pruebas.
"""
from __future__ import annotations

from decimal import Decimal

from .tipos import ConfigProveedor, Tramo

IVA = Decimal("1.21")

# Tarifa "Otros" · cuota NETA (sin IVA) por tramo de precio de adjudicación.
# hasta = None en el último tramo (2,60 % sin límite superior).
TRAMOS_BCA_OTROS: tuple[Tramo, ...] = (
    Tramo(Decimal("0"), Decimal("399"), Decimal("135")),
    Tramo(Decimal("400"), Decimal("799"), Decimal("175")),
    Tramo(Decimal("800"), Decimal("1199"), Decimal("210")),
    Tramo(Decimal("1200"), Decimal("1599"), Decimal("245")),
    Tramo(Decimal("1600"), Decimal("1999"), Decimal("283")),
    Tramo(Decimal("2000"), Decimal("2399"), Decimal("312")),
    Tramo(Decimal("2400"), Decimal("2799"), Decimal("335")),
    Tramo(Decimal("2800"), Decimal("3399"), Decimal("353")),
    Tramo(Decimal("3400"), Decimal("3999"), Decimal("366")),
    Tramo(Decimal("4000"), Decimal("4999"), Decimal("372")),
    Tramo(Decimal("5000"), Decimal("7499"), Decimal("389")),
    Tramo(Decimal("7500"), Decimal("9999"), Decimal("406")),
    Tramo(Decimal("10000"), Decimal("12499"), Decimal("416")),
    Tramo(Decimal("12500"), Decimal("14999"), Decimal("425")),
    Tramo(Decimal("15000"), Decimal("17499"), Decimal("464")),
    Tramo(Decimal("17500"), Decimal("19999"), Decimal("507")),
    Tramo(Decimal("20000"), None, Decimal("0"), Decimal("2.60")),
)

# Conceptos fijos (todas las facturas, de 1.250 € a 9.550 €):
#   honorarios de transferencia 69,77 € neto -> 84,42 € con IVA (no deducible REBU)
#   tasa de transferencia (DGT)              -> 55,70 € no sujeta
GESTION_CON_IVA = Decimal("84.42")
TASA_DGT = Decimal("55.70")
CONCEPTOS_FIJOS_BCA = GESTION_CON_IVA + TASA_DGT  # 140,12

# "Concurso BCA": única cuota de 351 € que se suma al precio; nada más.
CUOTA_CONCURSO_BCA = Decimal("351.00")


def config_bca_normal() -> ConfigProveedor:
    return ConfigProveedor(
        tramos=TRAMOS_BCA_OTROS,
        conceptos_fijos=CONCEPTOS_FIJOS_BCA,
        iva=IVA,
    )


def config_bca_concurso() -> ConfigProveedor:
    return ConfigProveedor(cuota_plana=CUOTA_CONCURSO_BCA)


# (adjudicacion, comision_con_iva) de las 13 facturas reales de FONDEMAR / BCA.
# Solo las de agosto 2026 en el tramo 5.000-7.499 cuadran con la tarifa vigente
# (389 neto -> 470,69 c/IVA). Las de 2025 usan una tarifa anterior y una lleva
# descuento del 50 %. Se usan como casos de prueba y de contraste.
FACTURAS_BCA = [
    # factura,          fecha,        adjudicacion, comision_c_iva, nota
    ("F19624701", "2026-08-20", Decimal("6700.00"), Decimal("470.69"), "vigente"),
    ("F19622230", "2026-08-12", Decimal("5200.00"), Decimal("470.69"), "vigente"),
    ("F19627246", "2026-08-31", Decimal("3950.00"), Decimal("221.43"), "descuento 50%"),
    ("F19511912", "2025-09-05", Decimal("3200.00"), Decimal("407.77"), "tarifa 2025"),
    ("F19512136", "2025-09-08", Decimal("2800.00"), Decimal("211.75"), "tarifa 2025"),
    ("F19512140", "2025-09-08", Decimal("9550.00"), Decimal("211.75"), "tarifa 2025"),
    ("F19512161", "2025-09-08", Decimal("1950.00"), Decimal("141.57"), "tarifa 2025"),
    ("F19512649", "2025-09-09", Decimal("9400.00"), Decimal("457.38"), "tarifa 2025"),
    ("F19512730", "2025-09-09", Decimal("3100.00"), Decimal("407.77"), "tarifa 2025"),
    ("F19513034", "2025-09-10", Decimal("6300.00"), Decimal("431.97"), "tarifa 2025"),
    ("F19513092", "2025-09-10", Decimal("1250.00"), Decimal("286.77"), "tarifa 2025"),
    ("F19513152", "2025-09-10", Decimal("5150.00"), Decimal("423.50"), "tarifa 2025"),
    ("F19513187", "2025-09-10", Decimal("4400.00"), Decimal("415.03"), "tarifa 2025"),
]
