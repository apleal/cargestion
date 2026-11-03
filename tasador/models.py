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
    class Modo(models.TextChoices):
        TABLA = "tabla", "Tabla por tramos (BCA)"
        IVA_ANUNCIO = "iva_anuncio", "IVA del anuncio (Auto1)"

    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.CASCADE, related_name="tipos_subasta"
    )
    nombre = models.CharField(max_length=60)  # "BCA normal", "Concurso BCA", "Auto1"
    modo = models.CharField(max_length=15, choices=Modo.choices, default=Modo.TABLA)
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
    iva_deducible = models.BooleanField(
        default=False,
        help_text="El importe lleva 21% de IVA que la empresa puede desgravar; "
        "el coste real que se usa para la rentabilidad es el neto, no el importe de arriba.",
    )
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
        if "pieza" in self.nombre.lower():
            return self.nombre  # «3 piezas» ya lo dice: sin repetir
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
    favorito = models.BooleanField(
        default=False, db_index=True,
        help_text="Marcado para seguirlo de cerca; se mantiene aunque se retase.",
    )
    url_cochesnet = models.URLField(
        "URL de coches.net", max_length=500, blank=True,
        help_text="Anuncio de coches.net que usas para saber a cuánto vender este coche; "
        "se guarda para no tener que buscarlo otra vez y vale para todas sus tasaciones.",
    )
    url_busqueda_cochesnet = models.URLField(
        "tu búsqueda de coches.net", max_length=1000, blank=True,
        help_text="La búsqueda de coches.net que prefieres para tasar este coche (se guarda sola al tasar).",
    )
    mds_modelo = models.PositiveSmallIntegerField(
        "MDS modelo", null=True, blank=True,
        help_text="Market Days Supply: coches iguales en venta ÷ ventas medias/día "
        "(últimos 45 días). Dato manual, se puede dejar en blanco.",
    )
    mds_similar = models.PositiveSmallIntegerField(
        "MDS similar", null=True, blank=True,
        help_text="Igual que MDS modelo, pero contando coches similares (no idénticos).",
    )
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
    iva_anuncio = models.DecimalField(
        **DEC, default=Decimal("0"),
        help_text="Solo Auto1: el importe de IVA que muestra el anuncio.",
    )
    precio_salida = models.DecimalField(
        **DEC, default=Decimal("0"),
        help_text="Puja mínima / precio de salida de la subasta.",
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

    ultima_comprobacion = models.DateTimeField(
        null=True, blank=True,
        help_text="Última vez que el seguimiento automático miró este coche en Auto1.",
    )
    fallos_ficha = models.PositiveSmallIntegerField(
        default=0,
        help_text="Pasadas seguidas en las que la ficha de Auto1 no mostraba precio "
        "(al llegar a 2 se marca como vendido).",
    )
    CIERRES_AUTO1 = [
        ("no_disponible", "Ya no está disponible"),
        ("adjudicado", "Adjudicado (Vendido)"),
        ("particular_rechazo", "El particular no aceptó la oferta"),
    ]
    cierre_auto1 = models.CharField(
        max_length=20, blank=True, choices=CIERRES_AUTO1,
        help_text="Motivo por el que el seguimiento automático dio por cerrado el coche "
        "en Auto1. Los cerrados salen de la vista activa pero se conservan.",
    )
    compra_directa = models.BooleanField(
        default=False,
        help_text="Auto1 lo muestra ahora como Compra Directa (puede volver a subasta).",
    )
    precio_compra_directa = models.DecimalField(**DEC, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "valoración"
        verbose_name_plural = "valoraciones"
        ordering = ["-fecha_valoracion", "-created_at"]

    def __str__(self) -> str:
        return f"{self.vehiculo} · {self.fecha_valoracion.isoformat()}"

    @property
    def cerrada(self) -> bool:
        """Fuera del seguimiento: estado final o cerrada por el servicio."""
        return bool(self.cierre_auto1) or bool(self.estado_id and self.estado.es_final)

    def clean(self) -> None:
        if self.precio_venta_estimado is not None and self.precio_venta_estimado < 0:
            raise ValidationError("El precio de venta no puede ser negativo.")


class PasadaAuto1(models.Model):
    """Parte de cada pasada del servicio de seguimiento automático de Auto1.

    Sirve para saber si el servicio está vivo: si no llegan partes, el Panel
    avisa. Los crea el propio servicio a través de la API."""

    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    ok = models.BooleanField(default=True)
    revisados = models.PositiveIntegerField(default=0)
    con_cambios = models.PositiveIntegerField(default=0)
    sin_cambios = models.PositiveIntegerField(default=0)
    sin_precio = models.PositiveIntegerField(
        default=0, help_text="Fichas que ya no muestran precio (¿vendidos?)."
    )
    errores = models.PositiveIntegerField(default=0)
    detalle = models.TextField(blank=True)

    class Meta:
        verbose_name = "pasada de seguimiento Auto1"
        verbose_name_plural = "pasadas de seguimiento Auto1"
        ordering = ["-fecha"]

    def __str__(self) -> str:
        return f"{self.fecha:%d/%m/%Y %H:%M} · {'OK' if self.ok else 'FALLO'}"


class ServicioAuto1(models.Model):
    """Estado del servicio de seguimiento de Auto1 (una sola fila).

    El servicio avisa cada ~30 s ("latido") y a la vez pregunta si alguien ha
    pedido una pasada desde el botón del Panel. Así el Panel sabe si el
    servicio está conectado, si está trabajando y cuándo toca la próxima."""

    ultimo_latido = models.DateTimeField(null=True, blank=True)
    programada = models.CharField(
        max_length=5, blank=True, help_text='Hora diaria de la pasada, p. ej. "08:30".'
    )
    en_curso_desde = models.DateTimeField(null=True, blank=True)
    pasada_solicitada = models.DateTimeField(
        null=True, blank=True, help_text="Pedida desde el Panel; el servicio la recoge."
    )
    solicitada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    pausado = models.BooleanField(
        default=False, help_text="Si está activo, no hace la pasada diaria automática."
    )
    detener_solicitada = models.BooleanField(
        default=False, help_text="Pedido de parar la pasada en curso."
    )
    progreso_actual = models.PositiveIntegerField(default=0)
    progreso_total = models.PositiveIntegerField(default=0)
    progreso_ref = models.CharField(max_length=20, blank=True)
    problemas = models.TextField(
        blank=True, help_text="Problemas de configuración que comunica el servicio."
    )
    soporta_busquedas = models.BooleanField(
        default=False,
        help_text="El servicio sabe hacer las búsquedas de Oportunidades (versión nueva). "
        "Un servicio antiguo conectado no las recoge nunca.",
    )

    class Meta:
        verbose_name = "servicio de seguimiento Auto1"
        verbose_name_plural = "servicio de seguimiento Auto1"

    def __str__(self) -> str:
        return "Servicio de seguimiento Auto1"

    @classmethod
    def obtener(cls) -> "ServicioAuto1":
        return cls.objects.get_or_create(pk=1)[0]


class EventoAuto1(models.Model):
    """Actividad reciente del servicio de seguimiento (las últimas líneas de su
    log), para ver desde la app que está trabajando. Se conservan las últimas 300."""

    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    texto = models.CharField(max_length=300)

    class Meta:
        verbose_name = "evento del seguimiento Auto1"
        verbose_name_plural = "eventos del seguimiento Auto1"
        ordering = ["-fecha", "-id"]

    def __str__(self) -> str:
        return f"{self.fecha:%d/%m %H:%M:%S} {self.texto[:60]}"


class BusquedaOportunidad(models.Model):
    """Búsqueda guardada de oportunidades en Auto1.

    Se define con un coche de referencia (la línea del plugin: marca, modelo,
    versión, año, km), la URL del listado de Auto1 donde buscar y el precio al
    que se espera vender. El servicio recorre el listado y, con los costes de
    siempre, detecta los coches que se pueden comprar a un 10 % o más de
    rentabilidad. Solo se consideran los de km parecidos al de referencia.
    """

    class Pais(models.TextChoices):
        ESPANA = "ES", "España"

    marca = models.CharField(max_length=40)
    modelo = models.CharField(max_length=80)
    version = models.CharField(max_length=120, blank=True)
    anio = models.PositiveSmallIntegerField("año", null=True, blank=True)
    km_referencia = models.PositiveIntegerField("km del coche de referencia")
    combustible = models.CharField(max_length=12, choices=Combustible.choices, blank=True)
    cambio = models.CharField(max_length=12, choices=Cambio.choices, blank=True)
    referencia_origen = models.CharField(
        max_length=20, blank=True, help_text="Referencia Auto1 del coche con el que se creó."
    )

    pais = models.CharField(max_length=2, choices=Pais.choices, default=Pais.ESPANA)
    url_listado = models.URLField(
        "URL del listado de Auto1", max_length=1000,
        help_text="La búsqueda de Auto1 con tus filtros; el servicio recorre todas sus páginas.",
    )
    palabras_titulo = models.CharField(
        "palabras del título", max_length=200, blank=True,
        help_text="Opcional: palabras que debe llevar el título del coche (p. ej. «1.0 TSI FR»).",
    )
    tolerancia_km = models.PositiveIntegerField(
        "tolerancia de km", default=10000,
        help_text="Solo cuentan coches con km entre referencia − tolerancia y referencia + tolerancia.",
    )
    potencia_cv = models.PositiveSmallIntegerField(
        "potencia (CV)", null=True, blank=True,
        help_text="Opcional: CV del coche que buscas. Vacío = no se filtra por potencia.",
    )
    tolerancia_cv = models.PositiveSmallIntegerField(
        "tolerancia de CV", default=5,
        help_text="Se aceptan coches con CV entre potencia − tolerancia y potencia + tolerancia.",
    )

    precio_venta_estimado = models.DecimalField(**DEC)
    depreciacion_1000km = models.DecimalField(
        "ajuste por cada 1.000 km", **DEC, default=Decimal("0"),
        help_text="Euros que baja el precio de venta por cada 1.000 km más que el coche de "
        "referencia (y sube por cada 1.000 de menos). 0 = el mismo precio para todos.",
    )
    km_base_venta = models.PositiveIntegerField(
        "km a los que vale ese precio", null=True, blank=True,
        help_text="Los km del coche al que corresponde el precio de venta. Vacío = los del coche de referencia.",
    )
    estado_carroceria = models.ForeignKey(
        EstadoCarroceria, on_delete=models.PROTECT, null=True, blank=True
    )
    piezas_pintura = models.PositiveSmallIntegerField(default=4)
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

    activa = models.BooleanField(default=True)
    solicitada = models.DateTimeField(
        null=True, blank=True,
        help_text="Pedida con «Buscar ahora»; el servicio la recoge en cuanto puede.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "búsqueda de oportunidades"
        verbose_name_plural = "búsquedas de oportunidades"
        ordering = ["-activa", "marca", "modelo", "version"]

    def __str__(self) -> str:
        return self.nombre

    @property
    def nombre(self) -> str:
        return " ".join(x for x in (self.marca, self.modelo, self.version) if x)

    @property
    def rango_km(self) -> tuple[int, int]:
        return max(0, self.km_referencia - self.tolerancia_km), self.km_referencia + self.tolerancia_km

    def aplicar_costes_por_defecto(self) -> None:
        """Costes de preparación «de siempre» (los parámetros vigentes)."""
        p = ParametrosCoste.vigentes()
        self.coste_alberto = p.comision_alberto
        self.coste_gasolina = p.gasolina
        self.coste_pintura_por_pieza = p.pintura_por_pieza
        self.coste_garantia = p.garantia
        self.coste_mecanica = p.mecanica
        self.coste_cambio_titularidad = p.cambio_titularidad
        self.coste_transporte = p.transporte
        self.coste_itv = p.itv
        self.coste_tapiceria = p.tapiceria
        self.coste_tintado = p.tintado
        self.coste_otros = Decimal("0")

    @property
    def ultima_ejecucion(self):
        return self.ejecuciones.first()


class EjecucionBusqueda(models.Model):
    """Una vez que el servicio ha recorrido el listado de una búsqueda: sirve para
    saber CUÁNDO se buscó, QUÉ se leyó y si falló."""

    class Estado(models.TextChoices):
        OK = "ok", "Correcta"
        ERROR = "error", "Con error"

    busqueda = models.ForeignKey(
        BusquedaOportunidad, on_delete=models.CASCADE, related_name="ejecuciones"
    )
    inicio = models.DateTimeField(default=timezone.now)
    estado = models.CharField(max_length=8, choices=Estado.choices, default=Estado.OK)
    origen = models.CharField(max_length=12, default="programada")
    paginas = models.PositiveSmallIntegerField(default=0)
    leidos = models.PositiveIntegerField("coches leídos", default=0)
    encajan = models.PositiveIntegerField("encajan con la búsqueda", default=0)
    revisados = models.PositiveIntegerField("fichas revisadas", default=0)
    comprables = models.PositiveIntegerField(default=0)
    nuevos_comprables = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    aviso = models.TextField(blank=True)

    class Meta:
        ordering = ["-inicio", "-id"]
        verbose_name = "ejecución de búsqueda"
        verbose_name_plural = "ejecuciones de búsqueda"

    def __str__(self) -> str:
        return f"{self.busqueda} · {self.inicio:%d/%m %H:%M}"


class Oportunidad(models.Model):
    """Un coche del listado de una búsqueda que encaja con el coche buscado.

    Se registran todos los que encajan (para llevar el control); solo los que
    se pueden comprar con la rentabilidad mínima son «comprables» y avisan."""

    busqueda = models.ForeignKey(
        BusquedaOportunidad, on_delete=models.CASCADE, related_name="oportunidades"
    )
    referencia = models.CharField(max_length=20)
    nombre = models.CharField(max_length=160)
    url = models.URLField(max_length=500, blank=True)
    tipo = models.CharField(
        max_length=12, blank=True, help_text="subasta · particular · compra_ya"
    )
    precio = models.DecimalField(**DEC, help_text="Puja mínima o precio de compra ya.")
    expectativa = models.DecimalField(**DEC, null=True, blank=True)
    iva_anuncio = models.DecimalField(**DEC, null=True, blank=True)
    km = models.PositiveIntegerField(null=True, blank=True)
    anio = models.PositiveSmallIntegerField(null=True, blank=True)
    cv = models.PositiveSmallIntegerField(null=True, blank=True)
    cambio = models.CharField(max_length=12, blank=True)
    ubicacion = models.CharField(max_length=80, blank=True)

    precio_venta = models.DecimalField(
        **DEC, null=True, blank=True,
        help_text="Precio de venta estimado usado para este coche (ajustado por sus km).",
    )
    evaluada = models.BooleanField(
        default=False, help_text="Se ha abierto la ficha y calculado con el IVA real."
    )
    tier = models.CharField(max_length=2, blank=True, help_text="15 · 12 · 10 · vacío = no llega")
    puja_maxima_10 = models.DecimalField(**DEC, null=True, blank=True)
    margen_10 = models.DecimalField(**DEC, null=True, blank=True)
    rentabilidad = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True,
        help_text="Rentabilidad sobre el coste total al precio actual.",
    )
    beneficio = models.DecimalField(**DEC, null=True, blank=True)

    precio_avisado = models.DecimalField(**DEC, null=True, blank=True)
    valoracion = models.ForeignKey(
        "Valoracion", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    ultima_ejecucion = models.ForeignKey(
        EjecucionBusqueda, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    primera_vez = models.DateTimeField(default=timezone.now)
    ultima_vez = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["busqueda", "precio"]
        constraints = [
            models.UniqueConstraint(fields=["busqueda", "referencia"], name="oportunidad_unica")
        ]
        verbose_name = "oportunidad"
        verbose_name_plural = "oportunidades"

    def __str__(self) -> str:
        return f"{self.referencia} · {self.nombre}"

    @property
    def comprable(self) -> bool:
        return bool(self.tier)


class TasacionMercado(models.Model):
    """Una tasación de mercado de una búsqueda: precio de venta sugerido a partir de
    anuncios comparables de coches.net (que pega la persona desde su navegador).

    Solo SUGIERE: no cambia nada hasta que se pulsa «Aplicar»."""

    busqueda = models.ForeignKey(
        BusquedaOportunidad, on_delete=models.CASCADE, related_name="tasaciones", null=True, blank=True
    )
    vehiculo = models.ForeignKey(
        "Vehiculo", on_delete=models.CASCADE, related_name="tasaciones_mercado", null=True, blank=True
    )
    valoracion = models.ForeignKey(
        "Valoracion", on_delete=models.SET_NULL, related_name="+", null=True, blank=True,
        help_text="La valoración (fila de la rejilla) desde la que se pidió; es la que se actualiza al aplicar.",
    )
    creada = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    n_pegados = models.PositiveIntegerField(default=0)
    n_comparables = models.PositiveIntegerField(default=0, help_text="Tras los filtros de la búsqueda.")
    n_usados = models.PositiveIntegerField(default=0, help_text="Tras la revisión de la IA.")
    km_referencia = models.PositiveIntegerField(default=0)

    precio_mercado = models.DecimalField(**DEC, null=True, blank=True, help_text="Precio de anuncio típico a los km de referencia.")
    rango_bajo = models.DecimalField(**DEC, null=True, blank=True)
    rango_alto = models.DecimalField(**DEC, null=True, blank=True)
    descuento_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5"))
    precio_sugerido = models.DecimalField(**DEC, null=True, blank=True)
    depreciacion_1000km = models.DecimalField(**DEC, default=Decimal("0"))
    pendiente_propia = models.BooleanField(
        default=False, help_text="La bajada por km sale de los anuncios (si no, es una estimación general)."
    )

    url_busqueda = models.URLField(
        max_length=1000, blank=True, help_text="La búsqueda de coches.net de la que salieron los anuncios."
    )
    nota = models.TextField(blank=True, help_text="Algo que conviene saber de cómo se ha calculado.")
    ia_usada = models.BooleanField(default=False)
    ia_modelo = models.CharField(max_length=60, blank=True)
    ia_confianza = models.CharField(max_length=10, blank=True)
    ia_resumen = models.TextField(blank=True)
    ia_error = models.TextField(blank=True)
    tokens_entrada = models.PositiveIntegerField(default=0)
    tokens_salida = models.PositiveIntegerField(default=0)

    anuncios = models.JSONField(default=list, blank=True)
    excluidos = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    aplicada = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creada", "-id"]
        verbose_name = "tasación de mercado"
        verbose_name_plural = "tasaciones de mercado"

    def __str__(self) -> str:
        return f"{self.nombre} · {self.creada:%d/%m %H:%M}"

    @property
    def nombre(self) -> str:
        if self.busqueda_id:
            return self.busqueda.nombre
        v = self.vehiculo
        return " ".join(x for x in (v.marca, v.modelo, v.version) if x) if v else "—"

    @property
    def venta_actual(self):
        if self.busqueda_id:
            return self.busqueda.precio_venta_estimado
        return self.valoracion.precio_venta_estimado if self.valoracion_id else None

    @property
    def valida(self) -> bool:
        return not self.error and self.precio_sugerido is not None

    def aplicar(self) -> None:
        """Pasa el precio sugerido a la búsqueda (con su bajada por km) o a la valoración de la rejilla."""
        if not self.busqueda_id:
            from . import services

            v = self.valoracion
            v.precio_venta_estimado = self.precio_sugerido
            v.save()
            services.recalcular_y_guardar(v)
            self.aplicada = timezone.now()
            self.save(update_fields=["aplicada"])
            return
        b = self.busqueda
        b.precio_venta_estimado = self.precio_sugerido
        b.depreciacion_1000km = self.depreciacion_1000km
        b.km_base_venta = self.km_referencia or b.km_referencia
        b.save(update_fields=["precio_venta_estimado", "depreciacion_1000km", "km_base_venta", "updated_at"])
        self.aplicada = timezone.now()
        self.save(update_fields=["aplicada"])
