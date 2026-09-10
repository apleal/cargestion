from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import models, services
from .dedup import buscar_vehiculo_similar
from .forms import PegarLotesForm, ValoracionForm
from .parser import parsear_texto


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


@login_required
def panel(request):
    hoy = timezone.localdate()
    proximas = (
        models.SesionSubasta.objects.filter(fecha__gte=hoy)
        .annotate(
            n_lotes=Count("valoraciones"),
            n_interesantes=Count(
                "valoraciones", filter=Q(valoraciones__estado__nombre="Interesante")
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
    vehiculo = None
    if request.GET.get("vehiculo"):
        vehiculo = get_object_or_404(models.Vehiculo, pk=request.GET["vehiculo"])
    if request.method == "POST":
        form = ValoracionForm(request.POST)
        if form.is_valid():
            v = form.save(commit=False)
            v.vehiculo = vehiculo or _vehiculo_desde_post(request)
            v.creado_por = request.user
            v.save()
            services.recalcular_y_guardar(v)
            return redirect("valoracion_editar", pk=v.pk)
    else:
        form = ValoracionForm()
    return render(
        request,
        "tasador/valoracion_form.html",
        {"form": form, "vehiculo": vehiculo, "valoracion": None},
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
    """Recalcula en vivo desde el formulario. Devuelve JSON."""
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
def sesion_detalle(request, pk):
    sesion = get_object_or_404(models.SesionSubasta, pk=pk)
    lotes = sesion.valoraciones.select_related("vehiculo", "estado").order_by(
        "orden_lote", "lote_id"
    )
    return render(
        request,
        "tasador/sesion_detalle.html",
        {"sesion": sesion, "lotes": lotes},
    )


@login_required
def pegar_lotes(request):
    preview = None
    if request.method == "POST":
        form = PegarLotesForm(request.POST)
        if form.is_valid():
            preview = parsear_texto(form.cleaned_data["texto"])
            for p in preview:
                p.similar = buscar_vehiculo_similar(
                    matricula=p.matricula, marca=p.marca, modelo=p.modelo, anio=p.anio
                )
    else:
        form = PegarLotesForm()
    return render(
        request, "tasador/pegar_lotes.html", {"form": form, "preview": preview}
    )
