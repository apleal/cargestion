from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import models, services
from .dedup import buscar_vehiculo_similar
from .forms import PegarLotesForm, SesionSubastaForm, ValoracionForm
from .parser import parsear_texto

OBJETIVOS_ORDEN = ["0.15", "0.12", "0.10"]


def _fmt_escenarios(escs) -> list[dict]:
    salida = []
    for e in escs:
        d = e.desglose
        salida.append(
            {
                "objetivo": f"{e.objetivo:.0%}",
                "puja_maxima": str(e.puja_maxima) if e.puja_maxima is not None else None,
                "beneficio_neto": str(d.beneficio_neto) if d else None,
                "rentabilidad_coste": f"{d.rentabilidad_coste:.1%}" if d else None,
                "margen_venta": f"{d.margen_venta:.1%}" if d else None,
                "comision": str(d.comision_coste) if d else None,
            }
        )
    return salida


def _fila_valoracion(v: models.Valoracion) -> dict:
    """Datos que necesita una fila de la rejilla tipo Excel."""
    esc = v.r_escenarios or {}
    def puja(pref):
        for k, val in esc.items():
            if k.startswith(pref):
                return val.get("puja_maxima")
        return None
    return {
        "id": v.pk,
        "puja_15": puja("0.15"),
        "puja_12": puja("0.12"),
        "puja_10": puja("0.10"),
        "beneficio": str(v.r_beneficio_neto),
        "rentabilidad": f"{v.r_rentabilidad_coste:.1%}",
        "transporte": str(v.coste_transporte),
        "zona_origen": v.zona_origen,
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
    ctx = {
        "proximas": proximas,
        "total_valoraciones": valoraciones.count(),
        "interesantes": valoraciones.filter(estado__nombre="Interesante").count(),
        "pujados": valoraciones.filter(estado__nombre="Pujado").count(),
        "adjudicados": valoraciones.filter(estado__nombre="Adjudicado").count(),
        "ultimas": valoraciones.order_by("-created_at")[:15],
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
    lotes = list(
        sesion.valoraciones.select_related("vehiculo", "estado", "estado_carroceria")
        .order_by("orden_lote", "lote_id", "created_at")
    )
    for v in lotes:
        v.fila = _fila_valoracion(v)
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

    lotes = parsear_texto(form.cleaned_data["texto"])
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
        "precio_venta_estimado", "descuento_comision_pct", "coste_transporte",
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
        v.puja_12 = f"{float(f['puja_12']):,.0f} €".replace(",", ".") if f["puja_12"] else "—"
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
        {"form": form, "vehiculo": None, "valoracion": None},
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
                "rentabilidad_coste": f"{d.rentabilidad_coste:.1%}",
                "margen_venta": f"{d.margen_venta:.1%}",
                "tramo": (
                    f"{d.tramo.desde}–{d.tramo.hasta or '∞'}" if d.tramo else "cuota plana"
                ),
            },
        }
    )


@login_required
def vehiculo_detalle(request, pk):
    veh = get_object_or_404(models.Vehiculo, pk=pk)
    valoraciones = veh.valoraciones.select_related("estado", "sesion_subasta").order_by(
        "fecha_valoracion"
    )
    return render(
        request,
        "tasador/vehiculo_detalle.html",
        {"vehiculo": veh, "valoraciones": valoraciones},
    )


@login_required
def pegar_lotes(request):
    """Página suelta para pegar: obliga a elegir/crear una subasta."""
    sesiones = models.SesionSubasta.objects.select_related("ubicacion").order_by("-fecha")[:20]
    return render(request, "tasador/pegar_lotes.html", {"sesiones": sesiones})
