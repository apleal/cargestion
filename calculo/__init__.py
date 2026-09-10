"""Motor de cálculo puro (sin Django).

Todas las cantidades monetarias son ``Decimal``. El redondeo a céntimos usa
``ROUND_HALF_UP``. Este paquete no importa Django: se puede probar y reutilizar
de forma aislada (web, API, scripts).
"""
from .tipos import Tramo, ConfigProveedor, EntradaValoracion, Desglose, Escenario
from .motor import (
    euros,
    tramo_para,
    comision_neta,
    coste_adquisicion,
    evaluar,
    puja_maxima,
    escenarios,
    precio_venta_minimo,
)

__all__ = [
    "Tramo",
    "ConfigProveedor",
    "EntradaValoracion",
    "Desglose",
    "Escenario",
    "euros",
    "tramo_para",
    "comision_neta",
    "coste_adquisicion",
    "evaluar",
    "puja_maxima",
    "escenarios",
    "precio_venta_minimo",
]
