"""Estructuras de datos del motor de cálculo."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Tramo:
    """Un tramo de la tabla de comisión de subasta.

    La cuota es ``cuota_fija + porcentaje% * puja``. Normalmente un tramo usa
    una de las dos (cuota fija o porcentaje), pero se admiten las dos a la vez.
    ``hasta = None`` significa "sin límite superior".
    """

    desde: Decimal
    hasta: Decimal | None
    cuota_fija: Decimal = Decimal("0")
    porcentaje: Decimal = Decimal("0")  # 2,60 se escribe Decimal("2.60")
    aplica_iva: bool = True

    def contiene(self, puja: Decimal) -> bool:
        if puja < self.desde:
            return False
        return self.hasta is None or puja <= self.hasta


@dataclass(frozen=True)
class ConfigProveedor:
    """Reglas de coste de adquisición de un proveedor / tipo de subasta.

    - Modo normal: ``tramos`` + ``conceptos_fijos`` (honorarios + tasas, ya con
      su IVA incluido donde corresponda).
    - Modo cuota plana (p. ej. "Concurso BCA"): ``cuota_plana`` distinta de
      ``None`` ignora tramos y conceptos; el coste es ``puja + cuota_plana``.
    """

    tramos: tuple[Tramo, ...] = ()
    conceptos_fijos: Decimal = Decimal("0")
    iva: Decimal = Decimal("1.21")
    cuota_plana: Decimal | None = None

    @property
    def es_cuota_plana(self) -> bool:
        return self.cuota_plana is not None


@dataclass(frozen=True)
class EntradaValoracion:
    """Datos de una valoración concreta que no dependen de la puja."""

    precio_venta: Decimal
    gastos_preparacion: Decimal
    descuento_comision_pct: Decimal = Decimal("0")
    regimen: str = "rebu"  # "rebu" | "general"
    base_margen: str = "adquisicion"  # "adquisicion" | "adjudicacion"


@dataclass(frozen=True)
class Desglose:
    """Resultado completo y auditable para una puja dada."""

    puja: Decimal
    comision_neta: Decimal
    comision_coste: Decimal
    conceptos_fijos: Decimal
    coste_adquisicion: Decimal
    gastos_preparacion: Decimal
    coste_total: Decimal
    base_margen: Decimal
    margen_bruto: Decimal
    iva_rebu: Decimal
    margen_neto: Decimal
    beneficio_neto: Decimal
    rentabilidad_coste: Decimal
    margen_venta: Decimal
    tramo: Tramo | None


@dataclass(frozen=True)
class Escenario:
    """Puja máxima y resultado para un objetivo de rentabilidad."""

    objetivo: Decimal  # 0,15 = 15 %
    puja_maxima: Decimal | None
    desglose: Desglose | None
