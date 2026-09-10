from django import forms
from django.utils import timezone

from . import models


class VehiculoForm(forms.ModelForm):
    class Meta:
        model = models.Vehiculo
        fields = [
            "matricula", "bastidor", "marca", "modelo", "version",
            "potencia_kw", "potencia_cv", "combustible", "cambio",
            "fecha_primera_matriculacion", "anio",
        ]
        widgets = {
            "fecha_primera_matriculacion": forms.DateInput(attrs={"type": "date"}),
        }


class ValoracionForm(forms.ModelForm):
    class Meta:
        model = models.Valoracion
        fields = [
            "sesion_subasta", "proveedor", "tipo_subasta", "ubicacion",
            "lote_id", "orden_lote", "url_anuncio", "zona_origen",
            "fecha_valoracion", "fecha_subasta", "kilometros",
            "regimen_fiscal", "iva_anuncio", "precio_venta_estimado", "precio_anunciado",
            "estado_carroceria", "piezas_pintura", "descuento_comision_pct",
            "coste_alberto", "coste_gasolina", "coste_pintura_por_pieza",
            "coste_garantia", "coste_mecanica", "coste_cambio_titularidad",
            "coste_transporte", "coste_itv", "coste_tapiceria", "coste_tintado",
            "coste_otros",
            "estado", "observaciones",
        ]
        widgets = {
            "fecha_valoracion": forms.DateInput(attrs={"type": "date"}),
            "fecha_subasta": forms.DateInput(attrs={"type": "date"}),
            "observaciones": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        params = models.ParametrosCoste.vigentes()
        defaults = {
            "coste_alberto": params.comision_alberto,
            "coste_gasolina": params.gasolina,
            "coste_pintura_por_pieza": params.pintura_por_pieza,
            "coste_garantia": params.garantia,
            "coste_mecanica": params.mecanica,
            "coste_cambio_titularidad": params.cambio_titularidad,
            "coste_transporte": params.transporte,
        }
        if not self.instance.pk:
            for campo, valor in defaults.items():
                self.fields[campo].initial = valor
            estado_pdte = models.EstadoValoracion.objects.filter(
                nombre="Pendiente de valorar"
            ).first()
            if estado_pdte:
                self.fields["estado"].initial = estado_pdte.pk
            tipo = models.TipoSubasta.objects.filter(es_predeterminado=True).first()
            if tipo:
                self.fields["tipo_subasta"].initial = tipo.pk
                self.fields["proveedor"].initial = tipo.proveedor_id


class SesionSubastaForm(forms.ModelForm):
    class Meta:
        model = models.SesionSubasta
        fields = ["proveedor", "ubicacion", "fecha", "hora_inicio", "hora_fin",
                  "identificador_venta", "url", "notas"]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date"}),
            "hora_inicio": forms.TimeInput(attrs={"type": "time"}),
            "hora_fin": forms.TimeInput(attrs={"type": "time"}),
            "notas": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ubicacion"].queryset = models.Ubicacion.objects.filter(
            activa=True
        ).select_related("proveedor")
        if not self.instance.pk:
            bca = models.Proveedor.objects.filter(nombre="BCA").first()
            if bca:
                self.fields["proveedor"].initial = bca.pk
            self.fields["fecha"].initial = timezone.localdate()


class PegarLotesForm(forms.Form):
    texto = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 8,
            "placeholder": "Pega aquí las líneas del scraper (una por coche, tal cual salen del portapapeles)…",
        }),
        label="Pegar del portapapeles",
    )
