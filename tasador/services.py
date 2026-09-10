"""Puente entre los modelos de Django y el motor de cálculo puro (``calculo``)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from calculo import ConfigProveedor, EntradaValoracion, Tramo, escenarios, evaluar
from calculo.motor import puja_maxima

from .models import (
    ConceptoFijo,
    EscenarioObjetivo,
    Proveedor,
    TarifaComision,
    TipoSubasta,
    Valoracion,
)


def _conceptos_fijos_vigentes(proveedor: Proveedor, fecha=None) -> Decimal:
    fecha = fecha or timezone.localdate()
    total = Decimal("0")
    for c in proveedor.conceptos_fijos.all():
        if c.vigencia_desde and fecha < c.vigencia_desde:
            continue
        if c.vigencia_hasta and fecha > c.vigencia_hasta:
            continue
        total += c.importe
    return total


def tarifa_vigente(proveedor: Proveedor, fecha=None) -> TarifaComision | None:
    fecha = fecha or timezone.localdate()
    qs = proveedor.tarifas_comision.filter(tipo_vehiculo="Otros")
    candidatas = [
        t for t in qs
        if (t.vigencia_desde is None or t.vigencia_desde <= fecha)
        and (t.vigencia_hasta is None or t.vigencia_hasta >= fecha)
    ]
    if candidatas:
        return sorted(
            candidatas, key=lambda t: t.vigencia_desde or timezone.datetime.min.date()
        )[-1]
    return qs.order_by("-vigencia_desde").first()


def construir_config(
    tipo_subasta: TipoSubasta,
    *,
    tarifa: TarifaComision | None = None,
    fecha=None,
) -> tuple[ConfigProveedor, TarifaComision | None]:
    """Crea el ``ConfigProveedor`` del motor a partir de un tipo de subasta."""
    proveedor = tipo_subasta.proveedor

    if tipo_subasta.cuota_plana is not None:
        return ConfigProveedor(cuota_plana=tipo_subasta.cuota_plana), None

    tarifa = tarifa or tarifa_vigente(proveedor, fecha)
    tramos: tuple[Tramo, ...] = ()
    iva = Decimal("1.21")
    if tarifa:
        iva = tarifa.iva
        tramos = tuple(
            Tramo(
                desde=t.importe_desde,
                hasta=t.importe_hasta,
                cuota_fija=t.cuota_fija,
                porcentaje=t.porcentaje,
                aplica_iva=t.aplica_iva,
            )
            for t in tarifa.tramos.order_by("importe_desde")
        )
    fijos = (
        _conceptos_fijos_vigentes(proveedor, fecha)
        if tipo_subasta.aplica_conceptos_fijos
        else Decimal("0")
    )
    return ConfigProveedor(tramos=tramos, conceptos_fijos=fijos, iva=iva), tarifa


@dataclass
class ResultadoCalculo:
    entrada: EntradaValoracion
    desglose_para_puja: object | None
    escenarios: list


def gastos_preparacion(v: Valoracion) -> Decimal:
    pintura = max(
        v.coste_pintura_por_pieza * Decimal(v.piezas_pintura),
        Decimal("0"),
    )
    return (
        v.coste_alberto
        + v.coste_gasolina
        + pintura
        + v.coste_garantia
        + v.coste_mecanica
        + v.coste_cambio_titularidad
        + v.coste_transporte
        + v.coste_itv
        + v.coste_tapiceria
        + v.coste_tintado
        + v.coste_otros
    )


def entrada_de_valoracion(v: Valoracion) -> EntradaValoracion:
    return EntradaValoracion(
        precio_venta=v.precio_venta_estimado or Decimal("0"),
        gastos_preparacion=gastos_preparacion(v),
        descuento_comision_pct=v.descuento_comision_pct or Decimal("0"),
        regimen=v.regimen_fiscal,
        base_margen=v.proveedor.base_margen_rebu,
    )


def objetivos_activos() -> list[Decimal]:
    objetivos = list(
        EscenarioObjetivo.objects.filter(activo=True).values_list(
            "rentabilidad_objetivo", flat=True
        )
    )
    return objetivos or [Decimal("0.15"), Decimal("0.12"), Decimal("0.10")]


def calcular(v: Valoracion, puja: Decimal | None = None) -> ResultadoCalculo:
    config, tarifa = construir_config(
        v.tipo_subasta, tarifa=v.tarifa_comision_aplicada, fecha=v.fecha_valoracion
    )
    entrada = entrada_de_valoracion(v)
    escs = escenarios(config, entrada, tuple(objetivos_activos()))
    desglose = evaluar(config, entrada, puja) if puja is not None else None
    return ResultadoCalculo(entrada=entrada, desglose_para_puja=desglose, escenarios=escs)


def recalcular_y_guardar(v: Valoracion) -> Valoracion:
    """Recalcula los campos ``r_*`` y guarda la valoración."""
    config, tarifa = construir_config(
        v.tipo_subasta, tarifa=v.tarifa_comision_aplicada, fecha=v.fecha_valoracion
    )
    if tarifa and not v.tarifa_comision_aplicada:
        v.tarifa_comision_aplicada = tarifa

    entrada = entrada_de_valoracion(v)
    objetivos = objetivos_activos()
    escs = escenarios(config, entrada, tuple(objetivos))

    principal = (
        EscenarioObjetivo.objects.filter(activo=True, es_principal=True).first()
    )
    obj_principal = (
        principal.rentabilidad_objetivo if principal else Decimal("0.15")
    )
    pmax_principal = puja_maxima(config, entrada, obj_principal)

    ref = evaluar(config, entrada, pmax_principal) if pmax_principal else None

    v.r_gastos_preparacion = entrada.gastos_preparacion
    v.r_coste_adquisicion = ref.coste_adquisicion if ref else Decimal("0")
    v.r_coste_total = ref.coste_total if ref else Decimal("0")
    v.r_iva_rebu = ref.iva_rebu if ref else Decimal("0")
    v.r_beneficio_neto = ref.beneficio_neto if ref else Decimal("0")
    v.r_rentabilidad_coste = ref.rentabilidad_coste if ref else Decimal("0")
    v.r_margen_venta = ref.margen_venta if ref else Decimal("0")
    v.r_puja_maxima_principal = pmax_principal
    v.r_escenarios = {
        f"{e.objetivo}": {
            "objetivo": str(e.objetivo),
            "puja_maxima": str(e.puja_maxima) if e.puja_maxima is not None else None,
            "beneficio_neto": (
                str(e.desglose.beneficio_neto) if e.desglose else None
            ),
            "rentabilidad_coste": (
                str(e.desglose.rentabilidad_coste) if e.desglose else None
            ),
            "margen_venta": str(e.desglose.margen_venta) if e.desglose else None,
        }
        for e in escs
    }
    v.save()
    return v
