"""Tasación IA: del formulario revisado al coche en la rejilla."""
from __future__ import annotations

import time

from .services_fichas import crear_coche_en_rejilla

PROVEEDOR = "Tasación IA"


def crear_desde_formulario(datos: dict, usuario=None):
    """``datos``: el ``cleaned_data`` de ``DatosCocheForm``. Devuelve (valoracion, era_reimportacion)."""
    observaciones = (datos.get("observaciones") or "").strip()
    avisos = [a.strip() for a in (datos.get("avisos") or "").split("\n") if a.strip()]
    if avisos and datos.get("origen") != "nayox" and "⚠" not in observaciones:
        observaciones = "\n".join(f"⚠ {a}" for a in avisos) + ("\n" + observaciones if observaciones else "")
    return crear_coche_en_rejilla(
        proveedor=PROVEEDOR, ubicacion=PROVEEDOR,
        referencia="IA-" + time.strftime("%y%m%d%H%M%S"),
        marca=datos["marca"], modelo=datos["modelo"], version=datos.get("version") or "", acabado=datos.get("acabado") or "",
        anio=datos.get("anio") or (datos["fecha_matriculacion"].year if datos.get("fecha_matriculacion") else None),
        fecha_matriculacion=datos.get("fecha_matriculacion"), km=datos["km"],
        combustible=datos.get("combustible") or "", cambio=datos.get("cambio") or "",
        potencia_cv=datos.get("potencia_cv"), matricula=datos.get("matricula") or "", vin=datos.get("vin") or "",
        precio_compra=datos.get("precio_compra"), observaciones=observaciones,
        carroceria_sin_danos=bool(datos.get("carroceria_sin_danos")), usuario=usuario,
    )
