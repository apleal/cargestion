"""Fórmulas económicas: coste, fiscalidad REBU, beneficio y puja máxima.

Reglas de redondeo
------------------
- Dinero: ``Decimal`` con 2 decimales, ``ROUND_HALF_UP``, aplicado en cada
  magnitud que se muestra o se guarda (``euros``).
- Porcentajes de rentabilidad: sin redondear internamente; se formatean al
  mostrarlos.
- La búsqueda de la puja máxima trabaja con la función ya redondeada a
  céntimos, de modo que el resultado es coherente con lo que verá el usuario.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .tipos import ConfigProveedor, Desglose, EntradaValoracion, Escenario, Tramo

CENT = Decimal("0.01")
CIENTO_VEINTIUNO = Decimal("121")
VEINTIUNO = Decimal("21")
CIEN = Decimal("100")

# Objetivos por defecto (15 %, 12 %, 10 %). Configurables desde la aplicación.
OBJETIVOS_DEFECTO = (Decimal("0.15"), Decimal("0.12"), Decimal("0.10"))


def euros(valor) -> Decimal:
    """Redondea a céntimos con ROUND_HALF_UP."""
    return Decimal(valor).quantize(CENT, rounding=ROUND_HALF_UP)


def tramo_para(config: ConfigProveedor, puja: Decimal) -> Tramo | None:
    """Tramo aplicable a ``puja``: el de mayor ``desde`` que no supera la puja.

    Así los valores intermedios entre el ``hasta`` de un tramo y el ``desde``
    del siguiente (que no deberían existir con límites en euros enteros, pero la
    búsqueda binaria los genera) caen en el tramo inferior. ``hasta`` se usa
    para validar la tabla y para mostrarla.
    """
    if not config.tramos:
        return None
    ordenados = sorted(config.tramos, key=lambda t: t.desde)
    elegido = ordenados[0]
    for tramo in ordenados:
        if puja >= tramo.desde:
            elegido = tramo
        else:
            break
    return elegido


def comision_neta(
    config: ConfigProveedor,
    puja: Decimal,
    descuento_pct: Decimal = Decimal("0"),
) -> Decimal:
    """Comisión de subasta neta (sin IVA), ya aplicado el descuento de lote."""
    if config.es_cuota_plana:
        return Decimal("0.00")
    tramo = tramo_para(config, puja)
    if tramo is None:
        return Decimal("0.00")
    base = tramo.cuota_fija + (tramo.porcentaje / CIEN) * puja
    base = base * (Decimal("1") - descuento_pct / CIEN)
    return euros(base)


def coste_adquisicion(
    config: ConfigProveedor,
    puja: Decimal,
    descuento_pct: Decimal = Decimal("0"),
) -> Decimal:
    """Todo lo que se paga para adquirir el coche (puja + comisión + fijos).

    En REBU el IVA de la comisión no es deducible, así que se cuenta como coste.
    """
    puja = Decimal(puja)
    if config.es_cuota_plana:
        return euros(puja + config.cuota_plana)
    tramo = tramo_para(config, puja)
    neta = comision_neta(config, puja, descuento_pct)
    factor_iva = config.iva if (tramo and tramo.aplica_iva) else Decimal("1")
    comision_coste = euros(neta * factor_iva)
    return euros(puja + comision_coste + config.conceptos_fijos)


TARIFA_AUTO1_DIVISOR = Decimal("0.21")


def tarifa_auto1_neta(iva_anuncio) -> Decimal:
    """Tarifa de subasta de Auto1 (neta) = IVA del anuncio / 0,21."""
    iva_anuncio = Decimal(iva_anuncio or 0)
    if iva_anuncio <= 0:
        return Decimal("0.00")
    return euros(iva_anuncio / TARIFA_AUTO1_DIVISOR)


def _evaluar_auto1(
    config: ConfigProveedor, entrada: EntradaValoracion, puja: Decimal
) -> Desglose:
    iva_anuncio = Decimal(entrada.iva_anuncio or 0)
    tarifa = tarifa_auto1_neta(iva_anuncio)
    compra_coche = euros(puja - tarifa - iva_anuncio)
    gestion = euros(config.conceptos_fijos)
    prep = euros(entrada.gastos_preparacion)
    gastos_lado = euros(tarifa + gestion + prep)
    coste_total = euros(compra_coche + gastos_lado)

    base_margen = euros(entrada.precio_venta - compra_coche)
    if entrada.regimen == "rebu":
        base_pos = base_margen if base_margen > 0 else Decimal("0")
        iva_rebu = euros(base_pos * VEINTIUNO / CIENTO_VEINTIUNO)
    else:
        iva_rebu = Decimal("0.00")
    margen_neto = euros(base_margen - iva_rebu)
    beneficio = euros(margen_neto - gastos_lado)

    rentabilidad = (beneficio / coste_total) if coste_total > 0 else Decimal("0")
    margen_venta = (
        (beneficio / entrada.precio_venta) if entrada.precio_venta > 0 else Decimal("0")
    )
    return Desglose(
        puja=euros(puja),
        comision_neta=tarifa,
        comision_coste=tarifa,
        conceptos_fijos=gestion,
        coste_adquisicion=compra_coche,
        gastos_preparacion=gastos_lado,  # incluye tarifa Auto1 + gestión + preparación
        coste_total=coste_total,
        base_margen=base_margen,
        margen_bruto=base_margen,
        iva_rebu=iva_rebu,
        margen_neto=margen_neto,
        beneficio_neto=beneficio,
        rentabilidad_coste=rentabilidad,
        margen_venta=margen_venta,
        tramo=None,
        modo="iva_anuncio",
        iva_anuncio=iva_anuncio,
        compra_coche=compra_coche,
    )


def evaluar(
    config: ConfigProveedor,
    entrada: EntradaValoracion,
    puja,
) -> Desglose:
    """Desglose completo para una puja concreta."""
    puja = Decimal(puja)
    if config.modo == "iva_anuncio":
        return _evaluar_auto1(config, entrada, puja)
    tramo = None if config.es_cuota_plana else tramo_para(config, puja)

    if config.es_cuota_plana:
        comision_n = Decimal("0.00")
        comision_c = Decimal("0.00")
        fijos = Decimal("0.00")
        adquisicion = euros(puja + config.cuota_plana)
    else:
        comision_n = comision_neta(config, puja, entrada.descuento_comision_pct)
        factor_iva = config.iva if (tramo and tramo.aplica_iva) else Decimal("1")
        comision_c = euros(comision_n * factor_iva)
        fijos = euros(config.conceptos_fijos)
        adquisicion = euros(puja + comision_c + fijos)

    gastos = euros(entrada.gastos_preparacion)
    coste_total = euros(adquisicion + gastos)

    if entrada.base_margen == "adjudicacion":
        base_margen = euros(entrada.precio_venta - puja)
    else:
        base_margen = euros(entrada.precio_venta - adquisicion)

    if entrada.regimen == "rebu":
        base_positiva = base_margen if base_margen > 0 else Decimal("0")
        iva_rebu = euros(base_positiva * VEINTIUNO / CIENTO_VEINTIUNO)
    else:
        # Régimen general: el IVA se liquida aparte y no reduce el margen aquí.
        # Pendiente de implementar en detalle (ver docs). Hoy solo se usa REBU.
        iva_rebu = Decimal("0.00")

    margen_neto = euros(base_margen - iva_rebu)
    beneficio = euros(margen_neto - gastos)

    rentabilidad = (
        (beneficio / coste_total) if coste_total > 0 else Decimal("0")
    )
    margen_venta = (
        (beneficio / entrada.precio_venta)
        if entrada.precio_venta > 0
        else Decimal("0")
    )

    return Desglose(
        puja=euros(puja),
        comision_neta=comision_n,
        comision_coste=comision_c,
        conceptos_fijos=fijos,
        coste_adquisicion=adquisicion,
        gastos_preparacion=gastos,
        coste_total=coste_total,
        base_margen=base_margen,
        margen_bruto=base_margen,
        iva_rebu=iva_rebu,
        margen_neto=margen_neto,
        beneficio_neto=beneficio,
        rentabilidad_coste=rentabilidad,
        margen_venta=margen_venta,
        tramo=tramo,
    )


def puja_maxima(
    config: ConfigProveedor,
    entrada: EntradaValoracion,
    objetivo: Decimal,
) -> Decimal | None:
    """Puja máxima que mantiene la rentabilidad sobre coste >= ``objetivo``.

    La rentabilidad es monótona decreciente respecto a la puja, así que se
    resuelve con búsqueda binaria. Esto es fiable aunque la comisión salte de
    tramo (la función a la que buscamos la raíz sigue siendo monótona).
    """
    venta = Decimal(entrada.precio_venta)
    if venta <= 0:
        return None
    # ¿Alcanzable siquiera con una puja mínima?
    if evaluar(config, entrada, Decimal("1")).rentabilidad_coste < objetivo:
        return None

    # En Auto1 la puja ("Precio Subasta") puede superar ligeramente la venta.
    lo, hi = Decimal("0"), venta + Decimal("6000")
    for _ in range(80):
        mid = (lo + hi) / 2
        if evaluar(config, entrada, mid).rentabilidad_coste >= objetivo:
            lo = mid
        else:
            hi = mid
    return euros(lo)


def precio_venta_minimo(
    config: ConfigProveedor,
    entrada: EntradaValoracion,
    puja: Decimal,
) -> Decimal:
    """Precio de venta con el que el beneficio neto es exactamente 0 para esa puja."""
    puja = Decimal(puja)
    adquisicion = coste_adquisicion(config, puja, entrada.descuento_comision_pct)
    gastos = euros(entrada.gastos_preparacion)
    if entrada.regimen == "rebu":
        # beneficio = (V - coste_adq_o_adj)/1.21 - gastos = 0  ->  V = coste + 1.21*gastos
        coste_ref = puja if entrada.base_margen == "adjudicacion" else adquisicion
        return euros(coste_ref + Decimal("1.21") * gastos)
    return euros(adquisicion + gastos)


def escenarios(
    config: ConfigProveedor,
    entrada: EntradaValoracion,
    objetivos=OBJETIVOS_DEFECTO,
) -> list[Escenario]:
    """Puja máxima y desglose para cada objetivo de rentabilidad."""
    salida: list[Escenario] = []
    for objetivo in objetivos:
        pmax = puja_maxima(config, entrada, objetivo)
        desglose = evaluar(config, entrada, pmax) if pmax is not None else None
        salida.append(Escenario(objetivo=objetivo, puja_maxima=pmax, desglose=desglose))
    return salida
