"""Oportunidades de Auto1: búsquedas guardadas de coches que se quieren comprar.

Fase 1: gestionar las búsquedas (crear, editar, pausar, borrar). El escaneo
diario de los listados y la pantalla de oportunidades encontradas llegan en las
fases siguientes.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import models
from .forms import BusquedaOportunidadForm


@login_required
def oportunidades_lista(request):
    busquedas = list(models.BusquedaOportunidad.objects.select_related("estado_carroceria"))
    return render(
        request,
        "tasador/oportunidades_lista.html",
        {"busquedas": busquedas, "n_activas": sum(1 for b in busquedas if b.activa)},
    )


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
    return render(request, "tasador/oportunidad_form.html", {"form": form, "busqueda": busqueda})


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
