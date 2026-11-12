"""Nayox: subir la ficha de inspección (PDF), crear el coche y pasar a tasarlo."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from . import models, nayox, services_nayox

MAX_ARCHIVOS = 20


def _recientes():
    return list(
        models.Valoracion.objects.filter(proveedor__nombre="Nayox")
        .select_related("vehiculo")
        .order_by("-created_at")[:15]
    )


@login_required
def nayox_importar(request):
    if request.method != "POST":
        return render(request, "tasador/nayox_importar.html", {"recientes": _recientes()})

    archivos = request.FILES.getlist("pdf")[:MAX_ARCHIVOS]
    if not archivos:
        messages.error(request, "Elige al menos un PDF de Nayox.")
        return render(request, "tasador/nayox_importar.html", {"recientes": _recientes()})

    importadas = []
    for archivo in archivos:
        try:
            ficha = nayox.leer_ficha(archivo.read())
            valoracion, repetida = services_nayox.importar_ficha(ficha, usuario=request.user)
        except nayox.NayoxError as e:
            messages.error(request, f"{archivo.name}: {e}")
            continue
        importadas.append(valoracion)
        km = f"{ficha.km:,}".replace(",", ".")
        messages.success(
            request,
            f"{'Actualizado' if repetida else 'Importado'}: {ficha.nombre} · {km} km (expediente {ficha.expediente}).",
        )
        for aviso in ficha.avisos():
            messages.warning(request, f"{ficha.marca.title()} {ficha.matricula}: {aviso}")

    if not importadas:
        return render(request, "tasador/nayox_importar.html", {"recientes": _recientes()})
    if len(importadas) == 1:
        # un solo coche: directo a tasarlo (marca, modelo, acabado y km ya vienen del PDF)
        return redirect("valoracion_tasar", pk=importadas[0].pk)
    return redirect("sesion_detalle", pk=importadas[0].sesion_subasta_id)
