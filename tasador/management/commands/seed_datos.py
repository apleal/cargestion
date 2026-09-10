"""Carga los datos iniciales: BCA, su tarifa de comisión, estados y escenarios.

Idempotente: se puede ejecutar varias veces sin duplicar nada.

    python manage.py seed_datos
"""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from calculo.datos_bca import (
    CUOTA_CONCURSO_BCA,
    GESTION_CON_IVA,
    TASA_DGT,
    TRAMOS_BCA_OTROS,
)
from tasador.models import (
    ConceptoFijo,
    EscenarioObjetivo,
    EstadoCarroceria,
    EstadoValoracion,
    Proveedor,
    TarifaComision,
    TarifaTransporte,
    TipoSubasta,
    TramoComision,
    Ubicacion,
)

ESTADOS_VALORACION = [
    ("Pendiente de valorar", 10, False),
    ("Interesante", 20, False),
    ("Descartado", 30, True),
    ("Pendiente de subasta", 40, False),
    ("Pujado", 50, False),
    ("No adjudicado", 60, True),
    ("Adjudicado", 70, False),
    ("En preparación", 80, False),
    ("Publicado", 90, False),
    ("Vendido", 100, True),
    ("Cancelado", 110, True),
]

ESTADOS_CARROCERIA = [
    ("Muy buen estado", 2, 10),
    ("Estado normal", 4, 20),
    ("Desgastado", 6, 30),
    ("Mal estado", 10, 40),
]

ESCENARIOS = [
    ("Objetivo", Decimal("0.15"), True, 10),
    ("Ajustado", Decimal("0.12"), False, 20),
    ("Mínimo", Decimal("0.10"), False, 30),
]

UBICACIONES_BCA = [
    ("BCA Madrid", "Madrid"),
    ("BCA Barcelona", "Barcelona"),
    ("BCA Sevilla", "Sevilla"),
    ("BCA Alicante", "Alicante"),
    ("BCA Valencia", "Valencia"),
    ("BCA Online", ""),
]

# Precios de EJEMPLO. Ajústalos en Configuración -> Tarifas de transporte.
TRANSPORTE_BCA = [
    ("Madrid", 350),
    ("Barcelona", 350),
    ("Valencia", 350),
    ("Sevilla", 450),
    ("Alicante", 380),
    ("Otras", 450),
]


class Command(BaseCommand):
    help = "Carga los datos iniciales (BCA, tarifas, estados, escenarios)."

    @transaction.atomic
    def handle(self, *args, **options):
        for nombre, orden, final in ESTADOS_VALORACION:
            EstadoValoracion.objects.update_or_create(
                nombre=nombre, defaults={"orden": orden, "es_final": final}
            )
        for nombre, piezas, orden in ESTADOS_CARROCERIA:
            EstadoCarroceria.objects.update_or_create(
                nombre=nombre,
                defaults={"piezas_estimadas": piezas, "orden": orden},
            )
        for nombre, obj, principal, orden in ESCENARIOS:
            EscenarioObjetivo.objects.update_or_create(
                nombre=nombre,
                defaults={
                    "rentabilidad_objetivo": obj,
                    "es_principal": principal,
                    "orden": orden,
                    "activo": True,
                },
            )

        bca, _ = Proveedor.objects.update_or_create(
            nombre="BCA",
            defaults={"activo": True, "notas": "BCA España Autosubastas de Vehículos SL"},
        )

        for nombre, provincia in UBICACIONES_BCA:
            Ubicacion.objects.update_or_create(
                proveedor=bca, nombre=nombre, defaults={"provincia": provincia}
            )

        TipoSubasta.objects.update_or_create(
            proveedor=bca,
            nombre="BCA normal",
            defaults={
                "usa_tabla_comision": True,
                "aplica_conceptos_fijos": True,
                "es_predeterminado": True,
            },
        )
        TipoSubasta.objects.update_or_create(
            proveedor=bca,
            nombre="Concurso BCA",
            defaults={
                "usa_tabla_comision": False,
                "aplica_conceptos_fijos": False,
                "cuota_plana": CUOTA_CONCURSO_BCA,
                "es_predeterminado": False,
            },
        )

        ConceptoFijo.objects.update_or_create(
            proveedor=bca,
            nombre="Honorarios de transferencia (con IVA)",
            defaults={"importe": GESTION_CON_IVA},
        )
        ConceptoFijo.objects.update_or_create(
            proveedor=bca,
            nombre="Tasa de transferencia (DGT, no sujeta)",
            defaults={"importe": TASA_DGT},
        )

        for origen, precio in TRANSPORTE_BCA:
            TarifaTransporte.objects.get_or_create(
                proveedor=bca,
                origen=origen,
                vigencia_desde=None,
                defaults={
                    "precio": Decimal(str(precio)),
                    "observaciones": "PRECIO DE EJEMPLO — ajustar",
                },
            )

        tarifa, _ = TarifaComision.objects.get_or_create(
            proveedor=bca,
            tipo_vehiculo="Otros",
            vigencia_desde=None,
            defaults={
                "iva": Decimal("1.21"),
                "notas": "Tarifa pública vigente. Contrastada con facturas de agosto 2026.",
            },
        )
        if not tarifa.tramos.exists():
            for t in TRAMOS_BCA_OTROS:
                TramoComision.objects.create(
                    tarifa=tarifa,
                    importe_desde=t.desde,
                    importe_hasta=t.hasta,
                    cuota_fija=t.cuota_fija,
                    porcentaje=t.porcentaje,
                    aplica_iva=t.aplica_iva,
                )

        errores = tarifa.validar_tramos()
        if errores:
            self.stderr.write(self.style.WARNING("Avisos en la tarifa: " + "; ".join(errores)))

        self.stdout.write(self.style.SUCCESS("Datos iniciales cargados."))
