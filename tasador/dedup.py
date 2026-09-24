"""Detección de vehículos ya conocidos (retasaciones)."""
from __future__ import annotations

from .models import Valoracion, Vehiculo


def buscar_vehiculo_similar(
    *,
    matricula: str = "",
    bastidor: str = "",
    referencia: str = "",
    marca: str = "",
    modelo: str = "",
    anio: int | None = None,
    km: int | None = None,
) -> Vehiculo | None:
    matricula = (matricula or "").strip().upper().replace(" ", "")
    bastidor = (bastidor or "").strip().upper()
    referencia = (referencia or "").strip()

    if matricula:
        v = Vehiculo.objects.filter(matricula__iexact=matricula).first()
        if v:
            return v
    if bastidor:
        v = Vehiculo.objects.filter(bastidor__iexact=bastidor).first()
        if v:
            return v
    if referencia:
        # Auto1 no da matrícula: el código de referencia del anuncio es el
        # identificador fiable de "mismo coche" entre escaneos. Se excluyen
        # coches con matrícula para no colgarse de uno de BCA por una
        # coincidencia de texto con su lote.
        anterior = (
            Valoracion.objects.filter(lote_id=referencia, vehiculo__matricula="")
            .select_related("vehiculo")
            .order_by("-created_at")
            .first()
        )
        if anterior:
            return anterior.vehiculo
    if marca and modelo and anio:
        qs = Vehiculo.objects.filter(
            marca__iexact=marca, modelo__iexact=modelo, anio=anio
        )
        # No cruzar entre coches con matrícula real (BCA) y sin ella (Auto1):
        # aunque coincidan marca/modelo/año/km, son de proveedores distintos.
        qs = qs.filter(matricula="") if not matricula else qs.exclude(matricula="")
        if km:
            # mismo coche si los km están dentro de ±5 % (o ±2.000)
            margen = max(int(km * 0.05), 2000)
            qs_km = qs.filter(
                km_ultimo_conocido__gte=km - margen,
                km_ultimo_conocido__lte=km + margen,
            )
            if qs_km.exists():
                return qs_km.first()
            if qs.filter(km_ultimo_conocido__isnull=True).exists():
                return qs.filter(km_ultimo_conocido__isnull=True).first()
            return None
        v = qs.first()
        if v:
            return v
    return None
