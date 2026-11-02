"""Oportunidades de Auto1: búsquedas guardadas de coches que se quieren comprar.

Se gestionan las búsquedas (crear, editar, pausar, borrar, «Buscar ahora») y
se ve el resultado de cada ejecución del servicio: cuándo se buscó, qué se leyó
y qué coches se pueden comprar.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from decimal import Decimal, InvalidOperation

from . import models, tasacion_mercado
from .forms import BusquedaOportunidadForm
from .views import _estado_servicio_auto1


@login_required
def oportunidades_lista(request):
    busquedas = list(models.BusquedaOportunidad.objects.select_related("estado_carroceria"))
    comprables = []
    for b in busquedas:
        b.ejec = b.ultima_ejecucion
        b.pedida_hace_min = (
            int((timezone.now() - b.solicitada).total_seconds() // 60) if b.solicitada else None
        )
        b.n_vigentes = 0
        if b.ejec is not None and b.ejec.estado == "ok":
            vigentes = list(b.oportunidades.filter(ultima_ejecucion=b.ejec).select_related("valoracion"))
            b.n_vigentes = len(vigentes)
            comprables += [o for o in vigentes if o.tier]
    orden = {"15": 0, "12": 1, "10": 2}
    comprables.sort(key=lambda o: (orden.get(o.tier, 9), o.precio))
    return render(
        request,
        "tasador/oportunidades_lista.html",
        {
            "busquedas": busquedas,
            "n_activas": sum(1 for b in busquedas if b.activa),
            "comprables": comprables,
            "sv": _estado_servicio_auto1(),
        },
    )


@login_required
def busqueda_coches(request, pk):
    """Todos los coches que encajaron en la última búsqueda (y los que ya no salen)."""
    b = get_object_or_404(models.BusquedaOportunidad, pk=pk)
    ejec = b.ultima_ejecucion
    todos = list(b.oportunidades.select_related("valoracion"))
    vigentes = [o for o in todos if ejec and o.ultima_ejecucion_id == ejec.pk]
    antiguos = [o for o in todos if not (ejec and o.ultima_ejecucion_id == ejec.pk)]
    orden = {"15": 0, "12": 1, "10": 2}
    vigentes.sort(key=lambda o: (orden.get(o.tier, 9), o.precio))
    antiguos.sort(key=lambda o: o.ultima_vez, reverse=True)
    return render(
        request,
        "tasador/busqueda_coches.html",
        {
            "busqueda": b, "ejec": ejec, "vigentes": vigentes, "antiguos": antiguos,
            "ejecuciones": list(b.ejecuciones.all()[:10]),
        },
    )


@login_required
@require_POST
def busqueda_buscar_ahora(request, pk):
    """Pide al servicio que recorra esta búsqueda en cuanto pueda (≤ 30 s)."""
    b = get_object_or_404(models.BusquedaOportunidad, pk=pk)
    b.solicitada = timezone.now()
    b.save(update_fields=["solicitada"])
    sv = _estado_servicio_auto1()
    if sv["conexion"] == "conectado":
        messages.success(request, f"Buscando «{b.nombre}»: el servicio la recoge en menos de un minuto y tarda unos minutos. Recarga para ver el resultado.")
    else:
        messages.warning(request, f"Petición guardada, pero el servicio no está conectado ({'nunca se ha conectado' if sv['conexion'] == 'nunca' else 'sin conexión'}): se hará cuando vuelva.")
    return redirect("oportunidades_lista")


@login_required
def busqueda_nueva(request):
    form = BusquedaOportunidadForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        b = form.save()
        messages.success(
            request,
            f"Búsqueda «{b.nombre}» creada: coches con {b.rango_km[0]:,}–{b.rango_km[1]:,} km.".replace(",", "."),
        )
        return redirect("oportunidades_lista")
    return render(request, "tasador/oportunidad_form.html", {"form": form, "busqueda": None})


@login_required
def busqueda_editar(request, pk):
    busqueda = get_object_or_404(models.BusquedaOportunidad, pk=pk)
    form = BusquedaOportunidadForm(request.POST or None, instance=busqueda)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Búsqueda guardada.")
        return redirect("oportunidades_lista")
    return render(
        request,
        "tasador/oportunidad_form.html",
        {
            "form": form,
            "busqueda": busqueda,
            "snippet_js": tasacion_mercado.SNIPPET_JS,
            "ia_disponible": tasacion_mercado.clave_disponible(),
            "tasaciones": list(busqueda.tasaciones.all()[:5]),
            "descuento_defecto": tasacion_mercado.DESCUENTO_NEGOCIACION_DEFECTO,
        },
    )


@login_required
@require_POST
def busqueda_alternar(request, pk):
    b = get_object_or_404(models.BusquedaOportunidad, pk=pk)
    b.activa = not b.activa
    b.save(update_fields=["activa", "updated_at"])
    messages.success(request, f"«{b.nombre}» {'activada' if b.activa else 'pausada'}.")
    return redirect("oportunidades_lista")


@login_required
@require_POST
def busqueda_eliminar(request, pk):
    b = get_object_or_404(models.BusquedaOportunidad, pk=pk)
    nombre = b.nombre
    b.delete()
    messages.success(request, f"Búsqueda «{nombre}» eliminada.")
    return redirect("oportunidades_lista")


@login_required
@require_POST
def busqueda_tasar(request, pk):
    """Tasa la búsqueda con los anuncios de coches.net que se han pegado."""
    b = get_object_or_404(models.BusquedaOportunidad, pk=pk)
    try:
        descuento = Decimal(request.POST.get("descuento", "").replace(",", ".") or tasacion_mercado.DESCUENTO_NEGOCIACION_DEFECTO)
        if not (Decimal("0") <= descuento <= Decimal("30")):
            raise InvalidOperation
    except InvalidOperation:
        messages.error(request, "El descuento de negociación debe ser un número entre 0 y 30.")
        return redirect("busqueda_editar", pk=b.pk)
    usar_ia = request.POST.get("usar_ia") == "on" and tasacion_mercado.clave_disponible()
    t = tasacion_mercado.tasar(
        b, request.POST.get("anuncios", ""), descuento_pct=descuento, usuario=request.user, usar_ia=usar_ia
    )
    return redirect("tasacion_detalle", pk=t.pk)


@login_required
def tasacion_detalle(request, pk):
    t = get_object_or_404(models.TasacionMercado.objects.select_related("busqueda"), pk=pk)
    return render(
        request, "tasador/tasacion_detalle.html",
        {"t": t, "b": t.busqueda, "ia_disponible": tasacion_mercado.clave_disponible()},
    )


@login_required
@require_POST
def tasacion_aplicar(request, pk):
    t = get_object_or_404(models.TasacionMercado.objects.select_related("busqueda"), pk=pk)
    if not t.valida:
        messages.error(request, "Esa tasación no tiene un precio que aplicar.")
        return redirect("tasacion_detalle", pk=t.pk)
    t.aplicar()
    messages.success(
        request,
        f"Aplicado: la búsqueda «{t.busqueda.nombre}» vende ahora a {t.precio_sugerido:,.0f} € "
        f"(con ajuste de {t.depreciacion_1000km:,.0f} € por cada 1.000 km).".replace(",", "."),
    )
    return redirect("busqueda_editar", pk=t.busqueda_id)
