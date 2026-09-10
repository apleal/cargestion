from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from . import models


class TramoInline(admin.TabularInline):
    model = models.TramoComision
    extra = 0


@admin.register(models.TarifaComision)
class TarifaComisionAdmin(SimpleHistoryAdmin):
    list_display = ("proveedor", "tipo_vehiculo", "vigencia_desde", "vigencia_hasta", "vigente")
    list_filter = ("proveedor", "tipo_vehiculo")
    inlines = [TramoInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        errores = form.instance.validar_tramos()
        if errores:
            self.message_user(
                request, "Avisos en los tramos: " + "; ".join(errores), level="WARNING"
            )


class UbicacionInline(admin.TabularInline):
    model = models.Ubicacion
    extra = 0


class TipoSubastaInline(admin.TabularInline):
    model = models.TipoSubasta
    extra = 0


class ConceptoFijoInline(admin.TabularInline):
    model = models.ConceptoFijo
    extra = 0


@admin.register(models.Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo", "base_margen_rebu")
    inlines = [UbicacionInline, TipoSubastaInline, ConceptoFijoInline]


@admin.register(models.ParametrosCoste)
class ParametrosCosteAdmin(SimpleHistoryAdmin):
    list_display = ("vigencia_desde", "comision_alberto", "pintura_por_pieza", "transporte")


@admin.register(models.EstadoCarroceria)
class EstadoCarroceriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "piezas_estimadas", "orden")


@admin.register(models.EscenarioObjetivo)
class EscenarioObjetivoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rentabilidad_objetivo", "es_principal", "activo", "orden")


@admin.register(models.EstadoValoracion)
class EstadoValoracionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "orden", "es_final")


@admin.register(models.SesionSubasta)
class SesionSubastaAdmin(admin.ModelAdmin):
    list_display = ("ubicacion", "fecha", "estado", "identificador_venta")
    list_filter = ("proveedor", "ubicacion", "estado")
    date_hierarchy = "fecha"


@admin.register(models.Vehiculo)
class VehiculoAdmin(SimpleHistoryAdmin):
    list_display = ("__str__", "marca", "modelo", "anio", "km_ultimo_conocido")
    search_fields = ("matricula", "bastidor", "marca", "modelo")


@admin.register(models.Valoracion)
class ValoracionAdmin(SimpleHistoryAdmin):
    list_display = (
        "vehiculo", "fecha_valoracion", "proveedor", "estado",
        "precio_venta_estimado", "r_puja_maxima_principal", "r_rentabilidad_coste",
    )
    list_filter = ("proveedor", "estado", "tipo_subasta", "sesion_subasta")
    search_fields = ("vehiculo__matricula", "vehiculo__marca", "vehiculo__modelo", "lote_id")
    autocomplete_fields = ("vehiculo",)
    readonly_fields = (
        "r_gastos_preparacion", "r_coste_adquisicion", "r_coste_total", "r_iva_rebu",
        "r_beneficio_neto", "r_rentabilidad_coste", "r_margen_venta",
        "r_puja_maxima_principal", "r_escenarios",
    )
