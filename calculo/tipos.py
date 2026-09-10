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

    - ``modo = "tabla"`` (BCA): ``tramos`` + ``conceptos_fijos`` (honorarios +
      tasas, con su IVA incluido). ``cuota_plana`` distinta de ``None`` (p. ej.
      "Concurso BCA") ignora tramos y conceptos: coste = ``puja + cuota_plana``.
    - ``modo = "iva_anuncio"`` (Auto1): la puja es el "Precio Subasta" (coche +
      tarifa + IVA). La tarifa neta = IVA_del_anuncio / 0,21; el IVA es
      deducible; ``conceptos_fijos`` es la gestión documental de Auto1.
    """

    tramos: tuple[Tramo, ...] = ()
    conceptos_fijos: Decimal = Decimal("0")
    iva: Decimal = Decimal("1.21")
    cuota_plana: Decimal | None = None
    modo: str = "tabla"  # "tabla" | "iva_anuncio"

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
    iva_anuncio: Decimal = Decimal("0")  # solo Auto1: el IVA que muestra el anuncio


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
    modo: str = "tabla"
    iva_anuncio: Decimal = Decimal("0")  # Auto1
    compra_coche: Decimal | None = None  # Auto1: puja - tarifa - iva_anuncio


@dataclass(frozen=True)
class Escenario:
    """Puja máxima y resultado para un objetivo de rentabilidad."""

    objetivo: Decimal  # 0,15 = 15 %
    puja_maxima: Decimal | None
    desglose: Desglose | None
