"""Crear un coche en la rejilla a partir de sus datos (Nayox, Tasación IA…).

Lo comparten los proveedores que no subastan por días ni dan precio en una lista:
la ficha/texto da los datos del coche y la rejilla calcula la puja máxima en cuanto
hay un precio de venta (que sale de tasarlo). Si se conoce el precio de compra, se usa
para ver si compensa.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from . import services
from .models import EstadoCarroceria, Proveedor, Valoracion
from .parser import LoteParseado


class FichaError(Exception):
    """Algo que se le puede explicar a la persona (no un fallo del programa)."""


def capitalizar(texto: str) -> str:
    """CUPRA -> Cupra, SERIE 3 -> Serie 3; las siglas cortas (BMW, GTI, A3) se quedan como están."""
    palabras = []
    for p in " ".join((texto or "").split()).split(" "):
        palabras.append(p.capitalize() if p.isupper() and len(p) > 3 and p.isalpha() else p)
    return " ".join(palabras)


def crear_coche_en_rejilla(
    *,
    proveedor: str,
    ubicacion: str,
    referencia: str,
    marca: str,
    modelo: str,
    version: str = "",
    acabado: str = "",
    anio: int | None = None,
    fecha_matriculacion: date | None = None,
    km: int | None = None,
    combustible: str = "",
    cambio: str = "",
    potencia_kw: int | None = None,
    potencia_cv: int | None = None,
    matricula: str = "",
    vin: str = "",
    precio_compra: int | Decimal | None = None,
    observaciones: str = "",
    carroceria_sin_danos: bool = False,
    usuario=None,
) -> tuple[Valoracion, bool]:
    """Crea (o actualiza, si ya estaba por su matrícula o referencia) el coche y su valoración.

    ``referencia`` identifica el coche en su proveedor (expediente, código…) y evita que dos coches
    parecidos sin matrícula se confundan. Devuelve (valoración, era_reimportación)."""
    if not Proveedor.objects.filter(nombre=proveedor).exists():
        raise FichaError(f"El proveedor {proveedor} no está configurado (ejecuta seed_datos).")
    sesion = services.sesion_continua(proveedor, ubicacion, usuario)
    lote = LoteParseado(
        texto_original=f"{proveedor} {referencia}",
        formato="ficha",
        lote=referencia[:20],
        referencia=referencia[:20],
        precio_subasta=int(precio_compra) if precio_compra else None,
        marca=capitalizar(marca),
        modelo=capitalizar(modelo),
        version=version[:120],
        potencia_kw=potencia_kw,
        potencia_cv=potencia_cv,
        combustible=combustible,
        cambio=cambio,
        kilometros=km,
        anio=anio,
        matricula=(matricula or "").upper().replace(" ", ""),
        fecha_matriculacion=fecha_matriculacion.isoformat() if fecha_matriculacion else "",
    )
    v, reimportada = services.crear_valoracion_desde_lote(lote, sesion, usuario=usuario)

    veh = v.vehiculo
    veh.bastidor = vin or veh.bastidor
    veh.version = veh.version or version[:120]
    veh.acabado = veh.acabado or acabado
    veh.potencia_cv = veh.potencia_cv or potencia_cv
    veh.potencia_kw = veh.potencia_kw or potencia_kw
    veh.save()

    v.kilometros = km
    if precio_compra:
        v.precio_salida = Decimal(precio_compra)
    if not reimportada and carroceria_sin_danos:
        # sin daños de carrocería declarados: el estado de menos pintura
        muy_bueno = EstadoCarroceria.objects.filter(nombre="Muy buen estado").first()
        if muy_bueno:
            v.estado_carroceria = muy_bueno
            v.piezas_pintura = muy_bueno.piezas_estimadas
    v.observaciones = observaciones
    services.recalcular_y_guardar(v)
    return v, reimportada
