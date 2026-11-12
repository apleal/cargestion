"""Tasación IA: subir un PDF o pegar un texto, revisar los datos y tasar el coche."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import extraccion, models, nayox, services_fichas, services_tasacion_ia, tasacion_mercado
from .forms_tasacion_ia import DatosCocheForm

MAX_TEXTO_PEGADO = 60000


def _recientes():
    return list(
        models.Valoracion.objects.filter(proveedor__nombre=services_tasacion_ia.PROVEEDOR)
        .select_related("vehiculo")
        .order_by("-created_at")[:15]
    )


def _pantalla(request, **extra):
    ctx = {"recientes": _recientes(), "ia_disponible": tasacion_mercado.clave_disponible()}
    ctx.update(extra)
    return render(request, "tasador/tasacion_ia.html", ctx)


def _revisar(request, form, notas=(), avisos=()):
    return render(
        request, "tasador/tasacion_ia_revisar.html",
        {"form": form, "notas": list(notas), "avisos": list(avisos), "ia_disponible": tasacion_mercado.clave_disponible()},
    )


@login_required
def tasacion_ia(request):
    return _pantalla(request)


@login_required
def tasacion_ia_manual(request):
    """Rellenar los datos a mano (sin PDF ni texto)."""
    return _revisar(request, DatosCocheForm(), notas=["Rellena los datos del coche."])


@login_required
@require_POST
def tasacion_ia_leer(request):
    texto = request.POST.get("texto", "")
    archivo = request.FILES.get("pdf")
    if not texto.strip() and not archivo:
        messages.error(request, "Sube un PDF o pega el texto con las características del coche.")
        return _pantalla(request)
    if len(texto) > MAX_TEXTO_PEGADO:
        messages.error(request, "El texto es demasiado largo. Pega solo las características del coche.")
        return _pantalla(request)
    pdf = None
    if archivo:
        if archivo.size > nayox.MAX_BYTES:
            messages.error(request, "El PDF pesa demasiado (máximo 10 MB).")
            return _pantalla(request)
        pdf = archivo.read()
    try:
        datos, notas = extraccion.extraer(texto, pdf, usar_ia=request.POST.get("usar_ia") == "on")
    except extraccion.ExtraccionError as e:
        messages.error(request, f"{archivo.name + ': ' if archivo else ''}{e}")
        return _pantalla(request)
    initial = {
        "marca": datos.marca, "modelo": datos.modelo, "version": datos.version, "acabado": datos.acabado,
        "anio": datos.anio, "fecha_matriculacion": datos.fecha_matriculacion, "km": datos.km,
        "combustible": datos.combustible, "cambio": datos.cambio, "potencia_cv": datos.potencia_cv,
        "matricula": datos.matricula, "vin": datos.vin, "precio_compra": datos.precio_compra,
        "observaciones": datos.observaciones, "carroceria_sin_danos": datos.carroceria_sin_danos,
        "avisos": "\n".join(datos.avisos), "origen": datos.origen,
    }
    return _revisar(request, DatosCocheForm(initial=initial), notas=notas, avisos=datos.avisos)


@login_required
@require_POST
def tasacion_ia_crear(request):
    form = DatosCocheForm(request.POST)
    if not form.is_valid():
        avisos = [a for a in request.POST.get("avisos", "").split("\n") if a.strip()]
        return _revisar(request, form, notas=["Hay datos que corregir."], avisos=avisos)
    try:
        v, repetido = services_tasacion_ia.crear_desde_formulario(form.cleaned_data, usuario=request.user)
    except services_fichas.FichaError as e:
        messages.error(request, str(e))
        return _revisar(request, form)
    km = f"{form.cleaned_data['km']:,}".replace(",", ".")
    messages.success(
        request,
        f"{'Actualizado' if repetido else 'Creado'}: {form.cleaned_data['marca']} {form.cleaned_data['modelo']} · {km} km. "
        "Ahora tásalo con anuncios de coches.net.",
    )
    return redirect("valoracion_tasar", pk=v.pk)
