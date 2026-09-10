"""Detección de vehículos ya conocidos (retasaciones)."""
from __future__ import annotations

from .models import Vehiculo


def buscar_vehiculo_similar(
    *,
    matricula: str = "",
    bastidor: str = "",
    marca: str = "",
    modelo: str = "",
    anio: int | None = None,
    km: int | None = None,
) -> Vehiculo | None:
    matricula = (matricula or "").strip().upper().replace(" ", "")
    bastidor = (bastidor or "").strip().upper()

    if matricula:
        v = Vehiculo.objects.filter(matricula__iexact=matricula).first()
        if v:
            return v
    if bastidor:
        v = Vehiculo.objects.filter(bastidor__iexact=bastidor).first()
        if v:
            return v
    if marca and modelo and anio:
        qs = Vehiculo.objects.filter(
            marca__iexact=marca, modelo__iexact=modelo, anio=anio
        )
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
