"""Modelo de datos del tasador.

Distinción central: ``Vehiculo`` es el coche físico; ``Valoracion`` es cada vez
que se tasa. Un vehículo tiene muchas valoraciones (retasaciones cuando vuelve a
subasta). Las tarifas se versionan por fecha y cada valoración guarda una copia
de los importes usados, de modo que cambiar una tarifa no altera lo anterior.
"""
from __future__ import annotations

from datetime import time
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

DEC = dict(max_digits=12, decimal_places=2)


class Combustible(models.TextChoices):
    GASOLINA = "gasolina", "Gasolina"
    DIESEL = "diesel", "Diésel"
    HIBRIDO = "hibrido", "Híbrido"
    HIBRIDO_ENCHUFABLE = "phev", "Híbrido enchufable"
    ELECTRICO = "electrico", "Eléctrico"
    GLP = "glp", "GLP"
    OTRO = "otro", "Otro"


class Cambio(models.TextChoices):
    MANUAL = "manual", "Manual"
    AUTOMATICO = "automatico", "Automático"


class RegimenFiscal(models.TextChoices):
    REBU = "rebu", "REBU (margen)"
    GENERAL = "general", "IVA general"


class BaseMargen(models.TextChoices):
    ADQUISICION = "adquisicion", "Venta − (adjudicación + comisión + gestión)"
    ADJUDICACION = "adjudicacion", "Venta − adjudicación"


# ---------------------------------------------------------------------------
# Configuración: proveedores y tarifas
# ---------------------------------------------------------------------------
class Proveedor(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    activo = models.BooleanField(default=True)
    base_margen_rebu = models.CharField(
        max_length=20,
        choices=BaseMargen.choices,
        default=BaseMargen.ADQUISICION,
        help_text="Qué se resta a la venta para calcular el margen REBU.",
    )
    notas = models.TextField(blank=True)

    class Meta:
        verbose_name = "proveedor"
        verbose_name_plural = "proveedores"
        ordering = ["nombre"]

    def __str__(self) -> str:
        return self.nombre


class Ubicacion(models.Model):
    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.CASCADE, related_name="ubicaciones"
    )
    nombre = models.CharField(max_length=80)  # "BCA Madrid"
    provincia = models.CharField(max_length=60, blank=True)
    zona = models.CharField(max_length=60, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "ubicación"
        verbose_name_plural = "ubicaciones"
        ordering = ["proveedor", "nombre"]
        unique_together = [("proveedor", "nombre")]

    def __str__(self) -> str:
        return self.nombre


class TipoSubasta(models.Model):
    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.CASCADE, related_name="tipos_subasta"
    )
    nombre = models.CharField(max_length=60)  # "BCA normal", "Concurso BCA"
    usa_tabla_comision = models.BooleanField(default=True)
    cuota_plana = models.DecimalField(
        **DEC, null=True, blank=True,
        help_text="Si se rellena, ignora la tabla y los conceptos fijos "
        "(p. ej. Concurso BCA = 351 €).",
    )
    aplica_conceptos_fijos = models.BooleanField(default=True)
    es_predeterminado = models.BooleanField(default=False)

    class Meta:
        verbose_name = "tipo de subasta"
        verbose_name_plural = "tipos de subasta"
        ordering = ["proveedor", "nombre"]
        unique_together = [("proveedor", "nombre")]

    def __str__(self) -> str:
        return f"{self.proveedor} · {self.nombre}"


class TarifaComision(models.Model):
    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.CASCADE, related_name="tarifas_comision"
    )
    tipo_vehiculo = models.CharField(max_length=40, default="Otros")
    vigencia_desde = models.DateField(null=True, blank=True)
    vigencia_hasta = models.DateField(null=True, blank=True)
    iva = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.21"))
    notas = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "tarifa de comisión"
        verbose_name_plural = "tarifas de comisión"
        ordering = ["proveedor", "-vigencia_desde"]

    def __str__(self) -> str:
        desde = self.vigencia_desde.isoformat() if self.vigencia_desde else "inicio"
        return f"{self.proveedor} · {self.tipo_vehiculo} (desde {desde})"

    @property
    def vigente(self) -> bool:
        hoy = timezone.localdate()
        if self.vigencia_desde and hoy < self.vigencia_desde:
            return False
        if self.vigencia_hasta and hoy > self.vigencia_hasta:
            return False
        return True

    def validar_tramos(self) -> list[str]:
        """Comprueba que los tramos cubren [0, ∞) sin huecos ni solapes."""
        errores: list[str] = []
        tramos = list(self.tramos.order_by("importe_desde"))
        if not tramos:
            return ["La tarifa no tiene tramos."]
        if tramos[0].importe_desde != Decimal("0"):
            errores.append("El primer tramo debe empezar en 0.")
        for anterior, siguiente in zip(tramos, tramos[1:]):
            if anterior.importe_hasta is None:
                errores.append("Solo el último tramo puede no tener límite superior.")
                continue
            hueco = siguiente.importe_desde - anterior.importe_hasta
            if hueco > Decimal("1"):
                errores.append(
                    f"Hueco entre {anterior.importe_hasta} y {siguiente.importe_desde}."
                )
            if siguiente.importe_desde <= anterior.importe_hasta:
                errores.append(
                    f"Solape en {siguiente.importe_desde}."
                )
        if tramos[-1].importe_hasta is not None:
            errores.append("El último tramo debe no tener límite superior.")
        return errores


class TramoComision(models.Model):
    tarifa = models.ForeignKey(
        TarifaComision, on_delete=models.CASCADE, related_name="tramos"
    )
    importe_desde = models.DecimalField(**DEC)
    importe_hasta = models.DecimalField(**DEC, null=True, blank=True)
    cuota_fija = models.DecimalField(**DEC, default=Decimal("0"))
    porcentaje = models.DecimalField(
        max_digits=6, decimal_places=3, default=Decimal("0"),
        help_text="2,60 % se escribe 2.600",
    )
    aplica_iva = models.BooleanField(default=True)

    class Meta:
        verbose_name = "tramo de comisión"
        verbose_name_plural = "tramos de comisión"
        ordering = ["tarifa", "importe_desde"]

    def __str__(self) -> str:
        hasta = self.importe_hasta if self.importe_hasta is not None else "∞"
        return f"{self.importe_desde}–{hasta}"


class ConceptoFijo(models.Model):
    """Honorarios, tasas y demás importes fijos de una compra (p. ej. BCA)."""

    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.CASCADE, related_name="conceptos_fijos"
    )
    nombre = models.CharField(max_length=80)
    importe = models.DecimalField(**DEC, help_text="Importe final (con IVA si lo lleva).")
    vigencia_desde = models.DateField(null=True, blank=True)
    vigencia_hasta = models.DateField(null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "concepto fijo"
        verbose_name_plural = "conceptos fijos"
        ordering = ["proveedor", "nombre"]

    def __str__(self) -> str:
        return f"{self.nombre}: {self.importe} €"


class TarifaTransporte(models.Model):
    """Coste de traer el coche desde una zona de origen (versionado)."""

    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.CASCADE, related_name="tarifas_transporte"
    )
    origen = models.CharField(max_length=60, help_text='Zona: "Madrid", "Barcelona"…')
    precio = models.DecimalField(**DEC, help_text="Importe neto (sin IVA).")
    vigencia_desde = models.DateField(null=True, blank=True)
    vigencia_hasta = models.DateField(null=True, blank=True)
    activa = models.BooleanField(default=True)
    observaciones = models.CharField(max_length=200, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "tarifa de transporte"
        verbose_name_plural = "tarifas de transporte"
        ordering = ["proveedor", "origen"]

    def __str__(self) -> str:
        return f"{self.origen}: {self.precio} €"

    @property
    def vigente(self) -> bool:
        hoy = timezone.localdate()
        if self.vigencia_desde and hoy < self.vigencia_desde:
            return False
        if self.vigencia_hasta and hoy > self.vigencia_hasta:
            return False
        return self.activa


class ParametrosCoste(models.Model):
    """Valores por defecto de los costes de preparación (versionados)."""

    vigencia_desde = models.DateField(default=timezone.localdate)
    comision_alberto = models.DecimalField(**DEC, default=Decimal("50"))
    gasolina = models.DecimalField(**DEC, default=Decimal("40"))
    pintura_por_pieza = models.DecimalField(**DEC, default=Decimal("87"))
    pintura_minima = models.DecimalField(**DEC, default=Decimal("0"))
    garantia = models.DecimalField(**DEC, default=Decimal("225"))
    mecanica = models.DecimalField(**DEC, default=Decimal("200"))
    cambio_titularidad = models.DecimalField(**DEC, default=Decimal("72"))
    transporte = models.DecimalField(**DEC, default=Decimal("350"))
    itv = models.DecimalField(**DEC, default=Decimal("40"))
    tapiceria = models.DecimalField(**DEC, default=Decimal("0"))
    tintado = models.DecimalField(**DEC, default=Decimal("0"))
    history = HistoricalRecords()

    class Meta:
        verbose_name = "parámetros de coste"
        verbose_name_plural = "parámetros de coste"
        ordering = ["-vigencia_desde"]

    def __str__(self) -> str:
        return f"Parámetros desde {self.vigencia_desde.isoformat()}"

    @classmethod
    def vigentes(cls) -> "ParametrosCoste":
        hoy = timezone.localdate()
        obj = cls.objects.filter(vigencia_desde__lte=hoy).order_by("-vigencia_desde").first()
        return obj or cls.objects.order_by("-vigencia_desde").first() or cls()


class EstadoCarroceria(models.Model):
    nombre = models.CharField(max_length=40, unique=True)
    piezas_estimadas = models.PositiveSmallIntegerField(default=4)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "estado de carrocería"
        verbose_name_plural = "estados de carrocería"
        ordering = ["orden", "piezas_estimadas"]

    def __str__(self) -> str:
        return f"{self.nombre} · {self.piezas_estimadas} piezas"


class EscenarioObjetivo(models.Model):
    nombre = models.CharField(max_length=40)
    rentabilidad_objetivo = models.DecimalField(
        max_digits=5, decimal_places=4, help_text="0,15 = 15 %"
    )
    es_principal = models.BooleanField(default=False)
    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "escenario objetivo"
        verbose_name_plural = "escenarios objetivo"
        ordering = ["orden", "-rentabilidad_objetivo"]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.rentabilidad_objetivo:.0%})"


class EstadoValoracion(models.Model):
    nombre = models.CharField(max_length=40, unique=True)
    orden = models.PositiveSmallIntegerField(default=0)
    es_final = models.BooleanField(default=False)
    color = models.CharField(max_length=7, blank=True, default="")

    class Meta:
        verbose_name = "estado de valoración"
        verbose_name_plural = "estados de valoración"
        ordering = ["orden"]

    def __str__(self) -> str:
        return self.nombre


# ---------------------------------------------------------------------------
# Núcleo
# ---------------------------------------------------------------------------
class SesionSubasta(models.Model):
    class Estado(models.TextChoices):
        PREVISTA = "prevista", "Prevista"
        EN_CURSO = "en_curso", "En curso"
        FINALIZADA = "finalizada", "Finalizada"

    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT)
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT)
    fecha = models.DateField()
    hora_inicio = models.TimeField(default=time(10, 0))
    hora_fin = models.TimeField(default=time(14, 0))
    identificador_venta = models.CharField(max_length=40, blank=True)
    url = models.URLField(blank=True)
    estado = models.CharField(
        max_length=12, choices=Estado.choices, default=Estado.PREVISTA
    )
    notas = models.TextField(blank=True)
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "sesión de subasta"
        verbose_name_plural = "sesiones de subasta"
        ordering = ["-fecha", "ubicacion__nombre"]

    def __str__(self) -> str:
        return f"{self.ubicacion} · {self.fecha.isoformat()}"

    @property
    def lotes_interesantes(self):
        return self.valoraciones.filter(estado__es_final=False)


class Vehiculo(models.Model):
    matricula = models.CharField(max_length=15, blank=True, db_index=True)
    bastidor = models.CharField("bastidor (VIN)", max_length=25, blank=True, db_index=True)
    marca = models.CharField(max_length=40, blank=True)
    modelo = models.CharField(max_length=80, blank=True)
    version = models.CharField(max_length=120, blank=True)
    potencia_kw = models.PositiveSmallIntegerField(null=True, blank=True)
    potencia_cv = models.PositiveSmallIntegerField(null=True, blank=True)
    combustible = models.CharField(
        max_length=12, choices=Combustible.choices, blank=True
    )
    cambio = models.CharField(max_length=12, choices=Cambio.choices, blank=True)
    fecha_primera_matriculacion = models.DateField(null=True, blank=True)
    anio = models.PositiveSmallIntegerField(null=True, blank=True)
    km_ultimo_conocido = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "vehículo"
        verbose_name_plural = "vehículos"
        ordering = ["marca", "modelo"]

    def __str__(self) -> str:
        nombre = " ".join(x for x in [self.marca, self.modelo] if x)
        return f"{nombre or 'Vehículo'} · {self.matricula or 's/matrícula'}"

    @property
    def numero_valoraciones(self) -> int:
        return self.valoraciones.count()


class Valoracion(models.Model):
    vehiculo = models.ForeignKey(
        Vehiculo, on_delete=models.PROTECT, related_name="valoraciones"
    )
    valoracion_anterior = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="retasaciones",
    )
    sesion_subasta = models.ForeignKey(
        SesionSubasta, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="valoraciones",
    )
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT)
    tipo_subasta = models.ForeignKey(TipoSubasta, on_delete=models.PROTECT)
    ubicacion = models.ForeignKey(
        Ubicacion, on_delete=models.SET_NULL, null=True, blank=True
    )
    lote_id = models.CharField(max_length=20, blank=True)
    orden_lote = models.PositiveIntegerField(null=True, blank=True)
    url_anuncio = models.URLField(blank=True)
    zona_origen = models.CharField(
        max_length=60, blank=True,
        help_text="Ciudad/zona donde está físicamente el coche (para el transporte).",
    )

    fecha_valoracion = models.DateField(default=timezone.localdate)
    fecha_subasta = models.DateField(null=True, blank=True)
    kilometros = models.PositiveIntegerField(null=True, blank=True)

    regimen_fiscal = models.CharField(
        max_length=10, choices=RegimenFiscal.choices, default=RegimenFiscal.REBU
    )
    precio_venta_estimado = models.DecimalField(**DEC)
    precio_anunciado = models.DecimalField(**DEC, null=True, blank=True)

    estado_carroceria = models.ForeignKey(
        EstadoCarroceria, on_delete=models.SET_NULL, null=True, blank=True
    )
    piezas_pintura = models.PositiveSmallIntegerField(default=4)
    descuento_comision_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0")
    )

    # Copia de los costes de preparación en el momento de valorar (netos).
    coste_alberto = models.DecimalField(**DEC, default=Decimal("50"))
    coste_gasolina = models.DecimalField(**DEC, default=Decimal("40"))
    coste_pintura_por_pieza = models.DecimalField(**DEC, default=Decimal("87"))
    coste_garantia = models.DecimalField(**DEC, default=Decimal("225"))
    coste_mecanica = models.DecimalField(**DEC, default=Decimal("200"))
    coste_cambio_titularidad = models.DecimalField(**DEC, default=Decimal("72"))
    coste_transporte = models.DecimalField(**DEC, default=Decimal("350"))
    coste_itv = models.DecimalField(**DEC, default=Decimal("0"))
    coste_tapiceria = models.DecimalField(**DEC, default=Decimal("0"))
    coste_tintado = models.DecimalField(**DEC, default=Decimal("0"))
    coste_otros = models.DecimalField(**DEC, default=Decimal("0"))

    tarifa_comision_aplicada = models.ForeignKey(
        TarifaComision, on_delete=models.SET_NULL, null=True, blank=True
    )

    puja_realizada = models.DecimalField(**DEC, null=True, blank=True)
    estado = models.ForeignKey(EstadoValoracion, on_delete=models.PROTECT)
    observaciones = models.TextField(blank=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    # Resultados calculados (snapshot).
    r_gastos_preparacion = models.DecimalField(**DEC, default=Decimal("0"))
    r_coste_adquisicion = models.DecimalField(**DEC, default=Decimal("0"))
    r_coste_total = models.DecimalField(**DEC, default=Decimal("0"))
    r_iva_rebu = models.DecimalField(**DEC, default=Decimal("0"))
    r_beneficio_neto = models.DecimalField(**DEC, default=Decimal("0"))
    r_rentabilidad_coste = models.DecimalField(
        max_digits=7, decimal_places=4, default=Decimal("0")
    )
    r_margen_venta = models.DecimalField(
        max_digits=7, decimal_places=4, default=Decimal("0")
    )
    r_puja_maxima_principal = models.DecimalField(**DEC, null=True, blank=True)
    r_escenarios = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "valoración"
        verbose_name_plural = "valoraciones"
        ordering = ["-fecha_valoracion", "-created_at"]

    def __str__(self) -> str:
        return f"{self.vehiculo} · {self.fecha_valoracion.isoformat()}"

    def clean(self) -> None:
        if self.precio_venta_estimado is not None and self.precio_venta_estimado < 0:
            raise ValidationError("El precio de venta no puede ser negativo.")
