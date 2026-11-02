"""Oportunidades de Auto1: evaluar los coches de un listado y registrar el resultado.

El servicio (navegador) lee el listado y las fichas; TODO el cálculo vive aquí,
con el mismo motor que el resto de la app, para que un cambio de fórmulas no se
desincronice. Un coche es «comprable» si su precio llega al menos al 10 % de
rentabilidad con el precio de venta y los costes de la búsqueda.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import services
from .models import (
    BusquedaOportunidad, EjecucionBusqueda, Oportunidad, Proveedor, TipoSubasta, Valoracion,
)
from .parser import parsear_linea_auto1

# El listado no trae el IVA del anuncio: se preselecciona con IVA 0 y esta holgura
# (el IVA casi no mueve el beneficio, pero sí un poco la rentabilidad), y la
# decisión real se toma con la ficha.
HOLGURA_LISTADO = Decimal("400")

TIERS = (("15", Decimal("0.15")), ("12", Decimal("0.12")), ("10", Decimal("0.10")))


def _valoracion_virtual(b: BusquedaOportunidad, precio: Decimal, iva: Decimal) -> Valoracion:
    """Una valoración SIN guardar con los costes de la búsqueda, para usar el motor."""
    proveedor = Proveedor.objects.get(nombre="Auto1")
    tipo = (
        TipoSubasta.objects.filter(proveedor=proveedor, es_predeterminado=True).first()
        or TipoSubasta.objects.filter(proveedor=proveedor).first()
    )
    return Valoracion(
        proveedor=proveedor, tipo_subasta=tipo, iva_anuncio=iva, precio_salida=precio,
        fecha_valoracion=timezone.localdate(),
        precio_venta_estimado=b.precio_venta_estimado,
        estado_carroceria=b.estado_carroceria, piezas_pintura=b.piezas_pintura,
        coste_alberto=b.coste_alberto, coste_gasolina=b.coste_gasolina,
        coste_pintura_por_pieza=b.coste_pintura_por_pieza, coste_garantia=b.coste_garantia,
        coste_mecanica=b.coste_mecanica, coste_cambio_titularidad=b.coste_cambio_titularidad,
        coste_transporte=b.coste_transporte, coste_itv=b.coste_itv,
        coste_tapiceria=b.coste_tapiceria, coste_tintado=b.coste_tintado, coste_otros=b.coste_otros,
    )


def _pujas_maximas(res) -> dict[str, Decimal | None]:
    por_objetivo = {Decimal(e.objetivo): e.puja_maxima for e in res.escenarios}
    return {tier: por_objetivo.get(obj) for tier, obj in TIERS}


def evaluar(b: BusquedaOportunidad, precio: Decimal, iva: Decimal = Decimal("0")) -> dict:
    """¿Se puede comprar a ``precio`` (con ese IVA de anuncio)? Devuelve el tier
    (15/12/10 o ""), el tope al 10 %, el margen hasta ese tope y la rentabilidad."""
    v = _valoracion_virtual(b, precio, iva)
    res = services.calcular(v, puja=precio)
    pujas = _pujas_maximas(res)
    tier = next((t for t, _ in TIERS if pujas[t] is not None and precio <= pujas[t]), "")
    p10 = pujas["10"]
    d = res.desglose_para_puja
    return {
        "tier": tier,
        "puja_maxima_10": p10,
        "margen_10": (p10 - precio) if (tier and p10 is not None) else None,
        "rentabilidad": d.rentabilidad_coste if d else None,
        "beneficio": d.beneficio_neto if d else None,
    }


def precio_max_listado(b: BusquedaOportunidad) -> int:
    """Precio del listado hasta el que merece la pena abrir la ficha (0 = ninguno)."""
    if not b.precio_venta_estimado:
        return 0
    v = _valoracion_virtual(b, Decimal("0"), Decimal("0"))
    p10 = _pujas_maximas(services.calcular(v))["10"]
    if p10 is None:
        return 0
    return int(p10 + HOLGURA_LISTADO)


@dataclass
class ResumenEjecucion:
    ejecucion: EjecucionBusqueda
    avisos: list[dict] = field(default_factory=list)


def _decimal(x) -> Decimal | None:
    return None if x in (None, "") else Decimal(str(x))


def _aplicar_costes_de_busqueda(v: Valoracion, b: BusquedaOportunidad) -> None:
    v.precio_venta_estimado = b.precio_venta_estimado
    v.estado_carroceria = b.estado_carroceria or v.estado_carroceria
    v.piezas_pintura = b.piezas_pintura
    for campo in (
        "coste_alberto", "coste_gasolina", "coste_pintura_por_pieza", "coste_garantia",
        "coste_mecanica", "coste_cambio_titularidad", "coste_transporte", "coste_itv",
        "coste_tapiceria", "coste_tintado", "coste_otros",
    ):
        setattr(v, campo, getattr(b, campo))


def pasar_a_seguimiento(op: Oportunidad, linea: str, usuario=None) -> Valoracion | None:
    """El coche comprable pasa al seguimiento normal de Auto1 (con la venta y los
    costes de la búsqueda si es nuevo; si ya lo tenías, se respeta lo tuyo)."""
    lote = parsear_linea_auto1(linea)
    if lote.dudosos or not lote.referencia:
        return None
    existente = (
        Valoracion.objects.filter(
            proveedor__nombre="Auto1", lote_id=lote.referencia, vehiculo__matricula=""
        )
        .order_by("-created_at")
        .first()
    )
    precio = Decimal(lote.precio_subasta or 0)
    iva = Decimal(lote.iva_anuncio or 0)
    if existente and existente.precio_salida == precio and existente.iva_anuncio == iva:
        return existente
    sesion = services.sesion_auto1_continua(usuario=usuario)
    v, era_retasacion = services.crear_valoracion_desde_lote(lote, sesion, usuario=usuario)
    if not era_retasacion or not v.precio_venta_estimado:
        _aplicar_costes_de_busqueda(v, op.busqueda)
    v.observaciones = f"Oportunidad «{op.busqueda.nombre}». {v.observaciones}"[:500]
    v.ultima_comprobacion = timezone.now()
    services.recalcular_y_guardar(v)
    return v


def registrar_resultado(b: BusquedaOportunidad, datos: dict, usuario=None) -> ResumenEjecucion:
    """Guarda lo que ha leído el servicio de una búsqueda.

    ``datos``: origen, paginas, leidos, encajan, error, aviso, y ``coches``: lista
    de {"tarjeta": {...}, "linea": "<8 campos>" | None} de los coches que encajan
    (``linea`` solo si se abrió la ficha). Devuelve la ejecución y los avisos
    (coches que se acaban de poder comprar, o que han bajado de precio)."""
    ahora = timezone.now()
    error = (datos.get("error") or "").strip()
    ejec = EjecucionBusqueda.objects.create(
        busqueda=b, inicio=ahora, origen=datos.get("origen") or "programada",
        estado=EjecucionBusqueda.Estado.ERROR if error else EjecucionBusqueda.Estado.OK,
        paginas=int(datos.get("paginas") or 0), leidos=int(datos.get("leidos") or 0),
        encajan=int(datos.get("encajan") or 0), error=error[:1000],
        aviso=(datos.get("aviso") or "")[:500],
    )
    resumen = ResumenEjecucion(ejec)
    b.solicitada = None
    b.save(update_fields=["solicitada"])
    if error:
        return resumen

    comprables = nuevos = revisados = 0
    for coche in datos.get("coches") or []:
        t = coche.get("tarjeta") or {}
        ref = (t.get("referencia") or "").strip()
        if not ref or t.get("precio") is None:
            continue
        precio = Decimal(str(t["precio"]))
        linea = coche.get("linea")
        iva = None
        if linea:
            lote = parsear_linea_auto1(linea)
            if not lote.dudosos and lote.precio_subasta:
                precio = Decimal(lote.precio_subasta)
                iva = Decimal(lote.iva_anuncio or 0)
        with transaction.atomic():
            op, creada = Oportunidad.objects.get_or_create(
                busqueda=b, referencia=ref,
                defaults={"precio": precio, "nombre": t.get("nombre", "")[:160], "primera_vez": ahora},
            )
            op.nombre = (t.get("nombre") or op.nombre)[:160]
            op.url = t.get("url") or op.url
            op.tipo = t.get("tipo") or ""
            op.precio = precio
            op.expectativa = _decimal(t.get("expectativa"))
            op.km, op.anio, op.cv = t.get("km"), t.get("anio"), t.get("cv")
            op.cambio = t.get("cambio") or ""
            op.ubicacion = (t.get("ubicacion") or "")[:80]
            op.ultima_vez, op.ultima_ejecucion = ahora, ejec

            if iva is not None:
                revisados += 1
                ev = evaluar(b, precio, iva)
                op.evaluada, op.iva_anuncio = True, iva
                op.tier, op.puja_maxima_10 = ev["tier"], ev["puja_maxima_10"]
                op.margen_10, op.rentabilidad, op.beneficio = (
                    ev["margen_10"], ev["rentabilidad"], ev["beneficio"],
                )
            else:
                # sin ficha no hay veredicto: o está muy por encima del precio útil, o es
                # «compra ya» (su tarifa es otra y no se calcula)
                op.evaluada, op.tier, op.iva_anuncio = False, "", None
                op.puja_maxima_10 = op.margen_10 = op.rentabilidad = op.beneficio = None
            op.save()

            if op.tier:
                comprables += 1
                nueva_info = op.precio_avisado is None or op.precio < op.precio_avisado
                if linea:
                    v = pasar_a_seguimiento(op, linea, usuario=usuario)
                    if v and op.valoracion_id != v.pk:
                        op.valoracion = v
                        op.save(update_fields=["valoracion"])
                if nueva_info:
                    nuevos += 1
                    op.precio_avisado = op.precio
                    op.save(update_fields=["precio_avisado"])
                    resumen.avisos.append(
                        {
                            "busqueda": b.nombre, "referencia": op.referencia, "nombre": op.nombre,
                            "url": op.url, "tipo": op.tipo, "precio": str(op.precio), "tier": op.tier,
                            "puja_maxima_10": str(op.puja_maxima_10) if op.puja_maxima_10 is not None else None,
                            "margen_10": str(op.margen_10) if op.margen_10 is not None else None,
                            "km": op.km, "anio": op.anio,
                        }
                    )
            elif op.precio_avisado is not None:
                # dejó de ser comprable (subió el precio): si vuelve a bajar, avisará otra vez
                op.precio_avisado = None
                op.save(update_fields=["precio_avisado"])

    ejec.revisados, ejec.comprables, ejec.nuevos_comprables = revisados, comprables, nuevos
    ejec.save(update_fields=["revisados", "comprables", "nuevos_comprables"])
    return resumen
