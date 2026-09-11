from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import models, services
from .dedup import buscar_vehiculo_similar
from .forms import PegarLotesForm, SesionSubastaForm, ValoracionForm
from .parser import parsear_texto

OBJETIVOS_ORDEN = ["0.15", "0.12", "0.10"]


def _carrocerias_piezas_json() -> str:
    """{id: piezas_estimadas} de cada estado de carrocería, para el JS del formulario."""
    return json.dumps(dict(models.EstadoCarroceria.objects.values_list("id", "piezas_estimadas")))


def _fmt_escenarios(escs) -> list[dict]:
    salida = []
    for e in escs:
        d = e.desglose
        salida.append(
            {
                "objetivo": _pct_es(e.objetivo, 0),
                "puja_maxima": str(e.puja_maxima) if e.puja_maxima is not None else None,
                "beneficio_neto": str(d.beneficio_neto) if d else None,
                "rentabilidad_coste": _pct_es(d.rentabilidad_coste) if d else None,
                "margen_venta": _pct_es(d.margen_venta) if d else None,
                "comision": str(d.comision_coste) if d else None,
            }
        )
    return salida


def _pct_es(x, dec=1) -> str:
    try:
        return f"{float(x) * 100:.{dec}f}".replace(".", ",") + " %"
    except (TypeError, ValueError):
        return "—"


def _tier_precio_salida(v: models.Valoracion) -> str | None:
    """¿A qué objetivo llega el precio de salida (real) de este momento?

    "15" = ya cumple el 15 % (el mejor caso) · "12" · "10" · None = no llega
    ni al 10 %. Se calcula con los importes guardados en la valoración (snapshot
    de ese momento), así que también sirve para leer el histórico: "el 10/09
    llegaba al 15 %, el 11/09 ya no llega ni al 10 %".
    """
    if not v.precio_salida:
        return None
    esc = v.r_escenarios or {}
    def puja(pref):
        for k, val in esc.items():
            if k.startswith(pref):
                pm = val.get("puja_maxima")
                return Decimal(pm) if pm else None
        return None
    for pref, tier in (("0.15", "15"), ("0.12", "12"), ("0.10", "10")):
        pm = puja(pref)
        if pm is not None and v.precio_salida <= pm:
            return tier
    return None


def _en_precio(v: models.Valoracion) -> bool:
    """¿El precio de salida ya está por debajo de la puja máxima al 15 % (el objetivo)?"""
    return _tier_precio_salida(v) == "15"


def _delta_precio_salida(v: models.Valoracion, anterior: models.Valoracion | None) -> tuple[str | None, str | None]:
    """Diferencia de precio de salida respecto a otra valoración del mismo coche."""
    if not (anterior and anterior.precio_salida and v.precio_salida):
        return None, None
    diff = anterior.precio_salida - v.precio_salida
    if diff == 0:
        return None, None
    signo = "baja" if diff > 0 else "sube"
    txt = f"{'↓' if diff > 0 else '↑'} {abs(diff):,.0f} €".replace(",", ".")
    return txt, signo


def _fila_valoracion(v: models.Valoracion) -> dict:
    """Datos que necesita una fila de la rejilla tipo Excel."""
    esc = v.r_escenarios or {}
    def puja(pref):
        for k, val in esc.items():
            if k.startswith(pref):
                return val.get("puja_maxima")
        return None

    tier = _tier_precio_salida(v)
    delta_txt, delta_signo = _delta_precio_salida(v, getattr(v, "valoracion_anterior", None))

    return {
        "id": v.pk,
        "puja_15": puja("0.15"),
        "puja_12": puja("0.12"),
        "puja_10": puja("0.10"),
        "beneficio": str(v.r_beneficio_neto),
        "rentabilidad": _pct_es(v.r_rentabilidad_coste),
        "transporte": str(v.coste_transporte),
        "zona_origen": v.zona_origen,
        "precio_salida": str(v.precio_salida),
        "tier": tier,
        "en_precio": tier == "15",
        "delta_txt": delta_txt,
        "delta_signo": delta_signo,
    }


@login_required
def panel(request):
    hoy = timezone.localdate()
    proximas = (
        models.SesionSubasta.objects.filter(fecha__gte=hoy)
        .select_related("ubicacion")
        .annotate(
            n_lotes=Count("valoraciones"),
            n_interesantes=Count(
                "valoraciones", filter=Q(valoraciones__estado__nombre="Interesante")
            ),
            n_sin_valorar=Count(
                "valoraciones",
                filter=Q(valoraciones__estado__nombre="Pendiente de valorar"),
            ),
        )
        .order_by("fecha")[:10]
    )
    valoraciones = models.Valoracion.objects.select_related("vehiculo", "estado")
    en_precio = (
        valoraciones.exclude(estado__es_final=True)
        .filter(
            precio_salida__gt=0,
            r_puja_maxima_principal__isnull=False,
            precio_salida__lte=F("r_puja_maxima_principal"),
        )
        .select_related("vehiculo", "sesion_subasta")
    )
    ctx = {
        "proximas": proximas,
        "total_valoraciones": valoraciones.count(),
        "interesantes": valoraciones.filter(estado__nombre="Interesante").count(),
        "pujados": valoraciones.filter(estado__nombre="Pujado").count(),
        "adjudicados": valoraciones.filter(estado__nombre="Adjudicado").count(),
        "ultimas": valoraciones.order_by("-created_at")[:15],
        "en_precio": en_precio.order_by("-updated_at")[:10],
        "en_precio_total": en_precio.count(),
    }
    return render(request, "tasador/panel.html", ctx)


# --------------------------------------------------------------------------
# Sesiones de subasta (la rejilla tipo Excel es la pantalla principal)
# --------------------------------------------------------------------------
@login_required
def sesion_lista(request):
    sesiones = (
        models.SesionSubasta.objects.select_related("ubicacion", "proveedor")
        .annotate(n_lotes=Count("valoraciones"))
        .order_by("-fecha")
    )
    return render(request, "tasador/sesion_lista.html", {"sesiones": sesiones})


@login_required
def sesion_nueva(request):
    if request.method == "POST":
        form = SesionSubastaForm(request.POST)
        if form.is_valid():
            sesion = form.save(commit=False)
            sesion.creada_por = request.user
            sesion.save()
            messages.success(request, "Subasta creada. Ahora pega los lotes.")
            return redirect("sesion_detalle", pk=sesion.pk)
    else:
        form = SesionSubastaForm()
    return render(request, "tasador/sesion_form.html", {"form": form})


@login_required
def sesion_detalle(request, pk):
    sesion = get_object_or_404(
        models.SesionSubasta.objects.select_related("ubicacion", "proveedor"), pk=pk
    )
    es_auto1 = sesion.proveedor.tipos_subasta.filter(modo="iva_anuncio").exists()
    todos = list(
        sesion.valoraciones.select_related(
            "vehiculo", "estado", "estado_carroceria", "valoracion_anterior"
        )
        .order_by("orden_lote", "created_at")
    )
    for v in todos:
        v.fila = _fila_valoracion(v)

    if es_auto1:
        # Auto1 es un mercado continuo: el mismo coche se vuelve a pegar varias
        # veces. Se agrupa por vehículo, se muestra solo el último escaneo como
        # fila principal (con un "+N" al historial) y se ordena por fecha de
        # escaneo más reciente primero.
        grupos: dict[int, list] = {}
        for v in todos:
            grupos.setdefault(v.vehiculo_id, []).append(v)
        lotes = []
        for vs in grupos.values():
            vs.sort(key=lambda x: x.created_at, reverse=True)
            principal, historial = vs[0], vs[1:]
            for h in historial:
                h.fila = _fila_valoracion(h)
            principal.historial = historial
            lotes.append(principal)
        lotes.sort(key=lambda v: v.created_at, reverse=True)
    else:
        for v in todos:
            v.historial = []
        lotes = todos

    zonas = list(
        sesion.proveedor.tarifas_transporte.filter(activa=True)
        .values_list("origen", flat=True)
    )
    ctx = {
        "sesion": sesion,
        "lotes": lotes,
        "estados": models.EstadoValoracion.objects.all(),
        "carrocerias": models.EstadoCarroceria.objects.all(),
        "zonas_transporte": zonas,
        "es_auto1": es_auto1,
        "pegar_form": PegarLotesForm(),
    }
    return render(request, "tasador/sesion_detalle.html", ctx)


@login_required
@require_POST
def sesion_pegar(request, pk):
    sesion = get_object_or_404(models.SesionSubasta, pk=pk)
    form = PegarLotesForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Pega algún texto.")
        return redirect("sesion_detalle", pk=pk)

    formato = (
        "auto1"
        if sesion.proveedor.tipos_subasta.filter(modo="iva_anuncio").exists()
        else "bca"
    )
    lotes = parsear_texto(form.cleaned_data["texto"], formato=formato)
    creados, retasaciones = 0, 0
    for lote in lotes:
        _v, es_ret = services.crear_valoracion_desde_lote(lote, sesion, request.user)
        creados += 1
        retasaciones += 1 if es_ret else 0

    msg = f"{creados} lote(s) añadido(s)."
    if retasaciones:
        msg += f" {retasaciones} ya se conocían (retasación enlazada)."
    messages.success(request, msg)
    return redirect("sesion_detalle", pk=pk)


@login_required
@require_POST
def celda_update(request, pk):
    """Edición en línea de una celda de la rejilla. Devuelve la fila recalculada."""
    v = get_object_or_404(models.Valoracion, pk=pk)
    campo = request.POST.get("campo")
    valor = request.POST.get("valor", "")

    editables_decimal = {
        "precio_venta_estimado", "descuento_comision_pct", "iva_anuncio", "coste_transporte",
        "coste_mecanica", "coste_garantia", "coste_pintura_por_pieza",
        "coste_alberto", "coste_gasolina", "coste_cambio_titularidad",
        "coste_itv", "coste_tapiceria", "coste_tintado", "coste_otros",
        "puja_realizada",
    }
    try:
        if campo in editables_decimal:
            setattr(v, campo, Decimal(valor or "0"))
        elif campo == "piezas_pintura":
            v.piezas_pintura = int(valor or 0)
        elif campo == "orden_lote":
            v.orden_lote = int(valor) if valor else None
        elif campo == "lote_id":
            v.lote_id = valor
        elif campo == "zona_origen":
            v.zona_origen = valor
            tt = services.tarifa_transporte(v.proveedor, valor, v.fecha_valoracion)
            if tt:
                v.coste_transporte = tt.precio
        elif campo == "estado_id":
            v.estado_id = int(valor)
        elif campo == "estado_carroceria_id":
            v.estado_carroceria_id = int(valor) if valor else None
            if v.estado_carroceria:
                v.piezas_pintura = v.estado_carroceria.piezas_estimadas
        elif campo == "kilometros":
            v.kilometros = int(valor) if valor else None
        else:
            return JsonResponse({"error": f"campo no editable: {campo}"}, status=400)
    except (InvalidOperation, ValueError):
        return JsonResponse({"error": "valor no válido"}, status=400)

    v.save()
    services.recalcular_y_guardar(v)
    fila = _fila_valoracion(v)
    fila["piezas_pintura"] = v.piezas_pintura
    return JsonResponse(fila)


@login_required
def sesion_sala(request, pk):
    """Modo sala de pujas: lectura, seguimiento por lote durante la subasta."""
    sesion = get_object_or_404(models.SesionSubasta, pk=pk)
    lotes = list(
        sesion.valoraciones.select_related("vehiculo", "estado")
        .order_by("orden_lote", "lote_id")
    )
    for v in lotes:
        f = _fila_valoracion(v)
        v.puja_12 = f["puja_12"]  # el template lo formatea con |eur
    return render(
        request, "tasador/sesion_sala.html", {"sesion": sesion, "lotes": lotes}
    )


# --------------------------------------------------------------------------
# Valoración individual (ajuste fino de costes)
# --------------------------------------------------------------------------
@login_required
def valoracion_lista(request):
    qs = models.Valoracion.objects.select_related(
        "vehiculo", "estado", "proveedor", "sesion_subasta"
    )
    estado = request.GET.get("estado")
    if estado:
        qs = qs.filter(estado__nombre=estado)
    return render(
        request,
        "tasador/valoracion_lista.html",
        {"valoraciones": qs[:200], "estados": models.EstadoValoracion.objects.all()},
    )


@login_required
def valoracion_nueva(request):
    if request.method == "POST":
        form = ValoracionForm(request.POST)
        if form.is_valid():
            v = form.save(commit=False)
            v.vehiculo = _vehiculo_desde_post(request)
            v.creado_por = request.user
            v.save()
            services.recalcular_y_guardar(v)
            return redirect("valoracion_editar", pk=v.pk)
    else:
        form = ValoracionForm()
    return render(
        request,
        "tasador/valoracion_form.html",
        {
            "form": form,
            "vehiculo": None,
            "valoracion": None,
            "carrocerias_piezas_json": _carrocerias_piezas_json(),
        },
    )


def _vehiculo_desde_post(request) -> models.Vehiculo:
    matricula = (request.POST.get("v_matricula") or "").strip().upper()
    if matricula:
        veh = models.Vehiculo.objects.filter(matricula=matricula).first()
        if veh:
            return veh
    return models.Vehiculo.objects.create(
        matricula=matricula,
        marca=(request.POST.get("v_marca") or "").strip(),
        modelo=(request.POST.get("v_modelo") or "").strip(),
        version=(request.POST.get("v_version") or "").strip(),
    )


@login_required
def valoracion_editar(request, pk):
    v = get_object_or_404(models.Valoracion.objects.select_related("vehiculo"), pk=pk)
    if request.method == "POST":
        form = ValoracionForm(request.POST, instance=v)
        if form.is_valid():
            v = form.save()
            services.recalcular_y_guardar(v)
            messages.success(request, "Valoración guardada.")
            return redirect("valoracion_editar", pk=v.pk)
    else:
        form = ValoracionForm(instance=v)
    resultado = services.calcular(v, puja=v.r_puja_maxima_principal)
    return render(
        request,
        "tasador/valoracion_form.html",
        {
            "form": form,
            "valoracion": v,
            "vehiculo": v.vehiculo,
            "escenarios": _fmt_escenarios(resultado.escenarios),
            "carrocerias_piezas_json": _carrocerias_piezas_json(),
        },
    )


@login_required
@require_POST
def calcular_api(request):
    def dec(nombre, defecto="0"):
        try:
            return Decimal(request.POST.get(nombre) or defecto)
        except (InvalidOperation, TypeError):
            return Decimal(defecto)

    tipo_id = request.POST.get("tipo_subasta")
    tipo = models.TipoSubasta.objects.filter(pk=tipo_id).first()
    if not tipo:
        tipo = models.TipoSubasta.objects.filter(es_predeterminado=True).first()
    if not tipo:
        return JsonResponse({"error": "No hay tipos de subasta configurados."}, status=400)

    v = models.Valoracion(
        proveedor=tipo.proveedor,
        tipo_subasta=tipo,
        regimen_fiscal=request.POST.get("regimen_fiscal") or "rebu",
        iva_anuncio=dec("iva_anuncio"),
        precio_venta_estimado=dec("precio_venta_estimado"),
        piezas_pintura=int(dec("piezas_pintura", "4")),
        descuento_comision_pct=dec("descuento_comision_pct"),
        coste_alberto=dec("coste_alberto"),
        coste_gasolina=dec("coste_gasolina"),
        coste_pintura_por_pieza=dec("coste_pintura_por_pieza"),
        coste_garantia=dec("coste_garantia"),
        coste_mecanica=dec("coste_mecanica"),
        coste_cambio_titularidad=dec("coste_cambio_titularidad"),
        coste_transporte=dec("coste_transporte"),
        coste_itv=dec("coste_itv"),
        coste_tapiceria=dec("coste_tapiceria"),
        coste_tintado=dec("coste_tintado"),
        coste_otros=dec("coste_otros"),
        fecha_valoracion=timezone.localdate(),
    )
    try:
        puja = Decimal(request.POST["puja"]) if request.POST.get("puja") else None
    except (InvalidOperation, KeyError):
        puja = None

    resultado = services.calcular(v, puja=puja)
    d = resultado.desglose_para_puja
    return JsonResponse(
        {
            "gastos_preparacion": str(resultado.entrada.gastos_preparacion),
            "preparacion": [
                {"concepto": x["concepto"], "importe": str(x["importe"])}
                for x in services.preparacion_detalle(v)
            ],
            "escenarios": _fmt_escenarios(resultado.escenarios),
            "desglose": None
            if d is None
            else {
                "puja": str(d.puja),
                "comision_neta": str(d.comision_neta),
                "comision_coste": str(d.comision_coste),
                "conceptos_fijos": str(d.conceptos_fijos),
                "coste_adquisicion": str(d.coste_adquisicion),
                "gastos_preparacion": str(d.gastos_preparacion),
                "coste_total": str(d.coste_total),
                "margen_bruto": str(d.margen_bruto),
                "iva_rebu": str(d.iva_rebu),
                "margen_neto": str(d.margen_neto),
                "beneficio_neto": str(d.beneficio_neto),
                "rentabilidad_coste": _pct_es(d.rentabilidad_coste),
                "margen_venta": _pct_es(d.margen_venta),
                "modo": d.modo,
                "iva_anuncio": str(d.iva_anuncio),
                "compra_coche": str(d.compra_coche) if d.compra_coche is not None else None,
                "tramo": (
                    f"{d.tramo.desde:.0f}–{d.tramo.hasta:.0f}"
                    if d.tramo and d.tramo.hasta is not None
                    else (
                        f"≥ {d.tramo.desde:.0f}" if d.tramo
                        else ("Auto1" if d.modo == "iva_anuncio" else "cuota plana")
                    )
                ),
            },
        }
    )


@login_required
def vehiculo_detalle(request, pk):
    """Ficha de un coche: histórico completo, ordenado de más antigua a más
    reciente, con la evolución del precio y si en cada momento se podía comprar
    al objetivo del 15 % ("ayer sí, hoy ya no porque han pujado")."""
    veh = get_object_or_404(models.Vehiculo, pk=pk)
    valoraciones = list(
        veh.valoraciones.select_related("estado", "sesion_subasta").order_by(
            "fecha_valoracion", "created_at"
        )
    )
    anterior = None
    for v in valoraciones:
        v.delta_txt, v.delta_signo = _delta_precio_salida(v, anterior)
        v.tier = _tier_precio_salida(v)
        anterior = v
    referencias = {v.lote_id for v in valoraciones if v.lote_id}
    return render(
        request,
        "tasador/vehiculo_detalle.html",
        {
            "vehiculo": veh,
            "valoraciones": valoraciones,
            "referencia": next(iter(referencias), "") if len(referencias) == 1 else "",
        },
    )


@login_required
def buscar_vehiculo(request):
    """Buscador por Ref. Auto1 o matrícula: lleva directo al histórico del coche."""
    q = (request.GET.get("q") or "").strip()
    if not q:
        return redirect(request.META.get("HTTP_REFERER") or "panel")

    vehiculos = models.Vehiculo.objects.filter(
        Q(matricula__iexact=q) | Q(valoraciones__lote_id__iexact=q)
    ).distinct()
    if vehiculos.count() == 1:
        return redirect("vehiculo_detalle", pk=vehiculos.first().pk)
    if vehiculos.count() > 1:
        return render(
            request, "tasador/buscar_resultados.html", {"q": q, "vehiculos": vehiculos}
        )
    messages.warning(request, f'No se encontró ningún coche con "{q}".')
    return redirect(request.META.get("HTTP_REFERER") or "panel")


@login_required
def pegar_lotes(request):
    """Página suelta para pegar: obliga a elegir/crear una subasta."""
    sesiones = models.SesionSubasta.objects.select_related("ubicacion").order_by("-fecha")[:20]
    return render(request, "tasador/pegar_lotes.html", {"sesiones": sesiones})
