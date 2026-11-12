"""Oportunidades de Auto1: búsquedas guardadas de coches que se quieren comprar.

Se gestionan las búsquedas (crear, editar, pausar, borrar, «Buscar ahora») y
se ve el resultado de cada ejecución del servicio: cuándo se buscó, qué se leyó
y qué coches se pueden comprar.
"""
from __future__ import annotations

import time

from django.contrib import messages
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from decimal import Decimal, InvalidOperation

from . import models, services, tasacion_mercado
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
    if request.method == "GET":
        _recordar_destino(request, "busqueda", busqueda.pk)
    return render(
        request,
        "tasador/oportunidad_form.html",
        {
            "form": form,
            "busqueda": busqueda,
            "snippet_js": tasacion_mercado.SNIPPET_JS,
            "snippet_cargador": tasacion_mercado.SNIPPET_CARGADOR,
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
    t = get_object_or_404(models.TasacionMercado.objects.select_related("busqueda", "valoracion"), pk=pk)
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
    if not t.busqueda_id and not t.valoracion_id:
        messages.error(request, "Esa tasación ya no está ligada a ningún coche.")
        return redirect("tasacion_detalle", pk=t.pk)
    t.aplicar()
    if t.busqueda_id:
        messages.success(
            request,
            f"Aplicado: la búsqueda «{t.busqueda.nombre}» vende ahora a {t.precio_sugerido:,.0f} € "
            f"(con ajuste de {t.depreciacion_1000km:,.0f} € por cada 1.000 km).".replace(",", "."),
        )
        return redirect("busqueda_editar", pk=t.busqueda_id)
    messages.success(
        request, f"Aplicado: {t.nombre} se vende a {t.precio_sugerido:,.0f} € (ya recalculadas las pujas).".replace(",", ".")
    )
    return redirect("sesion_detalle", pk=t.valoracion.sesion_subasta_id)


DESTINO_CADUCA_S = 12 * 3600


def _recordar_destino(request, tipo: str, pk: int) -> None:
    """Apunta (en la sesión) qué coche o búsqueda se está tasando: es adónde van los anuncios
    cuando el marcador de coches.net los trae de vuelta, aunque se cambien los filtros allí."""
    request.session["tasar_destino"] = {"tipo": tipo, "id": pk, "ts": time.time()}


def _destino_recordado(request):
    """El objeto (Valoracion o BusquedaOportunidad) recordado, o None si no hay o ha caducado."""
    d = request.session.get("tasar_destino") or {}
    if time.time() - d.get("ts", 0) > DESTINO_CADUCA_S:
        return None
    return _resolver_destino(d.get("tipo"), d.get("id"))


def _resolver_destino(tipo, pk):
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        return None
    if tipo == "valoracion":
        return models.Valoracion.objects.select_related("vehiculo", "sesion_subasta").filter(pk=pk).first()
    if tipo == "busqueda":
        return models.BusquedaOportunidad.objects.filter(pk=pk).first()
    return None


def _opciones_destino():
    """Los coches y búsquedas entre los que elegir cuando no se sabe de cuál son los anuncios."""
    opciones = []
    vistos = set()
    recientes = models.Valoracion.objects.select_related("vehiculo").order_by("-updated_at")[:40]
    for v in recientes:
        if v.vehiculo_id in vistos or len(vistos) >= 15:
            continue
        vistos.add(v.vehiculo_id)
        veh = v.vehiculo
        nombre = " ".join(x for x in (veh.marca, veh.modelo, veh.version) if x)
        km = v.kilometros or veh.km_ultimo_conocido
        opciones.append({"valor": f"valoracion:{v.pk}", "texto": f"Coche · {nombre}" + (f" · {km:,} km".replace(",", ".") if km else "")})
    for b in models.BusquedaOportunidad.objects.filter(activa=True):
        opciones.append({"valor": f"busqueda:{b.pk}", "texto": f"Búsqueda de oportunidades · {b.nombre}"})
    return opciones


def _descuento_de(request):
    try:
        d = Decimal(request.POST.get("descuento", "").replace(",", ".") or tasacion_mercado.DESCUENTO_NEGOCIACION_DEFECTO)
        if not (Decimal("0") <= d <= Decimal("30")):
            raise InvalidOperation
        return d
    except InvalidOperation:
        return None


@login_required
def valoracion_tasar(request, pk):
    """Tasador de mercado de UN coche de la rejilla: abre coches.net ya filtrado, recibe los
    anuncios (por el marcador o pegados) y enseña el precio de venta sugerido."""
    v = get_object_or_404(models.Valoracion.objects.select_related("vehiculo", "sesion_subasta"), pk=pk)
    if request.method == "POST":
        descuento = _descuento_de(request)
        if descuento is None:
            messages.error(request, "El descuento de negociación debe ser un número entre 0 y 30.")
            return redirect("valoracion_tasar", pk=v.pk)
        usar_ia = request.POST.get("usar_ia") == "on" and tasacion_mercado.clave_disponible()
        t = tasacion_mercado.tasar(
            v, request.POST.get("anuncios", ""), descuento_pct=descuento, usuario=request.user, usar_ia=usar_ia
        )
        return redirect("tasacion_detalle", pk=t.pk)
    _recordar_destino(request, "valoracion", v.pk)
    ref = tasacion_mercado.referencia_de_valoracion(v)
    url_sugerida = tasacion_mercado.url_busqueda_cochesnet(ref, v.pk)
    return render(
        request,
        "tasador/valoracion_tasar.html",
        {
            "v": v, "ref": ref,
            "url_cochesnet": v.vehiculo.url_busqueda_cochesnet or url_sugerida,
            "url_guardada": v.vehiculo.url_busqueda_cochesnet,
            "snippet_js": tasacion_mercado.SNIPPET_JS,
            "snippet_cargador": tasacion_mercado.SNIPPET_CARGADOR,
            "ia_disponible": tasacion_mercado.clave_disponible(),
            "descuento_defecto": tasacion_mercado.DESCUENTO_NEGOCIACION_DEFECTO,
            "tasaciones": list(v.vehiculo.tasaciones_mercado.all()[:5]),
        },
    )


@login_required
def valoracion_tasar_recibir(request, pk):
    """Página puente: el marcador de coches.net manda aquí los anuncios en la parte # de la
    dirección (no viaja al servidor); un pequeño script los envía a ``valoracion_tasar``."""
    v = get_object_or_404(models.Valoracion.objects.select_related("vehiculo"), pk=pk)
    return render(
        request, "tasador/tasacion_recibir.html",
        {"action": reverse("valoracion_tasar", args=[v.pk]), "nombre": f"{v.vehiculo.marca} {v.vehiculo.modelo}",
         "descuento_defecto": tasacion_mercado.DESCUENTO_NEGOCIACION_DEFECTO,
         "usar_ia": tasacion_mercado.clave_disponible(), "volver": reverse("valoracion_tasar", args=[v.pk])},
    )


@login_required
def tasar_recibir(request):
    """Adónde lleva el marcador los anuncios de coches.net (vienen en la parte # de la dirección,
    que no viaja al servidor). Un pequeño script los envía a ``tasar_enviar``."""
    destino = _destino_recordado(request)
    nombre = None
    if destino is not None:
        nombre = tasacion_mercado.referencia_de_valoracion(destino).nombre if isinstance(destino, models.Valoracion) else destino.nombre
    return render(
        request, "tasador/tasacion_recibir.html",
        {"action": reverse("tasar_enviar"), "nombre": nombre, "descuento_defecto": tasacion_mercado.DESCUENTO_NEGOCIACION_DEFECTO,
         "usar_ia": tasacion_mercado.clave_disponible(), "volver": reverse("oportunidades_lista")},
    )


@login_required
@require_POST
def tasar_enviar(request):
    """Recibe los anuncios del marcador y los tasa para el coche/búsqueda recordado. Si no se sabe
    de cuál son, pregunta (y no pierde los anuncios)."""
    anuncios = request.POST.get("anuncios", "")
    descuento = _descuento_de(request)
    if descuento is None:
        messages.error(request, "El descuento de negociación debe ser un número entre 0 y 30.")
        return redirect("oportunidades_lista")
    elegido = request.POST.get("destino", "")
    destino = None
    if elegido:
        tipo, _, pk = elegido.partition(":")
        destino = _resolver_destino(tipo, pk)
    if destino is None and not elegido:
        destino = _destino_recordado(request)
    if destino is None:
        return render(
            request, "tasador/tasar_elegir.html",
            {"anuncios": anuncios, "descuento": descuento, "usar_ia": request.POST.get("usar_ia") == "on",
             "opciones": _opciones_destino(), "equivocado": bool(elegido),
             "n_anuncios": anuncios.count('"precio"')},
        )
    usar_ia = request.POST.get("usar_ia") == "on" and tasacion_mercado.clave_disponible()
    t = tasacion_mercado.tasar(destino, anuncios, descuento_pct=descuento, usuario=request.user, usar_ia=usar_ia)
    return redirect("tasacion_detalle", pk=t.pk)


@login_required
@require_POST
def valoracion_url_busqueda(request, pk):
    """Guarda (o quita) la búsqueda de coches.net que la persona prefiere para tasar este coche."""
    v = get_object_or_404(models.Valoracion.objects.select_related("vehiculo"), pk=pk)
    entrada = request.POST.get("url", "").strip()
    if not entrada:
        v.vehiculo.url_busqueda_cochesnet = ""
        messages.success(request, "Listo: se usará la búsqueda sugerida por la app.")
    else:
        url = tasacion_mercado.url_valida_cochesnet(entrada)
        if not url:
            messages.error(request, "Eso no parece una búsqueda de coches.net (debe empezar por https://www.coches.net/).")
            return redirect("valoracion_tasar", pk=v.pk)
        v.vehiculo.url_busqueda_cochesnet = url
        messages.success(request, "Guardada: «Abrir coches.net» usará tu búsqueda para este coche.")
    v.vehiculo.save(update_fields=["url_busqueda_cochesnet"])
    return redirect("valoracion_tasar", pk=v.pk)


def marcador_js(request):
    """El código del marcador, siempre en su última versión. Lo carga el marcador instalado desde
    la página de coches.net. Es público (no lleva nada secreto: solo el código) y no se cachea."""
    r = HttpResponse(tasacion_mercado.codigo_para_la_app(), content_type="application/javascript; charset=utf-8")
    r["Cache-Control"] = "no-store"
    r["Access-Control-Allow-Origin"] = "*"
    return r


@login_required
@require_POST
def valoracion_acabado(request, pk):
    """Guarda el acabado que deben llevar los anuncios comparables de este coche (vacío = cualquiera)."""
    v = get_object_or_404(models.Valoracion.objects.select_related("vehiculo"), pk=pk)
    v.vehiculo.acabado = " ".join(request.POST.get("acabado", "").split())[:40]
    v.vehiculo.save(update_fields=["acabado"])
    messages.success(
        request,
        f"Acabado guardado: solo se usarán anuncios cuyo título lleve «{v.vehiculo.acabado}»."
        if v.vehiculo.acabado else "Acabado quitado: se usarán anuncios de cualquier acabado.",
    )
    return redirect("valoracion_tasar", pk=v.pk)
