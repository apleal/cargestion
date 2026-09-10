"""Datos de referencia de Auto1 (pestaña "Auto1_IA" del Excel).

Modelo Auto1
------------
El anuncio muestra un "Precio Subasta" (B) y un "IVA" (C). Ese IVA es el 21 %
de la tarifa de compra de Auto1, así que:

    tarifa_neta   = C / 0,21
    compra_coche  = B - tarifa_neta - C        (precio "limpio" del coche, base REBU)

El IVA (C) es deducible: no es coste. La tarifa neta sí es coste, junto con la
gestión documental de Auto1. El margen REBU se calcula sobre ``venta - compra_coche``.
"""
from __future__ import annotations

from decimal import Decimal

from .tipos import ConfigProveedor

# Gestión documental de Auto1 (P en el Excel = 469; Alberto la da por 478).
GESTION_AUTO1 = Decimal("478.00")


def config_auto1() -> ConfigProveedor:
    return ConfigProveedor(
        modo="iva_anuncio",
        conceptos_fijos=GESTION_AUTO1,
        iva=Decimal("1.21"),
    )
