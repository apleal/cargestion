"""Nayox: de la ficha de inspección (PDF) al coche y su valoración en la rejilla."""
from __future__ import annotations

from datetime import date

from . import services_fichas
from .models import Valoracion
from .nayox import FichaNayox, NayoxError


def _si_no(valor: bool | None) -> str:
    return {True: "sí", False: "no"}.get(valor, "?")


def observaciones_de(f: FichaNayox, hoy: date | None = None) -> str:
    """Lo importante de la ficha, para tenerlo a mano en la ficha de costes."""
    lineas = [f"Nayox · expediente {f.expediente}" + (f" · VIN {f.vin}" if f.vin else "")]
    for aviso in f.avisos(hoy):
        lineas.append(f"⚠ {aviso}")
    datos = []
    if f.primera_mano is not None:
        datos.append(f"primera mano: {_si_no(f.primera_mano)}")
    if f.adquirido_en:
        datos.append(f"adquirido en {f.adquirido_en.lower()}")
    if f.uso:
        datos.append(f.uso.lower())
    if f.mantenimiento:
        datos.append(f"mantenimiento {f.mantenimiento.lower()}" + (" en red oficial" if f.mantenimiento_red_oficial else ""))
    if f.proxima_itv:
        datos.append(f"próxima ITV {f.proxima_itv:%d/%m/%Y}")
    if f.accidentado is not None:
        datos.append(f"accidentado: {_si_no(f.accidentado)}")
    if f.color:
        datos.append(f"color {f.color.lower()}" + (" metalizado" if f.pintura_metalizada else ""))
    if datos:
        texto = "; ".join(datos)
        lineas.append(texto[0].upper() + texto[1:] + ".")
    if f.danos_carroceria:
        lineas.append(f"Carrocería: {f.danos_carroceria}.")
    if f.equipamiento:
        lineas.append("Equipamiento: " + ", ".join(f.equipamiento) + ".")
    return "\n".join(lineas)


def importar_ficha(f: FichaNayox, usuario=None, hoy: date | None = None) -> tuple[Valoracion, bool]:
    """Crea (o actualiza, si ya estaba por su matrícula) el coche y su valoración de Nayox.

    No hay precio de compra en la ficha: queda en 0 y la rejilla calcula la puja máxima en cuanto
    haya un precio de venta (que sale de tasar el coche). Devuelve (valoración, era_reimportación)."""
    try:
        return services_fichas.crear_coche_en_rejilla(
            proveedor="Nayox", ubicacion="Nayox", referencia=f.expediente or f.matricula or f.vin,
            marca=f.marca, modelo=f.modelo, version=f.version, acabado=f.acabado,
            anio=f.anio, fecha_matriculacion=f.fecha_matriculacion, km=f.km,
            combustible=f.combustible, cambio=f.cambio, potencia_kw=f.potencia_kw, potencia_cv=f.potencia_cv,
            matricula=f.matricula, vin=f.vin, observaciones=observaciones_de(f, hoy),
            carroceria_sin_danos=f.carroceria_sin_danos, usuario=usuario,
        )
    except services_fichas.FichaError as e:
        raise NayoxError(str(e)) from e
