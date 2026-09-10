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
        v = (
            Vehiculo.objects.filter(
                marca__iexact=marca, modelo__iexact=modelo, anio=anio
            )
            .first()
        )
        if v:
            return v
    return None
