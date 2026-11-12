"""Nayox: de la ficha de inspección (PDF) al coche y su valoración en la rejilla."""
from __future__ import annotations

from datetime import date

from . import services
from .models import EstadoCarroceria, Proveedor, Valoracion
from .nayox import FichaNayox, NayoxError, _capitalizar
from .parser import LoteParseado


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
    if not Proveedor.objects.filter(nombre="Nayox").exists():
        raise NayoxError("El proveedor Nayox no está configurado (ejecuta seed_datos).")
    sesion = services.sesion_continua("Nayox", "Nayox", usuario)
    lote = LoteParseado(
        texto_original=f"Nayox {f.expediente}",
        formato="nayox",
        lote=f.expediente[:20],
        marca=_capitalizar(f.marca),
        modelo=_capitalizar(f.modelo),
        version=f.version[:120],
        potencia_kw=f.potencia_kw,
        potencia_cv=f.potencia_cv,
        combustible=f.combustible,
        cambio=f.cambio,
        kilometros=f.km,
        anio=f.anio,
        matricula=f.matricula,
        fecha_matriculacion=f.fecha_matriculacion.isoformat() if f.fecha_matriculacion else "",
    )
    v, reimportada = services.crear_valoracion_desde_lote(lote, sesion, usuario=usuario)

    veh = v.vehiculo
    veh.bastidor = f.vin or veh.bastidor
    veh.version = veh.version or f.version[:120]
    veh.acabado = veh.acabado or f.acabado
    veh.potencia_cv = veh.potencia_cv or f.potencia_cv
    veh.potencia_kw = veh.potencia_kw or f.potencia_kw
    veh.save()

    v.kilometros = f.km
    if not reimportada and f.carroceria_sin_danos:
        # sin daños de carrocería declarados: el estado de menos pintura
        muy_bueno = EstadoCarroceria.objects.filter(nombre="Muy buen estado").first()
        if muy_bueno:
            v.estado_carroceria = muy_bueno
            v.piezas_pintura = muy_bueno.piezas_estimadas
    v.observaciones = observaciones_de(f, hoy)
    services.recalcular_y_guardar(v)
    return v, reimportada
